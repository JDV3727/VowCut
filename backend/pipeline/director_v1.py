"""
Camera quality scoring and hysteresis-based 2-camera switching (V1).

Scoring model (Phase 3):
  score = w_stability * stability   # steadiness dominates — never cut to a shaky camera
        + w_activity  * activity    # something is happening in frame
        + w_exposure  * exposure    # well-lit shot
        + w_rms       * rms         # audio content
        + w_onset     * onset       # audio events

Switching paths:
  beat-aligned: iterate over music beat positions, apply hysteresis per beat
  chunk-based:  fallback when no beats available, iterate over 2-s chunks

Hysteresis rule:
  Switch only if new_score > current_score * (1 + IMPROVEMENT_THRESHOLD)
  Enforce min 2s hold. Force-cut uses a tiered threshold that softens over time.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .types import ChunkFeature

# Scoring weights  (must sum to 1.0)
W_STABILITY = 0.30   # never want a shaky camera
W_ACTIVITY  = 0.25   # prefer shots where something is happening
W_EXPOSURE  = 0.20   # prefer well-exposed shots
W_RMS       = 0.15   # audio content as a secondary signal
W_ONSET     = 0.10   # audio events (applause, speech onset)

# Hysteresis: switch only if new cam is 15% better
IMPROVEMENT_THRESHOLD = 0.15

# Hard constraints
MIN_HOLD_S = 2.0
MAX_HOLD_S = 15.0


@dataclass
class ScoredChunk:
    source_id: str
    chunk_index: int
    t0: float
    t1: float
    score: float


def score_chunk(feature: ChunkFeature) -> float:
    return (
        W_STABILITY * feature.stability
        + W_ACTIVITY  * feature.activity
        + W_EXPOSURE  * feature.exposure
        + W_RMS       * feature.rms
        + W_ONSET     * feature.onset_strength
    )


def _tiered_force_threshold(held_s: float) -> float:
    """
    Force-cut improvement threshold softens as hold time grows, providing an
    escape valve when one camera is persistently (but not dramatically) better.

      held <  25s → 15%  (same as normal switch threshold)
      held >= 25s →  8%
      held >= 45s →  1%  (almost anything forces a cut)
    """
    if held_s >= 45.0:
        return 0.01
    if held_s >= 25.0:
        return 0.08
    return IMPROVEMENT_THRESHOLD


def _normalize(values: list[float]) -> list[float]:
    arr = np.array(values, dtype=float)
    mn, mx = arr.min(), arr.max()
    if mx - mn < 1e-9:
        return [0.5] * len(values)
    return ((arr - mn) / (mx - mn)).tolist()


def score_all(features_by_source: dict[str, list[ChunkFeature]]) -> dict[str, list[float]]:
    """
    Compute normalized quality scores for every source.

    Returns {source_id: [score_for_chunk_0, score_for_chunk_1, ...]}
    Each list may have different length; align by chunk_index.
    """
    raw: dict[str, list[float]] = {}
    for sid, feats in features_by_source.items():
        raw[sid] = [score_chunk(f) for f in sorted(feats, key=lambda x: x.chunk_index)]

    # Global normalization across all sources
    all_vals = [v for vals in raw.values() for v in vals]
    if not all_vals:
        return raw

    arr = np.array(all_vals, dtype=float)
    mn, mx = arr.min(), arr.max()
    if mx - mn < 1e-9:
        return {sid: [0.5] * len(v) for sid, v in raw.items()}

    normed = {}
    for sid, vals in raw.items():
        normed[sid] = [float((v - mn) / (mx - mn)) for v in vals]
    return normed


@dataclass
class CameraDecision:
    t0: float
    t1: float
    source_id: str
    score: float


def decide_switches(
    scores_by_source: dict[str, list[float]],
    chunk_duration_s: float = 2.0,
) -> list[CameraDecision]:
    """
    Apply hysteresis switching to produce a list of CameraDecisions.

    Args:
        scores_by_source: {source_id: [score_chunk_0, ...]}
        chunk_duration_s: duration of each feature chunk

    Returns:
        List of CameraDecisions sorted by t0.
    """
    if not scores_by_source:
        return []

    # Find max number of chunks
    n_chunks = max(len(v) for v in scores_by_source.values())
    source_ids = list(scores_by_source.keys())

    def get_score(sid: str, chunk_idx: int) -> float:
        vals = scores_by_source[sid]
        if chunk_idx < len(vals):
            return vals[chunk_idx]
        return 0.0

    # Start on the highest-scoring camera at chunk 0, not arbitrarily on source_ids[0]
    current_sid = max(source_ids, key=lambda s: get_score(s, 0))
    current_score = get_score(current_sid, 0)
    hold_start_chunk = 0

    decisions: list[CameraDecision] = []

    for c in range(n_chunks):
        t0 = c * chunk_duration_s
        hold_chunks = c - hold_start_chunk

        best_sid = current_sid
        best_score = get_score(current_sid, c)
        for sid in source_ids:
            s = get_score(sid, c)
            if s > best_score:
                best_score = s
                best_sid = sid

        held_s = hold_chunks * chunk_duration_s
        current_frame_score = get_score(current_sid, c)
        would_switch = (
            best_sid != current_sid
            and best_score > current_frame_score * (1 + IMPROVEMENT_THRESHOLD)
            and held_s >= MIN_HOLD_S
        )
        would_force_cut = (
            held_s >= MAX_HOLD_S
            and best_sid != current_sid
            and best_score > current_frame_score * (1 + _tiered_force_threshold(held_s))
        )

        if would_switch or would_force_cut:
            decisions.append(CameraDecision(
                t0=hold_start_chunk * chunk_duration_s,
                t1=t0,
                source_id=current_sid,
                score=current_score,
            ))
            current_sid = best_sid
            current_score = best_score
            hold_start_chunk = c

    # Close out last segment
    if decisions or hold_start_chunk == 0:
        decisions.append(CameraDecision(
            t0=hold_start_chunk * chunk_duration_s,
            t1=n_chunks * chunk_duration_s,
            source_id=current_sid,
            score=current_score,
        ))

    return decisions


def decide_switches_beat_aligned(
    scores_by_source: dict[str, list[float]],
    beats: list[float],
    total_duration_s: float,
    chunk_duration_s: float = 2.0,
) -> list[CameraDecision]:
    """
    Beat-driven hysteresis switching.

    Iterates over music beat positions instead of chunk boundaries so every
    cut point is musically motivated by construction.  Falls back to
    decide_switches() when no beats are provided.

    Args:
        scores_by_source:  {source_id: [score_chunk_0, ...]}
        beats:             beat timestamps in seconds (from music.json)
        total_duration_s:  full footage duration; used to close the last segment
        chunk_duration_s:  duration of each feature chunk (for score lookup)
    """
    if not scores_by_source:
        return []

    # Fall back to chunk-based when there are no beats
    if not beats:
        return decide_switches(scores_by_source, chunk_duration_s)

    source_ids = list(scores_by_source.keys())
    n_chunks = max(len(v) for v in scores_by_source.values())

    def get_score(sid: str, t: float) -> float:
        chunk_idx = min(int(t / chunk_duration_s), n_chunks - 1)
        vals = scores_by_source.get(sid, [])
        return vals[chunk_idx] if chunk_idx < len(vals) else 0.0

    # Only use beats that fall within the available footage
    valid_beats = [b for b in beats if 0.0 <= b < total_duration_s]
    if not valid_beats:
        return decide_switches(scores_by_source, chunk_duration_s)

    # Start on the highest-scoring camera at the first beat
    current_sid = max(source_ids, key=lambda s: get_score(s, valid_beats[0]))
    hold_start_t = 0.0
    decisions: list[CameraDecision] = []

    for beat_t in valid_beats:
        held_s = beat_t - hold_start_t

        best_sid = max(source_ids, key=lambda s: get_score(s, beat_t))
        best_score = get_score(best_sid, beat_t)
        current_score = get_score(current_sid, beat_t)

        would_switch = (
            best_sid != current_sid
            and best_score > current_score * (1 + IMPROVEMENT_THRESHOLD)
            and held_s >= MIN_HOLD_S
        )
        would_force_cut = (
            held_s >= MAX_HOLD_S
            and best_sid != current_sid
            and best_score > current_score * (1 + _tiered_force_threshold(held_s))
        )

        if would_switch or would_force_cut:
            decisions.append(CameraDecision(
                t0=hold_start_t,
                t1=beat_t,
                source_id=current_sid,
                score=current_score,
            ))
            current_sid = best_sid
            hold_start_t = beat_t

    # Close out the final segment to total_duration_s
    decisions.append(CameraDecision(
        t0=hold_start_t,
        t1=total_duration_s,
        source_id=current_sid,
        score=get_score(current_sid, hold_start_t),
    ))

    return decisions
