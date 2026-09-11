import csv
from pathlib import Path

import numpy as np

from hrv_app.benchmark.datasets import load_bidmc_csv, load_csv_pair
from hrv_app.benchmark.ecg_reference import build_ecg_reference
from hrv_app.benchmark.matching import apply_piecewise_lag, estimate_piecewise_lag, one_to_one_match
from hrv_app.benchmark.runner import run_record, write_report
from hrv_app.benchmark.synthetic import make_synthetic_record


def test_dual_ecg_reference_agrees_on_clean_synthetic_record():
    record = make_synthetic_record(duration_s=60.0)
    reference = build_ecg_reference(record.ecg, record.ecg_fs)
    assert reference.valid_coverage >= 0.95
    assert len(reference.beats_s) >= 45
    assert all(window.agreement_f1 >= 0.90 for window in reference.quality_windows if window.valid)


def test_piecewise_alignment_recovers_lag_and_one_to_one_metrics():
    ref = np.arange(1.0, 601.0, 0.8)
    # 220 ms pulse lag plus 20 ms drift over ten minutes.
    ppg = ref + 0.220 + (ref / 600.0) * 0.020
    windows = estimate_piecewise_lag(ref, ppg, window_s=300.0)
    aligned = apply_piecewise_lag(ppg, windows)
    matches = one_to_one_match(ref, aligned, 0.150)
    assert len(matches) == len(ref)
    assert 0.20 <= windows[0].lag_s <= 0.25
    assert windows[-1].lag_s > windows[0].lag_s
    assert np.percentile([abs(m.residual_s) for m in matches], 95) < 0.015


def test_production_interval_core_benchmark_smoke_is_high_accuracy():
    metrics, detail = run_record(make_synthetic_record(duration_s=60.0))
    assert metrics.error == ""
    assert metrics.f1_percent >= 98.0
    assert metrics.rr_mae_ms < 8.0
    assert metrics.rmssd_abs_error_ms < 5.0
    assert detail["ppg_evidence"]["dual_detector_ratio"] > 0.90


def test_runner_can_use_derived_ecg_reference():
    record = make_synthetic_record(duration_s=60.0)
    record.reference_beats_s = None
    metrics, detail = run_record(record)
    assert metrics.reference_method == "dual_ecg_consensus"
    assert metrics.reference_coverage >= 0.90
    assert metrics.f1_percent >= 95.0
    assert detail["ecg_reference"]["quality_windows"]


def test_bidmc_csv_loader_detects_physionet_column_names(tmp_path):
    path = tmp_path / "bidmc_01_Signals.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Time [s]", "RESP", "PLETH", "V", "AVR", "II"])
        for i in range(500):
            t = i / 125.0
            writer.writerow([t, 0.0, np.sin(t), 0.0, 0.0, np.cos(t)])
    record = load_bidmc_csv(path, "bidmc01")
    assert record.record_id == "bidmc01"
    assert abs(record.ppg_fs - 125.0) < 1e-6
    assert record.ppg.shape == record.ecg.shape == (500,)


def test_local_csv_pair_supports_different_sample_rates(tmp_path):
    ppg_path = tmp_path / "ppg.csv"
    ecg_path = tmp_path / "ecg.csv"
    with ppg_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle); writer.writerow(["time_s", "ppg"])
        for i in range(500): writer.writerow([i / 125.0, np.sin(i / 10.0)])
    with ecg_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle); writer.writerow(["time_s", "ecg"])
        for i in range(1000): writer.writerow([i / 250.0, np.cos(i / 10.0)])
    record = load_csv_pair(
        ppg_csv=ppg_path, ecg_csv=ecg_path,
        ppg_value_col="ppg", ecg_value_col="ecg",
        ppg_time_col="time_s", ecg_time_col="time_s",
    )
    assert abs(record.ppg_fs - 125.0) < 1e-6
    assert abs(record.ecg_fs - 250.0) < 1e-6


def test_benchmark_report_contains_csv_summary_and_details(tmp_path):
    metrics, detail = run_record(make_synthetic_record(duration_s=35.0))
    out = write_report(tmp_path / "report", [metrics], [detail])
    assert (out / "record_metrics.csv").exists()
    assert (out / "summary.json").exists()
    assert (out / "details.json").exists()
    assert '"schema_version": "benchmark-v0.4.1"' in (out / "summary.json").read_text(encoding="utf-8")
