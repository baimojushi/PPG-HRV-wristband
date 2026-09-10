from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

import numpy as np

from .config import AnalysisConfig
from .models import BeatRecord


@dataclass(slots=True)
class IntervalQualityEvidence:
    evidence_count: int = 0
    dual_detector_ratio: float = 1.0
    single_detector_ratio: float = 0.0
    detector_consensus_mean: float = 1.0
    detector_time_spread_p95_ms: float = 0.0
    sequence_rescue_ratio: float = 0.0
    local_clip_ratio: float = 0.0
    firmware_unmatched_ratio: float = 0.0

    def hard_reasons(self, config: AnalysisConfig) -> list[str]:
        if self.evidence_count <= 0:
            return []
        reasons: list[str] = []
        if self.dual_detector_ratio < config.interval_limited_min_dual_detector_ratio:
            reasons.append(
                f"双检测器一致心搏 {self.dual_detector_ratio * 100:.0f}% < "
                f"{config.interval_limited_min_dual_detector_ratio * 100:.0f}%"
            )
        if self.single_detector_ratio > config.interval_limited_max_single_detector_ratio:
            reasons.append(
                f"单检测器心搏 {self.single_detector_ratio * 100:.1f}% > "
                f"{config.interval_limited_max_single_detector_ratio * 100:.1f}%"
            )
        if self.detector_time_spread_p95_ms > config.interval_limited_max_detector_spread_p95_ms:
            reasons.append(
                f"独立检测器时间差 p95 {self.detector_time_spread_p95_ms:.1f} ms > "
                f"{config.interval_limited_max_detector_spread_p95_ms:.1f} ms"
            )
        if self.sequence_rescue_ratio > config.interval_limited_max_sequence_rescue_ratio:
            reasons.append(
                f"序列救援心搏 {self.sequence_rescue_ratio * 100:.1f}% > "
                f"{config.interval_limited_max_sequence_rescue_ratio * 100:.1f}%"
            )
        if self.local_clip_ratio > config.interval_limited_max_local_clip_ratio:
            reasons.append(
                f"心搏峰附近削底/饱和 {self.local_clip_ratio * 100:.1f}% > "
                f"{config.interval_limited_max_local_clip_ratio * 100:.1f}%"
            )
        return reasons

    def strict_reasons(self, config: AnalysisConfig) -> list[str]:
        if self.evidence_count <= 0:
            return []
        reasons: list[str] = []
        if self.dual_detector_ratio < config.interval_strict_min_dual_detector_ratio:
            reasons.append(f"双检测器一致心搏 {self.dual_detector_ratio * 100:.0f}%")
        if self.single_detector_ratio > config.interval_strict_max_single_detector_ratio:
            reasons.append(f"单检测器心搏 {self.single_detector_ratio * 100:.1f}%")
        if self.detector_time_spread_p95_ms > config.interval_strict_max_detector_spread_p95_ms:
            reasons.append(f"独立检测器时间差 p95 {self.detector_time_spread_p95_ms:.1f} ms")
        if self.sequence_rescue_ratio > config.interval_strict_max_sequence_rescue_ratio:
            reasons.append(f"序列救援心搏 {self.sequence_rescue_ratio * 100:.1f}%")
        if self.local_clip_ratio > config.interval_strict_max_local_clip_ratio:
            reasons.append(f"心搏峰附近削底/饱和 {self.local_clip_ratio * 100:.1f}%")
        return reasons


def evaluate_interval_quality(records: Sequence[BeatRecord]) -> IntervalQualityEvidence:
    evidence = [
        r for r in records
        if int(getattr(r, "detector_support_count", 0) or 0) > 0
    ]
    if not evidence:
        return IntervalQualityEvidence()

    count = len(evidence)
    dual = sum(int(r.detector_support_count) >= 2 for r in evidence) / count
    single = sum(
        bool(getattr(r, "single_detector", False))
        or int(r.detector_support_count) == 1
        for r in evidence
    ) / count
    consensus = np.asarray([
        float(r.detector_consensus)
        for r in evidence
        if np.isfinite(r.detector_consensus)
    ], dtype=float)
    spread = np.asarray([
        float(r.detector_time_spread_ms)
        for r in evidence
        if int(r.detector_support_count) >= 2
        and np.isfinite(r.detector_time_spread_ms)
    ], dtype=float)

    return IntervalQualityEvidence(
        evidence_count=count,
        dual_detector_ratio=float(dual),
        single_detector_ratio=float(single),
        detector_consensus_mean=(float(np.mean(consensus)) if consensus.size else 0.0),
        detector_time_spread_p95_ms=(float(np.percentile(spread, 95)) if spread.size else 0.0),
        sequence_rescue_ratio=float(sum(bool(r.sequence_rescued) for r in evidence) / count),
        local_clip_ratio=float(sum(bool(r.local_clipped) for r in evidence) / count),
        firmware_unmatched_ratio=float(sum(bool(r.firmware_unmatched) for r in evidence) / count),
    )
