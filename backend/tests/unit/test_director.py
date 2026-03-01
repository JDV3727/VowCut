"""Unit tests for director_v1.py — camera switching logic."""
from __future__ import annotations

import pytest

from backend.pipeline.director_v1 import (
    IMPROVEMENT_THRESHOLD,
    MAX_HOLD_S,
    MIN_HOLD_S,
    CameraDecision,
    decide_switches,
    score_all,
)
from backend.pipeline.types import ChunkFeature


def _make_features(source_id: str, scores: list[tuple[float, float, float]]) -> list[ChunkFeature]:
    return [
        ChunkFeature(
            source_id=source_id,
            chunk_index=i,
            t0=i * 2.0,
            t1=(i + 1) * 2.0,
            motion_score=m,
            rms=r,
            onset_strength=o,
        )
        for i, (m, r, o) in enumerate(scores)
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
