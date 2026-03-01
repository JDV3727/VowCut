"""
Assemble stage: segment selection with beat-snapping and camera switching.

1-cam path: select high-scoring chunks from single source.
2-cam path: delegate to director_v1.decide_switches, then snap to beats.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from .director_v1 import CameraDecision, decide_switches, decide_switches_beat_aligned, score_all
from .features import CHUNK_DURATION_S, DB_FILENAME
from .music import MUSIC_JSON, snap_to_beat
from .types import ChunkFeature, Manifest, Segment, Timeline, TimelineMetadata
from .utils import ProgressEmitter, log_path, manifest_write, now_iso, timeline_write

logger = logging.getLogger(__name__)

# Segment length constraints (seconds)
MIN_SEG_S = 2.0
MAX_SEG_S = 15.0
BEAT_SNAP_S = 0.15

# Weight of energy curve blended into chunk scores
ENERGY_WEIGHT = 0.2


def _load_features(db_path: Path) -> dict[str, list[ChunkFeature]]:
    """Load all chunk features from DuckDB, grouped by source_id."""
    import duckdb  # lazy import so module loads without duckdb installed
    con = duckdb.connect(str(db_path), read_only=True)
    rows = con.execute(
        "SELECT source_id, chunk_index, t0, t1, activity, stability, exposure, rms, onset_strength "
        "FROM chunk_features ORDER BY source_id, chunk_index"
    ).fetchall()
    con.close()

    result: dict[str, list[ChunkFeature]] = {}
    for row in rows:
        sid = row[0]
        feature = ChunkFeature(
            source_id=row[0],
            chunk_index=row[1],
            t0=row[2],
            t1=row[3],
            activity=row[4],
            stability=row[5],
            exposure=row[6],
            rms=row[7],
            onset_strength=row[8],
        )
        result.setdefault(sid, []).append(feature)
    return result


def _apply_energy_weighting(
    scores_by_source: dict[str, list[float]],
    features_by_source: dict[str, list[ChunkFeature]],
    music_data: dict,
) -> dict[str, list[float]]:
    """
    Blend energy curve into chunk scores: score_final = score * 0.8 + energy_norm * 0.2.
    No-op when music_data has no energy_curve.
    """
    energy_curve = music_data.get("energy_curve")
    energy_hop_s = music_data.get("energy_hop_s", 0.5)
    if not energy_curve:
        return scores_by_source

    energy_arr = np.array(energy_curve, dtype=float)
    e_min, e_max = energy_arr.min(), energy_arr.max()
    if e_max - e_min < 1e-9:
        return scores_by_source

    energy_norm = (energy_arr - e_min) / (e_max - e_min)

    result: dict[str, list[float]] = {}
    for sid, scores in scores_by_source.items():
        feats = sorted(features_by_source.get(sid, []), key=lambda f: f.chunk_index)
        blended = []
        for i, score in enumerate(scores):
            # Map chunk midpoint to energy bin
            t_mid = feats[i].t0 + (feats[i].t1 - feats[i].t0) / 2 if i < len(feats) else i * CHUNK_DURATION_S
            e_idx = min(int(t_mid / energy_hop_s), len(energy_norm) - 1)
            e_val = float(energy_norm[e_idx])
            blended.append(score * (1 - ENERGY_WEIGHT) + e_val * ENERGY_WEIGHT)
        result[sid] = blended
    return result


def _greedy_1cam(
    scores: list[float],
    features: list[ChunkFeature],
    target_length_s: float,
    beats: list[float],
) -> list[Segment]:
    """
    1-cam greedy path: pick top non-overlapping chunks until target_length_s is filled.
    Chunks are sorted by score (descending), selected greedily, then sorted by t0.
    Beat snap + MIN/MAX constraints are applied.
    """
    # Pair each chunk with its score, sort by score descending
    indexed = sorted(
        [(score, feat) for score, feat in zip(scores, features)],
        key=lambda x: x[0],
        reverse=True,
    )

    selected: list[ChunkFeature] = []
    total_s = 0.0

    for score, feat in indexed:
        dur = feat.t1 - feat.t0
        if dur < MIN_SEG_S:
            continue
        if dur > MAX_SEG_S:
            dur = MAX_SEG_S
        if total_s >= target_length_s:
            break
        # Clamp to budget
        remaining = target_length_s - total_s
        effective_dur = min(dur, remaining)
        if effective_dur < MIN_SEG_S:
            break
        selected.append(feat)
        total_s += effective_dur

    # Sort by t0 (chronological)
    selected.sort(key=lambda f: f.t0)

    segments: list[Segment] = []
    running_s = 0.0
    for feat in selected:
        if running_s >= target_length_s:
            break
        t0 = snap_to_beat(feat.t0, beats, BEAT_SNAP_S)
        t1 = snap_to_beat(feat.t1, beats, BEAT_SNAP_S)
        dur = t1 - t0
        if dur < MIN_SEG_S:
            continue
        if dur > MAX_SEG_S:
            t1 = t0 + MAX_SEG_S
            dur = MAX_SEG_S
        remaining = target_length_s - running_s
        if dur > remaining:
            t1 = t0 + remaining
            dur = remaining
        segments.append(Segment(master_t0=t0, master_t1=t1, source_id=feat.source_id))
        running_s += dur

    return segments


def _decisions_to_segments(
    decisions: list[CameraDecision],
    target_length_s: float,
    beats: list[float],
) -> list[Segment]:
    """
    Convert CameraDecisions to Segments:
    - Snap boundaries to beats (±BEAT_SNAP_S)
    - Enforce MIN_SEG_S / MAX_SEG_S
    - Trim total length to target_length_s
    """
    segments: list[Segment] = []
    running_s = 0.0

    for dec in decisions:
        if running_s >= target_length_s:
            break

        t0 = snap_to_beat(dec.t0, beats, BEAT_SNAP_S)
        t1 = snap_to_beat(dec.t1, beats, BEAT_SNAP_S)

        dur = t1 - t0
        if dur < MIN_SEG_S:
            continue
        if dur > MAX_SEG_S:
            t1 = t0 + MAX_SEG_S
            dur = MAX_SEG_S

        # Trim to remaining budget
        remaining = target_length_s - running_s
        if dur > remaining:
            t1 = t0 + remaining
            dur = remaining

        segments.append(Segment(master_t0=t0, master_t1=t1, source_id=dec.source_id))
        running_s += dur

    return segments


def run(
    project_dir: Path,
    manifest: Manifest,
    emitter: ProgressEmitter,
    target_length_s: float = 240.0,
) -> Manifest:
    """
    Assemble stage:
    1. Load chunk features from features.db.
    2. Score and select segments via director_v1 (or 1-cam path).
    3. Snap boundaries to beats.
    4. Write timeline.json.
    5. Mark stage done.

    Idempotent — skips if stage_status.assemble == "done".
    """
    if manifest.stage_status.assemble == "done":
        emitter.emit("assemble", "done", 1.0, "Skipped (already done)")
        return manifest

    emitter.emit("assemble", "running", 0.0, "Loading features")
    manifest.stage_status.assemble = "running"
    manifest_write(project_dir, manifest)

    db_path = project_dir / "features" / DB_FILENAME
    if not db_path.exists():
        raise FileNotFoundError(f"features.db not found at {db_path} — run features stage first")

    music_json_path = project_dir / MUSIC_JSON
    music_data: dict = {}
    if music_json_path.exists():
        music_data = json.loads(music_json_path.read_text())
    beats: list[float] = music_data.get("beats", [])

    features_by_source = _load_features(db_path)
    if not features_by_source:
        raise RuntimeError("features.db contains no rows — run features stage first")
    emitter.emit("assemble", "running", 0.2, f"Loaded features for {len(features_by_source)} source(s)")

    scores_by_source = score_all(features_by_source)
    scores_by_source = _apply_energy_weighting(scores_by_source, features_by_source, music_data)

    emitter.emit("assemble", "running", 0.4, "Scored chunks")

    # 1-cam greedy path — skip hysteresis for single source
    if len(features_by_source) == 1:
        sid = next(iter(features_by_source))
        feats = sorted(features_by_source[sid], key=lambda f: f.chunk_index)
        segments = _greedy_1cam(scores_by_source[sid], feats, target_length_s, beats)
        emitter.emit("assemble", "running", 0.8, f"{len(segments)} segments (1-cam greedy)")
    else:
        # Full footage duration needed to close the last beat-aligned decision
        total_duration_s = max(
            max((f.t1 for f in feats), default=0.0)
            for feats in features_by_source.values()
        )

        if beats:
            decisions = decide_switches_beat_aligned(
                scores_by_source,
                beats=beats,
                total_duration_s=total_duration_s,
                chunk_duration_s=CHUNK_DURATION_S,
            )
            emitter.emit("assemble", "running", 0.6, f"{len(decisions)} beat-aligned decisions")
        else:
            decisions = decide_switches(
                scores_by_source,
                chunk_duration_s=CHUNK_DURATION_S,
            )
            emitter.emit("assemble", "running", 0.6, f"{len(decisions)} camera decisions")

        segments = _decisions_to_segments(decisions, target_length_s, beats)
        emitter.emit("assemble", "running", 0.8, f"{len(segments)} segments → {sum(s.duration for s in segments):.1f}s")

    # Build and write timeline
    encoder_used = (manifest.accel.hevc_encoder if manifest.accel else "libx265")
    timeline = Timeline(
        schema_version="1.0",
        target_length_s=target_length_s,
        created_at=now_iso(),
        metadata=TimelineMetadata(
            encoder_used=encoder_used,
            feature_version=manifest.versions.feature_version,
            selection_version=manifest.versions.selection_version,
        ),
        segments=segments,
    )
    timeline_write(project_dir, timeline)

    log_file = log_path(project_dir, "assemble")
    with log_file.open("w") as log:
        log.write(f"Target: {target_length_s}s | Segments: {len(segments)}\n")
        for seg in segments:
            log.write(f"  [{seg.master_t0:.2f} → {seg.master_t1:.2f}] {seg.source_id} ({seg.duration:.2f}s)\n")

    manifest.stage_status.assemble = "done"
    manifest_write(project_dir, manifest)
    emitter.emit("assemble", "done", 1.0, f"Timeline: {len(segments)} segments, {sum(s.duration for s in segments):.1f}s")
    return manifest
