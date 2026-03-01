#!/usr/bin/env python3
"""
Detect and display GPU encoder availability.
Usage: python scripts/check_gpu.py
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.pipeline.accel import detect


def main() -> None:
    print("Detecting GPU encoders …")
    try:
        info = detect()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"  ffmpeg:          {info.ffmpeg_path}")
    print(f"  ffprobe:         {info.ffprobe_path}")
    print(f"  H.264 encoder:   {info.selected_encoder}")
    print(f"  HEVC encoder:    {info.hevc_encoder}")
    if info.fallbacks_used:
        print(f"  Fallbacks tried: {', '.join(info.fallbacks_used)}")
    print("GPU check complete.")


if __name__ == "__main__":
    main()
