from __future__ import annotations

import numpy as np
from scipy import signal

from .matching import one_to_one_match
from .types import ECGReference, QualityWindow


def _finite_signal(values: np.ndarray) -> np.ndarray:
    x = np.asarray(values, dtype=float).copy()
    finite = np.isfinite(x)
    if not np.any(finite):
        return np.zeros_like(x)
    if not np.all(finite):
        idx = np.arange(x.size, dtype=float)
        x[~finite] = np.interp(idx[~finite], idx[finite], x[finite])
    return x


def _bandpass(ecg: np.ndarray, fs: float, low_hz: float, high_hz: float) -> np.ndarray:
    x = _finite_signal(ecg)
    x -= float(np.median(x))
    nyq = fs * 0.5
    low = max(0.5 / nyq, low_hz / nyq)
    high = min(high_hz / nyq, 0.95)
    if x.size < max(32, int(2.0 * fs)) or not (0 < low < high < 1):
        return x
    sos = signal.butter(2, [low, high], btype="bandpass", output="sos")
    try:
        return signal.sosfiltfilt(sos, x)
    except ValueError:
        return x


def _moving_average(x: np.ndarray, samples: int) -> np.ndarray:
    n = max(1, int(samples))
    kernel = np.ones(n, dtype=float) / n
    return np.convolve(x, kernel, mode="same")


def _refine_to_qrs(filtered: np.ndarray, candidates: np.ndarray, fs: float) -> np.ndarray:
    radius = max(1, int(round(0.090 * fs)))
    refined: list[int] = []
    magnitude = np.abs(filtered)
    for idx in candidates:
        left = max(0, int(idx) - radius)
        right = min(filtered.size, int(idx) + radius + 1)
        if right <= left:
            continue
        refined.append(int(left + np.argmax(magnitude[left:right])))
    if not refined:
        return np.asarray([], dtype=int)
    refined = sorted(set(refined))
    # QRS refractory period; keep the larger deflection on duplicates.
    refractory = max(1, int(round(0.240 * fs)))
    compact = [refined[0]]
    for idx in refined[1:]:
        if idx - compact[-1] >= refractory:
            compact.append(idx)
        elif magnitude[idx] > magnitude[compact[-1]]:
            compact[-1] = idx
    return np.asarray(compact, dtype=int)


def detect_ecg_energy(ecg: np.ndarray, fs: float) -> np.ndarray:
    """Pan–Tompkins-like derivative-energy path, independently implemented."""
    filtered = _bandpass(ecg, fs, 5.0, 18.0)
    derivative = np.diff(filtered, prepend=filtered[0])
    envelope = _moving_average(derivative * derivative, int(round(0.120 * fs)))
    med = float(np.median(envelope))
    mad = float(np.median(np.abs(envelope - med)))
    prominence = max(2.0 * mad, float(np.percentile(envelope, 75) - med) * 0.35, 1e-12)
    peaks, _ = signal.find_peaks(
        envelope,
        distance=max(1, int(round(0.260 * fs))),
        prominence=prominence,
    )
    return _refine_to_qrs(filtered, peaks, fs)


def detect_ecg_bandpeak(ecg: np.ndarray, fs: float) -> np.ndarray:
    """Independent band-limited QRS-magnitude detector.

    Unlike the derivative-energy path this works directly on local absolute QRS
    deflection and prominence, providing useful detector heterogeneity for reference
    quality assessment.
    """
    filtered = _bandpass(ecg, fs, 8.0, 28.0)
    magnitude = _moving_average(np.abs(filtered), int(round(0.035 * fs)))
    med = float(np.median(magnitude))
    mad = float(np.median(np.abs(magnitude - med)))
    prominence = max(1.8 * mad, float(np.percentile(magnitude, 75) - med) * 0.30, 1e-9)
    peaks, _ = signal.find_peaks(
        magnitude,
        distance=max(1, int(round(0.260 * fs))),
        prominence=prominence,
    )
    return _refine_to_qrs(filtered, peaks, fs)


def build_ecg_reference(
    ecg: np.ndarray,
    fs: float,
    *,
    window_s: float = 20.0,
    agreement_tolerance_s: float = 0.080,
    min_window_f1: float = 0.90,
    min_beats_per_window: int = 6,
) -> ECGReference:
    if fs <= 0:
        raise ValueError("ECG sampling rate must be positive")
    ecg = np.asarray(ecg, dtype=float)
    a_idx = detect_ecg_energy(ecg, fs)
    b_idx = detect_ecg_bandpeak(ecg, fs)
    a = a_idx.astype(float) / fs
    b = b_idx.astype(float) / fs

    duration = float(ecg.size / fs)
    windows: list[QualityWindow] = []
    accepted: list[float] = []
    start = 0.0
    while start < duration:
        end = min(duration, start + window_s)
        amask = (a >= start) & (a < end)
        bmask = (b >= start) & (b < end)
        aa = a[amask]
        bb = b[bmask]
        matches = one_to_one_match(aa, bb, agreement_tolerance_s)
        correct = len(matches)
        se = correct / len(aa) if len(aa) else 0.0
        ppv = correct / len(bb) if len(bb) else 0.0
        f1 = (2.0 * se * ppv / (se + ppv)) if (se + ppv) > 0 else 0.0
        valid = bool(
            len(aa) >= min_beats_per_window
            and len(bb) >= min_beats_per_window
            and f1 >= min_window_f1
        )
        if valid:
            for match in matches:
                # Midpoint suppresses small detector-specific fiducial bias.
                accepted.append(float((aa[match.reference_index] + bb[match.ppg_index]) * 0.5))
        windows.append(
            QualityWindow(
                start_s=float(start),
                end_s=float(end),
                valid=valid,
                agreement_f1=float(f1),
                detector_a_count=int(len(aa)),
                detector_b_count=int(len(bb)),
                matched_count=int(correct),
            )
        )
        start = end

    return ECGReference(
        beats_s=np.asarray(sorted(set(accepted)), dtype=float),
        method="dual_ecg_consensus",
        quality_windows=windows,
        detector_a_s=a,
        detector_b_s=b,
    )


def reference_from_annotations(beats_s: np.ndarray, duration_s: float) -> ECGReference:
    beats = np.asarray(beats_s, dtype=float)
    beats = beats[np.isfinite(beats)]
    beats = np.unique(beats[(beats >= 0.0) & (beats <= max(duration_s, 0.0))])
    window = QualityWindow(
        start_s=0.0,
        end_s=float(max(duration_s, beats[-1] if beats.size else 0.0)),
        valid=True,
        agreement_f1=1.0,
        detector_a_count=int(beats.size),
        detector_b_count=int(beats.size),
        matched_count=int(beats.size),
    )
    return ECGReference(beats_s=beats, method="provided_annotations", quality_windows=[window])
