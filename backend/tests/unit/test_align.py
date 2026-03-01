"""Unit tests for align.py."""
from __future__ import annotations

import numpy as np
import pytest

from backend.pipeline.align import CONFIDENCE_THRESHOLD, _xcorr_offset


class TestXCorrOffset:
    def test_zero_lag_identical_signals(self):
        signal = np.random.rand(1000).astype(np.float32)
        offset_s, conf = _xcorr_offset(signal, signal, sr_hop=44100.0)
        assert abs(offset_s) < 0.1

    def test_known_lag(self):
        np.random.seed(42)
        base = np.random.rand(2000).astype(np.float32)
        lag_frames = 50
        delayed = np.zeros_like(base)
        delayed[lag_frames:] = base[: len(base) - lag_frames]

        hop_duration_s = 512 / 44100
        expected_offset_s = lag_frames * hop_duration_s

        offset_s, conf = _xcorr_offset(base, delayed, sr_hop=44100.0)
        # Allow ±1 frame tolerance
        assert abs(offset_s - (-expected_offset_s)) < hop_duration_s * 2

    def test_confidence_with_noise(self):
        signal = np.random.rand(1000).astype(np.float32)
        pure_noise = np.random.rand(1000).astype(np.float32)
        _, conf = _xcorr_offset(signal, pure_noise, sr_hop=44100.0)
        # Unrelated signals should have low confidence
        assert conf < 0.5
