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

    SQI 采用明确权重的质量分量，不再称作“置信概率”：
    - 削底/饱和：45%
    - 佩戴：20%
    - 采样时基：15%
    - 样本序号连续性：10%
    - 协议完整性：10%

    任一分量都可以在 summary 中追溯，不存在 V0.2 的 1e-6 几何平均和 +0.15 截断。
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
    sqi = float(np.clip(sqi, 0.0, 1.0))

    if sqi >= 0.80:
        status = VALID
    elif sqi >= 0.65:
        status = LIMITED
    else:
        status = INVALID

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
        reasons.append("采样时基抖动偏高")
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
        timing_jitter_p95_ms=timing_jitter_p95_ms,
        protocol_error_ratio=protocol_error_ratio,
        protocol_seq_gaps=protocol.sample_seq_gaps,
        reasons=reasons,
    )
