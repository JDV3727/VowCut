"""Unit tests for pipeline/utils.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.pipeline.utils import atomic_write, manifest_read, manifest_write, now_iso, to_json
from backend.pipeline.types import Manifest, PipelineState, StageStatuses, Versions


class TestAtomicWrite:
    def test_creates_file(self, tmp_path: Path):
        target = tmp_path / "out.json"
        atomic_write(target, '{"hello": "world"}')
        assert target.exists()
        assert json.loads(target.read_text()) == {"hello": "world"}

    def test_overwrites_existing(self, tmp_path: Path):
        target = tmp_path / "out.txt"
        target.write_text("old")
        atomic_write(target, "new")
        assert target.read_text() == "new"

    def test_creates_parent_dirs(self, tmp_path: Path):
        target = tmp_path / "a" / "b" / "c.txt"
        atomic_write(target, "content")
        assert target.read_text() == "content"


class TestManifestRoundtrip:
    def test_write_then_read(self, tmp_project: Path, sample_manifest: Manifest):
        # sample_manifest fixture already wrote it
        loaded = manifest_read(tmp_project)
        assert loaded.job_id == sample_manifest.job_id
        assert loaded.schema_version == "1.0"
        assert len(loaded.sources) == 1
        assert loaded.sources[0].id == "cam_a"

    def test_stage_statuses_preserved(self, tmp_project: Path, sample_manifest: Manifest):
        sample_manifest.stage_status.ingest = "done"
        manifest_write(tmp_project, sample_manifest)
        loaded = manifest_read(tmp_project)
        assert loaded.stage_status.ingest == "done"

    def test_accel_preserved(self, tmp_project: Path, sample_manifest: Manifest):
        loaded = manifest_read(tmp_project)
        assert loaded.accel is not None
        assert loaded.accel.selected_encoder == "libx264"
        assert loaded.accel.hevc_encoder == "libx265"
