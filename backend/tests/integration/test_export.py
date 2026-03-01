"""Integration test: export stage produces a valid MP4."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from backend.pipeline.types import (
    AccelInfo,
    Manifest,
    PipelineState,
    Segment,
    Source,
    SourceMetadata,
    StageStatuses,
    SyncInfo,
    Timeline,
    TimelineMetadata,
    Versions,
)
from backend.pipeline.utils import make_project_dir, manifest_write, now_iso, timeline_write
from backend.pipeline.validate import assert_valid_mp4

FIXTURES = Path(__file__).parent / "fixtures"
TINY_CLIP = FIXTURES / "tiny_clip.mp4"

pytestmark = pytest.mark.skipif(
    not TINY_CLIP.exists(),
    reason="tiny_clip.mp4 not found — run scripts/gen_test_clip.py first",
)


def _make_emitter():
    import asyncio
    from backend.pipeline.utils import ProgressEmitter
    loop = asyncio.new_event_loop()
    return ProgressEmitter(asyncio.Queue(), loop)


def test_export_produces_valid_mp4(tmp_path):
    from backend.pipeline import export as export_mod, ingest, proxies

    project_dir = make_project_dir(tmp_path, "export_test")
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
        metadata=SourceMetadata(0.0, 0, 0, 0.0, ""),
        sync=SyncInfo(0.0, 1.0, "high"),
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

    # Run ingest to get real duration
    manifest = ingest.run(project_dir, manifest, emitter)
    duration = manifest.sources[0].metadata.duration_s

    # Write a manual timeline covering the whole clip
    timeline = Timeline(
        schema_version="1.0",
        target_length_s=duration,
        created_at=now_iso(),
        metadata=TimelineMetadata(encoder_used="libx265", feature_version="1", selection_version="1"),
        segments=[Segment(master_t0=0.0, master_t1=duration, source_id="cam_a")],
    )
    timeline_write(project_dir, timeline)
    manifest.stage_status.assemble = "done"

    # Run export
    manifest = export_mod.run(project_dir, manifest, emitter, export_mode="high_quality_cpu")
    assert manifest.stage_status.export == "done"

    output = project_dir / "exports" / "highlight.mp4"
    assert output.exists()
    assert_valid_mp4("ffprobe", output)
