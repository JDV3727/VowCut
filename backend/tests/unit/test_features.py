"""Unit tests for features.py — video feature extraction via signalstats."""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from backend.pipeline.features import _extract_video_features, CHUNK_DURATION_S


class TestExtractVideoFeatures:
    def _make_result(self, returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
        r = MagicMock()
        r.returncode = returncode
        r.stdout = stdout
        r.stderr = stderr
        return r

    def _signalstats_output(
        self,
        frames: list[tuple[float, float, float]],  # (pts_time, ydif, yavg)
    ) -> str:
        """Build fake ffmpeg stdout matching the signalstats format:
           frame:N    pts:M       pts_time:T
           lavfi.signalstats.YAVG=V
           lavfi.signalstats.YDIF=V
        """
        lines = []
        for i, (pts, ydif, yavg) in enumerate(frames):
            lines.append(f"frame:{i}    pts:{int(pts * 512)}       pts_time:{pts}")
            lines.append(f"lavfi.signalstats.YAVG={yavg}")
            lines.append(f"lavfi.signalstats.YDIF={ydif}")
        return "\n".join(lines)

    def test_correct_chunk_count(self):
        """Return exactly n_chunks values for each output list."""
        duration_s = 10.0  # 5 chunks at 2s each
        frames = [(float(i) * 0.5, 10.0, 128.0) for i in range(20)]
        stdout = self._signalstats_output(frames)

        with patch("subprocess.run", return_value=self._make_result(0, stdout=stdout)):
            activity, stability, exposure = _extract_video_features("ffmpeg", "proxy.mp4", duration_s)

        assert len(activity) == 5
        assert len(stability) == 5
        assert len(exposure) == 5

    def test_nonzero_returncode_raises(self):
        with patch("subprocess.run", return_value=self._make_result(1, stderr="ffmpeg error")):
            with pytest.raises(RuntimeError, match="returncode=1"):
                _extract_video_features("ffmpeg", "proxy.mp4", 10.0)

    def test_all_zero_activity_warns(self, caplog):
        """No YDIF lines → all activity=0.0 → warning logged."""
        stdout = "frame:0    pts:0       pts_time:0\nlavfi.signalstats.YAVG=128.0\n"
        with patch("subprocess.run", return_value=self._make_result(0, stdout=stdout)):
            with caplog.at_level(logging.WARNING, logger="backend.pipeline.features"):
                activity, _, _ = _extract_video_features("ffmpeg", "proxy.mp4", 4.0)

        assert all(a == 0.0 for a in activity)
        assert any("zero" in rec.message.lower() for rec in caplog.records)

    def test_pts_time_chunk_assignment_and_values(self):
        """Verify activity, stability, and exposure are derived correctly per chunk."""
        # chunk 0 (t=0–2s): two frames with constant YDIF=15, YAVG=128
        # chunk 1 (t=2–4s): two frames with constant YDIF=6,  YAVG=50
        frames = [
            (0.0, 15.0, 128.0), (0.5, 15.0, 128.0),   # chunk 0
            (2.0,  6.0,  50.0), (2.5,  6.0,  50.0),   # chunk 1
        ]
        stdout = self._signalstats_output(frames)

        with patch("subprocess.run", return_value=self._make_result(0, stdout=stdout)):
            activity, stability, exposure = _extract_video_features("ffmpeg", "proxy.mp4", 4.0, chunk_s=2.0)

        # Chunk 0: mean_ydif=15 → activity=15/30=0.5; std_ydif=0 → stability=1.0; yavg=128 → exposure=1.0
        assert activity[0] == pytest.approx(0.5)
        assert stability[0] == pytest.approx(1.0)
        assert exposure[0] == pytest.approx(1.0)

        # Chunk 1: mean_ydif=6 → activity=6/30=0.2; std_ydif=0 → stability=1.0; yavg=50 → exposure=1-(78/128)=0.391
        assert activity[1] == pytest.approx(0.2)
        assert stability[1] == pytest.approx(1.0)
        assert exposure[1] == pytest.approx(1.0 - 78.0 / 128.0, abs=0.01)

    def test_stability_decreases_with_shaky_camera(self):
        """High variance in YDIF (shaky camera) should reduce stability below 1.0."""
        # Chunk 0: alternating low/high YDIF → high std → lower stability
        frames = [
            (0.0, 0.0, 128.0),
            (0.5, 30.0, 128.0),
            (1.0, 0.0, 128.0),
            (1.5, 30.0, 128.0),
        ]
        stdout = self._signalstats_output(frames)

        with patch("subprocess.run", return_value=self._make_result(0, stdout=stdout)):
            _, stability, _ = _extract_video_features("ffmpeg", "proxy.mp4", 2.0, chunk_s=2.0)

        # std ≈ 15 → stability = 1/(1+15/10) = 1/2.5 = 0.4
        assert stability[0] < 0.6

    def test_exposure_penalises_dark_and_blown_out(self):
        """Very dark (YAVG≈5) and blown-out (YAVG≈250) shots get low exposure scores."""
        frames_dark = [(0.0, 5.0, 5.0), (0.5, 5.0, 5.0)]
        frames_blown = [(2.0, 5.0, 250.0), (2.5, 5.0, 250.0)]
        frames_good = [(4.0, 5.0, 128.0), (4.5, 5.0, 128.0)]
        stdout = self._signalstats_output(frames_dark + frames_blown + frames_good)

        with patch("subprocess.run", return_value=self._make_result(0, stdout=stdout)):
            _, _, exposure = _extract_video_features("ffmpeg", "proxy.mp4", 6.0, chunk_s=2.0)

        assert exposure[0] < exposure[2]   # dark < neutral
        assert exposure[1] < exposure[2]   # blown-out < neutral
        assert exposure[2] == pytest.approx(1.0)  # neutral exposure = 1.0
