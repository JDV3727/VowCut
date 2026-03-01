"""Unit tests for director_v1.py — camera switching logic."""
from __future__ import annotations

import pytest

from backend.pipeline.director_v1 import (
    IMPROVEMENT_THRESHOLD,
    MAX_HOLD_S,
    MIN_HOLD_S,
    CameraDecision,
    _tiered_force_threshold,
    decide_switches,
    decide_switches_beat_aligned,
    score_all,
)
from backend.pipeline.types import ChunkFeature


def _make_features(source_id: str, scores: list[tuple[float, float, float]]) -> list[ChunkFeature]:
    """Create ChunkFeatures. Tuple is (quality, rms, onset); quality maps to activity=stability=exposure."""
    return [
        ChunkFeature(
            source_id=source_id,
            chunk_index=i,
            t0=i * 2.0,
            t1=(i + 1) * 2.0,
            activity=q,
            stability=q,
            exposure=q,
            rms=r,
            onset_strength=o,
        )
        for i, (q, r, o) in enumerate(scores)
    ]


class TestScoreAll:
    def test_single_source_normalized_0_to_1(self):
        feats = _make_features("cam_a", [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)])
        result = score_all({"cam_a": feats})
        assert len(result["cam_a"]) == 2
        assert result["cam_a"][0] == pytest.approx(0.0)
        assert result["cam_a"][1] == pytest.approx(1.0)

    def test_two_sources_global_normalization(self):
        a = _make_features("cam_a", [(0.5, 0.5, 0.5)])
        b = _make_features("cam_b", [(1.0, 1.0, 1.0)])
        result = score_all({"cam_a": a, "cam_b": b})
        assert result["cam_b"][0] > result["cam_a"][0]


class TestDecideSwitches:
    def test_single_source_no_switch(self):
        scores = {"cam_a": [0.5, 0.6, 0.4, 0.7]}
        decisions = decide_switches(scores, chunk_duration_s=2.0)
        # Single source — one big block
        assert all(d.source_id == "cam_a" for d in decisions)

    def test_switches_when_improvement_exceeds_threshold(self):
        # cam_b has much higher score after chunk 2
        scores = {
            "cam_a": [0.9, 0.9, 0.1, 0.1, 0.1],
            "cam_b": [0.0, 0.0, 0.9, 0.9, 0.9],
        }
        decisions = decide_switches(scores, chunk_duration_s=2.0)
        source_ids = [d.source_id for d in decisions]
        assert "cam_a" in source_ids
        assert "cam_b" in source_ids

    def test_min_hold_enforced(self):
        # cam_b slightly better from chunk 1, but shouldn't switch before MIN_HOLD_S
        scores = {
            "cam_a": [0.8, 0.4],
            "cam_b": [0.1, 0.9],
        }
        decisions = decide_switches(scores, chunk_duration_s=1.0)  # 1s chunks → MIN_HOLD=2s means must hold ≥2 chunks
        # Should NOT switch at chunk 1 since 1 chunk = 1s < MIN_HOLD_S=2s
        assert decisions[0].source_id == "cam_a"

    def test_empty_scores_returns_empty(self):
        assert decide_switches({}) == []

    def test_total_coverage(self):
        scores = {"cam_a": [0.5] * 10, "cam_b": [0.8] * 10}
        decisions = decide_switches(scores, chunk_duration_s=2.0)
        total = sum(d.t1 - d.t0 for d in decisions)
        assert abs(total - 20.0) < 0.1  # 10 chunks * 2s

    def test_force_cut_requires_improvement_threshold(self):
        """Force-cut at MAX_HOLD_S should NOT fire if alternative cam is only 2% better."""
        chunk_s = 1.0
        n = 20
        # cam_a dominant at chunk 0 → algorithm starts on cam_a.
        # From chunk 1 onward cam_b is only 2% better → below IMPROVEMENT_THRESHOLD (15%).
        # Force-cut (at 15s) requires 15% improvement, so no switch should occur.
        cam_a = [1.0] + [1.0] * (n - 1)
        cam_b = [0.0] + [1.02] * (n - 1)  # terrible at start, 2% better afterward

        decisions = decide_switches(
            {"cam_a": cam_a, "cam_b": cam_b},
            chunk_duration_s=chunk_s,
        )
        # Should stay on cam_a the entire time (2% < IMPROVEMENT_THRESHOLD=15%)
        assert all(d.source_id == "cam_a" for d in decisions)

    def test_beats_param_removed_from_signature(self):
        """decide_switches must not accept beats or beat_snap_s as parameters."""
        import inspect
        sig = inspect.signature(decide_switches)
        assert "beats" not in sig.parameters
        assert "beat_snap_s" not in sig.parameters


class TestTieredForceThreshold:
    def test_short_hold_returns_full_threshold(self):
        assert _tiered_force_threshold(10.0) == pytest.approx(IMPROVEMENT_THRESHOLD)

    def test_medium_hold_returns_reduced_threshold(self):
        assert _tiered_force_threshold(30.0) == pytest.approx(0.08)

    def test_long_hold_returns_minimal_threshold(self):
        assert _tiered_force_threshold(50.0) == pytest.approx(0.01)

    def test_threshold_decreases_monotonically(self):
        t10 = _tiered_force_threshold(10.0)
        t30 = _tiered_force_threshold(30.0)
        t50 = _tiered_force_threshold(50.0)
        assert t10 >= t30 >= t50


class TestDecideSwitchesBeatAligned:
    def test_falls_back_when_no_beats(self):
        """Empty beats list → falls back to decide_switches output."""
        scores = {"cam_a": [0.9, 0.9, 0.1], "cam_b": [0.0, 0.0, 0.9]}
        result_beat = decide_switches_beat_aligned(
            scores, beats=[], total_duration_s=6.0, chunk_duration_s=2.0
        )
        result_chunk = decide_switches(scores, chunk_duration_s=2.0)
        # Both should produce same source sequence
        assert [d.source_id for d in result_beat] == [d.source_id for d in result_chunk]

    def test_empty_scores_returns_empty(self):
        assert decide_switches_beat_aligned({}, beats=[0.0, 2.0], total_duration_s=4.0) == []

    def test_cuts_happen_at_beat_positions(self):
        """Switch boundaries must align with beat timestamps."""
        # cam_a dominates beats 0–4; cam_b dominates from beat 4 onward
        scores = {
            "cam_a": [1.0, 1.0, 0.0, 0.0, 0.0],  # chunks 0–1 good, 2–4 bad
            "cam_b": [0.0, 0.0, 1.0, 1.0, 1.0],  # chunks 0–1 bad, 2–4 good
        }
        beats = [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]
        decisions = decide_switches_beat_aligned(
            scores, beats=beats, total_duration_s=10.0, chunk_duration_s=2.0
        )
        # Every t0 and t1 boundary must be a beat position
        beat_set = set(beats)
        for dec in decisions:
            assert dec.t0 in beat_set or dec.t0 == 0.0
            assert dec.t1 in beat_set or dec.t1 == 10.0

    def test_starts_on_best_camera_at_first_beat(self):
        """Should start on cam_b when it scores higher at the first beat."""
        scores = {
            "cam_a": [0.2, 0.2],
            "cam_b": [0.9, 0.9],
        }
        beats = [0.0, 2.0]
        decisions = decide_switches_beat_aligned(
            scores, beats=beats, total_duration_s=4.0, chunk_duration_s=2.0
        )
        assert decisions[0].source_id == "cam_b"

    def test_last_segment_closes_at_total_duration(self):
        """Final segment t1 must equal total_duration_s."""
        scores = {"cam_a": [0.5, 0.5, 0.5], "cam_b": [0.3, 0.3, 0.3]}
        beats = [0.0, 2.0, 4.0]
        total = 7.5
        decisions = decide_switches_beat_aligned(
            scores, beats=beats, total_duration_s=total, chunk_duration_s=2.0
        )
        assert decisions[-1].t1 == pytest.approx(total)
