"""Integration tests for proxy generation."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.pipeline.validate import assert_valid_mp4, get_duration

FIXTURES = Path(__file__).parent / "fixtures"
TINY_CLIP = FIXTURES / "tiny_clip.mp4"

pytestmark = pytest.mark.skipif(
    not TINY_CLIP.exists(),
    reason="tiny_clip.mp4 not found — run scripts/gen_test_clip.py first",
)


def test_proxy_is_valid_mp4(tmp_path):
    """Encode a proxy and verify it is a valid 720p MP4."""
    out = tmp_path / "proxy.mp4"
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(TINY_CLIP),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-vf", "scale=-2:720", "-r", "30",
            "-an",
            str(out),
        ],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()
    data = assert_valid_mp4("ffprobe", out)
    streams = data["streams"]
    video = next(s for s in streams if s["codec_type"] == "video")
    assert video["height"] == 720


def test_audio_extraction_produces_wav(tmp_path):
    """Extract audio from tiny clip and verify WAV output."""
    out = tmp_path / "audio.wav"
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(TINY_CLIP),
            "-vn", "-ac", "1", "-ar", "44100", "-f", "wav",
            str(out),
        ],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert out.exists()
    assert out.stat().st_size > 44  # at least WAV header
