/**
 * Typed API client for the VowCut FastAPI backend.
 */

function getBaseUrl(): string {
  const port = window.__BACKEND_PORT__ ?? 8000;
  return `http://127.0.0.1:${port}`;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${getBaseUrl()}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`Backend error ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export interface HealthResponse {
  status: "ok";
}

export const health = (): Promise<HealthResponse> =>
  request<HealthResponse>("/health");

// ---------------------------------------------------------------------------
// GPU info
// ---------------------------------------------------------------------------

export interface GpuInfoResponse {
  detected: boolean;
  h264_encoder?: string;
  hevc_encoder?: string;
  ffmpeg_path?: string;
  ffprobe_path?: string;
  fallbacks_used?: string[];
  error?: string;
}

export const gpuInfo = (): Promise<GpuInfoResponse> =>
  request<GpuInfoResponse>("/gpu-info");

// ---------------------------------------------------------------------------
// Project
// ---------------------------------------------------------------------------

export interface CreateProjectRequest {
  source_paths: string[];
  song_path?: string | null;
  project_id?: string | null;
}

export interface CreateProjectResponse {
  project_id: string;
  project_dir: string;
}

export const createProject = (
  body: CreateProjectRequest
): Promise<CreateProjectResponse> =>
  request<CreateProjectResponse>("/project/create", {
    method: "POST",
    body: JSON.stringify(body),
  });

export interface RunJobRequest {
  project_id: string;
  export_mode?: string;
  target_length_s?: number;
  music_volume?: number;
}

export interface RunJobResponse {
  job_id: string;
}

export const runJob = (body: RunJobRequest): Promise<RunJobResponse> =>
  request<RunJobResponse>("/project/run", {
    method: "POST",
    body: JSON.stringify(body),
  });

// ---------------------------------------------------------------------------
// Artifacts
// ---------------------------------------------------------------------------

export interface ArtifactsResponse {
  project_id: string;
  stage_status: Record<string, string>;
  proxies: { source_id: string; proxy_path: string | null; exists: boolean }[];
  timeline: string | null;
  export: string | null;
  warnings: string[];
}

export const getArtifacts = (projectId: string): Promise<ArtifactsResponse> =>
  request<ArtifactsResponse>(`/project/artifacts/${projectId}`);

// ---------------------------------------------------------------------------
// SSE progress stream
// ---------------------------------------------------------------------------

export interface ProgressEvent {
  step: string;
  status: "running" | "done" | "error" | "warning" | "heartbeat";
  progress: number;
  detail: string;
  warning: string | null;
}

export function subscribeToEvents(
  jobId: string,
  onEvent: (event: ProgressEvent) => void,
  onError?: (err: Event) => void
): () => void {
  const url = `${getBaseUrl()}/project/events/${jobId}`;
  const es = new EventSource(url);

  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data) as ProgressEvent;
      onEvent(data);
      if (data.status === "done" || data.status === "error") {
        if (data.step === "pipeline") es.close();
      }
    } catch {
      // ignore parse errors
    }
  };

  es.onerror = (e) => {
    onError?.(e);
    es.close();
  };

  return () => es.close();
}
