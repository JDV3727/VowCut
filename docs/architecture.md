# VowCut Architecture

## Overview

VowCut is a local, cross-platform wedding highlight generator.
It consists of two processes:

```
┌─────────────────────────────────────────────┐
│  Electron (renderer: React + Zustand)       │
│  ┌──────────────────────────────────────┐   │
│  │  main process                        │   │
│  │  server-manager.ts → spawns Python   │   │
│  │  ipc-handlers.ts   → file dialogs    │   │
│  └──────────────────────────────────────┘   │
└──────────────────┬──────────────────────────┘
                   │ HTTP + SSE (localhost)
┌──────────────────▼──────────────────────────┐
│  Python FastAPI backend (uvicorn)           │
│  app.py → jobrunner.py → pipeline stages    │
└─────────────────────────────────────────────┘
```

## Process Communication

1. Electron `main.ts` spawns the Python backend as a child process.
2. `server-manager.ts` reads `PORT=<n>` from backend stdout, then passes the
   port to the renderer via `executeJavaScript`.
3. The renderer calls REST endpoints and subscribes to SSE for progress.

## Pipeline Stages (in order)

| Stage    | Module         | Purpose |
|----------|----------------|---------|
| ingest   | ingest.py      | ffprobe metadata extraction |
| proxy    | proxies.py     | 720p@30 H.264 + WAV audio |
| align    | align.py       | onset cross-correlation sync |
| features | features.py    | motion/RMS/onset → DuckDB |
| music    | music.py       | beat detection via librosa |
| assemble | assemble.py    | segment selection + cut decisions |
| export   | export.py      | ffmpeg concat + HEVC encode |

## State Management

- `manifest.json` is the single source of truth, written atomically after each stage.
- `manifest.settings_hashes` stores per-stage SHA256 hashes of each stage's inputs.
  Combined with `manifest.job_settings`, this drives cache invalidation: a stage is
  skipped only when its status is "done" AND its stored hash matches the current inputs.
- `manifest.job_settings` holds run-specific settings (target_length_s, export_mode,
  music_volume) written by the API before the pipeline starts.

## GPU Strategy

Detection runs once at startup (`accel.py`), validated with a 1-frame null encode.
See `docs/gpu-encode.md` for the full encoder priority list.
