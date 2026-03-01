# Manifest Schema

See `backend/schemas/manifest.schema.json` for the full JSON Schema.

## Key Fields

### `stage_status`
Values: `"pending"` | `"running"` | `"done"` | `"error"` | `"skipped"`

Each stage transitions: `pending → running → done` (or `error`).
The jobrunner skips stages already `"done"`.

### `sources[*].sync`
Set by the align stage:
- `offset_s`: seconds to add to timeline timestamps for this source
- `scale`: clock drift correction (V1 always 1.0)
- `sync_confidence`: `"high"` | `"medium"` | `"low"` | `"unset"`

### `accel`
Set once at startup. Contains validated encoder names and ffmpeg/ffprobe paths.

### `pipeline.overall_status`
Set by jobrunner: `"idle"` → `"running"` → `"done"` or `"error"`.

## Atomic Writes
`manifest.json` is always written via a temp-file rename (see `utils.atomic_write`).
This prevents partial reads if the process is killed mid-write.
