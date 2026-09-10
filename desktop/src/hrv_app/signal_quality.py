from __future__ import annotations

from collections.abc import Sequence
import numpy as np

from .config import AnalysisConfig
from .models import (
    INVALID,
    LIMITED,
    VALID,
    ProtocolHealth,
    SampleFrame,
    SignalQuality,
)


def evaluate_signal_quality(
    samples: Sequence[SampleFrame],
    protocol_health: ProtocolHealth | None = None,
    config: AnalysisConfig | None = None,
) -> SignalQuality:
    """
    计算透明、可解释的数据质量指数 SQI。

    v0.4.1 将质量拆成两层：
    - contact_score：传感器接触 / ADC 动态范围；
    - transport_score：设备时间戳、样本连续性、协议完整性。

    `sqi` 继续保留旧 UI 的综合显示语义，但正式 HRV 不再因为“波谷削底”
    直接判无效；HRV gate 使用 transport + BeatTimelineQuality。
    """
    cfg = config or AnalysisConfig()
    protocol = protocol_health or ProtocolHealth()

    if len(samples) < 8:
        return SignalQuality(
            sqi=0.0,
            status=INVALID,
            protocol_error_ratio=protocol.error_ratio,
            protocol_seq_gaps=protocol.sample_seq_gaps,
            reasons=["正在积累 PPG 信号"],
        )

    raw = np.asarray([s.raw for s in samples], dtype=float)
    seq = np.asarray([s.seq for s in samples], dtype=np.int64)
    t_us = np.asarray([s.t_us for s in samples], dtype=np.int64)
    flags = np.asarray([s.flags for s in samples], dtype=np.int64)

    wear = (flags & 0x01) != 0
    wear_ratio = float(np.mean(wear))

    # 数值边界和固件 flags 双重检查，兼容历史 CSV。
    clip_low = (raw <= cfg.adc_low) | ((flags & 0x02) != 0)
    clip_high = (raw >= cfg.adc_high) | ((flags & 0x04) != 0)
    clip_low_ratio = float(np.mean(clip_low))
    clip_high_ratio = float(np.mean(clip_high))
    clipping_ratio = min(clip_low_ratio + clip_high_ratio, 1.0)

    # seq 直接计算当前 SQI 窗口内的缺样比例。
    expected_count = max(int(seq[-1] - seq[0] + 1), len(seq))
    missing = max(expected_count - len(seq), 0)
    sequence_drop_ratio = float(missing / max(expected_count, 1))

    dt_ms = np.diff(t_us.astype(float)) / 1000.0
    expected_ms = 1000.0 / cfg.sample_rate_hz
    timing_error = np.abs(dt_ms - expected_ms)
    timing_jitter_p95_ms = (
        float(np.percentile(timing_error, 95))
        if timing_error.size
        else 0.0
    )

    if t_us.size >= 2 and t_us[-1] > t_us[0]:
        effective_sample_rate_hz = float(
            (len(t_us) - 1)
            / (
                (t_us[-1] - t_us[0])
                / 1e6
            )
        )
    else:
        effective_sample_rate_hz = 0.0

    timing_overrun_ratio = (
        float(
            np.mean(
                dt_ms
                > expected_ms * 1.5
            )
        )
        if dt_ms.size
        else 0.0
    )

    protocol_error_ratio = float(protocol.error_ratio)

    # -----------------------------------------------------------------------
    # 将每一项映射到 0–1；这些阈值全部集中在 config.py，可审计、可回归。
    # -----------------------------------------------------------------------
    clipping_score = float(np.clip(
        1.0 - clipping_ratio / cfg.sqi_clipping_fail_ratio,
        0.0,
        1.0,
    ))
    wear_score = float(np.clip(wear_ratio, 0.0, 1.0))
    timing_score = float(np.clip(
        1.0 - timing_jitter_p95_ms / cfg.sqi_timing_jitter_fail_ms,
        0.0,
        1.0,
    ))
    sequence_score = float(np.clip(
        1.0 - sequence_drop_ratio / cfg.sqi_sequence_drop_fail_ratio,
        0.0,
        1.0,
    ))
    protocol_score = float(np.clip(
        1.0 - protocol_error_ratio / cfg.sqi_protocol_error_fail_ratio,
        0.0,
        1.0,
    ))

    sqi = (
        0.45 * clipping_score
        + 0.20 * wear_score
        + 0.15 * timing_score
        + 0.10 * sequence_score
        + 0.10 * protocol_score
    )
    sqi = float(
        np.clip(
            sqi,
            0.0,
            1.0,
        )
    )

    # -------------------------------------------------------------------
    # 严重采样时基异常不能被“佩戴很好 / 没削顶”抵消。
    # -------------------------------------------------------------------
    effective_rate_error = (
        abs(
            effective_sample_rate_hz
            - cfg.sample_rate_hz
        )
        / cfg.sample_rate_hz
        if effective_sample_rate_hz > 0
        else 1.0
    )

    if (
        effective_rate_error
        > cfg.sqi_effective_rate_fail_ratio
        or timing_overrun_ratio
        > cfg.sqi_timing_overrun_fail_ratio
    ):
        # 直接压到 INVALID 区间。
        sqi = min(
            sqi,
            0.64,
        )

    elif (
        effective_rate_error
        > cfg.sqi_effective_rate_warn_ratio
        or timing_overrun_ratio
        > cfg.sqi_timing_overrun_warn_ratio
    ):
        # 中度时基偏差最多只能 LIMITED。
        sqi = min(
            sqi,
            0.79,
        )

    contact_score = float(np.clip(
        0.65 * clipping_score + 0.35 * wear_score,
        0.0,
        1.0,
    ))
    transport_score = float(np.clip(
        0.45 * timing_score + 0.30 * sequence_score + 0.25 * protocol_score,
        0.0,
        1.0,
    ))

    # Effective-rate / long-overrun are transport hard evidence and must not be
    # diluted by otherwise good packet counts.
    if (
        effective_rate_error > cfg.sqi_effective_rate_fail_ratio
        or timing_overrun_ratio > cfg.sqi_timing_overrun_fail_ratio
    ):
        transport_score = min(transport_score, 0.64)
    elif (
        effective_rate_error > cfg.sqi_effective_rate_warn_ratio
        or timing_overrun_ratio > cfg.sqi_timing_overrun_warn_ratio
    ):
        transport_score = min(transport_score, 0.79)

    def _status(value: float) -> str:
        if value >= 0.80:
            return VALID
        if value >= 0.65:
            return LIMITED
        return INVALID

    contact_status = _status(contact_score)
    transport_status = _status(transport_score)
    status = _status(sqi)

    reasons: list[str] = []
    if wear_ratio < 0.90:
        reasons.append("佩戴状态不稳定")
    if clip_low_ratio > 0.03:
        reasons.append("PPG 低端削底")
    if clip_high_ratio > 0.03:
        reasons.append("PPG 高端饱和")
    if sequence_drop_ratio > 0.002:
        reasons.append("存在采样序号缺口")
    if timing_jitter_p95_ms > 0.8:
        reasons.append(
            "采样时基抖动偏高"
            f"（p95 {timing_jitter_p95_ms:.1f} ms，"
            f"有效 {effective_sample_rate_hz:.1f} Hz）"
        )

    if (
        effective_rate_error
        > cfg.sqi_effective_rate_warn_ratio
    ):
        reasons.append(
            "有效采样率偏离目标 "
            f"{effective_sample_rate_hz:.1f}/"
            f"{cfg.sample_rate_hz:.0f} Hz"
        )

    if (
        timing_overrun_ratio
        > cfg.sqi_timing_overrun_warn_ratio
    ):
        reasons.append(
            f"采样超时比例 {timing_overrun_ratio * 100:.1f}%"
        )
    if protocol_error_ratio > cfg.protocol_max_error_ratio:
        reasons.append("协议错误比例偏高")
    if protocol.sample_seq_gaps > 0:
        reasons.append(f"协议侧累计样本序号缺口 {protocol.sample_seq_gaps}")

    if not reasons and status == VALID:
        reasons.append("PPG 与传输质量稳定")

    return SignalQuality(
        sqi=sqi,
        status=status,
        wear_ratio=wear_ratio,
        clip_low_ratio=clip_low_ratio,
        clip_high_ratio=clip_high_ratio,
        sequence_drop_ratio=sequence_drop_ratio,
        effective_sample_rate_hz=effective_sample_rate_hz,
        timing_jitter_p95_ms=timing_jitter_p95_ms,
        timing_overrun_ratio=timing_overrun_ratio,
        protocol_error_ratio=protocol_error_ratio,
        protocol_seq_gaps=protocol.sample_seq_gaps,
        transport_score=transport_score,
        transport_status=transport_status,
        contact_score=contact_score,
        contact_status=contact_status,
        reasons=reasons,
    )
