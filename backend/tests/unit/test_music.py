"""Unit tests for music.py — beat snapping."""
from __future__ import annotations

import pytest

from backend.pipeline.music import snap_to_beat


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
