"""Unit tests for features.py — motion extraction."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from backend.pipeline.features import _extract_motion_scores, CHUNK_DURATION_S


class TestExtractMotionScores:
    def _make_result(self, returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
        r = MagicMock()
        r.returncode = returncode
        r.stdout = stdout
        r.stderr = stderr
        return r

    def _scene_output(self, pts_scores: list[tuple[float, float]]) -> str:
        """Build fake ffmpeg stdout matching the real format:
           frame:N    pts:M       pts_time:T
           lavfi.scene_score=V
        """
        lines = []
        for i, (pts, score) in enumerate(pts_scores):
            lines.append(f"frame:{i}    pts:{int(pts*512)}       pts_time:{pts}")
            lines.append(f"lavfi.scene_score={score}")
        return "\n".join(lines)

    def test_correct_chunk_count(self):
        duration_s = 10.0  # → 5 chunks at 2s each
        chunk_s = 2.0
        pts_scores = [(float(i), 0.1) for i in range(20)]  # 20 frames spread over 10s
        stdout = self._scene_output(pts_scores)

        with patch("subprocess.run", return_value=self._make_result(0, stdout=stdout)):
            scores = _extract_motion_scores("ffmpeg", "proxy.mp4", duration_s, chunk_s)

        assert len(scores) == 5

    def test_nonzero_returncode_raises(self):
        with patch("subprocess.run", return_value=self._make_result(1, stderr="error output")):
            with pytest.raises(RuntimeError, match="returncode=1"):
                _extract_motion_scores("ffmpeg", "proxy.mp4", 10.0)

    def test_all_zero_warns(self, caplog):
        """When no scene score lines are present, all scores are zero — warn."""
        import logging

        stdout = "some ffmpeg output with no scene_score lines"
        with patch("subprocess.run", return_value=self._make_result(0, stdout=stdout)):
            with caplog.at_level(logging.WARNING, logger="backend.pipeline.features"):
                scores = _extract_motion_scores("ffmpeg", "proxy.mp4", 10.0)

        assert all(s == 0.0 for s in scores)
        assert any("zero" in rec.message.lower() for rec in caplog.records)

    def test_pts_time_chunk_assignment(self):
        """Frames at pts 0.5 and 2.5 should land in chunk 0 and chunk 1 respectively."""
        duration_s = 6.0
        chunk_s = 2.0
        # pts 0.5 → chunk 0, pts 2.5 → chunk 1, pts 4.5 → chunk 2
        pts_scores = [(0.5, 0.8), (2.5, 0.4), (4.5, 0.6)]
        stdout = self._scene_output(pts_scores)

        with patch("subprocess.run", return_value=self._make_result(0, stdout=stdout)):
            scores = _extract_motion_scores("ffmpeg", "proxy.mp4", duration_s, chunk_s)

        assert len(scores) == 3
        assert scores[0] == pytest.approx(0.8)
        assert scores[1] == pytest.approx(0.4)
        assert scores[2] == pytest.approx(0.6)
