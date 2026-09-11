from __future__ import annotations

from dataclasses import fields
from collections.abc import Sequence
from typing import Any

import numpy as np

from .types import BeatMatch, LagWindow, RecordMetrics


def _safe_corr(a: np.ndarray, b: np.ndarray) -> float:
    if a.size < 3 or b.size != a.size or np.std(a) <= 1e-12 or np.std(b) <= 1e-12:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def _sdnn(rr_ms: np.ndarray) -> float:
    return float(np.std(rr_ms, ddof=1)) if rr_ms.size >= 2 else float("nan")


def _rmssd_segments(ref: np.ndarray, ppg: np.ndarray, matches: Sequence[BeatMatch]) -> tuple[float, float]:
    ref_diffs: list[float] = []
    ppg_diffs: list[float] = []
    previous_rr_ref = previous_rr_ppg = None
    prev_match: BeatMatch | None = None
    for match in matches:
        if prev_match is None:
            prev_match = match
            continue
        contiguous = (
            match.reference_index == prev_match.reference_index + 1
            and match.ppg_index == prev_match.ppg_index + 1
        )
        if not contiguous:
            previous_rr_ref = previous_rr_ppg = None
            prev_match = match
            continue
        rr_ref = (ref[match.reference_index] - ref[prev_match.reference_index]) * 1000.0
        rr_ppg = (ppg[match.ppg_index] - ppg[prev_match.ppg_index]) * 1000.0
        if previous_rr_ref is not None and previous_rr_ppg is not None:
            ref_diffs.append(float(rr_ref - previous_rr_ref))
            ppg_diffs.append(float(rr_ppg - previous_rr_ppg))
        previous_rr_ref, previous_rr_ppg = rr_ref, rr_ppg
        prev_match = match
    r = float(np.sqrt(np.mean(np.square(ref_diffs)))) if ref_diffs else float("nan")
    p = float(np.sqrt(np.mean(np.square(ppg_diffs)))) if ppg_diffs else float("nan")
    return r, p


def compute_record_metrics(
    *,
    record_id: str,
    duration_s: float,
    reference_method: str,
    reference_coverage: float,
    reference_s: np.ndarray,
    ppg_s: np.ndarray,
    aligned_ppg_s: np.ndarray,
    matches: Sequence[BeatMatch],
    lag_windows: Sequence[LagWindow],
    execution_seconds: float,
) -> RecordMetrics:
    n_ref = int(len(reference_s))
    n_ppg = int(len(ppg_s))
    correct = int(len(matches))
    sensitivity = 100.0 * correct / n_ref if n_ref else 0.0
    ppv = 100.0 * correct / n_ppg if n_ppg else 0.0
    f1 = (2.0 * sensitivity * ppv / (sensitivity + ppv)) if sensitivity + ppv else 0.0

    residual_ms = np.asarray([abs(m.residual_s) * 1000.0 for m in matches], dtype=float)
    lags_ms = np.asarray([w.lag_s * 1000.0 for w in lag_windows], dtype=float)
    centers_min = np.asarray([w.center_s / 60.0 for w in lag_windows], dtype=float)
    if lags_ms.size >= 2 and np.ptp(centers_min) > 0:
        slope = float(np.polyfit(centers_min, lags_ms, 1)[0])
    else:
        slope = 0.0

    rr_ref: list[float] = []
    rr_ppg: list[float] = []
    prev: BeatMatch | None = None
    for match in matches:
        if prev is not None and (
            match.reference_index == prev.reference_index + 1
            and match.ppg_index == prev.ppg_index + 1
        ):
            rr_ref.append((reference_s[match.reference_index] - reference_s[prev.reference_index]) * 1000.0)
            rr_ppg.append((ppg_s[match.ppg_index] - ppg_s[prev.ppg_index]) * 1000.0)
        prev = match
    rr_ref_arr = np.asarray(rr_ref, dtype=float)
    rr_ppg_arr = np.asarray(rr_ppg, dtype=float)
    rr_error = np.abs(rr_ppg_arr - rr_ref_arr) if rr_ref_arr.size else np.asarray([], dtype=float)
    rmssd_ref, rmssd_ppg = _rmssd_segments(reference_s, ppg_s, matches)
    sdnn_ref = _sdnn(rr_ref_arr)
    sdnn_ppg = _sdnn(rr_ppg_arr)

    return RecordMetrics(
        record_id=str(record_id),
        duration_s=float(duration_s),
        reference_method=str(reference_method),
        reference_coverage=float(reference_coverage),
        n_reference=n_ref,
        n_ppg=n_ppg,
        n_correct=correct,
        sensitivity_percent=float(sensitivity),
        ppv_percent=float(ppv),
        f1_percent=float(f1),
        lag_median_ms=float(np.median(lags_ms)) if lags_ms.size else float("nan"),
        lag_iqr_ms=float(np.percentile(lags_ms, 75) - np.percentile(lags_ms, 25)) if lags_ms.size else float("nan"),
        lag_drift_ms_per_min=slope,
        timing_mae_ms=float(np.mean(residual_ms)) if residual_ms.size else float("nan"),
        timing_p95_ms=float(np.percentile(residual_ms, 95)) if residual_ms.size else float("nan"),
        rr_pair_count=int(rr_ref_arr.size),
        rr_mae_ms=float(np.mean(rr_error)) if rr_error.size else float("nan"),
        rr_p95_ms=float(np.percentile(rr_error, 95)) if rr_error.size else float("nan"),
        rr_correlation=_safe_corr(rr_ref_arr, rr_ppg_arr),
        rmssd_reference_ms=rmssd_ref,
        rmssd_ppg_ms=rmssd_ppg,
        rmssd_abs_error_ms=(float(abs(rmssd_ppg - rmssd_ref)) if np.isfinite(rmssd_ref) and np.isfinite(rmssd_ppg) else float("nan")),
        sdnn_reference_ms=sdnn_ref,
        sdnn_ppg_ms=sdnn_ppg,
        sdnn_abs_error_ms=(float(abs(sdnn_ppg - sdnn_ref)) if np.isfinite(sdnn_ref) and np.isfinite(sdnn_ppg) else float("nan")),
        execution_seconds=float(execution_seconds),
        realtime_ratio_percent=(100.0 * execution_seconds / duration_s if duration_s > 0 else float("nan")),
        ppg_detector_count=n_ppg,
    )


def aggregate_metrics(records: Sequence[RecordMetrics]) -> dict[str, Any]:
    valid = [r for r in records if not r.error]
    summary: dict[str, Any] = {"record_count": len(records), "valid_record_count": len(valid)}
    numeric_names = [
        "reference_coverage", "sensitivity_percent", "ppv_percent", "f1_percent",
        "timing_mae_ms", "timing_p95_ms", "rr_mae_ms", "rr_p95_ms", "rr_correlation",
        "rmssd_abs_error_ms", "sdnn_abs_error_ms", "lag_median_ms", "lag_iqr_ms",
        "lag_drift_ms_per_min", "realtime_ratio_percent",
    ]
    for name in numeric_names:
        values = np.asarray([getattr(r, name) for r in valid], dtype=float)
        values = values[np.isfinite(values)]
        if not values.size:
            summary[name] = {"median": None, "q25": None, "q75": None}
            continue
        summary[name] = {
            "median": float(np.median(values)),
            "q25": float(np.percentile(values, 25)),
            "q75": float(np.percentile(values, 75)),
        }
    return summary
