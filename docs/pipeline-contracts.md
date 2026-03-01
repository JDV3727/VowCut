# Pipeline Stage Contracts

Each stage follows a strict contract:

## Inputs
- `project_dir: Path` — directory containing `manifest.json`
- `manifest: Manifest` — current pipeline state (already read)
- `emitter: ProgressEmitter` — SSE event emitter

## Outputs
- Returns the (possibly mutated) `Manifest`
- Writes `manifest.json` atomically before returning
- Emits at least:
  - `emit(step, "running", 0.0, ...)` at start
  - `emit(step, "done", 1.0, ...)` on success
  - `emit(step, "error", progress, str(exc))` on failure

## Idempotency Rule
```python
if manifest.stage_status.<stage> == "done":
    emitter.emit(step, "done", 1.0, "Skipped (already done)")
    return manifest
```

## Error Handling
On any unhandled exception:
1. Set `manifest.stage_status.<stage> = "error"`
2. Set `manifest.pipeline.error = str(exc)`
3. Call `manifest_write(project_dir, manifest)`
4. Emit error event
5. Re-raise (jobrunner catches and terminates the pipeline)

## Segment Constraints (assemble stage)
- Min segment duration: 2.0s
- Max segment duration: 15.0s
- Beat snap window: ±150ms
- Output duration: within ±5s of target

## Song Export Rules
- Trim or loop to match output duration
- Fade in: 2s, fade out: 2s
- Volume: 0.6× (configurable)
- Music-only output (no ambient camera audio)
