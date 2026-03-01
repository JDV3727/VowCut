#!/usr/bin/env python3
"""
Golden dataset regression runner (Phase 4, Prompt 16).

Usage:
  python scripts/run_golden.py --input /path/to/golden/dataset --output run_report.json

Golden dataset directory layout:
  golden/
    <case_name>/
      settings.json          (source_paths, song_path, target_length_s, etc.)
      expected_metrics.json  (expected duration_s ±5s, min_segments, etc.)

Produces run_report.json with per-case pass/fail and metric values.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import os
import time
import uuid
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.config import Settings
from backend.jobrunner import create_project, start_job
from backend.pipeline.validate import assert_valid_mp4, get_duration


async def _run_case(case_dir: Path, settings: Settings) -> dict:
    case_name = case_dir.name
    settings_file = case_dir / "settings.json"
    metrics_file = case_dir / "expected_metrics.json"

    if not settings_file.exists():
        return {"case": case_name, "status": "skip", "reason": "No settings.json"}

    job_settings = json.loads(settings_file.read_text())
    expected = json.loads(metrics_file.read_text()) if metrics_file.exists() else {}

    project_id = str(uuid.uuid4())
    start = time.time()

    try:
        pid, project_dir = create_project(
            settings,
            job_settings["source_paths"],
            job_settings.get("song_path"),
            project_id=project_id,
        )
        job_id = await start_job(settings, pid, project_dir)

        # Wait for completion (poll manifest)
        from backend.pipeline.utils import manifest_read

        for _ in range(600):  # 10 min max
            await asyncio.sleep(1)
            try:
                manifest = manifest_read(project_dir)
                if manifest.pipeline.overall_status in ("done", "error"):
                    break
            except Exception:
                pass

        manifest = manifest_read(project_dir)
        elapsed = time.time() - start

        if manifest.pipeline.overall_status != "done":
            return {
                "case": case_name,
                "status": "fail",
                "reason": manifest.pipeline.error or "Pipeline did not complete",
                "elapsed_s": elapsed,
            }

        export_path = project_dir / "exports" / "highlight.mp4"
        if not export_path.exists():
            return {"case": case_name, "status": "fail", "reason": "highlight.mp4 not found", "elapsed_s": elapsed}

        ffprobe = settings.ffprobe_path or "ffprobe"
        assert_valid_mp4(ffprobe, export_path)
        actual_duration = get_duration(ffprobe, export_path)

        metrics = {
            "duration_s": actual_duration,
            "elapsed_s": elapsed,
        }

        # Check expectations
        failures = []
        if "target_length_s" in expected:
            target = expected["target_length_s"]
            if abs(actual_duration - target) > 5:
                failures.append(f"duration {actual_duration:.1f}s vs target {target}s (>±5s)")

        status = "fail" if failures else "pass"
        return {
            "case": case_name,
            "status": status,
            "metrics": metrics,
            "failures": failures,
            "elapsed_s": elapsed,
        }

    except Exception as exc:
        return {
            "case": case_name,
            "status": "error",
            "reason": str(exc),
            "elapsed_s": time.time() - start,
        }


async def main(args) -> None:
    golden_root = Path(args.input)
    output_path = Path(args.output)

    if not golden_root.exists():
        print(f"ERROR: {golden_root} does not exist", file=sys.stderr)
        sys.exit(1)

    settings = Settings()
    cases = sorted(p for p in golden_root.iterdir() if p.is_dir())

    if not cases:
        print("No cases found in golden dataset directory.", file=sys.stderr)
        sys.exit(1)

    print(f"Running {len(cases)} golden case(s) …")
    results = []
    for case_dir in cases:
        print(f"  [{case_dir.name}] … ", end="", flush=True)
        result = await _run_case(case_dir, settings)
        status = result["status"]
        print(status)
        results.append(result)

    passed = sum(1 for r in results if r["status"] == "pass")
    failed = sum(1 for r in results if r["status"] in ("fail", "error"))

    report = {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "cases": results,
    }
    output_path.write_text(json.dumps(report, indent=2))
    print(f"\nReport written to {output_path}")
    print(f"  {passed}/{len(results)} passed")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VowCut golden dataset runner")
    parser.add_argument("--input", required=True, help="Path to golden dataset directory")
    parser.add_argument("--output", default="run_report.json", help="Output report path")
    asyncio.run(main(parser.parse_args()))
