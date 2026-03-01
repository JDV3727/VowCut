"""
Cache invalidation helpers for VowCut pipeline stages.

Each stage's hash = SHA256(sorted_JSON({upstream_stored_hashes, own_new_inputs})).
Downstream stages inherit stale state automatically: when an upstream hash
changes, the downstream hash will differ from its stored value → re-runs.

Stage dependency graph:
  ingest ──► proxy ──► align
                  └──► features ──► assemble ──► export
  music  ──────────────────────────►
"""
from __future__ import annotations

from .types import Manifest
from .utils import _file_mtime, compute_hash


# ---------------------------------------------------------------------------
# Hash computation per stage
# ---------------------------------------------------------------------------

def compute_stage_hash(stage: str, manifest: Manifest) -> str:
    """Return the current (freshly computed) hash for *stage*."""
    sh = manifest.settings_hashes
    js = manifest.job_settings

    if stage == "ingest":
        data = {
            "source_paths": sorted(s.original_path for s in manifest.sources),
            "source_mtimes": sorted(
                _file_mtime(s.original_path) or "missing"
                for s in manifest.sources
            ),
        }

    elif stage == "proxy":
        data = {
            "upstream_ingest": sh.ingest,
            "resolution": "1280x720",
            "fps": 30,
        }

    elif stage == "align":
        data = {
            "upstream_proxy": sh.proxy,
        }

    elif stage == "features":
        data = {
            "upstream_proxy": sh.proxy,
            "chunk_duration_s": 2.0,
            "feature_version": manifest.versions.feature_version,
        }

    elif stage == "music":
        data = {
            "song_path": manifest.song_path,
            "song_mtime": _file_mtime(manifest.song_path),
        }

    elif stage == "assemble":
        data = {
            "upstream_features": sh.features,
            "upstream_align": sh.align,
            "upstream_music": sh.music,
            "selection_version": manifest.versions.selection_version,
            "target_length_s": js.target_length_s,
        }

    elif stage == "export":
        data = {
            "upstream_assemble": sh.assemble,
            "export_mode": js.export_mode,
            "music_volume": js.music_volume,
            "hevc_encoder": manifest.accel.hevc_encoder if manifest.accel else "libx265",
        }

    else:
        raise ValueError(f"Unknown stage: {stage!r}")

    return compute_hash(data)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_cached(stage: str, manifest: Manifest) -> bool:
    """Return True iff the stage status is 'done' AND the stored hash matches."""
    status = getattr(manifest.stage_status, stage, "pending")
    if status != "done":
        return False
    stored = getattr(manifest.settings_hashes, stage, "")
    current = compute_stage_hash(stage, manifest)
    return stored == current


def store_hash(stage: str, manifest: Manifest) -> None:
    """Write the current hash for *stage* into manifest.settings_hashes (in-place)."""
    current = compute_stage_hash(stage, manifest)
    setattr(manifest.settings_hashes, stage, current)
