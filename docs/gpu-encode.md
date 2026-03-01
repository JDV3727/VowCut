# GPU Encoding Strategy

## Detection

`accel.py` runs once at startup. For each encoder candidate it runs a 1-frame
null encode to confirm the encoder is actually functional (not just compiled in):

```bash
ffmpeg -f lavfi -i color=black:s=128x72:r=1 -frames:v 1 -c:v <encoder> -f null -
```

## H.264 Proxy Priority

| Platform | Priority |
|----------|----------|
| macOS    | `h264_videotoolbox` → `libx264` |
| Windows  | `h264_nvenc` → `h264_qsv` → `h264_amf` → `libx264` |
| Linux    | `h264_nvenc` → `h264_vaapi` → `libx264` |

Proxy settings: 720p @ 30fps, speed-optimized.

## HEVC Final Export Priority

| Platform | Priority |
|----------|----------|
| macOS    | `hevc_videotoolbox` → `libx265` |
| Windows  | `hevc_nvenc` → `hevc_qsv` → `libx265` |
| Linux    | `hevc_nvenc` → `hevc_vaapi` → `libx265` |

## Export Modes

### `fast_gpu`
Uses the detected HEVC encoder with quality-balanced settings:
- `hevc_videotoolbox`: `-q:v 60`
- `hevc_nvenc`: `-preset slow -rc vbr -cq 24`
- `hevc_qsv`: `-global_quality 24`
- CPU fallback: `libx265 -crf 20 -preset medium`

### `high_quality_cpu`
Always uses `libx265 -crf 20 -preset medium`, regardless of GPU availability.
Use this for archival-quality exports or when GPU artifacts are suspected.
