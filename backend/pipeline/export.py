"""
Export stage: ffmpeg concat + music overlay + GPU/CPU encode.

Song rules (V1):
  - Trim or loop song to match output duration
  - Fade in: 2s, Fade out: 2s
  - Volume scalar: 0.6 (configurable via settings)
  - Music-only output (no ambient audio)
"""
from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path

from .accel import ffmpeg_export_args
from .types import Manifest, Segment
from .utils import ProgressEmitter, log_path, manifest_write, timeline_read

logger = logging.getLogger(__name__)

MUSIC_VOLUME = 0.6
FADE_S = 2.0


def _build_concat_list(
    segments: list[Segment],
    sources_by_id: dict,
    use_proxies: bool = False,
) -> str:
    """Build ffmpeg concat demuxer content."""
    lines = []
    for seg in segments:
        src = sources_by_id.get(seg.source_id)
        if src is None:
            raise ValueError(f"Unknown source_id {seg.source_id} in timeline")
        path = src.proxy_path if use_proxies else src.original_path
        offset = src.sync.offset_s if src.sync else 0.0
        # Apply sync offset to timeline timestamps
        t0 = seg.master_t0 + offset
        t1 = seg.master_t1 + offset
        dur = t1 - t0
        lines.append(f"file '{path}'")
        lines.append(f"inpoint {t0:.6f}")
        lines.append(f"outpoint {t1:.6f}")
    return "\n".join(lines)


def _song_filter(song_path: str, total_s: float, volume: float = MUSIC_VOLUME, fade_s: float = FADE_S) -> str:
    """
    Build an ffmpeg audio filter_complex expression that:
    - Loops/trims the song to total_s
    - Applies fade in + fade out
    - Scales volume
    """
    fade_out_start = max(0, total_s - fade_s)
    return (
        f"[1:a]"
        f"aloop=loop=-1:size=2e+09,"
        f"atrim=0:{total_s:.6f},"
        f"afade=t=in:st=0:d={fade_s},"
        f"afade=t=out:st={fade_out_start:.6f}:d={fade_s},"
        f"volume={volume}"
        f"[aout]"
    )


def run(
    project_dir: Path,
    manifest: Manifest,
    emitter: ProgressEmitter,
    export_mode: str = "fast_gpu",
    music_volume: float = MUSIC_VOLUME,
) -> Manifest:
    """
    Export stage:
    1. Load timeline.json.
    2. Build ffmpeg concat demuxer.
    3. Mix song (trim/loop + fade + volume).
    4. Encode with GPU/CPU HEVC.
    5. Write exports/highlight.mp4.

    Idempotent — skips if stage_status.export == "done".
    """
    if manifest.stage_status.export == "done":
        emitter.emit("export", "done", 1.0, "Skipped (already done)")
        return manifest

    emitter.emit("export", "running", 0.0, "Loading timeline")
    manifest.stage_status.export = "running"
    manifest_write(project_dir, manifest)

    ffmpeg = manifest.accel.ffmpeg_path if manifest.accel else "ffmpeg"
    codec_args = ffmpeg_export_args(manifest.accel, export_mode) if manifest.accel else [
        "-c:v", "libx265", "-crf", "20", "-preset", "medium"
    ]

    timeline = timeline_read(project_dir)
    if not timeline.segments:
        raise ValueError("Timeline has no segments — run assemble stage first")

    sources_by_id = {s.id: s for s in manifest.sources}
    total_s = sum(seg.duration for seg in timeline.segments)

    exports_dir = project_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    output_path = exports_dir / "highlight.mp4"
    log_file = log_path(project_dir, "export")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, dir=project_dir
    ) as cf:
        concat_content = _build_concat_list(timeline.segments, sources_by_id)
        cf.write(concat_content)
        concat_file = cf.name

    try:
        with log_file.open("w") as log:
            if manifest.song_path:
                audio_filter = _song_filter(manifest.song_path, total_s, music_volume)
                cmd = [
                    ffmpeg,
                    "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", concat_file,
                    "-i", manifest.song_path,
                    "-filter_complex", audio_filter,
                    "-map", "0:v",
                    "-map", "[aout]",
                    *codec_args,
                    "-movflags", "+faststart",
                    str(output_path),
                ]
            else:
                cmd = [
                    ffmpeg,
                    "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", concat_file,
                    "-an",
                    *codec_args,
                    "-movflags", "+faststart",
                    str(output_path),
                ]

            log.write(f"Command: {' '.join(cmd)}\n\n")
            emitter.emit("export", "running", 0.1, "Encoding highlight reel")

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            for line in proc.stdout:
                log.write(line)
                if "frame=" in line or "time=" in line:
                    emitter.emit("export", "running", 0.5, line.strip()[:120])

            proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(f"Export encode failed (exit {proc.returncode}). See {log_file}")

    finally:
        try:
            Path(concat_file).unlink()
        except OSError:
            pass

    manifest.stage_status.export = "done"
    manifest_write(project_dir, manifest)
    emitter.emit("export", "done", 1.0, f"Export complete → {output_path}")
    return manifest
