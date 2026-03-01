"""
Shared utilities: atomic file writes, manifest I/O, progress emission.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncGenerator

from .types import Manifest, ProgressEvent, Segment, Source, Timeline

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

class _DataclassEncoder(json.JSONEncoder):
    """Serialize dataclasses and Paths to JSON-safe types."""

    def default(self, obj: Any) -> Any:
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return dataclasses.asdict(obj)
        if isinstance(obj, Path):
            return str(obj)
        return super().default(obj)


def to_json(obj: Any, indent: int = 2) -> str:
    return json.dumps(obj, cls=_DataclassEncoder, indent=indent)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Atomic file write (write to tmp, then rename)
# ---------------------------------------------------------------------------

def atomic_write(path: Path | str, content: str) -> None:
    """Write *content* to *path* atomically (same filesystem)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------

def _dict_to_manifest(d: dict) -> Manifest:
    """Reconstruct a Manifest dataclass from a raw dict (loaded from JSON)."""
    from .types import (
        AccelInfo,
        PipelineState,
        Source,
        SourceMetadata,
        StageStatuses,
        SyncInfo,
        Versions,
    )

    sources = []
    for s in d.get("sources", []):
        meta = s.get("metadata", {})
        sync = s.get("sync", {})
        sources.append(
            Source(
                id=s["id"],
                original_path=s["original_path"],
                metadata=SourceMetadata(
                    duration_s=meta.get("duration_s", 0.0),
                    width=meta.get("width", 0),
                    height=meta.get("height", 0),
                    fps=meta.get("fps", 0.0),
                    codec=meta.get("codec", ""),
                ),
                proxy_path=s.get("proxy_path"),
                audio_path=s.get("audio_path"),
                sync=SyncInfo(
                    offset_s=sync.get("offset_s", 0.0),
                    scale=sync.get("scale", 1.0),
                    sync_confidence=sync.get("sync_confidence", "unset"),
                ),
            )
        )

    accel_d = d.get("accel")
    accel = None
    if accel_d:
        accel = AccelInfo(
            ffmpeg_path=accel_d.get("ffmpeg_path", "ffmpeg"),
            ffprobe_path=accel_d.get("ffprobe_path", "ffprobe"),
            selected_encoder=accel_d.get("selected_encoder", "libx264"),
            validated=accel_d.get("validated", False),
            fallbacks_used=accel_d.get("fallbacks_used", []),
            hevc_encoder=accel_d.get("hevc_encoder", "libx265"),
            hevc_validated=accel_d.get("hevc_validated", False),
        )

    ver_d = d.get("versions", {})
    ss_d = d.get("stage_status", {})
    pl_d = d.get("pipeline", {})

    return Manifest(
        schema_version=d.get("schema_version", "1.0"),
        job_id=d.get("job_id", str(uuid.uuid4())),
        created_at=d.get("created_at", now_iso()),
        updated_at=d.get("updated_at", now_iso()),
        sources=sources,
        song_path=d.get("song_path"),
        accel=accel,
        versions=Versions(
            feature_version=ver_d.get("feature_version", "1"),
            selection_version=ver_d.get("selection_version", "1"),
        ),
        stage_status=StageStatuses(
            ingest=ss_d.get("ingest", "pending"),
            proxy=ss_d.get("proxy", "pending"),
            align=ss_d.get("align", "pending"),
            features=ss_d.get("features", "pending"),
            music=ss_d.get("music", "pending"),
            assemble=ss_d.get("assemble", "pending"),
            export=ss_d.get("export", "pending"),
        ),
        pipeline=PipelineState(
            overall_status=pl_d.get("overall_status", "idle"),
            error=pl_d.get("error"),
            warnings=pl_d.get("warnings", []),
        ),
    )


def manifest_read(project_dir: Path) -> Manifest:
    data = json.loads((project_dir / "manifest.json").read_text())
    return _dict_to_manifest(data)


def manifest_write(project_dir: Path, manifest: Manifest) -> None:
    manifest.updated_at = now_iso()
    atomic_write(project_dir / "manifest.json", to_json(manifest))


# ---------------------------------------------------------------------------
# Timeline I/O
# ---------------------------------------------------------------------------

def timeline_read(project_dir: Path) -> Timeline:
    from .types import TimelineMetadata

    d = json.loads((project_dir / "timeline.json").read_text())
    meta = d.get("metadata", {})
    segments = [
        Segment(
            master_t0=s["master_t0"],
            master_t1=s["master_t1"],
            source_id=s["source_id"],
        )
        for s in d.get("segments", [])
    ]
    return Timeline(
        schema_version=d.get("schema_version", "1.0"),
        target_length_s=d.get("target_length_s", 240.0),
        created_at=d.get("created_at", now_iso()),
        metadata=TimelineMetadata(
            encoder_used=meta.get("encoder_used", ""),
            feature_version=meta.get("feature_version", "1"),
            selection_version=meta.get("selection_version", "1"),
        ),
        segments=segments,
    )


def timeline_write(project_dir: Path, timeline: Timeline) -> None:
    atomic_write(project_dir / "timeline.json", to_json(timeline))


# ---------------------------------------------------------------------------
# Progress emitter
# ---------------------------------------------------------------------------

class ProgressEmitter:
    """
    Puts ProgressEvent dicts into an asyncio.Queue that an SSE endpoint drains.
    Thread-safe via run_coroutine_threadsafe when called from a thread pool.
    """

    def __init__(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
        self._queue = queue
        self._loop = loop

    def emit(
        self,
        step: str,
        status: str,
        progress: float,
        detail: str = "",
        warning: str | None = None,
    ) -> None:
        event = {
            "step": step,
            "status": status,
            "progress": round(progress, 4),
            "detail": detail,
            "warning": warning,
        }
        if self._loop.is_running():
            # Called from a worker thread while the event loop runs in main thread
            asyncio.run_coroutine_threadsafe(self._queue.put(event), self._loop)
        else:
            # Loop not running (e.g. synchronous tests) — use non-blocking put
            self._queue.put_nowait(event)

    async def aemit(
        self,
        step: str,
        status: str,
        progress: float,
        detail: str = "",
        warning: str | None = None,
    ) -> None:
        event = {
            "step": step,
            "status": status,
            "progress": round(progress, 4),
            "detail": detail,
            "warning": warning,
        }
        await self._queue.put(event)


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

def make_project_dir(base: Path, project_id: str) -> Path:
    project_dir = base / project_id
    for sub in ("originals", "proxies", "audio", "features", "exports", "logs"):
        (project_dir / sub).mkdir(parents=True, exist_ok=True)
    return project_dir


def log_path(project_dir: Path, stage: str) -> Path:
    return project_dir / "logs" / f"{stage}.log"
