"""
FastAPI application factory + lifespan.

Endpoints:
  GET  /health
  GET  /gpu-info
  POST /project/create
  POST /project/run
  GET  /project/events/{job_id}
  GET  /project/artifacts/{project_id}
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .config import Settings, get_settings
from .jobrunner import create_project, get_job, list_jobs, sse_stream, start_job
from .pipeline import accel as accel_mod
from .pipeline.types import AccelInfo
from .pipeline.utils import manifest_read

logger = logging.getLogger(__name__)

# Cached GPU detection result
_accel_cache: Optional[AccelInfo] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _accel_cache
    settings = get_settings()
    logger.info("VowCut backend starting")
    try:
        _accel_cache = accel_mod.detect(
            ffmpeg_path=settings.ffmpeg_path or None,
            ffprobe_path=settings.ffprobe_path or None,
        )
        logger.info("GPU encoder: %s  HEVC: %s", _accel_cache.selected_encoder, _accel_cache.hevc_encoder)
    except Exception as exc:
        logger.warning("GPU detection failed: %s — will retry on first job", exc)
    yield
    logger.info("VowCut backend shutdown")


app = FastAPI(title="VowCut", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# GPU info
# ---------------------------------------------------------------------------

@app.get("/gpu-info")
async def gpu_info():
    if _accel_cache is None:
        return {"detected": False, "error": "GPU detection not yet run or failed"}
    return {
        "detected": True,
        "h264_encoder": _accel_cache.selected_encoder,
        "hevc_encoder": _accel_cache.hevc_encoder,
        "ffmpeg_path": _accel_cache.ffmpeg_path,
        "ffprobe_path": _accel_cache.ffprobe_path,
        "fallbacks_used": _accel_cache.fallbacks_used,
    }


# ---------------------------------------------------------------------------
# Project endpoints
# ---------------------------------------------------------------------------

class CreateProjectRequest(BaseModel):
    source_paths: list[str]
    song_path: Optional[str] = None
    project_id: Optional[str] = None


class CreateProjectResponse(BaseModel):
    project_id: str
    project_dir: str


@app.post("/project/create", response_model=CreateProjectResponse)
async def project_create(req: CreateProjectRequest):
    settings = get_settings()
    try:
        project_id, project_dir = create_project(
            settings,
            req.source_paths,
            req.song_path,
            req.project_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return CreateProjectResponse(project_id=project_id, project_dir=str(project_dir))


class RunJobRequest(BaseModel):
    project_id: str
    export_mode: str = "fast_gpu"
    target_length_s: float = 240.0
    music_volume: float = 0.6


class RunJobResponse(BaseModel):
    job_id: str


@app.post("/project/run", response_model=RunJobResponse)
async def project_run(req: RunJobRequest):
    settings = get_settings()
    project_dir = Path(settings.projects_base_dir) / req.project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project {req.project_id} not found")

    # Check for existing running job
    existing = get_job(req.project_id)
    if existing and existing.status == "running":
        return RunJobResponse(job_id=existing.job_id)

    job_id = await start_job(settings, req.project_id, project_dir)
    return RunJobResponse(job_id=job_id)


# ---------------------------------------------------------------------------
# SSE progress stream
# ---------------------------------------------------------------------------

@app.get("/project/events/{job_id}")
async def project_events(job_id: str):
    async def event_generator():
        async for event in sse_stream(job_id):
            data = json.dumps(event)
            yield f"data: {data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------

@app.get("/project/artifacts/{project_id}")
async def project_artifacts(project_id: str):
    settings = get_settings()
    project_dir = Path(settings.projects_base_dir) / project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    try:
        manifest = manifest_read(project_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot read manifest: {exc}")

    proxies = []
    for src in manifest.sources:
        proxies.append({
            "source_id": src.id,
            "proxy_path": src.proxy_path,
            "audio_path": src.audio_path,
            "exists": Path(src.proxy_path).exists() if src.proxy_path else False,
        })

    export_path = project_dir / "exports" / "highlight.mp4"
    timeline_path = project_dir / "timeline.json"

    return {
        "project_id": project_id,
        "stage_status": {
            "ingest": manifest.stage_status.ingest,
            "proxy": manifest.stage_status.proxy,
            "align": manifest.stage_status.align,
            "features": manifest.stage_status.features,
            "music": manifest.stage_status.music,
            "assemble": manifest.stage_status.assemble,
            "export": manifest.stage_status.export,
        },
        "proxies": proxies,
        "timeline": str(timeline_path) if timeline_path.exists() else None,
        "export": str(export_path) if export_path.exists() else None,
        "warnings": manifest.pipeline.warnings,
    }


# ---------------------------------------------------------------------------
# Entry point (used by server-manager.ts)
# ---------------------------------------------------------------------------

def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def serve():
    """
    Start uvicorn.  Print `PORT=<n>` to stdout so Electron can read it.
    """
    settings = get_settings()
    port = settings.port if settings.port > 0 else _find_free_port()
    print(f"PORT={port}", flush=True)
    uvicorn.run(
        "backend.app:app",
        host=settings.host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    serve()
