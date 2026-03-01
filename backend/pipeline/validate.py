"""
Post-stage validation helpers using ffprobe.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def probe_video(ffprobe: str, path: str | Path) -> dict:
    """Run ffprobe on *path* and return parsed JSON."""
    cmd = [
        ffprobe,
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def assert_valid_mp4(ffprobe: str, path: str | Path) -> dict:
    """
    Verify that *path* is a valid MP4 with at least one video stream.
    Returns probe data on success; raises on failure.
    """
    data = probe_video(ffprobe, path)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError(f"No video stream in {path}")
    fmt = data.get("format", {})
    if float(fmt.get("duration", "0")) <= 0:
        raise ValueError(f"Zero duration in {path}")
    return data


def get_duration(ffprobe: str, path: str | Path) -> float:
    """Return video duration in seconds."""
    data = probe_video(ffprobe, path)
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    # Prefer stream-level duration
    for s in streams:
        if s.get("codec_type") == "video":
            try:
                return float(s["duration"])
            except (KeyError, ValueError):
                pass
    return float(fmt.get("duration", "0"))
