# VowCut

Local, cross-platform wedding highlight generator.

**Architecture:** Electron UI + Python FastAPI backend + chunked processing pipeline.

## Quick Start

### macOS / Linux
```bash
bash scripts/setup.sh
cd backend && source .venv/bin/activate
pytest                           # run all tests
python -m backend.app            # start backend on random port
```

### Windows
```powershell
.\scripts\setup.ps1
cd backend; .\.venv\Scripts\Activate.ps1
pytest
python -m backend.app
```

## Manual API test
```bash
# Health check
curl http://localhost:8000/health

# GPU info
curl http://localhost:8000/gpu-info

# Create a project
curl -X POST http://localhost:8000/project/create \
  -H "Content-Type: application/json" \
  -d '{"source_paths": ["/path/to/cam_a.mp4"], "song_path": "/path/to/song.mp3"}'

# Start processing (use project_id from above)
curl -X POST http://localhost:8000/project/run \
  -H "Content-Type: application/json" \
  -d '{"project_id": "<id>"}'

# Stream progress (SSE)
curl -N http://localhost:8000/project/events/<job_id>
```

## Project Structure

```
VowCut/
├── backend/          Python FastAPI backend + pipeline
├── electron/         Electron + React frontend
├── scripts/          Setup and utility scripts
└── docs/             Architecture and schema docs
```

See `docs/architecture.md` for a full system overview.

## V1 Acceptance Criteria

- First run < 60 min (2 cams, GPU enabled)
- Regenerate (cached) < 1 min
- Output duration within ±5s of target
- Works on clean Windows + macOS install
