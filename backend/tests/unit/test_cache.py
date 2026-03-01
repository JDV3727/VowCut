"""Unit tests for pipeline/cache.py."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from backend.pipeline.cache import compute_stage_hash, is_cached, store_hash
from backend.pipeline.types import (
    AccelInfo,
    JobSettings,
    Manifest,
    PipelineState,
    SettingsHashes,
    Source,
    SourceMetadata,
    StageStatuses,
    SyncInfo,
    Versions,
)
from backend.pipeline.utils import now_iso


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manifest(
    source_paths: list[str] | None = None,
    song_path: str | None = None,
    feature_version: str = "2",
    selection_version: str = "1",
    target_length_s: float = 240.0,
    export_mode: str = "fast_gpu",
    music_volume: float = 0.6,
    stage_status: StageStatuses | None = None,
    settings_hashes: SettingsHashes | None = None,
) -> Manifest:
    if source_paths is None:
        source_paths = ["/tmp/cam_a.mp4"]

    sources = [
        Source(
            id=f"cam_{chr(ord('a') + i)}",
            original_path=p,
            metadata=SourceMetadata(60.0, 1280, 720, 30.0, "h264"),
        )
        for i, p in enumerate(source_paths)
    ]

    return Manifest(
        schema_version="1.0",
        job_id=str(uuid.uuid4()),
        created_at=now_iso(),
        updated_at=now_iso(),
        sources=sources,
        song_path=song_path,
        accel=AccelInfo(
            ffmpeg_path="ffmpeg",
            ffprobe_path="ffprobe",
            selected_encoder="libx264",
            validated=True,
            hevc_encoder="libx265",
            hevc_validated=True,
        ),
        versions=Versions(feature_version=feature_version, selection_version=selection_version),
        stage_status=stage_status or StageStatuses(),
        pipeline=PipelineState(),
        settings_hashes=settings_hashes or SettingsHashes(),
        job_settings=JobSettings(
            target_length_s=target_length_s,
            export_mode=export_mode,
            music_volume=music_volume,
        ),
    )


# ---------------------------------------------------------------------------
# Hash computation tests
# ---------------------------------------------------------------------------

class TestComputeStageHash:
    def test_ingest_hash_changes_with_source_path(self):
        m1 = _make_manifest(source_paths=["/tmp/cam_a.mp4"])
        m2 = _make_manifest(source_paths=["/tmp/cam_b.mp4"])
        assert compute_stage_hash("ingest", m1) != compute_stage_hash("ingest", m2)

    def test_proxy_hash_inherits_ingest(self):
        m1 = _make_manifest()
        m2 = _make_manifest()
        # Same manifest → same proxy hash
        assert compute_stage_hash("proxy", m1) == compute_stage_hash("proxy", m2)

        # Simulate ingest having run on m2 with a stored hash
        m2.settings_hashes.ingest = "abc123"
        assert compute_stage_hash("proxy", m1) != compute_stage_hash("proxy", m2)

    def test_features_hash_changes_with_version(self):
        m1 = _make_manifest(feature_version="2")
        m2 = _make_manifest(feature_version="3")
        assert compute_stage_hash("features", m1) != compute_stage_hash("features", m2)

    def test_assemble_hash_changes_with_target(self):
        m1 = _make_manifest(target_length_s=240.0)
        m2 = _make_manifest(target_length_s=180.0)
        assert compute_stage_hash("assemble", m1) != compute_stage_hash("assemble", m2)

    def test_unknown_stage_raises(self):
        m = _make_manifest()
        with pytest.raises(ValueError, match="Unknown stage"):
            compute_stage_hash("nonexistent", m)


# ---------------------------------------------------------------------------
# is_cached tests
# ---------------------------------------------------------------------------

class TestIsCached:
    def test_is_cached_false_when_pending(self):
        m = _make_manifest(stage_status=StageStatuses(ingest="pending"))
        assert not is_cached("ingest", m)

    def test_is_cached_false_when_hash_differs(self):
        m = _make_manifest(
            stage_status=StageStatuses(ingest="done"),
            settings_hashes=SettingsHashes(ingest="wronghash"),
        )
        assert not is_cached("ingest", m)

    def test_is_cached_true_when_done_and_hash_matches(self):
        m = _make_manifest(stage_status=StageStatuses(ingest="done"))
        # Store the correct hash
        current = compute_stage_hash("ingest", m)
        m.settings_hashes.ingest = current
        assert is_cached("ingest", m)


# ---------------------------------------------------------------------------
# store_hash tests
# ---------------------------------------------------------------------------

class TestStoreHash:
    def test_store_hash_then_is_cached(self):
        m = _make_manifest(stage_status=StageStatuses(ingest="done"))
        # Before storing: hash is empty, so not cached
        assert not is_cached("ingest", m)

        store_hash("ingest", m)
        assert is_cached("ingest", m)

    def test_store_hash_updates_value(self):
        m = _make_manifest()
        store_hash("ingest", m)
        expected = compute_stage_hash("ingest", m)
        assert m.settings_hashes.ingest == expected
