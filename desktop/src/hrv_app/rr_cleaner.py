from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from collections.abc import Sequence
import numpy as np

from .config import AnalysisConfig
from .models import BeatFrame, BeatRecord, NNInterval, TimelineQuality


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

    def clean(self, beats: Sequence[BeatFrame]) -> CleanTimelineResult:
        cfg = self.config
        source = [b for b in beats if b.rr_ms > 0]

        if not source:
            return CleanTimelineResult([], [], TimelineQuality())

        records = [
            BeatRecord(
                seq=b.seq,
                t_us=b.t_us,
                rr_raw_ms=float(b.rr_ms),
                nn_ms=0.0,
                valid=False,
                corrected=False,
                reason="待判定",
                hr_bpm=float(b.hr_bpm),
                flags=b.flags,
                score=float(getattr(b, "score", 0.0)),
                rescued=bool(b.flags & 0x10),
                status="unresolved",
                metric_eligible=False,
            )
            for b in source
        ]

        nn_intervals: list[NNInterval] = []
        rhythm_history: deque[float] = deque(maxlen=cfg.rr_local_history)

        artifact_flags = [False] * len(source)
        corrected_flags = [False] * len(source)
        unresolved_flags = [False] * len(source)

        i = 0
        while i < len(source):
            beat = source[i]
            rr = float(beat.rr_ms)
            wear = bool(beat.flags & 0x01) if beat.flags else True

            expected, robust_scale = self._expected_rr(
                source,
                i,
                rhythm_history,
            )

            # 未佩戴或数值本身无效时不尝试插值。
            if not wear:
                self._reject(records[i], "no_wear", "未佩戴")
                artifact_flags[i] = True
                unresolved_flags[i] = True
                i += 1
                continue

            if not np.isfinite(rr) or rr <= 0:
                self._reject(records[i], "hard_outlier", "RR 无效")
                artifact_flags[i] = True
                unresolved_flags[i] = True
                i += 1
                continue

            # ----------------------------------------------------------------
            # 1) 伪峰拆分识别
            #
            # 例：局部节律约 820 ms，出现 639 + 311 ≈ 950 ms，
            # 且后一个 RR 又回到约 820 ms。中间 Peak 很可能是额外伪峰。
            # 此判定必须先于“RR<300”硬过滤，否则只会删掉其中一半。
            # ----------------------------------------------------------------
            if i + 1 < len(source):
                next_rr = float(source[i + 1].rr_ms)
                merged = rr + next_rr

                next_wear = (
                    bool(source[i + 1].flags & 0x01)
                    if source[i + 1].flags
                    else True
                )

                if (
                    next_wear
                    and rr > 0
                    and next_rr > 0
                    and self._is_false_peak_pair(
                        source,
                        i,
                        rr,
                        next_rr,
                        merged,
                        expected,
                    )
                ):
                    self._reject(
                        records[i],
                        "false_peak",
                        "伪峰：与下一 RR 合并",
                    )
                    artifact_flags[i] = True

                    merged_record = records[i + 1]
                    merged_record.nn_ms = merged
                    merged_record.valid = True
                    merged_record.corrected = True
                    merged_record.reason = "伪峰合并"
                    merged_record.status = "false_peak_merged"

                    # 修复值用于频域连续性；严格时域 RMSSD 不使用该值。
                    merged_record.metric_eligible = False
                    corrected_flags[i + 1] = True

                    nn_intervals.append(
                        NNInterval(
                            t_us=source[i + 1].t_us,
                            nn_ms=merged,
                            corrected=True,
                            metric_eligible=False,
                            source="false_peak_merge",
                        )
                    )
                    rhythm_history.append(merged)
                    i += 2
                    continue

            # ----------------------------------------------------------------
            # 2) 明显硬异常
            # ----------------------------------------------------------------
            if rr < cfg.rr_hard_min_ms:
                self._reject(records[i], "hard_outlier", "RR 过短")
                artifact_flags[i] = True
                unresolved_flags[i] = True
                i += 1
                continue

            if rr > cfg.rr_hard_max_ms:
                self._reject(records[i], "hard_outlier", "RR 过长")
                artifact_flags[i] = True
                unresolved_flags[i] = True
                i += 1
                continue

            # ----------------------------------------------------------------
            # 3) 漏搏识别
            #
            # 若 RR 接近局部节律的 2 倍或 3 倍，且下一搏恢复正常，
            # 在频域时间轴中补回缺失心搏。严格时域仍跳过这些修复区间。
            # ----------------------------------------------------------------
            multiple = int(round(rr / max(expected, 1.0)))
            if 2 <= multiple <= 3:
                per_interval = rr / multiple
                if self._is_missed_beat(
                    source,
                    i,
                    expected,
                    per_interval,
                ):
                    record = records[i]
                    record.nn_ms = per_interval
                    record.valid = True
                    record.corrected = True
                    record.metric_eligible = False
                    record.status = "missed_beat_repaired"
                    record.reason = f"疑似漏搏：拆分为 {multiple} 个 NN"
                    artifact_flags[i] = True
                    corrected_flags[i] = True

                    start_us = beat.t_us - int(round(rr * 1000.0))
                    step_us = rr * 1000.0 / multiple

                    for k in range(1, multiple + 1):
                        endpoint = int(round(start_us + k * step_us))
                        nn_intervals.append(
                            NNInterval(
                                t_us=endpoint,
                                nn_ms=per_interval,
                                corrected=True,
                                metric_eligible=False,
                                source="missed_beat_split",
                            )
                        )
                        rhythm_history.append(per_interval)

                    i += 1
                    continue

            # ----------------------------------------------------------------
            # 4) 局部难异常
            #
            # major deviation 用于捕获 311/328/359 ms 这类仍落在硬范围内的伪值；
            # MAD 条件负责捕获偏差较小但相对局部节律仍显著的异常。
            # ----------------------------------------------------------------
            if len(rhythm_history) >= cfg.rr_local_min_history:
                relative = abs(rr - expected) / max(expected, 1.0)
                robust_z = abs(rr - expected) / max(robust_scale, 1.0)

                if (
                    relative > cfg.rr_major_deviation_limit
                    or (
                        relative > cfg.rr_relative_deviation_limit
                        and robust_z > cfg.rr_mad_z_limit
                    )
                ):
                    self._reject(
                        records[i],
                        "local_outlier",
                        "局部 RR 异常",
                    )
                    artifact_flags[i] = True
                    unresolved_flags[i] = True
                    i += 1
                    continue

            # ----------------------------------------------------------------
            # 5) 原始正常 NN
            # ----------------------------------------------------------------
            record = records[i]
            record.nn_ms = rr
            record.valid = True
            record.corrected = False
            record.metric_eligible = True
            record.status = "accepted"
            record.reason = ""

            nn_intervals.append(
                NNInterval(
                    t_us=beat.t_us,
                    nn_ms=rr,
                    corrected=False,
                    metric_eligible=True,
                    source="raw",
                )
            )
            rhythm_history.append(rr)
            i += 1

        quality = self._build_quality(
            records,
            nn_intervals,
            artifact_flags,
            corrected_flags,
            unresolved_flags,
        )
        return CleanTimelineResult(records, nn_intervals, quality)

    def _expected_rr(
        self,
        source: Sequence[BeatFrame],
        index: int,
        history: deque[float],
    ) -> tuple[float, float]:
        cfg = self.config

        # 优先使用已确认的历史 NN，避免当前异常污染期望值。
        if len(history) >= cfg.rr_local_min_history:
            data = np.asarray(history, dtype=float)
        else:
            # 启动阶段从邻域中挑选 450–1200 ms 的候选做初始节律估计。
            # 这个范围只用于“建立初始中位数”，不直接决定最终 valid。
            left = max(0, index - 7)
            right = min(len(source), index + 8)
            data = np.asarray(
                [float(b.rr_ms) for b in source[left:right]],
                dtype=float,
            )
            data = data[(data >= 450.0) & (data <= 1200.0)]

            if data.size < 3 and history:
                data = np.asarray(history, dtype=float)

        if data.size == 0:
            return 800.0, cfg.rr_robust_scale_floor_ms

        median = float(np.median(data))
        mad = float(np.median(np.abs(data - median)))
        robust_scale = max(
            1.4826 * mad,
            cfg.rr_robust_scale_floor_ms,
        )
        return median, robust_scale

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

        corrected_intervals = sum(i.corrected for i in nn_intervals)
        interval_total = max(len(nn_intervals), 1)

        reasons: list[str] = []
        if detected / total > 0.05:
            reasons.append("异常搏比例偏高")
        if unresolved / total > 0.02:
            reasons.append("存在未解决 RR 异常")
        if max_run > 1:
            reasons.append("存在连续异常搏")

        return TimelineQuality(
            raw_rr_count=len(records),
            accepted_nn_count=accepted,
            detected_artifact_ratio=detected / total,
            corrected_interval_ratio=corrected_intervals / interval_total,
            unresolved_suspect_ratio=unresolved / total,
            valid_nn_ratio=accepted / total,
            max_consecutive_artifacts=max_run,
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
