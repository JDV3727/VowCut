"""Unit tests for accel.py — GPU detection and encoder arg builders."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.pipeline.accel import (
    _encoder_works,
    _select_encoder,
    ffmpeg_export_args,
    ffmpeg_proxy_args,
)
from backend.pipeline.types import AccelInfo


class TestEncoderWorks:
    def test_returns_false_on_nonzero_exit(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            assert _encoder_works("ffmpeg", "bad_encoder") is False

    def test_returns_true_on_zero_exit(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            assert _encoder_works("ffmpeg", "libx264") is True

    def test_returns_false_on_file_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert _encoder_works("bad_ffmpeg", "libx264") is False

    def test_returns_false_on_timeout(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 15)):
            assert _encoder_works("ffmpeg", "libx264") is False


class TestSelectEncoder:
    def test_picks_first_working(self):
        def works(ffmpeg, enc):
            return enc == "h264_videotoolbox"

        with patch("backend.pipeline.accel._encoder_works", side_effect=works):
            chosen, fallbacks = _select_encoder("ffmpeg", ["h264_videotoolbox", "libx264"])
        assert chosen == "h264_videotoolbox"
        assert fallbacks == []

    def test_falls_back_when_first_fails(self):
        def works(ffmpeg, enc):
            return enc == "libx264"

        with patch("backend.pipeline.accel._encoder_works", side_effect=works):
            chosen, fallbacks = _select_encoder("ffmpeg", ["h264_nvenc", "libx264"])
        assert chosen == "libx264"
        assert "h264_nvenc" in fallbacks

    def test_raises_when_all_fail(self):
        with patch("backend.pipeline.accel._encoder_works", return_value=False):
            with pytest.raises(RuntimeError, match="No working encoder"):
                _select_encoder("ffmpeg", ["bad1", "bad2"])


class TestArgBuilders:
    def _accel(self, h264: str = "libx264", hevc: str = "libx265") -> AccelInfo:
        return AccelInfo(
            ffmpeg_path="ffmpeg",
            ffprobe_path="ffprobe",
            selected_encoder=h264,
            validated=True,
            hevc_encoder=hevc,
            hevc_validated=True,
        )

    def test_proxy_libx264(self):
        args = ffmpeg_proxy_args(self._accel("libx264"))
        assert "-c:v" in args
        assert "libx264" in args
        assert "scale=-2:720" in " ".join(args)

    def test_proxy_videotoolbox(self):
        args = ffmpeg_proxy_args(self._accel("h264_videotoolbox"))
        assert "h264_videotoolbox" in args

    def test_export_cpu_mode(self):
        args = ffmpeg_export_args(self._accel(hevc="hevc_videotoolbox"), mode="high_quality_cpu")
        assert "libx265" in args
        assert "20" in args  # crf 20

    def test_export_gpu_hevc(self):
        args = ffmpeg_export_args(self._accel(hevc="hevc_videotoolbox"), mode="fast_gpu")
        assert "hevc_videotoolbox" in args
