#!/usr/bin/env python3
"""
Generate a tiny synthetic test clip for integration tests.
Produces: backend/tests/integration/fixtures/tiny_clip.mp4

The clip is 10 seconds, 1280x720, 30fps, H.264 with a 440 Hz sine wave audio track.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

OUTPUT = Path(__file__).parent.parent / "backend" / "tests" / "integration" / "fixtures" / "tiny_clip.mp4"
DURATION = 10


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", f"testsrc=duration={DURATION}:size=1280x720:rate=30",
        "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={DURATION}",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "28",
        "-c:a", "aac",
        "-b:a", "128k",
        "-t", str(DURATION),
        "-movflags", "+faststart",
        str(OUTPUT),
    ]
    print(f"Generating {OUTPUT} ...")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("ERROR: ffmpeg failed", file=sys.stderr)
        sys.exit(1)
    print(f"Done — {OUTPUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
