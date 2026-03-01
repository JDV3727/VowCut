"""
Feature extraction stage: chunk-based motion, RMS, and onset extraction → features.db (DuckDB).

Each source is split into non-overlapping chunks (default 2s). For each chunk:
  - motion_score: mean inter-frame pixel difference on proxy frames (via ffmpeg)
  - rms: root-mean-square of audio signal in that window
  - onset_strength: mean librosa onset envelope in that window
"""
from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from .types import ChunkFeature, Manifest
from .utils import ProgressEmitter, log_path, manifest_write

logger = logging.getLogger(__name__)

CHUNK_DURATION_S = 2.0
DB_FILENAME = "features.db"


# ---------------------------------------------------------------------------
# Motion extraction via ffmpeg signalstats / scene filter
# ---------------------------------------------------------------------------

def _extract_motion_scores(
    ffmpeg: str,
    proxy_path: str,
    duration_s: float,
    chunk_s: float = CHUNK_DURATION_S,
) -> list[float]:
    """
    Use ffmpeg `scene` filter to get per-frame scene-change scores (0–1),
    then average per chunk using wall-clock pts_time for assignment.

    Returns one score per chunk.
    """
    n_chunks = max(1, int(duration_s / chunk_s))
    scores_by_chunk: list[list[float]] = [[] for _ in range(n_chunks)]

    cmd = [
        ffmpeg,
        "-i", proxy_path,
        "-vf", r"select='gte(scene\,0)',metadata=print:file=-",
        "-an",
        "-f", "null",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg scene filter failed (returncode={result.returncode}) for {proxy_path}: {result.stderr[-500:]}"
        )

    # Parse pts_time + lavfi.scene_score from stdout.
    # metadata=print:file=- writes to stdout; ffmpeg diagnostics go to stderr.
    # ffmpeg format (one block per frame):
    #   frame:N    pts:M       pts_time:T.TTT
    #   lavfi.scene_score=V.VVVVVV
    current_pts: float | None = None
    for line in result.stdout.splitlines():
        # Frame info line contains pts_time: somewhere in it
        if "pts_time:" in line:
            try:
                current_pts = float(line.split("pts_time:")[1].split()[0])
            except (ValueError, IndexError):
                current_pts = None
        elif "lavfi.scene_score=" in line and current_pts is not None:
            try:
                val = float(line.split("lavfi.scene_score=")[1].split()[0])
                chunk_idx = min(int(current_pts / chunk_s), n_chunks - 1)
                scores_by_chunk[chunk_idx].append(val)
            except (ValueError, IndexError):
                pass
            current_pts = None

    scores = [float(np.mean(v)) if v else 0.0 for v in scores_by_chunk]

    if all(s == 0.0 for s in scores):
        logger.warning("All motion scores are zero for %s — scene filter may have produced no output", proxy_path)

    return scores


# ---------------------------------------------------------------------------
# Audio feature extraction
# ---------------------------------------------------------------------------

def _extract_audio_features(
    wav_path: str,
    duration_s: float,
    chunk_s: float = CHUNK_DURATION_S,
) -> tuple[list[float], list[float]]:
    """
    Returns (rms_per_chunk, onset_per_chunk).
    """
    import librosa
    import soundfile as sf

    samples, sr = sf.read(wav_path, dtype="float32", always_2d=False)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)

    n_chunks = max(1, int(duration_s / chunk_s))
    chunk_samples = int(chunk_s * sr)

    rms_list: list[float] = []
    onset_list: list[float] = []

    hop = 512
    onset_env = librosa.onset.onset_strength(y=samples, sr=sr, hop_length=hop)
    # Map onset frame indices to seconds
    frame_times = librosa.frames_to_time(np.arange(len(onset_env)), sr=sr, hop_length=hop)

    for c in range(n_chunks):
        t0 = c * chunk_s
        t1 = t0 + chunk_s
        s0 = int(t0 * sr)
        s1 = min(int(t1 * sr), len(samples))
        chunk_audio = samples[s0:s1] if s1 > s0 else np.zeros(chunk_samples)

        rms = float(np.sqrt(np.mean(chunk_audio ** 2)))
        rms_list.append(rms)

        mask = (frame_times >= t0) & (frame_times < t1)
        onset_val = float(onset_env[mask].mean()) if mask.any() else 0.0
        onset_list.append(onset_val)

    return rms_list, onset_list


# ---------------------------------------------------------------------------
# DuckDB helpers
# ---------------------------------------------------------------------------

def _init_db(db_path: Path):
    import duckdb  # lazy import
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE IF NOT EXISTS chunk_features (
            source_id     VARCHAR,
            chunk_index   INTEGER,
            t0            DOUBLE,
            t1            DOUBLE,
            motion_score  DOUBLE,
            rms           DOUBLE,
            onset_strength DOUBLE,
            PRIMARY KEY (source_id, chunk_index)
        )
    """)
    return con


def _upsert_features(con: duckdb.DuckDBPyConnection, features: list[ChunkFeature]) -> None:
    if not features:
        return
    con.executemany(
        """
        INSERT OR REPLACE INTO chunk_features
            (source_id, chunk_index, t0, t1, motion_score, rms, onset_strength)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (f.source_id, f.chunk_index, f.t0, f.t1, f.motion_score, f.rms, f.onset_strength)
            for f in features
        ],
    )


# ---------------------------------------------------------------------------
# Stage entry point
# ---------------------------------------------------------------------------

def run(
    project_dir: Path,
    manifest: Manifest,
    emitter: ProgressEmitter,
) -> Manifest:
    """
    Features stage: extract motion/RMS/onset per chunk → features.db.
    Idempotent — skips if stage_status.features == "done".
    """
    if manifest.stage_status.features == "done":
        emitter.emit("features", "done", 1.0, "Skipped (already done)")
        return manifest

    emitter.emit("features", "running", 0.0, "Starting feature extraction")
    manifest.stage_status.features = "running"
    manifest_write(project_dir, manifest)

    ffmpeg = manifest.accel.ffmpeg_path if manifest.accel else "ffmpeg"
    db_path = project_dir / "features" / DB_FILENAME
    con = _init_db(db_path)

    log_file = log_path(project_dir, "features")
    sources = manifest.sources

    with log_file.open("w") as log:
        for i, source in enumerate(sources):
            base_progress = i / max(len(sources), 1)
            emitter.emit("features", "running", base_progress, f"Extracting features: {source.id}")

            if not source.proxy_path or not source.audio_path:
                warn = f"Missing proxy or audio for {source.id} — skipping feature extraction"
                manifest.pipeline.warnings.append(warn)
                log.write(f"WARNING: {warn}\n")
                continue

            duration_s = source.metadata.duration_s
            n_chunks = max(1, int(duration_s / CHUNK_DURATION_S))
            log.write(f"{source.id}: {n_chunks} chunks @ {CHUNK_DURATION_S}s each\n")

            try:
                motion_scores = _extract_motion_scores(ffmpeg, source.proxy_path, duration_s)
                rms_scores, onset_scores = _extract_audio_features(source.audio_path, duration_s)

                # Align lists to n_chunks
                def _pad(lst: list[float]) -> list[float]:
                    return (lst + [0.0] * n_chunks)[:n_chunks]

                motion_scores = _pad(motion_scores)
                rms_scores = _pad(rms_scores)
                onset_scores = _pad(onset_scores)

                features = [
                    ChunkFeature(
                        source_id=source.id,
                        chunk_index=c,
                        t0=c * CHUNK_DURATION_S,
                        t1=(c + 1) * CHUNK_DURATION_S,
                        motion_score=motion_scores[c],
                        rms=rms_scores[c],
                        onset_strength=onset_scores[c],
                    )
                    for c in range(n_chunks)
                ]
                _upsert_features(con, features)
                log.write(f"  Wrote {len(features)} chunk records to DB\n")

            except Exception as e:
                manifest.stage_status.features = "error"
                manifest.pipeline.error = str(e)
                manifest_write(project_dir, manifest)
                emitter.emit("features", "error", base_progress, str(e))
                con.close()
                raise

            emitter.emit(
                "features", "running",
                (i + 1) / max(len(sources), 1),
                f"Done: {source.id}",
            )

    con.close()
    manifest.stage_status.features = "done"
    manifest_write(project_dir, manifest)
    emitter.emit("features", "done", 1.0, "Feature extraction complete")
    return manifest
