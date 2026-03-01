"""Unit tests for assemble.py — segment selection logic."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from backend.pipeline.assemble import (
    MIN_SEG_S, MAX_SEG_S, CHUNK_DURATION_S,
    _decisions_to_segments, _greedy_1cam, _load_features,
)
from backend.pipeline.director_v1 import CameraDecision
from backend.pipeline.types import ChunkFeature


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


def _make_chunk(source_id: str, chunk_index: int, t0: float, t1: float, score: float) -> ChunkFeature:
    return ChunkFeature(
        source_id=source_id,
        chunk_index=chunk_index,
        t0=t0,
        t1=t1,
        motion_score=score,
        rms=score,
        onset_strength=score,
    )


class TestEmptyFeaturesGuard:
    def test_empty_db_raises(self, tmp_path):
        """_load_features returning {} should cause run() to raise RuntimeError."""
        import asyncio
        import uuid
        from backend.pipeline.types import (
            AccelInfo, Manifest, PipelineState, Source, SourceMetadata,
            StageStatuses, SyncInfo, Versions,
        )
        from backend.pipeline.utils import ProgressEmitter, manifest_write, now_iso, make_project_dir
        from backend.pipeline import assemble

        project_dir = make_project_dir(tmp_path, "test_empty")
        accel = AccelInfo(
            ffmpeg_path="ffmpeg", ffprobe_path="ffprobe",
            selected_encoder="libx264", validated=True,
            hevc_encoder="libx265", hevc_validated=True,
        )
        source = Source(
            id="cam_a",
            original_path="/tmp/cam_a.mp4",
            metadata=SourceMetadata(duration_s=30.0, width=1280, height=720, fps=30.0, codec="h264"),
        )
        manifest = Manifest(
            schema_version="1.0", job_id=str(uuid.uuid4()),
            created_at=now_iso(), updated_at=now_iso(),
            sources=[source], accel=accel,
            versions=Versions(), stage_status=StageStatuses(), pipeline=PipelineState(),
        )
        manifest_write(project_dir, manifest)

        # Create features dir + empty DB
        (project_dir / "features").mkdir(exist_ok=True)
        import duckdb
        db_path = project_dir / "features" / "features.db"
        con = duckdb.connect(str(db_path))
        con.execute("""
            CREATE TABLE IF NOT EXISTS chunk_features (
                source_id VARCHAR, chunk_index INTEGER, t0 DOUBLE, t1 DOUBLE,
                motion_score DOUBLE, rms DOUBLE, onset_strength DOUBLE,
                PRIMARY KEY (source_id, chunk_index)
            )
        """)
        con.close()

        loop = asyncio.new_event_loop()
        emitter = ProgressEmitter(asyncio.Queue(), loop)

        with pytest.raises(RuntimeError, match="no rows"):
            assemble.run(project_dir, manifest, emitter)


class TestGreedy1Cam:
    def _make_feats(self, n: int, scores: list[float] | None = None) -> list[ChunkFeature]:
        s = scores or [float(i) / n for i in range(n)]
        return [_make_chunk("cam_a", i, i * 2.0, (i + 1) * 2.0, s[i]) for i in range(n)]

    def test_greedy_fills_target(self):
        """Total duration should be within ±5s of target_length_s."""
        n = 50  # 50 * 2s = 100s total available
        feats = self._make_feats(n, scores=[0.5] * n)
        scores = [0.5] * n
        target = 30.0

        segs = _greedy_1cam(scores, feats, target_length_s=target, beats=[])
        total = sum(s.master_t1 - s.master_t0 for s in segs)
        assert abs(total - target) <= 5.0

    def test_greedy_is_chronological(self):
        """Segments must be sorted by master_t0 after selection."""
        n = 20
        # Highest scores at the end to force non-trivial sort
        scores = list(range(n))
        feats = self._make_feats(n, scores=scores)

        segs = _greedy_1cam([float(s) for s in scores], feats, target_length_s=20.0, beats=[])
        t0s = [s.master_t0 for s in segs]
        assert t0s == sorted(t0s)

    def test_greedy_picks_high_score_chunks(self):
        """With ample budget, the highest-scoring chunks should be selected."""
        n = 10
        # Only the last 3 chunks have high scores
        scores = [0.0] * 7 + [1.0, 1.0, 1.0]
        feats = self._make_feats(n, scores=scores)

        # Budget for 3 segments (3 * 2s = 6s)
        segs = _greedy_1cam(scores, feats, target_length_s=6.0, beats=[])
        selected_t0s = {s.master_t0 for s in segs}
        # The three high-score chunks start at 14, 16, 18
        assert selected_t0s == {14.0, 16.0, 18.0}
