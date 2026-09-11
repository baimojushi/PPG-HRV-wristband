from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .datasets import load_bidmc, load_csv_pair, load_npz
from .runner import run_record, write_report
from .synthetic import make_synthetic_record


def _parse_records(text: str) -> list[str]:
    result: list[str] = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            left, right = token.split("-", 1)
            result.extend(f"{i:02d}" for i in range(int(left), int(right) + 1))
        else:
            result.append(token)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ECG/public PPG interval-core benchmark")
    sub = parser.add_subparsers(dest="command", required=True)

    smoke = sub.add_parser("synthetic", help="Run an offline synthetic smoke benchmark")
    smoke.add_argument("--output", default="benchmark_results/synthetic")

    bidmc = sub.add_parser("bidmc", help="Download/cache and benchmark open BIDMC ECG+PPG records")
    bidmc.add_argument("--records", default="01-05", help="e.g. 01-05 or 01,02,17")
    bidmc.add_argument("--cache", default="benchmark_data/bidmc")
    bidmc.add_argument("--output", default="benchmark_results/bidmc")

    pair = sub.add_parser("csv-pair", help="Benchmark a synchronized wrist PPG + external ECG pair")
    pair.add_argument("--ppg", required=True)
    pair.add_argument("--ecg", required=True)
    pair.add_argument("--ppg-value", required=True)
    pair.add_argument("--ecg-value", required=True)
    pair.add_argument("--ppg-time", required=True)
    pair.add_argument("--ecg-time", required=True)
    pair.add_argument("--record-id", default="local_pair")
    pair.add_argument("--output", default="benchmark_results/local_pair")

    npz = sub.add_parser("npz", help="Benchmark a portable NPZ record")
    npz.add_argument("path")
    npz.add_argument("--output", default="benchmark_results/npz")

    for cmd in (smoke, bidmc, pair, npz):
        cmd.add_argument("--fail-under-f1", type=float, default=None,
                         help="Optional CI gate. No scientific threshold is imposed by default.")
        cmd.add_argument("--fail-over-rr-mae-ms", type=float, default=None,
                         help="Optional CI gate for median per-record RR MAE.")
    return parser


def _run(records, output: str, args) -> int:
    metrics = []
    details = []
    for record in records:
        result, detail = run_record(record)
        metrics.append(result)
        details.append(detail)
        status = "ERROR" if result.error else f"F1={result.f1_percent:.2f}% RR_MAE={result.rr_mae_ms:.2f}ms"
        print(f"{record.record_id}: {status}")
    out = write_report(output, metrics, details)
    print(f"Report: {out}")

    good = [m for m in metrics if not m.error]
    if not good:
        return 2
    f1_values = [m.f1_percent for m in good]
    rr_values = [m.rr_mae_ms for m in good if m.rr_mae_ms == m.rr_mae_ms]
    import numpy as np
    if args.fail_under_f1 is not None and float(np.median(f1_values)) < args.fail_under_f1:
        print("CI gate failed: median F1 below requested threshold", file=sys.stderr)
        return 3
    if args.fail_over_rr_mae_ms is not None and rr_values and float(np.median(rr_values)) > args.fail_over_rr_mae_ms:
        print("CI gate failed: median RR MAE above requested threshold", file=sys.stderr)
        return 4
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "synthetic":
        return _run([make_synthetic_record()], args.output, args)
    if args.command == "bidmc":
        records = [load_bidmc(r, args.cache) for r in _parse_records(args.records)]
        return _run(records, args.output, args)
    if args.command == "csv-pair":
        record = load_csv_pair(
            ppg_csv=args.ppg, ecg_csv=args.ecg,
            ppg_value_col=args.ppg_value, ecg_value_col=args.ecg_value,
            ppg_time_col=args.ppg_time, ecg_time_col=args.ecg_time,
            record_id=args.record_id,
        )
        return _run([record], args.output, args)
    if args.command == "npz":
        return _run([load_npz(args.path)], args.output, args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
