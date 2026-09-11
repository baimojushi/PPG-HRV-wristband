from __future__ import annotations

from time import perf_counter

import numpy as np

from ..config import AnalysisConfig
from ..interval_core import IntervalCore
from ..models import SampleFrame


def _as_samples(ppg: np.ndarray, fs: float) -> list[SampleFrame]:
    values = np.asarray(ppg, dtype=float)
    finite = np.isfinite(values)
    if not np.any(finite):
        values = np.zeros_like(values)
    elif not np.all(finite):
        idx = np.arange(values.size, dtype=float)
        values = values.copy()
        values[~finite] = np.interp(idx[~finite], idx[finite], values[finite])

    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    scale = max(1.4826 * mad, float(np.std(values)), 1e-6)
    # Public datasets do not use this device's ADC units. Map a copy into a safe ADC
    # range for the hardware-contact fields while preserving the real PPG in filtered.
    raw_proxy = np.clip(2048.0 + 220.0 * (values - median) / scale, 256.0, 3840.0)
    step_us = 1e6 / fs
    return [
        SampleFrame(
            seq=i,
            t_us=int(round(i * step_us)),
            raw=float(raw_proxy[i]),
            avg=float(raw_proxy[i]),
            filtered=float(values[i]),
            peak=0,
            hr_bpm=0.0,
            flags=1,
        )
        for i in range(values.size)
    ]


def detect_with_production_interval_core(
    ppg: np.ndarray,
    fs: float,
    *,
    config: AnalysisConfig | None = None,
    commit_step_s: float = 4.0,
) -> tuple[np.ndarray, float, dict[str, float]]:
    """Run the exact v0.4.1 interval core without firmware beat input."""
    if fs <= 0:
        raise ValueError("PPG sampling rate must be positive")
    samples = _as_samples(np.asarray(ppg, dtype=float), fs)
    if len(samples) < max(24, int(fs * 3)):
        return np.asarray([], dtype=float), 0.0, {}

    cfg = config or AnalysisConfig()
    core = IntervalCore(cfg)
    lag_s = max(0.0, float(cfg.correction_output_lag_seconds))
    total_s = len(samples) / fs
    last_committed_us = 0
    rr_history: list[float] = []
    beats_us: list[int] = []
    supports: list[int] = []
    consensuses: list[float] = []
    spreads: list[float] = []
    rescues = 0

    start_clock = perf_counter()
    commit_s = max(2.0, float(commit_step_s))
    while commit_s + lag_s < total_s:
        latest_s = commit_s + lag_s
        end_index = min(len(samples), int(np.ceil(latest_s * fs)) + 1)
        history_s = float(cfg.waveform_context_history_seconds) + 3.0
        start_index = max(0, int(np.floor((commit_s - history_s) * fs)))
        window = samples[start_index:end_index]
        proposals = core.propose(
            window,
            [],
            last_committed_t_us=last_committed_us,
            rr_history_ms=rr_history,
            commit_until_t_us=int(round(commit_s * 1e6)),
        )
        for proposal in proposals:
            if beats_us and proposal.t_us <= beats_us[-1]:
                continue
            if beats_us:
                rr = (proposal.t_us - beats_us[-1]) / 1000.0
                if cfg.waveform_min_rr_ms <= rr <= cfg.waveform_max_rr_ms:
                    rr_history.append(float(rr))
                    rr_history = rr_history[-32:]
            beats_us.append(int(proposal.t_us))
            supports.append(int(proposal.detector_support_count))
            consensuses.append(float(proposal.detector_consensus))
            if np.isfinite(proposal.detector_time_spread_ms):
                spreads.append(float(proposal.detector_time_spread_ms))
            rescues += int(bool(proposal.sequence_rescued))
            last_committed_us = int(proposal.t_us)
        commit_s += float(commit_step_s)

    # Final tail: the production app intentionally avoids the last edge samples. Keep
    # 250 ms as the boundary guard while still evaluating almost all of the record.
    final_commit_s = max(0.0, total_s - 0.25)
    history_s = float(cfg.waveform_context_history_seconds) + lag_s + 3.0
    start_index = max(0, int(np.floor((final_commit_s - history_s) * fs)))
    proposals = core.propose(
        samples[start_index:],
        [],
        last_committed_t_us=last_committed_us,
        rr_history_ms=rr_history,
        commit_until_t_us=int(round(final_commit_s * 1e6)),
    )
    for proposal in proposals:
        if beats_us and proposal.t_us <= beats_us[-1]:
            continue
        beats_us.append(int(proposal.t_us))
        supports.append(int(proposal.detector_support_count))
        consensuses.append(float(proposal.detector_consensus))
        if np.isfinite(proposal.detector_time_spread_ms):
            spreads.append(float(proposal.detector_time_spread_ms))
        rescues += int(bool(proposal.sequence_rescued))

    elapsed = perf_counter() - start_clock
    count = max(len(beats_us), 1)
    evidence = {
        "dual_detector_ratio": float(sum(v >= 2 for v in supports) / count),
        "detector_consensus_mean": float(np.mean(consensuses)) if consensuses else 0.0,
        "detector_time_spread_p95_ms": float(np.percentile(spreads, 95)) if spreads else 0.0,
        "sequence_rescue_ratio": float(rescues / count),
    }
    return np.asarray(beats_us, dtype=float) / 1e6, float(elapsed), evidence
