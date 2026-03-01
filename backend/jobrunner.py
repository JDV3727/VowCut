"""
Job lifecycle orchestrator.

Responsibilities:
- Accept a job request and run stages in order.
- Emit SSE ProgressEvents via per-job asyncio.Queue.
- Skip-if-done contract: each stage is only run if its status != "done".
- Store job state in an in-memory registry keyed by job_id.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from .config import Settings
from .pipeline import accel as accel_mod
from .pipeline import align, assemble, export, features, ingest, music, proxies
from .pipeline import cache
from .pipeline.types import AccelInfo, Manifest, Source, SourceMetadata, StageStatuses, PipelineState, Versions
from .pipeline.utils import (
    ProgressEmitter,
    make_project_dir,
    manifest_read,
    manifest_write,
    now_iso,
)

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="vowcut-job")


@dataclass
class JobRecord:
    job_id: str
    project_id: str
    project_dir: Path
    status: str = "pending"         # pending | running | done | error
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    loop: Optional[asyncio.AbstractEventLoop] = None
    error: Optional[str] = None


# In-memory job registry
_jobs: dict[str, JobRecord] = {}


def get_job(job_id: str) -> Optional[JobRecord]:
    return _jobs.get(job_id)


def list_jobs() -> list[JobRecord]:
    return list(_jobs.values())


async def sse_stream(job_id: str) -> AsyncGenerator[dict, None]:
    """Yield SSE dicts from the job's progress queue until the job finishes."""
    job = _jobs.get(job_id)
    if job is None:
        yield {"step": "error", "status": "error", "progress": 0, "detail": f"Unknown job {job_id}"}
        return

    while True:
        try:
            event = await asyncio.wait_for(job.queue.get(), timeout=30)
            yield event
            if event.get("status") in ("done", "error") and event.get("step") == "pipeline":
                break
        except asyncio.TimeoutError:
            yield {"step": "heartbeat", "status": "running", "progress": -1, "detail": ""}


# ---------------------------------------------------------------------------
# Job creation
# ---------------------------------------------------------------------------

def create_project(
    settings: Settings,
    source_paths: list[str],
    song_path: Optional[str],
    project_id: Optional[str] = None,
) -> tuple[str, Path]:
    """
    Create project directory + initial manifest.json.
    Returns (project_id, project_dir).
    """
    pid = project_id or str(uuid.uuid4())
    project_dir = make_project_dir(Path(settings.projects_base_dir), pid)

    # Detect GPU once (cached in accel singleton)
    detected = accel_mod.detect()

    sources = [
        Source(
            id=f"cam_{chr(ord('a') + i)}",
            original_path=p,
            metadata=SourceMetadata(0.0, 0, 0, 0.0, ""),
        )
        for i, p in enumerate(source_paths)
    ]

    manifest = Manifest(
        schema_version="1.0",
        job_id=pid,
        created_at=now_iso(),
        updated_at=now_iso(),
        sources=sources,
        song_path=song_path,
        accel=detected,
        versions=Versions(),
        stage_status=StageStatuses(),
        pipeline=PipelineState(),
    )
    manifest_write(project_dir, manifest)
    return pid, project_dir


# ---------------------------------------------------------------------------
# Pipeline runner (runs in thread pool)
# ---------------------------------------------------------------------------

def _run_pipeline(job: JobRecord, settings: Settings) -> None:
    """Execute all pipeline stages. Runs in a thread pool executor."""
    loop = job.loop
    emitter = ProgressEmitter(job.queue, loop)

    try:
        manifest = manifest_read(job.project_dir)
        manifest.pipeline.overall_status = "running"
        manifest_write(job.project_dir, manifest)

        js = manifest.job_settings

        # Stage order
        stages = [
            ("ingest",   lambda pd, m, e: ingest.run(pd, m, e)),
            ("proxy",    lambda pd, m, e: proxies.run(pd, m, e)),
            ("align",    lambda pd, m, e: align.run(pd, m, e)),
            ("features", lambda pd, m, e: features.run(pd, m, e)),
            ("music",    lambda pd, m, e: music.run(pd, m, e)),
            ("assemble", lambda pd, m, e: assemble.run(pd, m, e, target_length_s=js.target_length_s)),
            ("export",   lambda pd, m, e: export.run(pd, m, e, export_mode=js.export_mode, music_volume=js.music_volume)),
        ]

        for stage_name, stage_fn in stages:
            if cache.is_cached(stage_name, manifest):
                emitter.emit(stage_name, "done", 1.0, "Skipped (cached)")
                continue
            manifest = stage_fn(job.project_dir, manifest, emitter)
            cache.store_hash(stage_name, manifest)
            manifest_write(job.project_dir, manifest)

        manifest.pipeline.overall_status = "done"
        manifest_write(job.project_dir, manifest)
        emitter.emit("pipeline", "done", 1.0, "All stages complete")
        job.status = "done"

    except Exception as exc:
        logger.exception("Pipeline error for job %s", job.job_id)
        job.status = "error"
        job.error = str(exc)
        try:
            manifest = manifest_read(job.project_dir)
            manifest.pipeline.overall_status = "error"
            manifest.pipeline.error = str(exc)
            manifest_write(job.project_dir, manifest)
        except Exception:
            pass
        emitter.emit("pipeline", "error", 0.0, str(exc))


async def start_job(
    settings: Settings,
    project_id: str,
    project_dir: Path,
) -> str:
    """Schedule the pipeline and return job_id."""
    job = JobRecord(
        job_id=project_id,
        project_id=project_id,
        project_dir=project_dir,
        loop=asyncio.get_event_loop(),
    )
    _jobs[job.job_id] = job
    job.status = "running"

    loop = asyncio.get_event_loop()
    loop.run_in_executor(_executor, _run_pipeline, job, settings)

    return job.job_id
