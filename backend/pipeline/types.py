"""
Core dataclasses for VowCut pipeline.
All pipeline modules import from here — never define schema types elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


# ---------------------------------------------------------------------------
# Source metadata
# ---------------------------------------------------------------------------

@dataclass
class SourceMetadata:
    duration_s: float
    width: int
    height: int
    fps: float
    codec: str


@dataclass
class SyncInfo:
    offset_s: float = 0.0
    scale: float = 1.0
    sync_confidence: Literal["high", "medium", "low", "unset"] = "unset"


@dataclass
class Source:
    id: str
    original_path: str
    metadata: SourceMetadata
    proxy_path: Optional[str] = None
    audio_path: Optional[str] = None
    sync: SyncInfo = field(default_factory=SyncInfo)


# ---------------------------------------------------------------------------
# Acceleration / GPU info
# ---------------------------------------------------------------------------

@dataclass
class AccelInfo:
    ffmpeg_path: str
    ffprobe_path: str
    selected_encoder: str          # e.g. "h264_videotoolbox"
    validated: bool = False
    fallbacks_used: list[str] = field(default_factory=list)

    # hevc equivalent for final export
    hevc_encoder: str = "libx265"
    hevc_validated: bool = False


# ---------------------------------------------------------------------------
# Stage status
# ---------------------------------------------------------------------------

StageStatus = Literal["pending", "running", "done", "error", "skipped"]

@dataclass
class StageStatuses:
    ingest: StageStatus = "pending"
    proxy: StageStatus = "pending"
    align: StageStatus = "pending"
    features: StageStatus = "pending"
    music: StageStatus = "pending"
    assemble: StageStatus = "pending"
    export: StageStatus = "pending"


# ---------------------------------------------------------------------------
# Pipeline state
# ---------------------------------------------------------------------------

@dataclass
class PipelineState:
    overall_status: Literal["idle", "running", "done", "error"] = "idle"
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Manifest (top-level job state written to manifest.json)
# ---------------------------------------------------------------------------

@dataclass
class Versions:
    feature_version: str = "2"
    selection_version: str = "1"


@dataclass
class Manifest:
    schema_version: str
    job_id: str
    created_at: str
    updated_at: str

    sources: list[Source] = field(default_factory=list)
    song_path: Optional[str] = None

    accel: Optional[AccelInfo] = None
    versions: Versions = field(default_factory=Versions)

    stage_status: StageStatuses = field(default_factory=StageStatuses)
    pipeline: PipelineState = field(default_factory=PipelineState)


# ---------------------------------------------------------------------------
# Timeline / segments
# ---------------------------------------------------------------------------

@dataclass
class Segment:
    master_t0: float
    master_t1: float
    source_id: str

    @property
    def duration(self) -> float:
        return self.master_t1 - self.master_t0


@dataclass
class TimelineMetadata:
    encoder_used: str
    feature_version: str
    selection_version: str


@dataclass
class Timeline:
    schema_version: str
    target_length_s: float
    created_at: str
    metadata: TimelineMetadata
    segments: list[Segment] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Progress event (sent over SSE)
# ---------------------------------------------------------------------------

@dataclass
class ProgressEvent:
    step: str
    status: Literal["running", "done", "error", "warning"]
    progress: float          # 0.0 – 1.0
    detail: str = ""
    warning: Optional[str] = None


# ---------------------------------------------------------------------------
# Feature record (one per chunk per source, stored in features.db)
# ---------------------------------------------------------------------------

@dataclass
class ChunkFeature:
    source_id: str
    chunk_index: int
    t0: float
    t1: float
    activity: float        # mean inter-frame luma diff, normalised 0–1 (higher = more movement)
    stability: float       # inverse of frame-diff variance, 0–1 (higher = steadier camera)
    exposure: float        # luma-based exposure quality, 0–1 (peaks at mid-grey ≈ 128)
    rms: float
    onset_strength: float
