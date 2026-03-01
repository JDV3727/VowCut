"""Unit tests for assemble.py — segment selection logic."""
from __future__ import annotations

import pytest

from backend.pipeline.assemble import MIN_SEG_S, MAX_SEG_S, _decisions_to_segments
from backend.pipeline.director_v1 import CameraDecision


def _decision(t0: float, t1: float, sid: str = "cam_a") -> CameraDecision:
    return CameraDecision(t0=t0, t1=t1, source_id=sid, score=0.5)


class TestDecisionsToSegments:
    def test_basic_conversion(self):
        decisions = [_decision(0.0, 10.0)]
        segs = _decisions_to_segments(decisions, target_length_s=30.0, beats=[])
        assert len(segs) == 1
        assert segs[0].source_id == "cam_a"
        assert segs[0].duration == pytest.approx(10.0)

    def test_short_segments_filtered(self):
        decisions = [_decision(0.0, 1.0), _decision(1.0, 10.0)]  # first < MIN_SEG_S
        segs = _decisions_to_segments(decisions, target_length_s=30.0, beats=[])
        assert all(s.duration >= MIN_SEG_S for s in segs)

    def test_long_segments_clamped(self):
        decisions = [_decision(0.0, 60.0)]  # > MAX_SEG_S
        segs = _decisions_to_segments(decisions, target_length_s=60.0, beats=[])
        assert all(s.duration <= MAX_SEG_S for s in segs)

    def test_total_capped_at_target(self):
        decisions = [_decision(0.0, 10.0), _decision(10.0, 20.0), _decision(20.0, 30.0)]
        segs = _decisions_to_segments(decisions, target_length_s=15.0, beats=[])
        total = sum(s.duration for s in segs)
        assert total <= 15.0 + 0.01

    def test_beat_snap_applied(self):
        decisions = [_decision(0.0, 5.0)]
        beats = [0.0, 5.1]  # 5.0 should snap to 5.1? No — 5.1 is 0.1s away, within 0.15
        segs = _decisions_to_segments(decisions, target_length_s=30.0, beats=beats)
        assert segs[0].master_t1 == pytest.approx(5.1)
