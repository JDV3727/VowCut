"""
Shared pytest fixtures.
"""
from __future__ import annotations

import json
import tempfile
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
    SyncInfo,
    Versions,
)
from backend.pipeline.utils import manifest_write, now_iso


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal project directory with manifest."""
    for sub in ("originals", "proxies", "audio", "features", "exports", "logs"):
        (tmp_path / sub).mkdir()
    return tmp_path


@pytest.fixture
def sample_accel() -> AccelInfo:
    return AccelInfo(
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
        selected_encoder="libx264",
        validated=True,
        fallbacks_used=[],
        hevc_encoder="libx265",
        hevc_validated=True,
    )


@pytest.fixture
def sample_manifest(tmp_project: Path, sample_accel: AccelInfo) -> Manifest:
    source = Source(
        id="cam_a",
        original_path="/tmp/cam_a.mp4",
        metadata=SourceMetadata(duration_s=60.0, width=1280, height=720, fps=30.0, codec="h264"),
        proxy_path=str(tmp_project / "proxies" / "cam_a_proxy.mp4"),
        audio_path=str(tmp_project / "audio" / "cam_a.wav"),
        sync=SyncInfo(offset_s=0.0, scale=1.0, sync_confidence="high"),
    )
    manifest = Manifest(
        schema_version="1.0",
        job_id=str(uuid.uuid4()),
        created_at=now_iso(),
        updated_at=now_iso(),
        sources=[source],
        song_path=None,
        accel=sample_accel,
        versions=Versions(),
        stage_status=StageStatuses(),
        pipeline=PipelineState(),
    )
    manifest_write(tmp_project, manifest)
    return manifest


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "integration" / "fixtures"
