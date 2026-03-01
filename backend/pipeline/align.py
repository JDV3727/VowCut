"""
Align stage: timestamp-based offset computation and sync validation.

Strategy (V1): uses audio onset cross-correlation to compute offset_s between
each camera and cam_a (reference). Falls back to offset=0.0 with confidence=low
if not enough onset density is detected.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np

from .types import Manifest, SyncInfo
from .utils import ProgressEmitter, log_path, manifest_write

logger = logging.getLogger(__name__)


def _load_wav_mono(wav_path: str) -> tuple[np.ndarray, int]:
    """Load a WAV file as mono float32. Returns (samples, sample_rate)."""
    import soundfile as sf

    data, sr = sf.read(wav_path, dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data, sr


def _onset_envelope(samples: np.ndarray, sr: int, hop_length: int = 512) -> np.ndarray:
    """Compute onset strength envelope using librosa."""
    import librosa

    return librosa.onset.onset_strength(y=samples, sr=sr, hop_length=hop_length)


def _xcorr_offset(ref: np.ndarray, sig: np.ndarray, sr_hop: float) -> tuple[float, float]:
    """
    Compute offset via normalized cross-correlation.

    Returns (offset_s, confidence) where confidence is the peak correlation value.
    offset_s > 0 means *sig* starts later than *ref*.
    """
    # Trim to same length for speed
    n = min(len(ref), len(sig), int(sr_hop * 600))  # max 600 hops (≈5 min)
    ref = ref[:n]
    sig = sig[:n]

    # Normalize
    ref = ref - ref.mean()
    sig = sig - sig.mean()
    ref_std = ref.std() or 1.0
    sig_std = sig.std() or 1.0

    corr = np.correlate(ref / ref_std, sig / sig_std, mode="full")
    peak_idx = int(np.argmax(corr))
    confidence = float(corr[peak_idx]) / max(n, 1)

    lag = peak_idx - (n - 1)
    hop_duration_s = 512 / (sr_hop or 44100)
    offset_s = lag * hop_duration_s
    return offset_s, confidence


CONFIDENCE_THRESHOLD = 0.3  # below this → low confidence, offset forced to 0


def _align_pair(
    ref_wav: str,
    src_wav: str,
) -> SyncInfo:
    ref_samples, ref_sr = _load_wav_mono(ref_wav)
    src_samples, src_sr = _load_wav_mono(src_wav)

    # Dead audio guard: silent source cannot be aligned
    if src_samples.std() < 1e-7:
        return SyncInfo(offset_s=0.0, scale=1.0, sync_confidence="low")

    # Resample to common SR if needed (simple: use librosa)
    if ref_sr != src_sr:
        import librosa

        src_samples = librosa.resample(src_samples, orig_sr=src_sr, target_sr=ref_sr)
        src_sr = ref_sr

    ref_env = _onset_envelope(ref_samples, ref_sr)
    src_env = _onset_envelope(src_samples, src_sr)

    offset_s, confidence = _xcorr_offset(ref_env, src_env, float(ref_sr))

    if confidence < CONFIDENCE_THRESHOLD:
        return SyncInfo(offset_s=0.0, scale=1.0, sync_confidence="low")

    # Offset sanity check: |offset| >= half the shorter clip duration → unreliable
    dur_ref = len(ref_samples) / ref_sr
    dur_src = len(src_samples) / src_sr
    if abs(offset_s) >= min(dur_ref, dur_src) / 2:
        return SyncInfo(offset_s=0.0, scale=1.0, sync_confidence="low")

    conf_label = "high" if confidence > 0.4 else "medium"
    return SyncInfo(offset_s=offset_s, scale=1.0, sync_confidence=conf_label)


def run(
    project_dir: Path,
    manifest: Manifest,
    emitter: ProgressEmitter,
) -> Manifest:
    """
    Align stage:
    1. Use cam_a (or first source) as reference.
    2. Cross-correlate onset envelopes against each other source.
    3. Store offset_s + sync_confidence in manifest.sources[*].sync.

    Idempotent — skips if stage_status.align == "done".
    """
    if manifest.stage_status.align == "done":
        emitter.emit("align", "done", 1.0, "Skipped (already done)")
        return manifest

    emitter.emit("align", "running", 0.0, "Starting alignment")
    manifest.stage_status.align = "running"
    manifest_write(project_dir, manifest)

    sources = manifest.sources
    if len(sources) < 2:
        # Single camera — no alignment needed
        if sources:
            sources[0].sync = SyncInfo(offset_s=0.0, scale=1.0, sync_confidence="high")
        manifest.stage_status.align = "done"
        manifest_write(project_dir, manifest)
        emitter.emit("align", "done", 1.0, "Single source — no alignment required")
        return manifest

    ref = sources[0]
    if not ref.audio_path:
        raise RuntimeError(f"Reference source {ref.id} has no audio_path — run proxy stage first")

    log_file = log_path(project_dir, "align")
    with log_file.open("w") as log:
        ref.sync = SyncInfo(offset_s=0.0, scale=1.0, sync_confidence="high")
        log.write(f"Reference: {ref.id}\n")

        for i, src in enumerate(sources[1:], 1):
            progress = i / max(len(sources) - 1, 1)
            emitter.emit("align", "running", progress * 0.9, f"Aligning {src.id} → {ref.id}")

            if not src.audio_path:
                warn = f"No audio_path for {src.id} — skipping alignment, offset=0"
                manifest.pipeline.warnings.append(warn)
                log.write(f"  WARNING: {warn}\n")
                src.sync = SyncInfo(offset_s=0.0, scale=1.0, sync_confidence="low")
                continue

            try:
                sync = _align_pair(ref.audio_path, src.audio_path)
                src.sync = sync
                log.write(f"  {src.id}: offset={sync.offset_s:.3f}s  confidence={sync.sync_confidence}\n")
            except Exception as e:
                warn = f"Alignment failed for {src.id}: {e} — using offset=0"
                manifest.pipeline.warnings.append(warn)
                log.write(f"  WARNING: {warn}\n")
                src.sync = SyncInfo(offset_s=0.0, scale=1.0, sync_confidence="low")

    manifest.stage_status.align = "done"
    manifest_write(project_dir, manifest)
    emitter.emit("align", "done", 1.0, "Alignment complete")
    return manifest
