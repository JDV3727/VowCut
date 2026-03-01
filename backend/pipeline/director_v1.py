"""
Camera quality scoring and hysteresis-based 2-camera switching (V1).

Scoring model:
  score = w_motion * motion_score + w_rms * rms + w_onset * onset_strength

Hysteresis rule:
  Switch camera only if new_score > current_score * (1 + IMPROVEMENT_THRESHOLD)
  Enforce min 2s / max 15s hold per source.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .types import ChunkFeature

# Scoring weights
W_MOTION = 0.4
W_RMS = 0.3
W_ONSET = 0.3

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
        W_MOTION * feature.motion_score
        + W_RMS * feature.rms
        + W_ONSET * feature.onset_strength
    )


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

    decisions: list[CameraDecision] = []
    current_sid = source_ids[0]
    current_score = get_score(current_sid, 0)
    hold_start_chunk = 0
    hold_chunks = 0

    for c in range(n_chunks):
        t0 = c * chunk_duration_s
        t1 = (c + 1) * chunk_duration_s
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
            and best_score > current_frame_score * (1 + IMPROVEMENT_THRESHOLD)
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
