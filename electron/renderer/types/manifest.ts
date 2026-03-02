/**
 * TypeScript equivalents of the Python manifest dataclasses.
 * Keep in sync with backend/pipeline/types.py.
 */

export type StageStatus = "pending" | "running" | "done" | "error" | "skipped";

export interface SourceMetadata {
  duration_s: number;
  width: number;
  height: number;
  fps: number;
  codec: string;
}

export interface SyncInfo {
  offset_s: number;
  scale: number;
  sync_confidence: "high" | "medium" | "low" | "unset";
}

export interface Source {
  id: string;
  original_path: string;
  metadata: SourceMetadata;
  proxy_path: string | null;
  audio_path: string | null;
  sync: SyncInfo;
}

export interface AccelInfo {
  ffmpeg_path: string;
  ffprobe_path: string;
  selected_encoder: string;
  validated: boolean;
  fallbacks_used: string[];
  hevc_encoder: string;
  hevc_validated: boolean;
}

export interface StageStatuses {
  ingest: StageStatus;
  proxy: StageStatus;
  align: StageStatus;
  features: StageStatus;
  music: StageStatus;
  assemble: StageStatus;
  export: StageStatus;
}

export interface PipelineState {
  overall_status: "idle" | "running" | "done" | "error";
  error: string | null;
  warnings: string[];
}

export interface SettingsHashes {
  ingest: string;
  proxy: string;
  align: string;
  features: string;
  music: string;
  assemble: string;
  export: string;
}

export interface JobSettings {
  target_length_s: number;
  export_mode: string;
  music_volume: number;
}

export interface Manifest {
  schema_version: string;
  job_id: string;
  created_at: string;
  updated_at: string;
  sources: Source[];
  song_path: string | null;
  accel: AccelInfo | null;
  versions: { feature_version: string; selection_version: string };
  stage_status: StageStatuses;
  pipeline: PipelineState;
  settings_hashes: SettingsHashes;
  job_settings: JobSettings;
}

export interface Segment {
  master_t0: number;
  master_t1: number;
  source_id: string;
}

export interface Timeline {
  schema_version: string;
  target_length_s: number;
  created_at: string;
  metadata: {
    encoder_used: string;
    feature_version: string;
    selection_version: string;
  };
  segments: Segment[];
}
