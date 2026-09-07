from __future__ import annotations

from .models import (
    INVALID,
    LIMITED,
    VALID,
    FrequencyDomainMetrics,
    QualityAssessment,
    SignalQuality,
    TimeDomainMetrics,
    TimelineQuality,
)


def compute_quality_assessment(
    signal_quality: SignalQuality,
    timeline_quality: TimelineQuality,
    time_metrics: TimeDomainMetrics,
    frequency_metrics: FrequencyDomainMetrics,
) -> QualityAssessment:
    """
    汇总结果有效性。

    V0.2 的“confidence”是人工公式分数，却在 UI 上呈现成概率。
    V0.2.1 只保留：
    - SQI：数据质量指数；
    - VALID / LIMITED / INVALID：结果有效性；
    - 明确的原因列表。
    """
    reasons = (
        list(signal_quality.reasons)
        + list(timeline_quality.reasons)
    )

    if time_metrics.valid and frequency_metrics.valid:
        # “valid=True”表示允许正式显示数值；
        # 结果等级仍由各模块的 VALID / LIMITED 决定。
        if (
            time_metrics.status == VALID
            and frequency_metrics.status == VALID
        ):
            status = VALID
        else:
            status = LIMITED

    elif time_metrics.valid:
        # 前 5 分钟频域尚未就绪，或频域被质量门暂停时，
        # 时域仍可作为独立 LIMITED 结果。
        status = LIMITED

    else:
        status = INVALID

    if time_metrics.validity_reason:
        reasons.append(time_metrics.validity_reason)
    if (
        frequency_metrics.validity_reason
        and "窗口积累中" not in frequency_metrics.validity_reason
    ):
        reasons.append(frequency_metrics.validity_reason)

    return QualityAssessment(
        sqi=signal_quality.sqi,
        status=status,
        time_status=time_metrics.status,
        frequency_status=frequency_metrics.status,
        reasons=list(dict.fromkeys(reasons)),
    )
