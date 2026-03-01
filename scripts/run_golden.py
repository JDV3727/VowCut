#!/usr/bin/env python3
"""
Golden dataset regression runner (Phase 4, Prompt 16).

Usage:
  python scripts/run_golden.py --input /path/to/golden/dataset --output run_report.json

Golden dataset directory layout:
  golden/
    <case_name>/
      settings.json          (source_paths, song_path, target_length_s, etc.)
      expected_metrics.json  (expected duration_s ±tol, min_segments, etc.)

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
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.config import Settings
from backend.jobrunner import create_project, start_job
from backend.pipeline.validate import assert_valid_mp4, get_duration

# ---------------------------------------------------------------------------
# Timeline structural validation
# ---------------------------------------------------------------------------

MIN_SEG_S = 0.5
MAX_SEG_S = 30.0


def _validate_timeline(
    project_dir: Path,
    target_length_s: float,
    tolerance_frac: float,
) -> list[str]:
    """
    Validate timeline.json structure. Returns a list of error strings
    (empty list = valid).
    """
    errors: list[str] = []
    timeline_path = project_dir / "timeline.json"

    if not timeline_path.exists():
        return ["timeline.json does not exist"]

    try:
        data = json.loads(timeline_path.read_text())
    except Exception as exc:
        return [f"timeline.json is not valid JSON: {exc}"]

    segments = data.get("segments", [])
    if not segments:
        errors.append("timeline contains no segments")
        return errors

    # Per-segment checks
    prev_t0 = -1.0
    total_duration = 0.0
    source_ids: set[str] = set()

    for i, seg in enumerate(segments):
        t0 = seg.get("master_t0", 0.0)
        t1 = seg.get("master_t1", 0.0)
        dur = t1 - t0
        source_ids.add(seg.get("source_id", ""))

        if dur < MIN_SEG_S:
            errors.append(f"segment[{i}] duration {dur:.3f}s < MIN_SEG_S ({MIN_SEG_S}s)")
        if dur > MAX_SEG_S:
            errors.append(f"segment[{i}] duration {dur:.3f}s > MAX_SEG_S ({MAX_SEG_S}s)")
        if t0 < prev_t0:
            errors.append(
                f"segment[{i}] master_t0={t0:.3f} is before previous segment's t0={prev_t0:.3f} "
                "(not chronologically sorted)"
            )
        prev_t0 = t0
        total_duration += dur

    # Total duration check
    tolerance_s = max(5.0, target_length_s * tolerance_frac)
    if abs(total_duration - target_length_s) > tolerance_s:
        errors.append(
            f"total timeline duration {total_duration:.1f}s differs from "
            f"target {target_length_s}s by more than ±{tolerance_s:.1f}s"
        )

    return errors, source_ids  # type: ignore[return-value]


def _validate_timeline_full(
    project_dir: Path,
    target_length_s: float,
    expected: dict,
) -> tuple[list[str], set[str]]:
    """
    Run full timeline validation and return (errors, source_ids).
    source_ids is the set of distinct source_id values found in the timeline.
    """
    tolerance_frac = expected.get("duration_tolerance_frac", 0.05)
    result = _validate_timeline(project_dir, target_length_s, tolerance_frac)

    # _validate_timeline returns early with a list if file is missing or unparseable
    if isinstance(result, list):
        return result, set()

    errors, source_ids = result
    return errors, source_ids


# ---------------------------------------------------------------------------
# Case runner
# ---------------------------------------------------------------------------

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
    target_length_s = job_settings.get("target_length_s", 240.0)

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
            # Include stage_status detail in failure report
            stage_detail = {
                stage: getattr(manifest.stage_status, stage, "unknown")
                for stage in ("ingest", "proxy", "align", "features", "music", "assemble", "export")
            }
            return {
                "case": case_name,
                "status": "fail",
                "reason": manifest.pipeline.error or "Pipeline did not complete",
                "stage_status": stage_detail,
                "elapsed_s": elapsed,
            }

        export_path = project_dir / "exports" / "highlight.mp4"
        if not export_path.exists():
            return {
                "case": case_name,
                "status": "fail",
                "reason": "highlight.mp4 not found",
                "elapsed_s": elapsed,
            }

        ffprobe = settings.ffprobe_path or "ffprobe"
        assert_valid_mp4(ffprobe, export_path)
        actual_duration = get_duration(ffprobe, export_path)

        metrics = {
            "duration_s": actual_duration,
            "elapsed_s": elapsed,
        }

        # Check expectations
        failures: list[str] = []
        tolerance_frac = expected.get("duration_tolerance_frac", 0.05)

        if "target_length_s" in expected:
            target = expected["target_length_s"]
            tolerance_s = max(5.0, target * tolerance_frac)
            if abs(actual_duration - target) > tolerance_s:
                failures.append(
                    f"duration {actual_duration:.1f}s vs target {target}s "
                    f"(>±{tolerance_s:.1f}s)"
                )

        # Timeline structural validation
        timeline_errors, source_ids = _validate_timeline_full(
            project_dir, target_length_s, expected
        )
        failures.extend(timeline_errors)

        # 2-cam validation
        min_source_ids = expected.get("min_source_ids")
        if min_source_ids is not None:
            if len(source_ids) < min_source_ids:
                failures.append(
                    f"timeline uses {len(source_ids)} distinct source_id(s), "
                    f"expected at least {min_source_ids}"
                )

        if "min_segments" in expected:
            # Count segments for metrics
            try:
                tl_data = json.loads((project_dir / "timeline.json").read_text())
                n_segs = len(tl_data.get("segments", []))
                metrics["segment_count"] = n_segs
                if n_segs < expected["min_segments"]:
                    failures.append(
                        f"only {n_segs} segment(s), expected >= {expected['min_segments']}"
                    )
            except Exception:
                pass

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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

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
