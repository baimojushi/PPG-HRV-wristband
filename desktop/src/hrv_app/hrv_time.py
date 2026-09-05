from __future__ import annotations

from collections.abc import Sequence
import numpy as np

from .config import AnalysisConfig
from .models import (
    INVALID,
    VALID,
    BeatRecord,
    NNInterval,
    SignalQuality,
    TimeDomainMetrics,
)


def _max_artifact_run(records: Sequence[BeatRecord]) -> int:
    max_run = 0
    current = 0

    for record in records:
        if record.status != "accepted":
            current += 1
            max_run = max(max_run, current)
        else:
            current = 0

    return max_run


def _rmssd_block_bootstrap_ci(
    diffs: np.ndarray,
    iterations: int = 300,
    block_size: int = 3,
) -> tuple[float, float]:
    """
    对相邻 NN 差值做短块 bootstrap，给出近似 95% 区间。

    这是统计区间，不是“设备有 95% 概率正确”的含义。
    固定随机种子保证同一输入重复分析结果一致。
    """
    if diffs.size < 8:
        return 0.0, 0.0

    rng = np.random.default_rng(20260904)
    n = len(diffs)
    values = np.empty(iterations, dtype=float)

    starts = np.arange(max(n - block_size + 1, 1))

    for iteration in range(iterations):
        sampled: list[float] = []

        while len(sampled) < n:
            start = int(rng.choice(starts))
            block = diffs[start:start + block_size]
            sampled.extend(block.tolist())

        sample = np.asarray(sampled[:n], dtype=float)
        values[iteration] = np.sqrt(np.mean(np.square(sample)))

    low, high = np.percentile(values, [2.5, 97.5])
    return float(low), float(high)


def compute_time_domain(
    records: Sequence[BeatRecord],
    nn_intervals: Sequence[NNInterval],
    signal_quality: SignalQuality,
    config: AnalysisConfig | None = None,
) -> TimeDomainMetrics:
    cfg = config or AnalysisConfig()

    # 质量统计以“最近 60 个原始 RR 事件”为窗口，避免修复插值改变分母。
    record_window = list(records)[-cfg.time_window_rr_count:]
    if not record_window:
        return TimeDomainMetrics(
            valid=False,
            status=INVALID,
            validity_reason="RR 数据不足",
        )

    start_us = record_window[0].t_us
    end_us = record_window[-1].t_us

    interval_window = [
        interval
        for interval in nn_intervals
        if start_us <= interval.t_us <= end_us
    ]

    strict_intervals = [
        interval
        for interval in interval_window
        if interval.metric_eligible
        and not interval.corrected
        and interval.nn_ms > 0
        and np.isfinite(interval.nn_ms)
    ]

    total_records = max(len(record_window), 1)
    artifact_count = sum(
        record.status != "accepted"
        for record in record_window
    )
    corrected_count = sum(record.corrected for record in record_window)
    unresolved_count = sum(
        record.status in {
            "hard_outlier",
            "local_outlier",
            "no_wear",
            "unresolved",
        }
        for record in record_window
    )

    artifact_ratio = artifact_count / total_records
    corrected_ratio = corrected_count / total_records
    unresolved_ratio = unresolved_count / total_records
    max_consecutive = _max_artifact_run(record_window)

    values = np.asarray(
        [interval.nn_ms for interval in strict_intervals],
        dtype=float,
    )

    # 只有时间上连续的、原始 accepted NN 对才进入 RMSSD / pNN50。
    strict_by_time = {
        interval.t_us: interval
        for interval in strict_intervals
    }
    diffs: list[float] = []

    accepted_records = [
        record
        for record in record_window
        if record.status == "accepted"
        and record.metric_eligible
    ]

    for first, second in zip(accepted_records[:-1], accepted_records[1:]):
        # 中间如果存在被删除/修复的原始事件，则两端不再视为“相邻 NN”。
        first_index = record_window.index(first)
        second_index = record_window.index(second)

        if second_index != first_index + 1:
            continue

        first_interval = strict_by_time.get(first.t_us)
        second_interval = strict_by_time.get(second.t_us)

        if first_interval and second_interval:
            diffs.append(second_interval.nn_ms - first_interval.nn_ms)

    diff_array = np.asarray(diffs, dtype=float)

    reasons: list[str] = []
    if len(values) < cfg.time_min_valid_rr_count:
        reasons.append(
            f"有效 NN 不足：{len(values)}/{cfg.time_min_valid_rr_count}"
        )
    if artifact_ratio > cfg.time_max_artifact_ratio:
        reasons.append(
            f"异常搏 {artifact_ratio * 100:.1f}% > "
            f"{cfg.time_max_artifact_ratio * 100:.1f}%"
        )
    if unresolved_ratio > cfg.time_max_unresolved_ratio:
        reasons.append(
            f"未解决异常 {unresolved_ratio * 100:.1f}% > "
            f"{cfg.time_max_unresolved_ratio * 100:.1f}%"
        )
    if max_consecutive > cfg.time_max_consecutive_artifacts:
        reasons.append(
            f"连续异常搏 {max_consecutive} > "
            f"{cfg.time_max_consecutive_artifacts}"
        )
    if signal_quality.sqi < cfg.time_min_sqi:
        reasons.append(
            f"SQI {signal_quality.sqi * 100:.0f}% < "
            f"{cfg.time_min_sqi * 100:.0f}%"
        )

    valid = (
        not reasons
        and diff_array.size >= 4
    )

    if values.size:
        mean_nn = float(np.mean(values))
        mean_hr = float(60000.0 / mean_nn) if mean_nn > 0 else 0.0
        sdnn = (
            float(np.std(values, ddof=1))
            if values.size >= 2
            else 0.0
        )
    else:
        mean_nn = 0.0
        mean_hr = 0.0
        sdnn = 0.0

    rmssd = (
        float(np.sqrt(np.mean(np.square(diff_array))))
        if diff_array.size
        else 0.0
    )
    pnn50 = (
        float(np.mean(np.abs(diff_array) > 50.0) * 100.0)
        if diff_array.size
        else 0.0
    )

    ci_low, ci_high = (
        _rmssd_block_bootstrap_ci(diff_array)
        if valid
        else (0.0, 0.0)
    )

    return TimeDomainMetrics(
        valid=valid,
        status=VALID if valid else INVALID,
        validity_reason="；".join(reasons),
        nn_count=int(values.size),
        mean_nn_ms=mean_nn,
        mean_hr_bpm=mean_hr,
        rmssd_ms=rmssd,
        rmssd_ci_low_ms=ci_low,
        rmssd_ci_high_ms=ci_high,
        sdnn_ms=sdnn,
        pnn50_percent=pnn50,
        artifact_ratio=float(artifact_ratio),
        detected_artifact_ratio=float(artifact_ratio),
        corrected_ratio=float(corrected_ratio),
        unresolved_suspect_ratio=float(unresolved_ratio),
        max_consecutive_artifacts=max_consecutive,
    )
