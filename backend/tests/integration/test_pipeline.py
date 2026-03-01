"""
Integration test: end-to-end pipeline with tiny synthetic clip.
Requires ffmpeg on PATH and the tiny_clip.mp4 fixture (generate via scripts/gen_test_clip.py).
"""
from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

import pytest

from backend.pipeline.types import AccelInfo, Manifest, Source, SourceMetadata, StageStatuses, PipelineState, Versions
from backend.pipeline.utils import manifest_read, manifest_write, now_iso, make_project_dir

FIXTURES = Path(__file__).parent / "fixtures"
TINY_CLIP = FIXTURES / "tiny_clip.mp4"

pytestmark = pytest.mark.skipif(
    not TINY_CLIP.exists(),
    reason="tiny_clip.mp4 not found — run scripts/gen_test_clip.py first",
)


@pytest.fixture
def e2e_project(tmp_path: Path) -> tuple[Path, Manifest]:
    project_dir = make_project_dir(tmp_path, "e2e_test")

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
    return project_dir, manifest


def _make_emitter():
    """Create a no-op emitter for integration tests."""
    import asyncio
    from backend.pipeline.utils import ProgressEmitter

    loop = asyncio.new_event_loop()
    queue = asyncio.Queue()
    return ProgressEmitter(queue, loop)


class TestIngestStage:
    def test_ingest_fills_metadata(self, e2e_project):
        from backend.pipeline import ingest

        project_dir, manifest = e2e_project
        emitter = _make_emitter()
        result = ingest.run(project_dir, manifest, emitter)
        assert result.stage_status.ingest == "done"
        src = result.sources[0]
        assert src.metadata.width > 0
        assert src.metadata.duration_s > 0


class TestProxyStage:
    def test_proxy_creates_files(self, e2e_project):
        from backend.pipeline import ingest, proxies

        project_dir, manifest = e2e_project
        emitter = _make_emitter()
        manifest = ingest.run(project_dir, manifest, emitter)
        manifest = proxies.run(project_dir, manifest, emitter)

        assert manifest.stage_status.proxy == "done"
        assert manifest.sources[0].proxy_path is not None
        assert Path(manifest.sources[0].proxy_path).exists()
        assert manifest.sources[0].audio_path is not None
        assert Path(manifest.sources[0].audio_path).exists()
