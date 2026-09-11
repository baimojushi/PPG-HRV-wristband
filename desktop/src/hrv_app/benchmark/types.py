from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

import numpy as np


@dataclass(slots=True)
class BenchmarkRecord:
    """One synchronized PPG/ECG benchmark recording.

    `reference_beats_s` may be supplied by a dataset with trusted annotations. If it
    is absent, the framework derives a *reference consensus* from two independent ECG
    QRS detectors and only evaluates windows where those ECG detectors agree.
    """

    record_id: str
    ppg: np.ndarray
    ppg_fs: float
    ecg: np.ndarray | None = None
    ecg_fs: float | None = None
    reference_beats_s: np.ndarray | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        if self.ppg_fs <= 0:
            return 0.0
        return float(len(self.ppg) / self.ppg_fs)


@dataclass(slots=True)
class QualityWindow:
    start_s: float
    end_s: float
    valid: bool
    agreement_f1: float
    detector_a_count: int
    detector_b_count: int
    matched_count: int


@dataclass(slots=True)
class ECGReference:
    beats_s: np.ndarray
    method: str
    quality_windows: list[QualityWindow]
    detector_a_s: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    detector_b_s: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))

    @property
    def valid_coverage(self) -> float:
        if not self.quality_windows:
            return 1.0 if self.beats_s.size else 0.0
        total = sum(max(0.0, w.end_s - w.start_s) for w in self.quality_windows)
        good = sum(
            max(0.0, w.end_s - w.start_s)
            for w in self.quality_windows
            if w.valid
        )
        return float(good / total) if total > 0 else 0.0


@dataclass(slots=True)
class LagWindow:
    center_s: float
    lag_s: float
    matched_count: int
    reference_count: int


@dataclass(slots=True)
class BeatMatch:
    reference_index: int
    ppg_index: int
    residual_s: float


@dataclass(slots=True)
class RecordMetrics:
    record_id: str
    duration_s: float
    reference_method: str
    reference_coverage: float
    n_reference: int
    n_ppg: int
    n_correct: int
    sensitivity_percent: float
    ppv_percent: float
    f1_percent: float
    lag_median_ms: float
    lag_iqr_ms: float
    lag_drift_ms_per_min: float
    timing_mae_ms: float
    timing_p95_ms: float
    rr_pair_count: int
    rr_mae_ms: float
    rr_p95_ms: float
    rr_correlation: float
    rmssd_reference_ms: float
    rmssd_ppg_ms: float
    rmssd_abs_error_ms: float
    sdnn_reference_ms: float
    sdnn_ppg_ms: float
    sdnn_abs_error_ms: float
    execution_seconds: float
    realtime_ratio_percent: float
    ppg_detector_count: int
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
