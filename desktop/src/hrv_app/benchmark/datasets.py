from __future__ import annotations

from pathlib import Path
from urllib.request import Request, urlopen
import csv

import numpy as np

from .types import BenchmarkRecord


BIDMC_BASE = "https://physionet.org/files/bidmc/1.0.0/bidmc_csv"


def _normalize_record_id(record_id: str) -> str:
    text = str(record_id).strip().lower().replace("bidmc", "").replace("_", "")
    number = int(text)
    if not 1 <= number <= 53:
        raise ValueError("BIDMC record must be between 01 and 53")
    return f"{number:02d}"


def fetch_bidmc_csv(record_id: str, cache_dir: str | Path) -> Path:
    """Download one open-access BIDMC CSV recording into a local cache."""
    rid = _normalize_record_id(record_id)
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"bidmc_{rid}_Signals.csv"
    if path.exists() and path.stat().st_size > 1000:
        return path
    url = f"{BIDMC_BASE}/bidmc_{rid}_Signals.csv"
    request = Request(url, headers={"User-Agent": "PPG-HRV-benchmark/0.4.1"})
    tmp = path.with_suffix(path.suffix + ".part")
    try:
        with urlopen(request, timeout=90) as response, tmp.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return path


def load_bidmc_csv(path: str | Path, record_id: str | None = None) -> BenchmarkRecord:
    path = Path(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"Missing CSV header: {path}")
        aliases = {name.strip().lower(): name for name in reader.fieldnames}
        time_name = aliases.get("time [s]") or aliases.get("time")
        ppg_name = aliases.get("pleth") or aliases.get("ppg")
        ecg_name = aliases.get("ii") or aliases.get("ecg") or aliases.get("ekg")
        if not (time_name and ppg_name and ecg_name):
            raise ValueError(f"BIDMC CSV must contain Time [s], PLETH and II: {reader.fieldnames}")
        time_s: list[float] = []
        ppg: list[float] = []
        ecg: list[float] = []
        for row in reader:
            try:
                t = float(row[time_name])
                p = float(row[ppg_name])
                e = float(row[ecg_name])
            except (TypeError, ValueError):
                continue
            if np.isfinite(t) and np.isfinite(p) and np.isfinite(e):
                time_s.append(t)
                ppg.append(p)
                ecg.append(e)
    t = np.asarray(time_s, dtype=float)
    if t.size < 3:
        raise ValueError(f"Not enough synchronized samples in {path}")
    dt = np.diff(t)
    dt = dt[dt > 0]
    fs = float(1.0 / np.median(dt)) if dt.size else 125.0
    rid = record_id or path.stem
    return BenchmarkRecord(
        record_id=str(rid),
        ppg=np.asarray(ppg, dtype=float),
        ppg_fs=fs,
        ecg=np.asarray(ecg, dtype=float),
        ecg_fs=fs,
        metadata={
            "dataset": "BIDMC",
            "source_file": str(path),
            "license": "Open Data Commons Attribution License v1.0",
        },
    )


def load_bidmc(record_id: str, cache_dir: str | Path) -> BenchmarkRecord:
    rid = _normalize_record_id(record_id)
    return load_bidmc_csv(fetch_bidmc_csv(rid, cache_dir), record_id=f"bidmc{rid}")


def _load_series_csv(path: str | Path, value_col: str, time_col: str) -> tuple[np.ndarray, np.ndarray]:
    times: list[float] = []
    values: list[float] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                t = float(row[time_col])
                v = float(row[value_col])
            except (KeyError, TypeError, ValueError):
                continue
            if np.isfinite(t) and np.isfinite(v):
                times.append(t)
                values.append(v)
    if len(times) < 3:
        raise ValueError(f"Not enough valid rows in {path}")
    t = np.asarray(times, dtype=float)
    return t, np.asarray(values, dtype=float)


def load_csv_pair(
    *,
    ppg_csv: str | Path,
    ecg_csv: str | Path,
    ppg_value_col: str,
    ecg_value_col: str,
    ppg_time_col: str,
    ecg_time_col: str,
    record_id: str = "local_pair",
) -> BenchmarkRecord:
    """Load a synchronized external ECG + wrist PPG experiment.

    The two files may have different sampling rates. Their timestamp columns must use
    the same time unit and clock origin; fixed physiological lag and slow drift are
    handled later by the alignment stage.
    """
    ppg_t, ppg = _load_series_csv(ppg_csv, ppg_value_col, ppg_time_col)
    ecg_t, ecg = _load_series_csv(ecg_csv, ecg_value_col, ecg_time_col)
    ppg_fs = float(1.0 / np.median(np.diff(ppg_t)))
    ecg_fs = float(1.0 / np.median(np.diff(ecg_t)))

    # Preserve synchronization. Crop both streams to their common time interval, then
    # place that overlap at t=0. Subtracting each file's first timestamp separately
    # would silently destroy a real device-start offset.
    common_start = float(max(ppg_t[0], ecg_t[0]))
    common_end = float(min(ppg_t[-1], ecg_t[-1]))
    if common_end - common_start < 3.0:
        raise ValueError("PPG/ECG CSV files have less than 3 s of overlapping time")
    ppg_uniform_t = np.arange(common_start, common_end, 1.0 / ppg_fs)
    ecg_uniform_t = np.arange(common_start, common_end, 1.0 / ecg_fs)
    ppg = np.interp(ppg_uniform_t, ppg_t, ppg)
    ecg = np.interp(ecg_uniform_t, ecg_t, ecg)

    return BenchmarkRecord(
        record_id=str(record_id),
        ppg=ppg,
        ppg_fs=ppg_fs,
        ecg=ecg,
        ecg_fs=ecg_fs,
        metadata={"dataset": "local_csv_pair", "ppg_csv": str(ppg_csv), "ecg_csv": str(ecg_csv)},
    )


def load_npz(path: str | Path, record_id: str | None = None) -> BenchmarkRecord:
    data = np.load(path, allow_pickle=False)
    ppg = np.asarray(data["ppg"], dtype=float)
    ppg_fs = float(data["ppg_fs"])
    ecg = np.asarray(data["ecg"], dtype=float) if "ecg" in data else None
    ecg_fs = float(data["ecg_fs"]) if "ecg_fs" in data else None
    ref = np.asarray(data["reference_beats_s"], dtype=float) if "reference_beats_s" in data else None
    return BenchmarkRecord(
        record_id=str(record_id or Path(path).stem), ppg=ppg, ppg_fs=ppg_fs,
        ecg=ecg, ecg_fs=ecg_fs, reference_beats_s=ref,
        metadata={"dataset": "npz", "source_file": str(path)},
    )
