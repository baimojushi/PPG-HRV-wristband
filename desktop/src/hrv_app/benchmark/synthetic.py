from __future__ import annotations

import numpy as np

from .types import BenchmarkRecord


def make_synthetic_record(duration_s: float = 90.0, fs: float = 125.0) -> BenchmarkRecord:
    rng = np.random.default_rng(7)
    t = np.arange(int(duration_s * fs), dtype=float) / fs
    beats: list[float] = []
    current = 0.8
    while current < duration_s - 1.0:
        rr = 0.80 + 0.045 * np.sin(2.0 * np.pi * 0.10 * current) + 0.018 * np.sin(2.0 * np.pi * 0.23 * current)
        current += rr
        beats.append(current)
    ref = np.asarray(beats, dtype=float)

    ecg = 0.015 * rng.standard_normal(t.size)
    ppg = 0.010 * rng.standard_normal(t.size) + 0.03 * np.sin(2.0 * np.pi * 0.08 * t)
    for beat in ref:
        ecg += 1.7 * np.exp(-0.5 * ((t - beat) / 0.018) ** 2)
        ptime = beat + 0.230 + 0.006 * np.sin(2.0 * np.pi * beat / 55.0)
        ppg += 1.2 * np.exp(-0.5 * ((t - ptime) / 0.055) ** 2)
        ppg += 0.18 * np.exp(-0.5 * ((t - ptime - 0.18) / 0.045) ** 2)
    return BenchmarkRecord(
        record_id="synthetic_smoke",
        ppg=ppg,
        ppg_fs=fs,
        ecg=ecg,
        ecg_fs=fs,
        reference_beats_s=ref,
        metadata={"dataset": "synthetic", "true_pulse_lag_ms": 230.0},
    )
