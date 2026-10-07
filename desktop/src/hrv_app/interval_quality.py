from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any

import numpy as np

from .config import AnalysisConfig
from .models import BeatRecord


@dataclass(slots=True, frozen=True)
class BeatTimingEvidence:
    """Auditable components behind one formal beat timing-quality score.

    Firmware phase agreement is deliberately diagnostic only.  v0.4.1+ makes
    the dual waveform detector/sequence resolver authoritative for the formal
    beat timeline, so a missing or phase-shifted firmware beat must not by
    itself invalidate an otherwise well-supported waveform beat.
    """

    timing_quality: float = 1.0
    waveform_quality: float = 1.0
    detector_timing_quality: float = 1.0
    provenance_quality: float = 1.0
    firmware_alignment_available: bool = False
    firmware_alignment_quality: float = 0.0
    timing_quality_reason: str = "direct_dual_detector"
    firmware_alignment_reason: str = "firmware_unmatched"


def _piecewise_quality(
    value: float,
    good_limit: float,
    limited_limit: float,
    limited_quality: float,
    floor_quality: float,
    hard_limit: float,
) -> float:
    value = max(float(value), 0.0)
    good_limit = max(float(good_limit), 1e-9)
    limited_limit = max(float(limited_limit), good_limit + 1e-9)
    hard_limit = max(float(hard_limit), limited_limit + 1e-9)

    if value <= good_limit:
        return 1.0
    if value <= limited_limit:
        fraction = (value - good_limit) / (limited_limit - good_limit)
        return float(1.0 - fraction * (1.0 - limited_quality))

    fraction = min((value - limited_limit) / (hard_limit - limited_limit), 1.0)
    return float(limited_quality - fraction * (limited_quality - floor_quality))


def evaluate_beat_timing_quality(
    proposal: Any,
    timing_shift_ms: float,
    config: AnalysisConfig | None = None,
) -> BeatTimingEvidence:
    """Separate waveform shape, detector timing and provenance confidence.

    The old implementation copied ``waveform_score`` straight into
    ``timing_quality``.  That made a visually strong peak look perfectly timed
    even when it was a single-detector or sequence-rescued decision.  This
    score keeps those concepts separate while leaving firmware agreement as a
    diagnostic channel only.
    """

    cfg = config or AnalysisConfig()
    waveform_quality = float(np.clip(
        float(getattr(proposal, "waveform_score", 0.0) or 0.0),
        0.0,
        1.0,
    ))
    uncertainty_ms = float(getattr(proposal, "timing_uncertainty_ms", 0.0) or 0.0)
    if not np.isfinite(uncertainty_ms):
        uncertainty_ms = float(cfg.interval_max_timing_uncertainty_ms)

    detector_timing_quality = _piecewise_quality(
        uncertainty_ms,
        cfg.fiducial_strict_max_uncertainty_p95_ms,
        cfg.fiducial_limited_max_uncertainty_p95_ms,
        limited_quality=0.75,
        floor_quality=0.55,
        hard_limit=cfg.interval_max_timing_uncertainty_ms,
    )

    provenance_quality = 1.0
    reasons: list[str] = []
    if bool(getattr(proposal, "single_detector", False)):
        provenance_quality *= 0.88
        reasons.append("single_detector")
    if bool(getattr(proposal, "sequence_rescued", False)):
        provenance_quality *= 0.78
        reasons.append("sequence_rescued")
    if bool(getattr(proposal, "low_prominence_rescue", False)):
        provenance_quality *= 0.90
        reasons.append("low_prominence_rescue")
    if bool(getattr(proposal, "local_clipped", False)):
        provenance_quality *= 0.70
        reasons.append("local_clip_near_fiducial")
    if uncertainty_ms > cfg.fiducial_strict_max_uncertainty_p95_ms:
        reasons.append(f"timing_uncertainty_{uncertainty_ms:.1f}ms")

    timing_quality = float(np.clip(
        waveform_quality * detector_timing_quality * provenance_quality,
        0.0,
        1.0,
    ))

    matched_firmware_t_us = int(
        getattr(proposal, "matched_firmware_t_us", 0) or 0
    )
    firmware_available = matched_firmware_t_us > 0
    if firmware_available:
        absolute_shift_ms = abs(float(timing_shift_ms))
        firmware_alignment_quality = _piecewise_quality(
            absolute_shift_ms,
            cfg.interval_consensus_tolerance_ms,
            min(200.0, cfg.waveform_firmware_match_max_ms * 0.5),
            limited_quality=0.70,
            floor_quality=0.20,
            hard_limit=cfg.waveform_firmware_match_max_ms,
        )
        if absolute_shift_ms <= cfg.interval_consensus_tolerance_ms:
            firmware_reason = "firmware_phase_close"
        elif absolute_shift_ms <= min(200.0, cfg.waveform_firmware_match_max_ms * 0.5):
            firmware_reason = "firmware_phase_offset"
        else:
            firmware_reason = "firmware_phase_large_offset"
    else:
        firmware_alignment_quality = 0.0
        firmware_reason = "firmware_unmatched"

    return BeatTimingEvidence(
        timing_quality=timing_quality,
        waveform_quality=waveform_quality,
        detector_timing_quality=float(detector_timing_quality),
        provenance_quality=float(provenance_quality),
        firmware_alignment_available=bool(firmware_available),
        firmware_alignment_quality=float(firmware_alignment_quality),
        timing_quality_reason="+".join(reasons) if reasons else "direct_dual_detector",
        firmware_alignment_reason=firmware_reason,
    )


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
