"""
Music analysis stage: beat detection and energy curve extraction via librosa.
Results are written to manifest (stored in project state.json-equivalent fields).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np

from .types import Manifest
from .utils import ProgressEmitter, atomic_write, log_path, manifest_write, now_iso

logger = logging.getLogger(__name__)

# Output file inside the project directory
MUSIC_JSON = "music.json"

# Minimum beats required before using detected grid; below this → uniform fallback
_MIN_BEATS = 4


def _analyze_song(song_path: str) -> dict:
    """
    Load the song, detect beats, compute energy curve.

    Returns a dict with:
      - beats: list[float]         beat timestamps in seconds
      - energy_curve: list[float]  RMS energy per 0.5-s bin
      - tempo_bpm: float
      - duration_s: float
    """
    import librosa
    import soundfile as sf

    samples, sr = sf.read(song_path, dtype="float32", always_2d=False)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)

    duration_s = len(samples) / sr

    # Beat detection
    tempo, beat_frames = librosa.beat.beat_track(y=samples, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    # Scalar tempo (librosa may return array)
    if hasattr(tempo, "__len__"):
        tempo = float(tempo[0])
    else:
        tempo = float(tempo)

    # Beat fallback: if too few beats detected, use a uniform grid at the detected tempo
    beat_fallback = False
    if len(beat_times) < _MIN_BEATS:
        beat_fallback = True
        beat_interval_s = 60.0 / tempo if tempo > 0 else 0.5
        n_beats = int(duration_s / beat_interval_s) + 1
        beat_times = [i * beat_interval_s for i in range(n_beats) if i * beat_interval_s <= duration_s]

    # Energy curve in 0.5s bins
    hop_s = 0.5
    hop_samples = int(hop_s * sr)
    energy = []
    for start in range(0, len(samples), hop_samples):
        chunk = samples[start : start + hop_samples]
        energy.append(float(np.sqrt(np.mean(chunk ** 2))))

    result = {
        "beats": beat_times,
        "energy_curve": energy,
        "energy_hop_s": hop_s,
        "tempo_bpm": tempo,
        "duration_s": duration_s,
    }
    if beat_fallback:
        result["beat_fallback"] = True
    return result


def run(
    project_dir: Path,
    manifest: Manifest,
    emitter: ProgressEmitter,
) -> dict:
    """
    Music stage:
    1. Analyze song_path with librosa.
    2. Write music.json to project directory.
    3. Mark stage done.

    Returns the music analysis dict.
    Idempotent — reloads music.json if stage already done.
    """
    music_json_path = project_dir / MUSIC_JSON

    if manifest.stage_status.music == "done" and music_json_path.exists():
        emitter.emit("music", "done", 1.0, "Skipped (already done)")
        return json.loads(music_json_path.read_text())

    if not manifest.song_path:
        raise ValueError("No song_path in manifest — cannot run music stage")

    emitter.emit("music", "running", 0.0, "Analyzing song")
    manifest.stage_status.music = "running"
    manifest_write(project_dir, manifest)

    log_file = log_path(project_dir, "music")

    try:
        analysis = _analyze_song(manifest.song_path)
    except Exception as e:
        manifest.stage_status.music = "error"
        manifest.pipeline.error = str(e)
        manifest_write(project_dir, manifest)
        emitter.emit("music", "error", 0.0, str(e))
        raise

    atomic_write(music_json_path, json.dumps(analysis, indent=2))

    with log_file.open("w") as log:
        log.write(f"Song: {manifest.song_path}\n")
        log.write(f"Duration: {analysis['duration_s']:.1f}s\n")
        log.write(f"Tempo: {analysis['tempo_bpm']:.1f} BPM\n")
        log.write(f"Beats detected: {len(analysis['beats'])}\n")

    manifest.stage_status.music = "done"
    manifest_write(project_dir, manifest)
    emitter.emit("music", "done", 1.0, f"Beat detection complete — {len(analysis['beats'])} beats")
    return analysis


def snap_to_beat(t: float, beats: list[float], max_offset_s: float = 0.15) -> float:
    """
    Snap timestamp *t* to the nearest beat within *max_offset_s*.
    Returns *t* unchanged if no beat is close enough.
    """
    if not beats:
        return t
    arr = np.array(beats)
    diffs = np.abs(arr - t)
    idx = int(np.argmin(diffs))
    if diffs[idx] <= max_offset_s:
        return float(arr[idx])
    return t
