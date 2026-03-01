"""Unit tests for music.py — beat snapping and beat fallback."""
from __future__ import annotations

import unittest.mock as mock

import pytest

from backend.pipeline.music import snap_to_beat, _analyze_song, _MIN_BEATS


class TestSnapToBeat:
    def test_snaps_to_close_beat(self):
        beats = [1.0, 2.0, 3.0, 4.0]
        result = snap_to_beat(1.05, beats, max_offset_s=0.15)
        assert result == pytest.approx(1.0)

    def test_no_snap_when_outside_window(self):
        beats = [1.0, 2.0, 3.0]
        result = snap_to_beat(1.5, beats, max_offset_s=0.15)
        assert result == pytest.approx(1.5)

    def test_empty_beats_returns_t(self):
        assert snap_to_beat(2.5, [], 0.15) == pytest.approx(2.5)

    def test_snaps_to_nearest_not_first(self):
        beats = [0.0, 2.0, 4.0]
        result = snap_to_beat(3.9, beats, max_offset_s=0.15)
        assert result == pytest.approx(4.0)


class TestBeatFallback:
    def _make_fake_audio(self, tmp_path, duration_s: float = 5.0, sr: int = 16000):
        """Write a short silent wav file."""
        import numpy as np
        import soundfile as sf

        samples = (np.random.rand(int(sr * duration_s)) * 0.1).astype(np.float32)
        path = tmp_path / "song.wav"
        sf.write(str(path), samples, sr)
        return str(path)

    def test_beat_fallback_when_few_beats(self, tmp_path):
        """When beat_track returns fewer than _MIN_BEATS, beat_fallback=True in result."""
        import numpy as np

        song_path = self._make_fake_audio(tmp_path, duration_s=10.0)

        # Mock librosa.beat.beat_track to return only 1 beat
        with mock.patch("librosa.beat.beat_track") as mock_bt:
            mock_bt.return_value = (120.0, np.array([10]))  # 1 beat frame
            result = _analyze_song(song_path)

        assert result.get("beat_fallback") is True
        # Should have generated a uniform grid with multiple beats
        assert len(result["beats"]) >= _MIN_BEATS

    def test_no_fallback_with_enough_beats(self, tmp_path):
        """When beat_track returns >= _MIN_BEATS, beat_fallback key absent."""
        import numpy as np

        song_path = self._make_fake_audio(tmp_path, duration_s=10.0)

        # Mock beat_track to return 10 beat frames
        with mock.patch("librosa.beat.beat_track") as mock_bt:
            mock_bt.return_value = (120.0, np.arange(10))
            result = _analyze_song(song_path)

        assert "beat_fallback" not in result
