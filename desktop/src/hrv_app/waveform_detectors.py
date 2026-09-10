from __future__ import annotations

from dataclasses import dataclass
import warnings

import numpy as np
from scipy import signal

from .config import AnalysisConfig
from .ppg_preprocessor import PreprocessedPPG


@dataclass(slots=True)
class DetectorPeak:
    detector: str
    index: int
    t_us: int
    score: float
    prominence: float


def _boxcar(values: np.ndarray, size: int) -> np.ndarray:
    size = max(int(size), 1)
    if size <= 1:
        return values.astype(float, copy=True)
    kernel = np.ones(size, dtype=float) / float(size)
    return np.convolve(values, kernel, mode="same")


def _prominence_score(values: np.ndarray, peaks: np.ndarray) -> tuple[np.ndarray, float]:
    if peaks.size == 0:
        return np.asarray([], dtype=float), 1.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        prominences = signal.peak_prominences(values, peaks)[0]
    amplitude = max(
        float(np.percentile(values, 95) - np.percentile(values, 5)),
        1e-6,
    )
    scores = np.clip(prominences / (0.35 * amplitude), 0.0, 1.0)
    return scores.astype(float), amplitude


def detect_elgendi_like(
    ppg: PreprocessedPPG,
    config: AnalysisConfig | None = None,
) -> list[DetectorPeak]:
    """Elgendi-style moving-window detector.

    This is an independently implemented detector inspired by the open method:
    positive half-wave -> square -> short/beat moving averages -> adaptive blocks
    -> strongest systolic peak per block. It intentionally does not consult RR
    history or firmware beat events.
    """

    cfg = config or AnalysisConfig()
    x = np.asarray(ppg.signal, dtype=float)
    fs = float(ppg.sample_rate_hz)
    if x.size < max(24, int(fs)):
        return []

    positive = np.maximum(x, 0.0)
    squared = positive * positive

    peak_window = max(1, int(round(cfg.interval_elgendi_peak_window_s * fs)))
    beat_window = max(peak_window + 1, int(round(cfg.interval_elgendi_beat_window_s * fs)))
    ma_peak = _boxcar(squared, peak_window)
    ma_beat = _boxcar(squared, beat_window)
    threshold = ma_beat + cfg.interval_elgendi_offset * float(np.mean(squared))
    wave = ma_peak > threshold

    edges = np.diff(np.pad(wave.astype(np.int8), (1, 1)))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)

    min_block = max(1, int(round(cfg.interval_elgendi_peak_window_s * fs)))
    candidates: list[int] = []
    for start, end in zip(starts, ends, strict=False):
        if end - start < min_block:
            continue
        local = x[start:end]
        if local.size == 0:
            continue
        candidates.append(int(start + np.argmax(local)))

    if not candidates:
        return []

    # minimum physiological separation; when blocks overlap choose the stronger peak.
    min_delay = max(1, int(round(cfg.interval_detector_min_delay_s * fs)))
    candidates = sorted(set(candidates))
    compact: list[int] = []
    for idx in candidates:
        if not compact or idx - compact[-1] >= min_delay:
            compact.append(idx)
        elif x[idx] > x[compact[-1]]:
            compact[-1] = idx

    peaks = np.asarray(compact, dtype=int)
    prom_scores, _ = _prominence_score(x, peaks)
    if peaks.size:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            prominences = signal.peak_prominences(x, peaks)[0]
    else:
        prominences = np.asarray([])

    result: list[DetectorPeak] = []
    for idx, pscore, prominence in zip(peaks, prom_scores, prominences, strict=False):
        # Block evidence: short MA exceeds adaptive beat threshold at the peak.
        denom = max(float(threshold[idx]), 1e-9)
        block_margin = float(np.clip((ma_peak[idx] - threshold[idx]) / denom, 0.0, 1.0))
        score = float(np.clip(0.72 * pscore + 0.28 * block_margin, 0.0, 1.0))
        result.append(
            DetectorPeak(
                detector="elgendi_like",
                index=int(idx),
                t_us=int(ppg.t_us[idx]),
                score=score,
                prominence=float(prominence),
            )
        )
    return result


def detect_multiscale_persistence(
    ppg: PreprocessedPPG,
    config: AnalysisConfig | None = None,
) -> list[DetectorPeak]:
    """Multi-scale local-maximum persistence detector.

    MSPTD-family detectors are valuable because a real pulse maximum persists as a
    local maximum across many temporal scales. This implementation keeps that design
    idea but is intentionally compact and independently written: low-threshold local
    maxima are proposed first, then each candidate is scored by how many symmetric
    lag scales still regard it as a maximum. No amplitude threshold from the other
    detector is reused, keeping the two detection paths heterogeneous.
    """

    cfg = config or AnalysisConfig()
    x = np.asarray(ppg.signal, dtype=float)
    fs = float(ppg.sample_rate_hz)
    if x.size < max(24, int(fs)):
        return []

    amplitude = max(float(np.percentile(x, 95) - np.percentile(x, 5)), 1e-6)
    min_distance = max(1, int(round(cfg.interval_detector_min_delay_s * fs)))
    base_prominence = amplitude * cfg.interval_multiscale_base_prominence_ratio
    base, props = signal.find_peaks(
        x,
        distance=max(1, int(round(min_distance * 0.70))),
        prominence=max(base_prominence, 1e-6),
    )
    if base.size == 0:
        return []

    lag_min = max(1, int(round(cfg.interval_multiscale_min_scale_s * fs)))
    lag_max = max(lag_min + 1, int(round(cfg.interval_multiscale_max_scale_s * fs)))
    lags = np.unique(np.linspace(lag_min, lag_max, num=18).round().astype(int))

    scored: list[tuple[int, float, float]] = []
    prominences = props.get("prominences", np.zeros(base.size, dtype=float))
    for idx, prominence in zip(base, prominences, strict=False):
        valid = 0
        persistent = 0
        for lag in lags:
            left = int(idx) - int(lag)
            right = int(idx) + int(lag)
            if left < 0 or right >= x.size:
                continue
            valid += 1
            if x[idx] >= x[left] and x[idx] >= x[right]:
                persistent += 1
        if valid < max(4, len(lags) // 3):
            continue
        persistence = persistent / valid
        prominence_score = float(np.clip(prominence / (0.35 * amplitude), 0.0, 1.0))
        score = float(np.clip(0.68 * persistence + 0.32 * prominence_score, 0.0, 1.0))
        if persistence >= cfg.interval_multiscale_min_persistence:
            scored.append((int(idx), score, float(prominence)))

    if not scored:
        return []

    # Resolve any residual dicrotic/shoulder candidates by score within min delay.
    scored.sort(key=lambda item: item[0])
    compact: list[tuple[int, float, float]] = []
    for item in scored:
        idx, score, _ = item
        if not compact or idx - compact[-1][0] >= min_distance:
            compact.append(item)
        elif score > compact[-1][1]:
            compact[-1] = item

    return [
        DetectorPeak(
            detector="multiscale",
            index=idx,
            t_us=int(ppg.t_us[idx]),
            score=score,
            prominence=prominence,
        )
        for idx, score, prominence in compact
    ]
