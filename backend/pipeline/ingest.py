"""
Ingest stage: ffprobe metadata extraction + source registration.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

from .types import AccelInfo, Manifest, Source, SourceMetadata
from .utils import ProgressEmitter, log_path, manifest_write, now_iso


def _ffprobe_metadata(ffprobe: str, path: str) -> SourceMetadata:
    cmd = [
        ffprobe,
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {result.stderr.strip()}")

    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    fmt = data.get("format", {})

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError(f"No video stream found in {path}")

    # Duration: prefer stream, fall back to format
    dur_raw = video.get("duration") or fmt.get("duration", "0")
    duration_s = float(dur_raw)

    # FPS: parse "num/den" strings
    fps_str = video.get("r_frame_rate", "30/1")
    try:
        num, den = fps_str.split("/")
        fps = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        fps = 30.0

    return SourceMetadata(
        duration_s=duration_s,
        width=int(video.get("width", 0)),
        height=int(video.get("height", 0)),
        fps=fps,
        codec=video.get("codec_name", "unknown"),
    )


def run(
    project_dir: Path,
    manifest: Manifest,
    emitter: ProgressEmitter,
) -> Manifest:
    """
    Ingest stage:
    1. Validate ffprobe is reachable.
    2. For each source, extract video metadata.
    3. Mark stage as done.

    Idempotent — skips if stage_status.ingest == "done".
    """
    if manifest.stage_status.ingest == "done":
        emitter.emit("ingest", "done", 1.0, "Skipped (already done)")
        return manifest

    emitter.emit("ingest", "running", 0.0, "Starting ingest")
    manifest.stage_status.ingest = "running"
    manifest_write(project_dir, manifest)

    ffprobe = manifest.accel.ffprobe_path if manifest.accel else "ffprobe"
    sources = manifest.sources

    log_file = log_path(project_dir, "ingest")
    log_file.parent.mkdir(parents=True, exist_ok=True)

    with log_file.open("w") as log:
        for i, source in enumerate(sources):
            progress = i / max(len(sources), 1)
            emitter.emit("ingest", "running", progress, f"Probing {source.id}")
            log.write(f"Probing {source.id}: {source.original_path}\n")

            try:
                meta = _ffprobe_metadata(ffprobe, source.original_path)
                source.metadata = meta
                log.write(
                    f"  -> {meta.width}x{meta.height} {meta.fps:.2f}fps "
                    f"{meta.duration_s:.1f}s [{meta.codec}]\n"
                )
            except Exception as e:
                manifest.stage_status.ingest = "error"
                manifest.pipeline.error = str(e)
                manifest_write(project_dir, manifest)
                emitter.emit("ingest", "error", progress, str(e))
                raise

    manifest.stage_status.ingest = "done"
    manifest_write(project_dir, manifest)
    emitter.emit("ingest", "done", 1.0, f"Ingested {len(sources)} source(s)")
    return manifest
