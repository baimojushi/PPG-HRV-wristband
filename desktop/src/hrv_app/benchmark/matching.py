from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .types import BeatMatch, LagWindow, QualityWindow


def one_to_one_match(
    reference_s: Sequence[float],
    candidate_s: Sequence[float],
    tolerance_s: float,
) -> list[BeatMatch]:
    """Greedy chronological one-to-one matching.

    This prevents one candidate beat from satisfying two adjacent references, which is
    essential when reporting sensitivity/PPV/F1.
    """

    ref = np.asarray(reference_s, dtype=float)
    cand = np.asarray(candidate_s, dtype=float)
    matches: list[BeatMatch] = []
    i = j = 0
    tol = float(max(tolerance_s, 0.0))
    while i < ref.size and j < cand.size:
        delta = float(cand[j] - ref[i])
        if abs(delta) <= tol:
            # If the next candidate is closer to this reference and still in range,
            # use it; otherwise commit the current pair.
            if j + 1 < cand.size:
                next_delta = float(cand[j + 1] - ref[i])
                if abs(next_delta) < abs(delta) and abs(next_delta) <= tol:
                    j += 1
                    continue
            matches.append(BeatMatch(i, j, delta))
            i += 1
            j += 1
        elif delta < -tol:
            j += 1
        else:
            i += 1
    return matches


def _score_lag(
    reference: np.ndarray,
    ppg: np.ndarray,
    lag_s: float,
    tolerance_s: float,
) -> tuple[int, float]:
    aligned = ppg - float(lag_s)
    matches = one_to_one_match(reference, aligned, tolerance_s)
    if not matches:
        return 0, float("inf")
    residual = np.asarray([abs(m.residual_s) for m in matches], dtype=float)
    return len(matches), float(np.median(residual))


def estimate_piecewise_lag(
    reference_s: Sequence[float],
    ppg_s: Sequence[float],
    *,
    window_s: float = 300.0,
    lag_min_s: float = -0.10,
    lag_max_s: float = 0.80,
    lag_step_s: float = 0.005,
    tolerance_s: float = 0.150,
) -> list[LagWindow]:
    """Estimate ECG→PPG lag, allowing slow drift across long records.

    PPG-beats/MSPTDfast v2 uses a ±150 ms correctness window and allows lag to vary
    within a recording (re-estimated every 300 s). We independently implement that
    design idea here, without copying toolbox code.
    """

    ref = np.asarray(reference_s, dtype=float)
    ppg = np.asarray(ppg_s, dtype=float)
    if ref.size == 0 or ppg.size == 0:
        return []

    start = float(min(ref[0], ppg[0]))
    end = float(max(ref[-1], ppg[-1]))
    width = max(float(window_s), 30.0)
    centers = np.arange(start + width / 2.0, end + width / 2.0, width)
    if centers.size == 0:
        centers = np.asarray([(start + end) / 2.0], dtype=float)

    lag_grid = np.arange(lag_min_s, lag_max_s + 0.5 * lag_step_s, lag_step_s)
    result: list[LagWindow] = []
    half = width / 2.0
    for center in centers:
        rmask = (ref >= center - half) & (ref < center + half)
        pmask = (ppg >= center - half + lag_min_s) & (ppg < center + half + lag_max_s)
        r = ref[rmask]
        p = ppg[pmask]
        if r.size < 4 or p.size < 4:
            continue

        best_lag = 0.0
        best_count = -1
        best_residual = float("inf")
        for lag in lag_grid:
            count, residual = _score_lag(r, p, float(lag), tolerance_s)
            if count > best_count or (count == best_count and residual < best_residual):
                best_count = count
                best_residual = residual
                best_lag = float(lag)

        # Refine using robust residuals around the best coarse lag.
        aligned = p - best_lag
        matches = one_to_one_match(r, aligned, tolerance_s)
        if matches:
            residuals = np.asarray([m.residual_s for m in matches], dtype=float)
            best_lag += float(np.median(residuals))
        result.append(
            LagWindow(
                center_s=float(center),
                lag_s=float(best_lag),
                matched_count=max(int(best_count), 0),
                reference_count=int(r.size),
            )
        )

    if not result:
        # Short recording fallback: estimate one global lag.
        best_lag = 0.0
        best_count = -1
        best_residual = float("inf")
        for lag in lag_grid:
            count, residual = _score_lag(ref, ppg, float(lag), tolerance_s)
            if count > best_count or (count == best_count and residual < best_residual):
                best_count = count
                best_residual = residual
                best_lag = float(lag)
        result = [
            LagWindow(
                center_s=float((start + end) / 2.0),
                lag_s=best_lag,
                matched_count=max(int(best_count), 0),
                reference_count=int(ref.size),
            )
        ]
    return result


def apply_piecewise_lag(ppg_s: Sequence[float], windows: Sequence[LagWindow]) -> np.ndarray:
    ppg = np.asarray(ppg_s, dtype=float)
    if ppg.size == 0 or not windows:
        return ppg.copy()
    centers = np.asarray([w.center_s for w in windows], dtype=float)
    lags = np.asarray([w.lag_s for w in windows], dtype=float)
    order = np.argsort(centers)
    centers = centers[order]
    lags = lags[order]
    if centers.size == 1:
        return ppg - lags[0]
    interp_lag = np.interp(ppg, centers, lags, left=lags[0], right=lags[-1])
    return ppg - interp_lag


def in_valid_windows(times_s: Sequence[float], windows: Sequence[QualityWindow]) -> np.ndarray:
    times = np.asarray(times_s, dtype=float)
    if times.size == 0:
        return np.zeros(0, dtype=bool)
    if not windows:
        return np.ones(times.size, dtype=bool)
    mask = np.zeros(times.size, dtype=bool)
    for window in windows:
        if not window.valid:
            continue
        mask |= (times >= float(window.start_s)) & (times < float(window.end_s))
    return mask
