from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from collections.abc import Sequence
import numpy as np

from .config import AnalysisConfig
from .models import BeatFrame, BeatRecord, NNInterval, TimelineQuality
from .interval_artifacts import IntervalArtifactClassifier, IntervalArtifactDecision


@dataclass(slots=True)
class CleanedRR:
    rr_raw_ms: float
    nn_ms: float
    valid: bool
    corrected: bool
    reason: str


@dataclass(slots=True)
class CleanTimelineResult:
    records: list[BeatRecord]
    nn_intervals: list[NNInterval]
    quality: TimelineQuality
    artifact_decisions: list[IntervalArtifactDecision] = field(default_factory=list)


class BeatTimelineCleaner:
    """
    心搏事件级 RR → NN 清洗。

    V0.2 的单点清洗无法处理两类最常见的结构性错误：
    1. 额外伪峰：一个真实 RR 被切成两个较短 RR；
    2. 漏峰：一个长 RR 实际包含两个或三个心搏周期。

    本实现保留所有原始 BeatFrame，用可回溯、可前瞻的批量算法重新构建 NN 时间轴。
    无法可靠修复的异常直接跳过，不再用局部中位数“伪造一个看似正常的 NN”。
    """

    def __init__(self, config: AnalysisConfig | None = None):
        self.config = config or AnalysisConfig()
        self._artifact_classifier = IntervalArtifactClassifier(self.config)

    def clean(self, beats: Sequence[BeatFrame]) -> CleanTimelineResult:
        """Build an auditable raw-beat -> artifact -> NN timeline.

        v0.4.2 moves the structural decision into ``IntervalArtifactClassifier``.
        Detector consensus remains waveform evidence only; every RR is reviewed in
        sequence context before it is allowed into the NN timeline.
        """
        source = [beat for beat in beats if float(beat.rr_ms) > 0]
        if not source:
            return CleanTimelineResult([], [], TimelineQuality(), [])

        decisions = self._artifact_classifier.classify(source)
        decision_by_index = {decision.index: decision for decision in decisions}

        records: list[BeatRecord] = []
        for index, beat in enumerate(source):
            decision = decision_by_index[index]
            records.append(
                BeatRecord(
                    seq=beat.seq,
                    t_us=beat.t_us,
                    rr_raw_ms=float(beat.rr_ms),
                    nn_ms=0.0,
                    valid=False,
                    corrected=False,
                    reason=decision.reason or "待判定",
                    hr_bpm=float(beat.hr_bpm),
                    flags=beat.flags,
                    score=float(getattr(beat, "score", 0.0)),
                    rescued=bool(beat.flags & 0x10),
                    source_t_us=int(getattr(beat, "source_t_us", 0)),
                    timing_shift_ms=float(getattr(beat, "timing_shift_ms", 0.0)),
                    timing_quality=float(getattr(beat, "timing_quality", 1.0)),
                    timing_uncertainty_ms=float(getattr(beat, "timing_uncertainty_ms", 0.0)),
                    timing_recovered=bool(getattr(beat, "timing_recovered", False)),
                    refined=bool(getattr(beat, "refined", False)),
                    correction_method=str(getattr(beat, "correction_method", "")),
                    waveform_score=float(getattr(beat, "waveform_score", 0.0)),
                    reference_rr_ms=float(getattr(beat, "reference_rr_ms", 0.0)),
                    matched_firmware_t_us=int(getattr(beat, "matched_firmware_t_us", 0)),
                    inserted_by_smoother=bool(getattr(beat, "inserted_by_smoother", False)),
                    low_prominence_rescue=bool(getattr(beat, "low_prominence_rescue", False)),
                    detector_support_count=int(getattr(beat, "detector_support_count", 0) or 0),
                    detector_names=str(getattr(beat, "detector_names", "") or ""),
                    detector_consensus=float(getattr(beat, "detector_consensus", 0.0) or 0.0),
                    detector_time_spread_ms=float(getattr(beat, "detector_time_spread_ms", 0.0) or 0.0),
                    single_detector=bool(getattr(beat, "single_detector", False)),
                    sequence_rescued=bool(getattr(beat, "sequence_rescued", False)),
                    firmware_unmatched=bool(getattr(beat, "firmware_unmatched", False)),
                    local_clipped=bool(getattr(beat, "local_clipped", False)),
                    artifact_class=decision.artifact_class,
                    artifact_confidence=float(decision.confidence),
                    artifact_reference_rr_ms=float(decision.reference_rr_ms),
                    artifact_evidence=decision.evidence,
                    status=decision.status,
                    metric_eligible=False,
                )
            )

        nn_intervals: list[NNInterval] = []
        artifact_flags = [False] * len(source)
        corrected_flags = [False] * len(source)
        unresolved_flags = [False] * len(source)

        for decision in decisions:
            index = decision.index
            record = records[index]
            status = decision.status

            if status == "accepted":
                record.nn_ms = float(decision.corrected_rr_ms)
                record.valid = True
                record.corrected = False
                record.metric_eligible = True
                record.reason = ""
                nn_intervals.append(
                    NNInterval(
                        t_us=record.t_us,
                        nn_ms=record.nn_ms,
                        corrected=False,
                        metric_eligible=True,
                        source="raw",
                    )
                )
                continue

            artifact_flags[index] = True

            if status == "false_peak":
                self._reject(record, status, decision.reason)
                # Resolved as a pair: this record is the extra beat itself, so it
                # emits no NN interval.
                continue

            if status == "false_peak_merged":
                record.nn_ms = float(decision.corrected_rr_ms)
                record.valid = True
                record.corrected = True
                record.metric_eligible = False
                record.reason = decision.reason
                corrected_flags[index] = True
                nn_intervals.append(
                    NNInterval(
                        t_us=record.t_us,
                        nn_ms=record.nn_ms,
                        corrected=True,
                        metric_eligible=False,
                        source="false_peak_merge",
                    )
                )
                continue

            if status == "missed_beat_repaired":
                record.nn_ms = float(decision.corrected_rr_ms)
                record.valid = True
                record.corrected = True
                record.metric_eligible = False
                corrected_flags[index] = True

                multiple = max(int(decision.split_count), 2)
                start_us = record.t_us - int(round(record.rr_raw_ms * 1000.0))
                step_us = record.rr_raw_ms * 1000.0 / multiple
                for part in range(1, multiple + 1):
                    nn_intervals.append(
                        NNInterval(
                            t_us=int(round(start_us + part * step_us)),
                            nn_ms=float(decision.corrected_rr_ms),
                            corrected=True,
                            metric_eligible=False,
                            source="missed_beat_split",
                        )
                    )
                continue

            if status == "long_short_repaired":
                record.nn_ms = float(decision.corrected_rr_ms)
                record.valid = True
                record.corrected = True
                record.metric_eligible = False
                corrected_flags[index] = True
                nn_intervals.append(
                    NNInterval(
                        t_us=record.t_us,
                        nn_ms=record.nn_ms,
                        corrected=True,
                        metric_eligible=False,
                        source="long_short_pair",
                    )
                )
                continue

            self._reject(record, status, decision.reason)
            unresolved_flags[index] = True

        quality = self._build_quality(
            records,
            nn_intervals,
            artifact_flags,
            corrected_flags,
            unresolved_flags,
        )
        return CleanTimelineResult(records, nn_intervals, quality, decisions)

    def _expected_rr(
        self,
        source: Sequence[BeatFrame],
        index: int,
        history: deque[float],
    ) -> tuple[float, float]:
        """
        v0.3.7：未来感知局部节律。

        v0.3.6 的 expected RR 一旦 `history` 足够长，就完全依赖单向历史。
        一个被拒绝的 RR 会停止 history 更新，随后可能形成“越拒绝越不能恢复”
        的长串 local_outlier。

        现在正式 Beat 本身已经延迟约 7.25 s 提交，清洗器天然拥有后续 RR。
        因此这里始终参考对称邻域：
        - 单个异常不会改变邻域中位数；
        - 持续的真实心率变化可以由未来正常搏确认；
        - false-peak / missed-beat 的结构判定仍由后面的专门规则完成。
        """
        cfg = self.config

        left = max(
            0,
            index - 8,
        )
        right = min(
            len(source),
            index + 9,
        )

        local = np.asarray(
            [
                float(
                    beat.rr_ms
                )
                for beat in source[
                    left:right
                ]
            ],
            dtype=float,
        )

        # 这里只建立局部节律中心。
        # 过短 / 过长值留给结构性伪峰与漏搏规则处理。
        local = local[
            np.isfinite(local)
            & (
                local
                >= max(
                    400.0,
                    cfg.rr_hard_min_ms,
                )
            )
            & (
                local
                <= min(
                    1400.0,
                    cfg.rr_hard_max_ms,
                )
            )
        ]

        historical = (
            np.asarray(
                history,
                dtype=float,
            )
            if history
            else np.asarray(
                [],
                dtype=float,
            )
        )

        if (
            local.size >= 5
            and historical.size
            >= cfg.rr_local_min_history
        ):
            local_median = float(
                np.median(
                    local
                )
            )
            history_median = float(
                np.median(
                    historical
                )
            )

            relative_shift = abs(
                local_median
                - history_median
            ) / max(
                history_median,
                1.0,
            )

            local_mad = float(
                np.median(
                    np.abs(
                        local
                        - local_median
                    )
                )
            )

            local_coherent = (
                local_mad
                / max(
                    local_median,
                    1.0,
                )
                <= 0.12
            )

            if (
                relative_shift > 0.10
                and local_coherent
            ):
                # 未来若确认新的稳定节律，允许 expected 跟随真实变化。
                data = local
            else:
                # 正常情况下融合过去和未来，提高单搏抗扰动能力。
                data = np.concatenate(
                    [
                        historical,
                        local,
                    ]
                )

        elif local.size >= 3:
            data = local

        elif historical.size:
            data = historical

        else:
            data = np.asarray(
                [800.0],
                dtype=float,
            )

        median = float(
            np.median(
                data
            )
        )
        mad = float(
            np.median(
                np.abs(
                    data
                    - median
                )
            )
        )

        robust_scale = max(
            1.4826
            * mad,
            cfg.rr_robust_scale_floor_ms,
        )

        return (
            median,
            robust_scale,
        )

    def _is_false_peak_pair(
        self,
        source: Sequence[BeatFrame],
        index: int,
        rr: float,
        next_rr: float,
        merged: float,
        expected: float,
    ) -> bool:
        cfg = self.config

        merged_close = (
            abs(merged - expected) / max(expected, 1.0)
            <= cfg.false_peak_merge_tolerance
        )
        components_short = (
            rr < expected * cfg.false_peak_component_max_ratio
            and next_rr < expected * cfg.false_peak_component_max_ratio
        )

        # 前瞻一搏必须恢复到局部节律附近。
        # 这样可以避免把真实“心率突然翻倍并持续”误合并成伪峰。
        if index + 2 < len(source):
            lookahead = float(source[index + 2].rr_ms)
            lookahead_ok = (
                abs(lookahead - expected) / max(expected, 1.0)
                <= cfg.false_peak_lookahead_tolerance
            )
        else:
            lookahead_ok = True

        return merged_close and components_short and lookahead_ok

    def _is_missed_beat(
        self,
        source: Sequence[BeatFrame],
        index: int,
        expected: float,
        per_interval: float,
    ) -> bool:
        cfg = self.config

        split_close = (
            abs(per_interval - expected) / max(expected, 1.0)
            <= cfg.missed_beat_split_tolerance
        )

        if index + 1 < len(source):
            next_rr = float(source[index + 1].rr_ms)
            lookahead_ok = (
                abs(next_rr - expected) / max(expected, 1.0)
                <= cfg.missed_beat_lookahead_tolerance
            )
        else:
            lookahead_ok = True

        return split_close and lookahead_ok

    @staticmethod
    def _reject(record: BeatRecord, status: str, reason: str) -> None:
        record.nn_ms = 0.0
        record.valid = False
        record.corrected = False
        record.metric_eligible = False
        record.status = status
        record.reason = reason

    @staticmethod
    def _build_quality(
        records: Sequence[BeatRecord],
        nn_intervals: Sequence[NNInterval],
        artifact_flags: Sequence[bool],
        corrected_flags: Sequence[bool],
        unresolved_flags: Sequence[bool],
    ) -> TimelineQuality:
        total = max(len(records), 1)
        detected = sum(bool(x) for x in artifact_flags)
        corrected_records = sum(bool(x) for x in corrected_flags)
        unresolved = sum(bool(x) for x in unresolved_flags)
        accepted = sum(r.status == "accepted" for r in records)

        max_run = 0
        current_run = 0
        for flag in artifact_flags:
            if flag:
                current_run += 1
                max_run = max(max_run, current_run)
            else:
                current_run = 0

        max_unresolved_run = 0
        current_unresolved_run = 0
        for flag in unresolved_flags:
            if flag:
                current_unresolved_run += 1
                max_unresolved_run = max(max_unresolved_run, current_unresolved_run)
            else:
                current_unresolved_run = 0

        corrected_intervals = sum(i.corrected for i in nn_intervals)
        interval_total = max(len(nn_intervals), 1)

        timing_quality = np.asarray(
            [
                float(record.timing_quality)
                for record in records
                if (record.source_t_us > 0 or record.refined)
                and np.isfinite(record.timing_quality)
            ],
            dtype=float,
        )
        timing_uncertainty = np.asarray(
            [
                float(record.timing_uncertainty_ms)
                for record in records
                if (record.source_t_us > 0 or record.refined)
                and np.isfinite(record.timing_uncertainty_ms)
            ],
            dtype=float,
        )
        timing_shift = np.asarray(
            [
                abs(float(record.timing_shift_ms))
                for record in records
                if (record.source_t_us > 0 or record.refined)
                and np.isfinite(record.timing_shift_ms)
            ],
            dtype=float,
        )

        fiducial_quality_mean = (
            float(np.mean(timing_quality))
            if timing_quality.size
            else 1.0
        )
        fiducial_uncertainty_p95_ms = (
            float(np.percentile(timing_uncertainty, 95))
            if timing_uncertainty.size
            else 0.0
        )
        fiducial_shift_p95_ms = (
            float(np.percentile(timing_shift, 95))
            if timing_shift.size
            else 0.0
        )
        fiducial_unstable_ratio = (
            float(
                np.mean(
                    timing_quality
                    < 0.62
                )
            )
            if timing_quality.size
            else 0.0
        )

        interval_evidence = [
            record for record in records
            if int(getattr(record, "detector_support_count", 0) or 0) > 0
        ]
        if interval_evidence:
            evidence_count = max(len(interval_evidence), 1)
            dual_detector_ratio = sum(
                int(record.detector_support_count) >= 2 for record in interval_evidence
            ) / evidence_count
            single_detector_ratio = sum(
                bool(record.single_detector) or int(record.detector_support_count) == 1
                for record in interval_evidence
            ) / evidence_count
            consensus_values = np.asarray([
                float(record.detector_consensus)
                for record in interval_evidence
                if np.isfinite(record.detector_consensus)
            ], dtype=float)
            spread_values = np.asarray([
                float(record.detector_time_spread_ms)
                for record in interval_evidence
                if int(record.detector_support_count) >= 2
                and np.isfinite(record.detector_time_spread_ms)
            ], dtype=float)
            detector_consensus_mean = (
                float(np.mean(consensus_values)) if consensus_values.size else 0.0
            )
            detector_time_spread_p95_ms = (
                float(np.percentile(spread_values, 95)) if spread_values.size else 0.0
            )
            sequence_rescue_ratio = sum(
                bool(record.sequence_rescued) for record in interval_evidence
            ) / evidence_count
            local_clip_ratio = sum(
                bool(record.local_clipped) for record in interval_evidence
            ) / evidence_count
            firmware_unmatched_ratio = sum(
                bool(record.firmware_unmatched) for record in interval_evidence
            ) / evidence_count
        else:
            # Historical/unit-test BeatFrames have no interval-core evidence.
            # Preserve backward compatibility instead of treating "not recorded" as bad quality.
            dual_detector_ratio = 1.0
            single_detector_ratio = 0.0
            detector_consensus_mean = 1.0
            detector_time_spread_p95_ms = 0.0
            sequence_rescue_ratio = 0.0
            local_clip_ratio = 0.0
            firmware_unmatched_ratio = 0.0

        reasons: list[str] = []
        if detected / total > 0.05:
            reasons.append("异常搏比例偏高")
        if unresolved / total > 0.02:
            reasons.append("存在未解决 RR 异常")
        if max_unresolved_run > 1:
            reasons.append("存在连续未解决 RR 异常")
        if fiducial_unstable_ratio > 0.05:
            reasons.append("心搏时间标志点稳定性偏低")

        return TimelineQuality(
            raw_rr_count=len(records),
            accepted_nn_count=accepted,
            detected_artifact_ratio=detected / total,
            corrected_interval_ratio=corrected_intervals / interval_total,
            unresolved_suspect_ratio=unresolved / total,
            valid_nn_ratio=accepted / total,
            max_consecutive_artifacts=max_run,
            max_consecutive_unresolved=max_unresolved_run,
            resolved_artifact_ratio=max((detected - unresolved) / total, 0.0),
            fiducial_quality_mean=fiducial_quality_mean,
            fiducial_uncertainty_p95_ms=fiducial_uncertainty_p95_ms,
            fiducial_shift_p95_ms=fiducial_shift_p95_ms,
            fiducial_unstable_ratio=fiducial_unstable_ratio,
            dual_detector_ratio=float(dual_detector_ratio),
            single_detector_ratio=float(single_detector_ratio),
            detector_consensus_mean=float(detector_consensus_mean),
            detector_time_spread_p95_ms=float(detector_time_spread_p95_ms),
            sequence_rescue_ratio=float(sequence_rescue_ratio),
            local_clip_ratio=float(local_clip_ratio),
            firmware_unmatched_ratio=float(firmware_unmatched_ratio),
            reasons=reasons,
        )


class RRCleaner:
    """
    V0.2 单点 API 的兼容层。

    新 AnalysisEngine 已不再使用它；保留仅用于旧调用方和回归测试。
    单点接口无法实现伪峰合并与漏搏回溯，新增代码应使用 BeatTimelineCleaner。
    """

    def __init__(self, config: AnalysisConfig | None = None):
        self.config = config or AnalysisConfig()
        self._valid_history: deque[float] = deque(
            maxlen=self.config.rr_local_history
        )

    def reset(self) -> None:
        self._valid_history.clear()

    def clean(self, rr_ms: float, wear: bool = True) -> CleanedRR:
        cfg = self.config
        rr_ms = float(rr_ms)

        if not wear:
            return CleanedRR(rr_ms, 0.0, False, False, "未佩戴")
        if not np.isfinite(rr_ms) or rr_ms <= 0:
            return CleanedRR(rr_ms, 0.0, False, False, "RR 无效")
        if rr_ms < cfg.rr_hard_min_ms:
            return self._fallback(rr_ms, "RR 过短")
        if rr_ms > cfg.rr_hard_max_ms:
            return self._fallback(rr_ms, "RR 过长")

        if len(self._valid_history) >= cfg.rr_local_min_history:
            history = np.asarray(self._valid_history, dtype=float)
            median = float(np.median(history))
            mad = float(np.median(np.abs(history - median)))
            scale = max(
                1.4826 * mad,
                cfg.rr_robust_scale_floor_ms,
            )
            relative = abs(rr_ms - median) / max(median, 1.0)
            robust_z = abs(rr_ms - median) / scale

            if (
                relative > cfg.rr_major_deviation_limit
                or (
                    relative > cfg.rr_relative_deviation_limit
                    and robust_z > cfg.rr_mad_z_limit
                )
            ):
                return self._fallback(rr_ms, "局部 RR 异常")

        self._valid_history.append(rr_ms)
        return CleanedRR(rr_ms, rr_ms, True, False, "")

    def _fallback(self, rr_ms: float, reason: str) -> CleanedRR:
        # 兼容接口仍返回局部中位数；正式 HRV 链不再使用该替代值。
        if self._valid_history:
            replacement = float(np.median(np.asarray(self._valid_history)))
            return CleanedRR(rr_ms, replacement, False, True, reason)
        return CleanedRR(rr_ms, 0.0, False, False, reason)
