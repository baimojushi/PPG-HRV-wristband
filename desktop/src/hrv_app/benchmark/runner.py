from __future__ import annotations

from pathlib import Path
import csv
import json
import math
from typing import Any

import numpy as np

from .ecg_reference import build_ecg_reference, reference_from_annotations
from .matching import apply_piecewise_lag, estimate_piecewise_lag, in_valid_windows, one_to_one_match
from .metrics import aggregate_metrics, compute_record_metrics
from .production_detector import detect_with_production_interval_core
from .types import BenchmarkRecord, RecordMetrics


def run_record(
    record: BenchmarkRecord,
    *,
    match_tolerance_s: float = 0.150,
    lag_window_s: float = 300.0,
) -> tuple[RecordMetrics, dict[str, Any]]:
    try:
        if record.reference_beats_s is not None:
            reference = reference_from_annotations(record.reference_beats_s, record.duration_s)
        else:
            if record.ecg is None or not record.ecg_fs:
                raise ValueError("Record has neither reference beat annotations nor ECG waveform")
            reference = build_ecg_reference(record.ecg, float(record.ecg_fs))

        ppg_beats, elapsed, ppg_evidence = detect_with_production_interval_core(record.ppg, record.ppg_fs)
        ref_mask = in_valid_windows(reference.beats_s, reference.quality_windows)
        ref_eval = reference.beats_s[ref_mask]

        # Align first, then apply ECG-valid windows in aligned time. Applying quality
        # windows to raw PPG timestamps would incorrectly discard beats near window
        # boundaries simply because PPG physiologically follows the ECG R wave.
        lags = estimate_piecewise_lag(
            ref_eval,
            ppg_beats,
            window_s=lag_window_s,
            tolerance_s=match_tolerance_s,
        )
        aligned_all = apply_piecewise_lag(ppg_beats, lags)
        ppg_mask = in_valid_windows(aligned_all, reference.quality_windows)
        ppg_eval = ppg_beats[ppg_mask]
        aligned_ppg = aligned_all[ppg_mask]
        matches = one_to_one_match(ref_eval, aligned_ppg, match_tolerance_s)
        metrics = compute_record_metrics(
            record_id=record.record_id,
            duration_s=record.duration_s,
            reference_method=reference.method,
            reference_coverage=reference.valid_coverage,
            reference_s=ref_eval,
            ppg_s=ppg_eval,
            aligned_ppg_s=aligned_ppg,
            matches=matches,
            lag_windows=lags,
            execution_seconds=elapsed,
        )
        detail = {
            "record_id": record.record_id,
            "metadata": record.metadata,
            "ppg_evidence": ppg_evidence,
            "ecg_reference": {
                "method": reference.method,
                "reference_coverage": reference.valid_coverage,
                "reference_beat_count": int(reference.beats_s.size),
                "quality_windows": [
                    {
                        "start_s": w.start_s, "end_s": w.end_s, "valid": w.valid,
                        "agreement_f1": w.agreement_f1,
                        "detector_a_count": w.detector_a_count,
                        "detector_b_count": w.detector_b_count,
                        "matched_count": w.matched_count,
                    }
                    for w in reference.quality_windows
                ],
            },
            "lag_windows": [
                {"center_s": w.center_s, "lag_s": w.lag_s, "matched_count": w.matched_count, "reference_count": w.reference_count}
                for w in lags
            ],
            "metrics": metrics.to_dict(),
        }
        return metrics, detail
    except Exception as exc:
        metrics = RecordMetrics(
            record_id=record.record_id, duration_s=record.duration_s, reference_method="",
            reference_coverage=0.0, n_reference=0, n_ppg=0, n_correct=0,
            sensitivity_percent=0.0, ppv_percent=0.0, f1_percent=0.0,
            lag_median_ms=float("nan"), lag_iqr_ms=float("nan"), lag_drift_ms_per_min=float("nan"),
            timing_mae_ms=float("nan"), timing_p95_ms=float("nan"), rr_pair_count=0,
            rr_mae_ms=float("nan"), rr_p95_ms=float("nan"), rr_correlation=float("nan"),
            rmssd_reference_ms=float("nan"), rmssd_ppg_ms=float("nan"), rmssd_abs_error_ms=float("nan"),
            sdnn_reference_ms=float("nan"), sdnn_ppg_ms=float("nan"), sdnn_abs_error_ms=float("nan"),
            execution_seconds=0.0, realtime_ratio_percent=float("nan"), ppg_detector_count=0,
            error=f"{type(exc).__name__}: {exc}",
        )
        return metrics, {"record_id": record.record_id, "error": metrics.error}


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def write_report(
    output_dir: str | Path,
    metrics: list[RecordMetrics],
    details: list[dict[str, Any]],
    *,
    run_metadata: dict[str, Any] | None = None,
) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    rows = [m.to_dict() for m in metrics]
    if rows:
        with (output / "record_metrics.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    summary = {
        "schema_version": "benchmark-v0.4.1",
        "method": {
            "correctness_tolerance_ms": 150,
            "ecg_reference": "two independent ECG detectors; only agreement windows are scored unless annotations are supplied",
            "ppg_detector": "production v0.4.1 interval core",
            "alignment": "piecewise ECG-to-PPG lag with 300 s default windows",
        },
        "aggregate": aggregate_metrics(metrics),
        "records": [_json_safe(row) for row in rows],
        "run_metadata": run_metadata or {},
    }
    (output / "summary.json").write_text(
        json.dumps(_json_safe(summary), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "details.json").write_text(
        json.dumps(_json_safe(details), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output
