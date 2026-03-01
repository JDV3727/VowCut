"""Unit tests for align.py."""
from __future__ import annotations

import numpy as np
import pytest

from backend.pipeline.align import CONFIDENCE_THRESHOLD, _xcorr_offset, _align_pair


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


class TestConfidenceThreshold:
    def test_threshold_is_0_3(self):
        """Regression guard: CONFIDENCE_THRESHOLD must be 0.3, not the old 0.1."""
        assert CONFIDENCE_THRESHOLD == pytest.approx(0.3)


class TestAlignPairGuards:
    def _write_wav(self, tmp_path, name: str, samples: np.ndarray, sr: int = 16000) -> str:
        import soundfile as sf
        path = tmp_path / name
        sf.write(str(path), samples, sr)
        return str(path)

    def test_dead_audio_returns_low_confidence(self, tmp_path):
        """Source with near-zero audio should get low confidence without crash."""
        sr = 16000
        ref = np.random.rand(sr * 5).astype(np.float32) * 0.5
        src = np.zeros(sr * 5, dtype=np.float32)  # dead audio

        ref_path = self._write_wav(tmp_path, "ref.wav", ref, sr)
        src_path = self._write_wav(tmp_path, "src.wav", src, sr)

        sync = _align_pair(ref_path, src_path)
        assert sync.sync_confidence == "low"
        assert sync.offset_s == pytest.approx(0.0)

    def test_insane_offset_returns_low_confidence(self, tmp_path):
        """When cross-corr returns an offset >= half the clip duration, force low confidence."""
        import unittest.mock as mock

        sr = 16000
        dur_s = 4.0
        ref = np.random.rand(int(sr * dur_s)).astype(np.float32)
        # Give src non-trivial audio so dead-audio guard doesn't fire
        src = np.random.rand(int(sr * dur_s)).astype(np.float32)

        ref_path = self._write_wav(tmp_path, "ref.wav", ref, sr)
        src_path = self._write_wav(tmp_path, "src.wav", src, sr)

        # Force xcorr to return an absurd offset (>= half the 4s clip = 2s)
        with mock.patch("backend.pipeline.align._xcorr_offset", return_value=(3.0, 0.9)):
            sync = _align_pair(ref_path, src_path)

        assert sync.sync_confidence == "low"
        assert sync.offset_s == pytest.approx(0.0)
