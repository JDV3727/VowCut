"""
GPU detection and ffmpeg encoder validation.
Probe-tests each candidate with a 1-frame null encode before committing.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from .types import AccelInfo


# ---------------------------------------------------------------------------
# Encoder candidate lists (priority order)
# ---------------------------------------------------------------------------

_H264_CANDIDATES_MACOS = ["h264_videotoolbox", "libx264"]
_H264_CANDIDATES_WIN = ["h264_nvenc", "h264_qsv", "h264_amf", "libx264"]
_H264_CANDIDATES_LINUX = ["h264_nvenc", "h264_vaapi", "libx264"]

_HEVC_CANDIDATES_MACOS = ["hevc_videotoolbox", "libx265"]
_HEVC_CANDIDATES_WIN = ["hevc_nvenc", "hevc_qsv", "libx265"]
_HEVC_CANDIDATES_LINUX = ["hevc_nvenc", "hevc_vaapi", "libx265"]


def _os() -> str:
    s = platform.system().lower()
    if "darwin" in s:
        return "macos"
    if "windows" in s:
        return "windows"
    return "linux"


def _find_binary(name: str) -> str:
    """Return full path to *name* or just the name if not on PATH."""
    found = shutil.which(name)
    return found if found else name


def _encoder_works(ffmpeg: str, encoder: str) -> bool:
    """
    Probe-test *encoder* with a 1-frame null encode.
    Returns True only if ffmpeg exits 0.
    """
    cmd = [
        ffmpeg,
        "-f", "lavfi",
        "-i", "color=black:s=128x72:r=1",
        "-frames:v", "1",
        "-c:v", encoder,
        "-f", "null",
        "-",
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _select_encoder(
    ffmpeg: str, candidates: list[str]
) -> tuple[str, list[str]]:
    """
    Try *candidates* in order; return (chosen, fallbacks_used).
    *fallbacks_used* lists encoders tried before the chosen one.
    """
    tried: list[str] = []
    for enc in candidates:
        if _encoder_works(ffmpeg, enc):
            return enc, tried
        tried.append(enc)
    # Should not happen — libx264/libx265 are always present in a real install
    raise RuntimeError(
        f"No working encoder found. Tried: {candidates}. "
        "Is ffmpeg installed with codec support?"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect(
    ffmpeg_path: Optional[str] = None,
    ffprobe_path: Optional[str] = None,
) -> AccelInfo:
    """
    Detect GPU encoders and validate ffmpeg/ffprobe availability.

    Returns a fully-populated AccelInfo.  Call once at startup and cache.
    """
    ffmpeg = ffmpeg_path or _find_binary("ffmpeg")
    ffprobe = ffprobe_path or _find_binary("ffprobe")

    os_name = _os()

    h264_candidates = {
        "macos": _H264_CANDIDATES_MACOS,
        "windows": _H264_CANDIDATES_WIN,
        "linux": _H264_CANDIDATES_LINUX,
    }[os_name]

    hevc_candidates = {
        "macos": _HEVC_CANDIDATES_MACOS,
        "windows": _HEVC_CANDIDATES_WIN,
        "linux": _HEVC_CANDIDATES_LINUX,
    }[os_name]

    h264_enc, h264_fallbacks = _select_encoder(ffmpeg, h264_candidates)
    hevc_enc, _ = _select_encoder(ffmpeg, hevc_candidates)

    return AccelInfo(
        ffmpeg_path=ffmpeg,
        ffprobe_path=ffprobe,
        selected_encoder=h264_enc,
        validated=True,
        fallbacks_used=h264_fallbacks,
        hevc_encoder=hevc_enc,
        hevc_validated=True,
    )


def ffmpeg_proxy_args(accel: AccelInfo) -> list[str]:
    """Return codec-specific ffmpeg args for proxy encode (H.264 720p@30)."""
    enc = accel.selected_encoder
    if enc == "h264_videotoolbox":
        return ["-c:v", enc, "-q:v", "65", "-vf", "scale=-2:720", "-r", "30"]
    if enc in ("h264_nvenc", "h264_amf"):
        return ["-c:v", enc, "-preset", "fast", "-vf", "scale=-2:720", "-r", "30"]
    if enc == "h264_qsv":
        return ["-c:v", enc, "-global_quality", "28", "-vf", "scale=-2:720", "-r", "30"]
    # libx264 fallback
    return ["-c:v", "libx264", "-preset", "fast", "-crf", "23", "-vf", "scale=-2:720", "-r", "30"]


def ffmpeg_export_args(accel: AccelInfo, mode: str = "fast_gpu") -> list[str]:
    """Return codec-specific ffmpeg args for final HEVC export."""
    enc = accel.hevc_encoder
    if mode == "high_quality_cpu" or enc == "libx265":
        return ["-c:v", "libx265", "-crf", "20", "-preset", "medium"]
    if enc == "hevc_videotoolbox":
        return ["-c:v", enc, "-q:v", "60"]
    if enc in ("hevc_nvenc",):
        return ["-c:v", enc, "-preset", "slow", "-rc", "vbr", "-cq", "24"]
    if enc == "hevc_qsv":
        return ["-c:v", enc, "-global_quality", "24"]
    return ["-c:v", "libx265", "-crf", "20", "-preset", "medium"]
