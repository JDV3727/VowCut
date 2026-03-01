"""
Integration tests for features.py — requires tiny_clip.mp4 fixture.
Run scripts/gen_test_clip.py first to generate the fixture.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from backend.pipeline.types import (
    AccelInfo,
    Manifest,
    PipelineState,
    Source,
    SourceMetadata,
    StageStatuses,
    Versions,
)
from backend.pipeline.utils import ProgressEmitter, make_project_dir, manifest_write, now_iso

FIXTURES = Path(__file__).parent / "fixtures"
TINY_CLIP = FIXTURES / "tiny_clip.mp4"

pytestmark = pytest.mark.skipif(
    not TINY_CLIP.exists(),
    reason="tiny_clip.mp4 not found — run scripts/gen_test_clip.py first",
)


def _make_emitter() -> ProgressEmitter:
    loop = asyncio.new_event_loop()
    return ProgressEmitter(asyncio.Queue(), loop)


@pytest.fixture
def features_project(tmp_path: Path) -> tuple[Path, Manifest]:
    """Run ingest + proxies for tiny_clip, then return project ready for features."""
    from backend.pipeline import ingest, proxies

    project_dir = make_project_dir(tmp_path, "feat_test")
    accel = AccelInfo(
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
        selected_encoder="libx264",
        validated=True,
        hevc_encoder="libx265",
        hevc_validated=True,
    )
    source = Source(
        id="cam_a",
        original_path=str(TINY_CLIP),
        metadata=SourceMetadata(duration_s=0.0, width=0, height=0, fps=0.0, codec=""),
    )
    manifest = Manifest(
        schema_version="1.0",
        job_id=str(uuid.uuid4()),
        created_at=now_iso(),
        updated_at=now_iso(),
        sources=[source],
        accel=accel,
        versions=Versions(),
        stage_status=StageStatuses(),
        pipeline=PipelineState(),
    )
    manifest_write(project_dir, manifest)

    emitter = _make_emitter()
    manifest = ingest.run(project_dir, manifest, emitter)
    manifest = proxies.run(project_dir, manifest, emitter)
    return project_dir, manifest


class TestFeaturesIntegration:
    def test_db_exists_after_run(self, features_project):
        from backend.pipeline import features

        project_dir, manifest = features_project
        emitter = _make_emitter()
        features.run(project_dir, manifest, emitter)

        db_path = project_dir / "features" / "features.db"
        assert db_path.exists()

    def test_nonzero_rows_in_db(self, features_project):
        from backend.pipeline import features
        from backend.pipeline.assemble import _load_features
        from backend.pipeline.features import DB_FILENAME

        project_dir, manifest = features_project
        emitter = _make_emitter()
        features.run(project_dir, manifest, emitter)

        db_path = project_dir / "features" / DB_FILENAME
        result = _load_features(db_path)
        total_rows = sum(len(v) for v in result.values())
        assert total_rows > 0

    def test_activity_scores_are_plausible(self, features_project):
        """At least one non-zero activity score should exist for a real video."""
        from backend.pipeline import features
        from backend.pipeline.assemble import _load_features
        from backend.pipeline.features import DB_FILENAME

        project_dir, manifest = features_project
        emitter = _make_emitter()
        features.run(project_dir, manifest, emitter)

        db_path = project_dir / "features" / DB_FILENAME
        result = _load_features(db_path)
        all_activity = [f.activity for feats in result.values() for f in feats]
        assert any(s > 0.0 for s in all_activity), "All activity scores are zero — signalstats likely broken"

    def test_idempotency(self, features_project):
        """Running features stage twice should produce the same row count."""
        from backend.pipeline import features
        from backend.pipeline.assemble import _load_features
        from backend.pipeline.features import DB_FILENAME

        project_dir, manifest = features_project
        emitter = _make_emitter()

        # First run
        manifest = features.run(project_dir, manifest, emitter)
        db_path = project_dir / "features" / DB_FILENAME
        count_first = sum(len(v) for v in _load_features(db_path).values())

        # Reset stage status to force re-run
        manifest.stage_status.features = "pending"

        # Second run
        features.run(project_dir, manifest, emitter)
        count_second = sum(len(v) for v in _load_features(db_path).values())

        assert count_first == count_second
