# VowCut

GPU-accelerated, local 1–2 camera 4K60 wedding highlight generator producing 3–5 minute music-driven montage videos with beat-aware cuts and stable switching.

## Overview

VowCut takes footage from up to two cameras and automatically assembles a polished wedding highlight reel. Cuts are driven by music beats, segments are kept concise, and the entire pipeline runs locally on GPU hardware.

## Features

- GPU-accelerated processing
- 1–2 camera support with timestamp-based alignment
- 4K @ 60fps output
- 3–5 minute music-driven highlight montage
- Beat-aware cuts
- Stable multi-camera switching
- Segment lengths between 2–15 seconds
- Music-only audio output (no ambient mixing)

## Scope

### V1 — In Scope

- 1–2 cameras only
- Timestamp-based alignment (no drift modeling)
- Music-only output (no ambient mixing)
- Segment lengths 2–15 seconds

### Out of Scope (Future Versions)

- 3+ cameras
- Speech detection
- Face detection
- Documentary full-length edits
