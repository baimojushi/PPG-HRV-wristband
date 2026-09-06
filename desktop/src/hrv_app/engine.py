from __future__ import annotations

from collections import deque
import copy
import threading

import numpy as np

from .config import AnalysisConfig
from .confidence import compute_quality_assessment
from .frequency_stats import compute_frequency_statistics
from .fixed_lag_corrector import FixedLagWaveformCorrector
from .hrv_frequency import compute_frequency_domain
from .hrv_time import compute_time_domain
from .models import (
    AnalysisSnapshot,
    BeatFrame,
    BeatRecord,
    DiagnosticFrame,
    FirmwareMetricFrame,
    NNInterval,
    ProtocolHealth,
    SampleFrame,
    TimelineQuality,
    UserAnnotation,
)
from .rr_cleaner import BeatTimelineCleaner
from .signal_quality import evaluate_signal_quality
from .spwvd import compute_spwvd


class AnalysisEngine:
    """
    线程安全分析引擎。

    v0.3.7 关键变化：
    - `_firmware_beats` 保存固件实时 Accepted，只作为诊断证据；
    - `_raw_beats` 改为 7.25 s 固定滞后整窗 PPG 复核后的正式心搏；
    - 正式心搏可以在固件漏检时直接由波形补回；
    - 固件多检 / 次级峰不会自动进入正式 HRV 时间线；
    - BeatTimelineCleaner 再对正式时间线做未来感知的 NN 质量审计；
    - 导出通过 export_bundle() 冻结同一个 snapshot，避免 CSV/JSON 不同步。
    """

    def __init__(
        self,
        config: AnalysisConfig | None = None,
    ):
        self.config = config or AnalysisConfig()
        self._lock = threading.RLock()
        self._timeline_cleaner = BeatTimelineCleaner(
            self.config
        )

        # 桌面端保留至少 5 分钟 Sample，频域质量门需要审计整个频域窗口，
        # 不能只看最后 30 秒的 PPG 是否突然变好。
        sample_capacity = int(
            self.config.sample_rate_hz
            * max(
                self.config.frequency_window_seconds + 10.0,
                60.0,
            )
        )

        self._samples: deque[SampleFrame] = deque(
            maxlen=sample_capacity
        )

        # v0.3.6 软件人工标注。
        # 数量远小于 Sample，不跟随 5 分钟 Sample ring 自动淘汰。
        self._annotations: deque[UserAnnotation] = deque(
            maxlen=2000
        )

        # 固件 Beat 原样保存，便于确认“存在性判断”是否正确。
        self._firmware_beats: deque[BeatFrame] = deque(
            maxlen=5000
        )

        # `_raw_beats` 从 v0.3.7 起表示：
        # 固定滞后整窗波形复核后的正式 HRV 心搏时间线。
        self._raw_beats: deque[BeatFrame] = deque(
            maxlen=5000
        )

        self._waveform_corrector = (
            FixedLagWaveformCorrector(
                self.config
            )
        )

        # 正式时间线自己的 RR 历史。
        # 它只来自已经提交的 PPG 主波，不再由固件 Winner 直接驱动。
        self._refined_rr_history: deque[float] = deque(
            maxlen=15
        )
        self._last_refined_t_us = 0
        self._last_correction_run_t_us = 0

        self._cleaned_records: list[BeatRecord] = []
        self._nn_intervals: list[NNInterval] = []
        self._timeline_quality = TimelineQuality()

        self._metric_history: deque[dict] = deque(
            maxlen=5000
        )

        self._last_snapshot = AnalysisSnapshot()
        self._last_metric_us: int | None = None

        # `_latest_hr_bpm` 只表示 Accepted Beat 计算出的主心率。
        # `_latest_sample_hr_bpm` 单独保留 SampleFrame 当前 Accepted HR，供 Debug 对照。
        self._latest_hr_bpm = 0.0
        self._latest_sample_hr_bpm = 0.0

        self._last_diagnostic: DiagnosticFrame | None = None
        self._last_firmware_metric: FirmwareMetricFrame | None = None
        self._protocol_health = ProtocolHealth()

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()
            self._annotations.clear()
            self._firmware_beats.clear()
            self._raw_beats.clear()
            self._waveform_corrector.reset()
            self._refined_rr_history.clear()
            self._last_refined_t_us = 0
            self._last_correction_run_t_us = 0
            self._cleaned_records.clear()
            self._nn_intervals.clear()
            self._metric_history.clear()

            self._timeline_quality = TimelineQuality()
            self._last_snapshot = AnalysisSnapshot()
            self._last_metric_us = None

            self._latest_hr_bpm = 0.0
            self._latest_sample_hr_bpm = 0.0
            self._last_diagnostic = None
            self._last_firmware_metric = None
            self._protocol_health = ProtocolHealth()

    def ingest_sample(
        self,
        frame: SampleFrame,
    ) -> None:
        with self._lock:
            self._samples.append(frame)

            # SampleFrame.hr_bpm 是 zeezPPG 基于 Accepted RR 中位数得到的实时 HR。
            # v0.3.4 保留同极性锁、增量自相关，并加入独立相位跟踪；这里仍保留采样帧 HR 作为实时 Debug 对照。
            if (
                np.isfinite(frame.hr_bpm)
                and frame.hr_bpm > 0
            ):
                self._latest_sample_hr_bpm = float(
                    frame.hr_bpm
                )

            self._run_fixed_lag_correction_locked(
                force=False
            )

    def add_user_annotation(
        self,
        device_t_us: int,
        host_monotonic_ns: int,
        label_type: str = "未分类",
        note: str = "",
    ) -> UserAnnotation | None:
        """
        在当前 UI 显示的数据时间轴上创建人工异常标注。

        `device_t_us` 由 UI 最近一次绘图时冻结，因此它对应用户真正看到的
        屏幕右缘，而不是按键之后后台线程刚收到的“更新 Sample”。

        标注只记录证据：
        - 不改变 Winner；
        - 不改变 RR；
        - 不改变 SQI / HRV；
        - 不回馈任何在线检测状态。
        """
        with self._lock:
            if not self._samples:
                return None

            latest_sample = self._samples[-1]

            # UI 显示时间必须落在当前内存中的设备数据范围。
            # 极端情况下 UI 卡顿超过 Sample ring 长度时，拒绝伪造标注。
            minimum_t_us = int(
                self._samples[0].t_us
            )
            maximum_t_us = int(
                latest_sample.t_us
            )
            mark_t_us = int(
                device_t_us
            )

            if not (
                minimum_t_us
                <= mark_t_us
                <= maximum_t_us
            ):
                return None

            # 找到最接近屏幕右缘的真实 Sample，用它记录 seq。
            sample_times = np.asarray(
                [
                    sample.t_us
                    for sample in self._samples
                ],
                dtype=np.int64,
            )

            index = int(
                np.searchsorted(
                    sample_times,
                    mark_t_us,
                )
            )
            index = min(
                max(index, 0),
                len(
                    sample_times
                ) - 1,
            )

            if (
                index > 0
                and abs(
                    int(
                        sample_times[
                            index - 1
                        ]
                    )
                    - mark_t_us
                )
                < abs(
                    int(
                        sample_times[index]
                    )
                    - mark_t_us
                )
            ):
                index -= 1

            anchor_sample = self._samples[
                index
            ]

            # 点击时冻结最近 12 秒状态，和 UI Debug 行使用相同观察尺度。
            debug_start_us = (
                mark_t_us
                - 12_000_000
            )

            recent_samples = [
                sample
                for sample in self._samples
                if (
                    debug_start_us
                    <= sample.t_us
                    <= mark_t_us
                )
            ]

            recent_firmware = [
                beat
                for beat in self._firmware_beats
                if (
                    debug_start_us
                    <= beat.t_us
                    <= mark_t_us
                )
            ]

            recent_refined = [
                beat
                for beat in self._raw_beats
                if (
                    debug_start_us
                    <= beat.t_us
                    <= mark_t_us
                )
            ]

            expected_rr_values = np.asarray(
                [
                    sample.expected_rr_ms
                    for sample in recent_samples
                    if (
                        np.isfinite(
                            sample.expected_rr_ms
                        )
                        and sample.expected_rr_ms > 0
                    )
                ],
                dtype=float,
            )

            waveform_reference_rr_ms = float(
                self._waveform_corrector.last_diagnostics.reference_rr_ms
            )

            expected_rr_ms = (
                waveform_reference_rr_ms
                if waveform_reference_rr_ms > 0
                else (
                    float(
                        np.median(
                            expected_rr_values
                        )
                    )
                    if expected_rr_values.size
                    else 0.0
                )
            )

            last_firmware = (
                recent_firmware[-1]
                if recent_firmware
                else None
            )
            last_refined = (
                recent_refined[-1]
                if recent_refined
                else None
            )

            signal_quality = (
                evaluate_signal_quality(
                    recent_samples,
                    self._protocol_health,
                    self.config,
                )
                if recent_samples
                else self._last_snapshot.signal_quality
            )

            next_id = (
                self._annotations[-1].annotation_id
                + 1
                if self._annotations
                else 1
            )

            lookback_us = int(
                round(
                    self.config.user_annotation_lookback_seconds
                    * 1e6
                )
            )

            annotation = UserAnnotation(
                annotation_id=next_id,
                device_t_us=mark_t_us,
                latest_sample_t_us=int(
                    latest_sample.t_us
                ),
                latest_sample_seq=int(
                    latest_sample.seq
                ),
                label_start_us=(
                    mark_t_us
                    - lookback_us
                ),
                label_end_us=mark_t_us,
                host_monotonic_ns=int(
                    host_monotonic_ns
                ),
                label_type=(
                    str(label_type).strip()
                    or "未分类"
                ),
                note=str(
                    note
                ).strip(),
                ui_data_lag_ms=float(
                    (
                        latest_sample.t_us
                        - mark_t_us
                    )
                    / 1000.0
                ),
                hr_bpm=float(
                    last_refined.hr_bpm
                    if last_refined is not None
                    else 0.0
                ),
                expected_rr_ms=(
                    expected_rr_ms
                ),
                winner_score=float(
                    last_firmware.score
                    if last_firmware is not None
                    else 0.0
                ),
                timing_quality=float(
                    last_refined.timing_quality
                    if last_refined is not None
                    else 0.0
                ),
                timing_uncertainty_ms=float(
                    last_refined.timing_uncertainty_ms
                    if last_refined is not None
                    else 0.0
                ),
                fiducial_shift_ms=float(
                    last_refined.timing_shift_ms
                    if last_refined is not None
                    else 0.0
                ),
                candidate_count_12s=int(
                    sum(
                        bool(
                            sample.peak
                        )
                        for sample in recent_samples
                    )
                ),
                rescue_count_12s=int(
                    sum(
                        bool(
                            beat.flags
                            & 0x10
                        )
                        for beat in recent_refined
                    )
                ),
                phase_recovery_count_12s=int(
                    sum(
                        bool(
                            beat.timing_recovered
                        )
                        for beat in recent_refined
                    )
                ),
                sqi=float(
                    signal_quality.sqi
                ),
                effective_sample_rate_hz=float(
                    signal_quality.effective_sample_rate_hz
                ),
                timing_jitter_p95_ms=float(
                    signal_quality.timing_jitter_p95_ms
                ),
            )

            self._annotations.append(
                annotation
            )

            return copy.deepcopy(
                annotation
            )

    def annotations(
        self,
    ) -> list[UserAnnotation]:
        with self._lock:
            return copy.deepcopy(
                list(
                    self._annotations
                )
            )

    def recent_annotations(
        self,
        seconds: float = 12.0,
        end_t_us: int | None = None,
    ) -> list[UserAnnotation]:
        with self._lock:
            if not self._annotations:
                return []

            if end_t_us is None:
                if not self._samples:
                    return []
                end_t_us = int(
                    self._samples[-1].t_us
                )

            start_t_us = int(
                end_t_us
                - seconds
                * 1e6
            )

            return copy.deepcopy(
                [
                    annotation
                    for annotation
                    in self._annotations
                    if (
                        start_t_us
                        <= annotation.device_t_us
                        <= end_t_us
                    )
                ]
            )

    def ingest_beat(
        self,
        frame: BeatFrame,
    ) -> None:
        """
        保存固件实时 Accepted Beat。

        v0.3.7 中它不再直接进入 HRV 时间线。
        固件 Beat 的作用：
        - 对照 zeezPPG 是否漏检 / 多检 / 错相位；
        - 给导出和未来模型训练提供证据；
        - 与整窗波形解析出的正式主波做匹配审计。

        正式 HR / RR / HRV 只由固定滞后波形复核器提交。
        """
        with self._lock:
            firmware_frame = copy.deepcopy(
                frame
            )
            firmware_frame.source_t_us = int(
                frame.t_us
            )

            self._firmware_beats.append(
                firmware_frame
            )

    def _sample_flags_near_locked(
        self,
        t_us: int,
    ) -> int:
        if not self._samples:
            return 0

        sample_times = np.asarray(
            [
                sample.t_us
                for sample in self._samples
            ],
            dtype=np.int64,
        )

        index = int(
            np.searchsorted(
                sample_times,
                int(
                    t_us
                ),
            )
        )
        index = min(
            max(
                index,
                0,
            ),
            len(
                sample_times
            ) - 1,
        )

        if (
            index > 0
            and abs(
                int(
                    sample_times[
                        index - 1
                    ]
                )
                - int(
                    t_us
                )
            )
            < abs(
                int(
                    sample_times[
                        index
                    ]
                )
                - int(
                    t_us
                )
            )
        ):
            index -= 1

        return int(
            self._samples[
                index
            ].flags
        )

    def _run_fixed_lag_correction_locked(
        self,
        force: bool,
    ) -> None:
        """
        将“8 秒输出余裕”用于真正的未来波形复核。

        实时模式：
            commit_until = latest_sample - 7.25 s

        因此一个待提交主波拥有：
        - 约 12 s 过去波形；
        - 约 7.25 s 未来波形；
        - 未来多个 Firmware Beat；
        - 完整的主周期自相关证据。

        会话结束 / 导出时 `force=True`：
        最后约 0.25 s 边界仍不提交，避免卷积和局部最大值边缘效应；
        其余尾部使用当前会话全部已知波形离线完成。
        """
        if not self._samples:
            return

        latest_sample_t_us = int(
            self._samples[-1].t_us
        )

        if not force:
            interval_us = int(
                round(
                    self.config.correction_run_interval_seconds
                    * 1e6
                )
            )

            if (
                self._last_correction_run_t_us > 0
                and latest_sample_t_us
                - self._last_correction_run_t_us
                < interval_us
            ):
                return

            commit_until_t_us = int(
                latest_sample_t_us
                - round(
                    self.config.correction_output_lag_seconds
                    * 1e6
                )
            )
        else:
            # 导出 / 停止采集时可以使用已经存在的全部未来数据。
            # 只保留 0.25 s 右边界保护，不把卷积边界误认成主峰。
            commit_until_t_us = int(
                latest_sample_t_us
                - 250_000
            )

        self._last_correction_run_t_us = (
            latest_sample_t_us
        )

        if (
            commit_until_t_us
            <= int(
                self._samples[0].t_us
            )
        ):
            return

        proposals = (
            self._waveform_corrector.propose(
                list(
                    self._samples
                ),
                list(
                    self._firmware_beats
                ),
                last_committed_t_us=int(
                    self._last_refined_t_us
                ),
                rr_history_ms=list(
                    self._refined_rr_history
                ),
                commit_until_t_us=(
                    commit_until_t_us
                ),
            )
        )

        if not proposals:
            return

        for proposal in proposals:
            refined_t_us = int(
                proposal.t_us
            )

            if (
                self._last_refined_t_us > 0
                and refined_t_us
                <= self._last_refined_t_us
            ):
                continue

            if self._last_refined_t_us == 0:
                rr_ms = 0.0
            else:
                rr_ms = (
                    refined_t_us
                    - self._last_refined_t_us
                ) / 1000.0

            # 这里不因为“看起来不像 expected RR”而删除主波。
            # reference RR 只用于搜索尺度。
            # 最终 RR 是否可进入 HRV 由未来感知 BeatTimelineCleaner 审计。
            if (
                np.isfinite(
                    rr_ms
                )
                and self.config.waveform_min_rr_ms
                <= rr_ms
                <= self.config.rr_hard_max_ms
            ):
                self._refined_rr_history.append(
                    float(
                        rr_ms
                    )
                )

            self._last_refined_t_us = (
                refined_t_us
            )

            valid_history = np.asarray(
                [
                    value
                    for value
                    in self._refined_rr_history
                    if (
                        np.isfinite(
                            value
                        )
                        and value > 0
                    )
                ],
                dtype=float,
            )

            if valid_history.size:
                median_rr = float(
                    np.median(
                        valid_history[
                            -min(
                                valid_history.size,
                                9,
                            ):
                        ]
                    )
                )

                refined_hr = (
                    60000.0
                    / median_rr
                    if median_rr > 0
                    else 0.0
                )
            elif (
                proposal.reference_rr_ms > 0
            ):
                refined_hr = (
                    60000.0
                    / proposal.reference_rr_ms
                )
            else:
                refined_hr = 0.0

            matched_source_t_us = int(
                proposal.matched_firmware_t_us
            )

            timing_shift_ms = (
                (
                    refined_t_us
                    - matched_source_t_us
                )
                / 1000.0
                if matched_source_t_us > 0
                else 0.0
            )

            flags = (
                int(
                    proposal.matched_firmware_flags
                )
                if matched_source_t_us > 0
                else self._sample_flags_near_locked(
                    refined_t_us
                )
            )

            waveform_score = float(
                np.clip(
                    proposal.waveform_score,
                    0.0,
                    1.0,
                )
            )

            refined = BeatFrame(
                seq=int(
                    proposal.seq
                ),
                t_us=refined_t_us,
                rr_ms=float(
                    rr_ms
                ),
                hr_bpm=float(
                    refined_hr
                ),
                # v0.3.7 正式 Beat 的 score 表示整窗波形主波质量。
                score=waveform_score,
                flags=flags,
                source_t_us=(
                    matched_source_t_us
                ),
                timing_shift_ms=float(
                    timing_shift_ms
                ),
                timing_quality=(
                    waveform_score
                ),
                timing_uncertainty_ms=float(
                    proposal.timing_uncertainty_ms
                ),
                timing_recovered=bool(
                    proposal.inserted_by_smoother
                    or proposal.low_prominence_rescue
                    or abs(
                        timing_shift_ms
                    )
                    > self.config.fiducial_max_applied_shift_ms
                ),
                refined=True,
                correction_method=(
                    "fixed_lag_waveform"
                ),
                waveform_score=(
                    waveform_score
                ),
                reference_rr_ms=float(
                    proposal.reference_rr_ms
                ),
                matched_firmware_t_us=(
                    matched_source_t_us
                ),
                inserted_by_smoother=bool(
                    proposal.inserted_by_smoother
                ),
                low_prominence_rescue=bool(
                    proposal.low_prominence_rescue
                ),
            )

            self._raw_beats.append(
                refined
            )

            if refined_hr > 0:
                self._latest_hr_bpm = float(
                    refined_hr
                )

            # 第一搏没有 RR，不刷新 HRV。
            if rr_ms <= 0:
                continue

            if self._last_metric_us is None:
                self._last_metric_us = (
                    refined_t_us
                )

            if (
                refined_t_us
                - self._last_metric_us
                >= self.config.metric_update_seconds
                * 1e6
            ):
                self._update_metrics_locked(
                    refined_t_us,
                    record_history=True,
                )
                self._last_metric_us = (
                    refined_t_us
                )

    def ingest_firmware_metric(
        self,
        frame: FirmwareMetricFrame,
    ) -> None:
        # 固件 RMSSD 只做诊断参考，不进入最终 HRV 链。
        with self._lock:
            self._last_firmware_metric = frame

    def ingest_diagnostic(
        self,
        frame: DiagnosticFrame,
    ) -> None:
        with self._lock:
            self._last_diagnostic = frame

    def ingest_protocol_health(
        self,
        health: ProtocolHealth,
    ) -> None:
        with self._lock:
            self._protocol_health = copy.deepcopy(
                health
            )

    def force_update(
        self,
        record_history: bool = False,
    ) -> AnalysisSnapshot:
        with self._lock:
            self._run_fixed_lag_correction_locked(
                force=True
            )
            self._update_metrics_locked(
                self._current_time_us_locked(),
                record_history=record_history,
            )
            return copy.deepcopy(
                self._last_snapshot
            )

    def snapshot(self) -> AnalysisSnapshot:
        with self._lock:
            if self._last_snapshot.t_us == 0:
                self._update_metrics_locked(
                    self._current_time_us_locked(),
                    record_history=False,
                )

            return copy.deepcopy(
                self._last_snapshot
            )

    def _current_time_us_locked(self) -> int:
        if self._samples:
            return self._samples[-1].t_us
        if self._raw_beats:
            return self._raw_beats[-1].t_us
        return 0

    def _quality_samples_locked(
        self,
        seconds: float,
    ) -> list[SampleFrame]:
        if not self._samples:
            return []

        end_us = self._samples[-1].t_us
        start_us = end_us - int(
            seconds * 1e6
        )

        return [
            sample
            for sample in self._samples
            if sample.t_us >= start_us
        ]

    def _update_metrics_locked(
        self,
        now_us: int,
        record_history: bool,
    ) -> None:
        # ---------------------------------------------------------------
        # 每次重新清洗整段原始 Beat。
        # 5000 个事件规模很小，换来可回溯的一致性和可复现导出。
        # ---------------------------------------------------------------
        clean_result = self._timeline_cleaner.clean(
            list(self._raw_beats)
        )
        self._cleaned_records = clean_result.records
        self._nn_intervals = clean_result.nn_intervals
        self._timeline_quality = clean_result.quality

        # 时域看最近 30 秒信号质量；频域审计整个 5 分钟窗口。
        signal_quality = evaluate_signal_quality(
            self._quality_samples_locked(
                self.config.signal_quality_window_seconds
            ),
            self._protocol_health,
            self.config,
        )
        frequency_signal_quality = evaluate_signal_quality(
            self._quality_samples_locked(
                self.config.frequency_window_seconds
            ),
            self._protocol_health,
            self.config,
        )

        time_metrics = compute_time_domain(
            self._cleaned_records,
            self._nn_intervals,
            signal_quality,
            self.config,
        )

        frequency_metrics = compute_frequency_domain(
            self._cleaned_records,
            self._nn_intervals,
            frequency_signal_quality,
            self._protocol_health,
            self.config,
        )

        quality = compute_quality_assessment(
            signal_quality,
            self._timeline_quality,
            time_metrics,
            frequency_metrics,
        )

        self._last_snapshot = AnalysisSnapshot(
            t_us=now_us,
            hr_bpm=self._latest_hr_bpm,
            time=time_metrics,
            frequency=frequency_metrics,
            signal_quality=signal_quality,
            timeline_quality=copy.deepcopy(
                self._timeline_quality
            ),
            quality=quality,
            protocol_health=copy.deepcopy(
                self._protocol_health
            ),
        )

        if record_history:
            self._append_history_locked(
                self._last_snapshot
            )

    def _history_row(
        self,
        snapshot: AnalysisSnapshot,
    ) -> dict:
        time_metrics = snapshot.time
        frequency = snapshot.frequency
        annotations = self.annotations()

        return {
            "t_us": snapshot.t_us,
            "hr_bpm": snapshot.hr_bpm,

            "time_status": time_metrics.status,
            "time_validity_reason": (
                time_metrics.validity_reason
            ),
            "rmssd_ms": (
                time_metrics.rmssd_ms
                if time_metrics.valid
                else np.nan
            ),
            "rmssd_ci_low_ms": (
                time_metrics.rmssd_ci_low_ms
                if time_metrics.valid
                else np.nan
            ),
            "rmssd_ci_high_ms": (
                time_metrics.rmssd_ci_high_ms
                if time_metrics.valid
                else np.nan
            ),
            "sdnn_ms": (
                time_metrics.sdnn_ms
                if time_metrics.valid
                else np.nan
            ),
            "pnn50_percent": (
                time_metrics.pnn50_percent
                if time_metrics.valid
                else np.nan
            ),
            "fiducial_quality_mean": (
                time_metrics.fiducial_quality_mean
            ),
            "fiducial_uncertainty_p95_ms": (
                time_metrics.fiducial_uncertainty_p95_ms
            ),
            "fiducial_shift_p95_ms": (
                time_metrics.fiducial_shift_p95_ms
            ),
            "fiducial_unstable_ratio": (
                time_metrics.fiducial_unstable_ratio
            ),

            "frequency_status": frequency.status,
            "frequency_validity_reason": (
                frequency.validity_reason
            ),
            "total_power_ms2": (
                frequency.total_power_ms2
                if frequency.valid
                else np.nan
            ),
            "vlf_ms2": (
                frequency.vlf_ms2
                if frequency.valid
                else np.nan
            ),
            "lf_ms2": (
                frequency.lf_ms2
                if frequency.valid
                else np.nan
            ),
            "hf_ms2": (
                frequency.hf_ms2
                if frequency.valid
                else np.nan
            ),
            "lf_nu": (
                frequency.lf_nu
                if frequency.valid
                else np.nan
            ),
            "hf_nu": (
                frequency.hf_nu
                if frequency.valid
                else np.nan
            ),
            "lf_hf": (
                frequency.lf_hf
                if frequency.valid
                else np.nan
            ),
            "hf_lf": (
                frequency.hf_lf
                if frequency.valid
                else np.nan
            ),
            "spectral_agreement": (
                frequency.spectral_agreement
            ),
            "spectral_agreement_raw": (
                frequency.spectral_agreement_raw
            ),
            "spectral_shape_agreement": (
                frequency.spectral_shape_agreement
            ),
            "band_power_agreement": (
                frequency.band_power_agreement
            ),
            "interpolation_agreement": (
                frequency.interpolation_agreement
            ),

            "sqi": snapshot.signal_quality.sqi,
            "overall_status": snapshot.quality.status,
            "detected_artifact_ratio": (
                time_metrics.detected_artifact_ratio
            ),
            "corrected_ratio": (
                time_metrics.corrected_ratio
            ),
            "unresolved_suspect_ratio": (
                time_metrics.unresolved_suspect_ratio
            ),
            "max_consecutive_artifacts": (
                time_metrics.max_consecutive_artifacts
            ),

            "protocol_error_ratio": (
                snapshot.protocol_health.error_ratio
            ),
            "protocol_crc_errors": (
                snapshot.protocol_health.crc_errors
            ),
            "protocol_format_errors": (
                snapshot.protocol_health.format_errors
            ),
            "protocol_seq_gaps": (
                snapshot.protocol_health.sample_seq_gaps
            ),
        }

    def _append_history_locked(
        self,
        snapshot: AnalysisSnapshot,
    ) -> None:
        row = self._history_row(snapshot)

        # 同一个 t_us 不重复入历史。
        if (
            self._metric_history
            and self._metric_history[-1]["t_us"]
            == row["t_us"]
        ):
            self._metric_history[-1] = row
        else:
            self._metric_history.append(row)

    def recent_signal(
        self,
        seconds: float = 12.0,
        field: str = "filtered",
    ) -> tuple[np.ndarray, np.ndarray]:
        with self._lock:
            if not self._samples:
                return np.array([]), np.array([])

            end_us = self._samples[-1].t_us
            start_us = end_us - int(
                seconds * 1e6
            )
            selected = [
                sample
                for sample in self._samples
                if sample.t_us >= start_us
            ]

        if not selected:
            return np.array([]), np.array([])

        t = np.asarray(
            [sample.t_us for sample in selected],
            dtype=float,
        ) / 1e6
        t -= t[-1]

        if field == "raw":
            y = np.asarray(
                [sample.raw for sample in selected],
                dtype=float,
            )
        elif field == "avg":
            y = np.asarray(
                [sample.avg for sample in selected],
                dtype=float,
            )
        else:
            y = np.asarray(
                [sample.filtered for sample in selected],
                dtype=float,
            )

        return t, y

    def recent_signal_debug(
        self,
        seconds: float = 12.0,
    ) -> tuple[
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        dict,
    ]:
        """
        返回 v0.3.7 固定滞后整窗复核调试序列。

        数据层仍保留：
        - detector_score；
        - Firmware Candidate；
        - Firmware Accepted；
        - 正式 fixed-lag waveform Beat。

        UI 只绘制两条连续视觉序列：
        - 滤波 PPG；
        - 正式 fixed-lag waveform Beat 0/1。

        窗口右缘与正式 Beat 使用同一个成熟时间：
        latest received - 7.25 s。
        """
        with self._lock:
            if not self._samples:
                empty = np.array([])

                return (
                    empty,
                    empty,
                    empty,
                    empty,
                    empty,
                    empty,
                    {
                        "duration_s": 0.0,
                        "candidate_count": 0,
                        "accepted_beat_count": 0,
                        "firmware_beat_count": 0,
                        "rescue_count": 0,
                        "candidate_bpm_estimate": 0.0,
                        "accepted_bpm_estimate": 0.0,
                        "candidate_minus_accepted": 0,
                        "expected_rr_ms": 0.0,
                        "sample_hr_bpm": self._latest_sample_hr_bpm,
                        "accepted_hr_bpm": self._latest_hr_bpm,
                        "accepted_score_mean": 0.0,
                        "fiducial_quality_mean": 0.0,
                        "fiducial_uncertainty_p95_ms": 0.0,
                        "fiducial_shift_p95_ms": 0.0,
                        "effective_sample_rate_hz": 0.0,
                        "timing_jitter_p95_ms": 0.0,
                        "timing_overrun_ratio": 0.0,
                        "end_t_us": 0,
                        "latest_received_t_us": 0,
                        "display_lag_s": 0.0,
                        "correction_reference_rr_ms": 0.0,
                        "correction_autocorr_confidence": 0.0,
                        "correction_inserted_count": 0,
                        "correction_firmware_matched_count": 0,
                        "annotation_count": len(
                            self._annotations
                        ),
                        "recent_annotation_count": 0,
                        "last_annotation_age_s": -1.0,
                    },
                )

            latest_received_t_us = int(
                self._samples[-1].t_us
            )

            target_lag_us = int(
                round(
                    self.config.correction_output_lag_seconds
                    * 1e6
                )
            )

            delayed_end_us = (
                latest_received_t_us
                - target_lag_us
            )

            # 启动阶段尚未积累 7.25 s 时先显示已有 PPG，
            # 但正式绿色 Beat 只有成熟后才出现。
            if (
                delayed_end_us
                <= int(
                    self._samples[0].t_us
                )
            ):
                end_us = (
                    latest_received_t_us
                )
            else:
                end_us = int(
                    delayed_end_us
                )

            start_us = end_us - int(
                seconds * 1e6
            )

            selected = [
                sample
                for sample in self._samples
                if (
                    start_us
                    <= sample.t_us
                    <= end_us
                )
            ]

            accepted_beats = [
                beat
                for beat in self._raw_beats
                if start_us <= beat.t_us <= end_us
            ]

            firmware_beats = [
                beat
                for beat in self._firmware_beats
                if start_us <= beat.t_us <= end_us
            ]

            recent_annotations = [
                annotation
                for annotation in self._annotations
                if (
                    start_us
                    <= annotation.device_t_us
                    <= end_us
                )
            ]

            annotation_count = len(
                self._annotations
            )

            last_annotation_t_us = (
                self._annotations[-1].device_t_us
                if self._annotations
                else 0
            )

            sample_hr_bpm = (
                self._latest_sample_hr_bpm
            )
            accepted_hr_bpm = (
                self._latest_hr_bpm
            )

        if not selected:
            empty = np.array([])

            return (
                empty,
                empty,
                empty,
                empty,
                empty,
                empty,
                {
                    "duration_s": 0.0,
                    "candidate_count": 0,
                    "accepted_beat_count": 0,
                    "firmware_beat_count": 0,
                    "rescue_count": 0,
                    "candidate_bpm_estimate": 0.0,
                    "accepted_bpm_estimate": 0.0,
                    "candidate_minus_accepted": 0,
                    "expected_rr_ms": 0.0,
                    "sample_hr_bpm": sample_hr_bpm,
                    "accepted_hr_bpm": accepted_hr_bpm,
                    "accepted_score_mean": 0.0,
                    "fiducial_quality_mean": 0.0,
                    "fiducial_uncertainty_p95_ms": 0.0,
                    "fiducial_shift_p95_ms": 0.0,
                    "effective_sample_rate_hz": 0.0,
                    "timing_jitter_p95_ms": 0.0,
                    "timing_overrun_ratio": 0.0,
                    "end_t_us": int(
                        end_us
                    ),
                    "latest_received_t_us": int(
                        latest_received_t_us
                    ),
                    "display_lag_s": float(
                        max(
                            latest_received_t_us
                            - end_us,
                            0,
                        )
                        / 1e6
                    ),
                    "correction_reference_rr_ms": float(
                        self._waveform_corrector.last_diagnostics.reference_rr_ms
                    ),
                    "correction_autocorr_confidence": float(
                        self._waveform_corrector.last_diagnostics.autocorr_confidence
                    ),
                    "correction_inserted_count": 0,
                    "correction_firmware_matched_count": 0,
                    "annotation_count": int(
                        annotation_count
                    ),
                    "recent_annotation_count": int(
                        len(
                            recent_annotations
                        )
                    ),
                    "last_annotation_age_s": (
                        float(
                            (
                                end_us
                                - last_annotation_t_us
                            )
                            / 1e6
                        )
                        if last_annotation_t_us > 0
                        else -1.0
                    ),
                },
            )

        sample_times_us = np.asarray(
            [
                sample.t_us
                for sample in selected
            ],
            dtype=np.int64,
        )

        t = (
            sample_times_us.astype(float)
            / 1e6
        )
        t -= t[-1]

        filtered = np.asarray(
            [
                sample.filtered
                for sample in selected
            ],
            dtype=float,
        )

        detector_score = np.asarray(
            [
                float(
                    np.clip(
                        sample.detector_score,
                        0.0,
                        1.0,
                    )
                )
                for sample in selected
            ],
            dtype=float,
        )

        candidate = np.asarray(
            [
                1.0
                if sample.peak
                else 0.0
                for sample in selected
            ],
            dtype=float,
        )

        accepted = np.zeros_like(
            candidate
        )
        firmware_accepted = np.zeros_like(
            candidate
        )

        def mark_event(
            target: np.ndarray,
            event_t_us: int,
        ) -> None:
            index = int(
                np.searchsorted(
                    sample_times_us,
                    event_t_us,
                )
            )

            nearby: list[int] = []

            if 0 <= index < len(sample_times_us):
                nearby.append(index)
            if 0 <= index - 1 < len(sample_times_us):
                nearby.append(index - 1)

            if not nearby:
                return

            nearest = min(
                nearby,
                key=lambda candidate_index:
                    abs(
                        int(sample_times_us[candidate_index])
                        - int(event_t_us)
                    ),
            )
            target[nearest] = 1.0

        for beat in accepted_beats:
            mark_event(
                accepted,
                beat.t_us,
            )

        for beat in firmware_beats:
            mark_event(
                firmware_accepted,
                beat.t_us,
            )

        duration_s = (
            float(
                sample_times_us[-1]
                - sample_times_us[0]
            )
            / 1e6
            if len(sample_times_us) >= 2
            else 0.0
        )

        if (
            len(sample_times_us) >= 2
            and duration_s > 0
        ):
            effective_sample_rate_hz = (
                (len(sample_times_us) - 1)
                / duration_s
            )

            dt_ms = (
                np.diff(
                    sample_times_us.astype(float)
                )
                / 1000.0
            )

            expected_ms = (
                1000.0
                / self.config.sample_rate_hz
            )

            timing_jitter_p95_ms = float(
                np.percentile(
                    np.abs(
                        dt_ms - expected_ms
                    ),
                    95,
                )
            )

            timing_overrun_ratio = float(
                np.mean(
                    dt_ms
                    > expected_ms * 1.5
                )
            )
        else:
            effective_sample_rate_hz = 0.0
            timing_jitter_p95_ms = 0.0
            timing_overrun_ratio = 0.0

        candidate_count = int(
            np.count_nonzero(
                candidate > 0.5
            )
        )

        accepted_count = len(
            accepted_beats
        )
        firmware_count = len(
            firmware_beats
        )

        rescue_count = sum(
            bool(
                beat.flags
                & 0x10
            )
            for beat in firmware_beats
        )

        fiducial_recovery_count = sum(
            bool(
                beat.timing_recovered
            )
            for beat in accepted_beats
        )

        waveform_inserted_count = sum(
            bool(
                beat.inserted_by_smoother
            )
            for beat in accepted_beats
        )

        waveform_firmware_matched_count = sum(
            bool(
                beat.matched_firmware_t_us
            )
            for beat in accepted_beats
        )

        candidate_bpm = (
            candidate_count
            * 60.0
            / duration_s
            if duration_s > 0
            else 0.0
        )

        accepted_bpm = (
            accepted_count
            * 60.0
            / duration_s
            if duration_s > 0
            else 0.0
        )

        expected_values = np.asarray(
            [
                sample.expected_rr_ms
                for sample in selected
                if sample.expected_rr_ms > 0
            ],
            dtype=float,
        )

        correction_reference_rr_ms = float(
            self._waveform_corrector.last_diagnostics.reference_rr_ms
        )

        expected_rr_ms = (
            correction_reference_rr_ms
            if correction_reference_rr_ms > 0
            else (
                float(
                    expected_values[-1]
                )
                if expected_values.size
                else 0.0
            )
        )

        beat_scores = np.asarray(
            [
                beat.score
                for beat in accepted_beats
                if beat.score > 0
            ],
            dtype=float,
        )

        accepted_score_mean = (
            float(
                np.mean(beat_scores)
            )
            if beat_scores.size
            else 0.0
        )

        fiducial_quality = np.asarray(
            [
                beat.timing_quality
                for beat in accepted_beats
                if beat.refined
            ],
            dtype=float,
        )
        fiducial_uncertainty = np.asarray(
            [
                beat.timing_uncertainty_ms
                for beat in accepted_beats
                if beat.refined
            ],
            dtype=float,
        )
        fiducial_shift = np.asarray(
            [
                abs(beat.timing_shift_ms)
                for beat in accepted_beats
                if beat.refined
            ],
            dtype=float,
        )

        fiducial_quality_mean = (
            float(np.mean(fiducial_quality))
            if fiducial_quality.size
            else 0.0
        )
        fiducial_uncertainty_p95_ms = (
            float(np.percentile(fiducial_uncertainty, 95))
            if fiducial_uncertainty.size
            else 0.0
        )
        fiducial_shift_p95_ms = (
            float(np.percentile(fiducial_shift, 95))
            if fiducial_shift.size
            else 0.0
        )

        return (
            t,
            filtered,
            detector_score,
            candidate,
            firmware_accepted,
            accepted,
            {
                "duration_s": duration_s,
                "candidate_count": candidate_count,
                "accepted_beat_count": accepted_count,
                "firmware_beat_count": firmware_count,
                "rescue_count": rescue_count,
                "fiducial_recovery_count": fiducial_recovery_count,
                "candidate_bpm_estimate": candidate_bpm,
                "accepted_bpm_estimate": accepted_bpm,
                "candidate_minus_accepted": max(
                    candidate_count
                    - accepted_count,
                    0,
                ),
                "expected_rr_ms": expected_rr_ms,
                "sample_hr_bpm": sample_hr_bpm,
                "accepted_hr_bpm": accepted_hr_bpm,
                "accepted_score_mean": accepted_score_mean,
                "fiducial_quality_mean": fiducial_quality_mean,
                "fiducial_uncertainty_p95_ms": (
                    fiducial_uncertainty_p95_ms
                ),
                "fiducial_shift_p95_ms": fiducial_shift_p95_ms,
                "effective_sample_rate_hz": float(
                    effective_sample_rate_hz
                ),
                "timing_jitter_p95_ms": float(
                    timing_jitter_p95_ms
                ),
                "timing_overrun_ratio": float(
                    timing_overrun_ratio
                ),
                "end_t_us": int(
                    end_us
                ),
                "latest_received_t_us": int(
                    latest_received_t_us
                ),
                "display_lag_s": float(
                    max(
                        latest_received_t_us
                        - end_us,
                        0,
                    )
                    / 1e6
                ),
                "correction_reference_rr_ms": float(
                    correction_reference_rr_ms
                ),
                "correction_autocorr_confidence": float(
                    self._waveform_corrector.last_diagnostics.autocorr_confidence
                ),
                "correction_inserted_count": int(
                    waveform_inserted_count
                ),
                "correction_firmware_matched_count": int(
                    waveform_firmware_matched_count
                ),
                "annotation_count": int(
                    annotation_count
                ),
                "recent_annotation_count": int(
                    len(
                        recent_annotations
                    )
                ),
                "last_annotation_age_s": (
                    float(
                        (
                            end_us
                            - last_annotation_t_us
                        )
                        / 1e6
                    )
                    if last_annotation_t_us > 0
                    else -1.0
                ),
            },
        )

    def metric_history(self) -> list[dict]:
        with self._lock:
            return copy.deepcopy(
                list(self._metric_history)
            )

    def beat_records(self) -> list[BeatRecord]:
        with self._lock:
            return copy.deepcopy(
                self._cleaned_records
            )

    def nn_intervals(self) -> list[NNInterval]:
        with self._lock:
            return copy.deepcopy(
                self._nn_intervals
            )

    def protocol_health(self) -> ProtocolHealth:
        with self._lock:
            return copy.deepcopy(
                self._protocol_health
            )

    def diagnostics(
        self,
    ) -> DiagnosticFrame | None:
        with self._lock:
            return copy.deepcopy(
                self._last_diagnostic
            )

    def frequency_statistics(self) -> dict:
        with self._lock:
            return compute_frequency_statistics(
                list(self._metric_history)
            )

    def compute_spwvd(self):
        with self._lock:
            if self._last_snapshot.t_us == 0:
                self._update_metrics_locked(
                    self._current_time_us_locked(),
                    record_history=False,
                )

            return compute_spwvd(
                copy.deepcopy(
                    self._nn_intervals
                ),
                frequency_valid=(
                    self._last_snapshot.frequency.valid
                ),
                frequency_reason=(
                    self._last_snapshot.frequency.validity_reason
                ),
                config=self.config,
            )

    def export_bundle(self) -> dict:
        """
        在一个锁内冻结 snapshot / beats / history / stats。

        不再出现 V0.2：
        hrv_windows.csv 使用旧窗口，
        summary.json 又调用 force_update() 得到几秒后的新窗口。
        """
        with self._lock:
            self._update_metrics_locked(
                self._current_time_us_locked(),
                record_history=False,
            )

            snapshot = copy.deepcopy(
                self._last_snapshot
            )
            history = copy.deepcopy(
                list(self._metric_history)
            )

            current_row = self._history_row(
                snapshot
            )
            if (
                not history
                or history[-1]["t_us"]
                != current_row["t_us"]
            ):
                history.append(current_row)
            else:
                history[-1] = current_row

            return {
                "snapshot": snapshot,

                # v0.3.4：分析导出同时冻结最近约 5 分钟原始 Sample / 固件 Beat / HRV 细化 Beat。
                "samples": copy.deepcopy(
                    list(self._samples)
                ),
                "annotations": copy.deepcopy(
                    list(self._annotations)
                ),
                "firmware_beats": copy.deepcopy(
                    list(self._firmware_beats)
                ),
                "raw_beats": copy.deepcopy(
                    list(self._raw_beats)
                ),

                "beats": copy.deepcopy(
                    self._cleaned_records
                ),
                "nn_intervals": copy.deepcopy(
                    self._nn_intervals
                ),
                "history": history,
                "frequency_statistics": (
                    compute_frequency_statistics(
                        history
                    )
                ),
                "protocol_health": copy.deepcopy(
                    self._protocol_health
                ),
            }

    def summary_dict(
        self,
        snapshot: AnalysisSnapshot | None = None,
    ) -> dict:
        if snapshot is None:
            snapshot = self.force_update(
                record_history=False
            )

        time_metrics = snapshot.time
        frequency = snapshot.frequency
        user_annotations = self.annotations()

        return {
            "snapshot_t_us": snapshot.t_us,
            "hr_bpm": round(
                snapshot.hr_bpm,
                3,
            ),
            "result_status": (
                snapshot.quality.status
            ),

            "user_annotations": {
                "count": len(
                    user_annotations
                ),
                "last_device_t_us": (
                    user_annotations[-1].device_t_us
                    if user_annotations
                    else None
                ),
                "last_label_type": (
                    user_annotations[-1].label_type
                    if user_annotations
                    else None
                ),
                "label_lookback_seconds": (
                    self.config.user_annotation_lookback_seconds
                ),
            },

            "time_domain": {
                "valid": time_metrics.valid,
                "status": time_metrics.status,
                "validity_reason": (
                    time_metrics.validity_reason
                ),
                "nn_count": time_metrics.nn_count,

                # 正式指标：窗口无效时写 null。
                "mean_nn_ms": (
                    round(time_metrics.mean_nn_ms, 3)
                    if time_metrics.valid
                    else None
                ),
                "mean_hr_bpm": (
                    round(time_metrics.mean_hr_bpm, 3)
                    if time_metrics.valid
                    else None
                ),
                "rmssd_ms": (
                    round(time_metrics.rmssd_ms, 3)
                    if time_metrics.valid
                    else None
                ),
                "rmssd_95ci_ms": (
                    [
                        round(
                            time_metrics.rmssd_ci_low_ms,
                            3,
                        ),
                        round(
                            time_metrics.rmssd_ci_high_ms,
                            3,
                        ),
                    ]
                    if time_metrics.valid
                    else None
                ),
                "sdnn_ms": (
                    round(time_metrics.sdnn_ms, 3)
                    if time_metrics.valid
                    else None
                ),
                "pnn50_percent": (
                    round(
                        time_metrics.pnn50_percent,
                        3,
                    )
                    if time_metrics.valid
                    else None
                ),

                # 调试值明确标为 candidate，不允许 UI 当正式 HRV 使用。
                "candidate_rmssd_ms": round(
                    time_metrics.rmssd_ms,
                    3,
                ),
                "detected_artifact_ratio": round(
                    time_metrics.detected_artifact_ratio,
                    5,
                ),
                "corrected_ratio": round(
                    time_metrics.corrected_ratio,
                    5,
                ),
                "unresolved_suspect_ratio": round(
                    time_metrics.unresolved_suspect_ratio,
                    5,
                ),
                "max_consecutive_artifacts": (
                    time_metrics.max_consecutive_artifacts
                ),
                "fiducial_quality_mean": round(
                    time_metrics.fiducial_quality_mean,
                    4,
                ),
                "fiducial_uncertainty_p95_ms": round(
                    time_metrics.fiducial_uncertainty_p95_ms,
                    3,
                ),
                "fiducial_shift_p95_ms": round(
                    time_metrics.fiducial_shift_p95_ms,
                    3,
                ),
                "fiducial_unstable_ratio": round(
                    time_metrics.fiducial_unstable_ratio,
                    5,
                ),
            },

            "frequency_domain": {
                "valid": frequency.valid,
                "status": frequency.status,
                "validity_reason": (
                    frequency.validity_reason
                ),
                "progress": round(
                    frequency.progress,
                    4,
                ),
                "duration_seconds": round(
                    frequency.duration_seconds,
                    2,
                ),
                "total_power_ms2": (
                    round(
                        frequency.total_power_ms2,
                        3,
                    )
                    if frequency.valid
                    else None
                ),
                "vlf_ms2": (
                    round(frequency.vlf_ms2, 3)
                    if frequency.valid
                    else None
                ),
                "lf_ms2": (
                    round(frequency.lf_ms2, 3)
                    if frequency.valid
                    else None
                ),
                "hf_ms2": (
                    round(frequency.hf_ms2, 3)
                    if frequency.valid
                    else None
                ),
                "lf_nu": (
                    round(frequency.lf_nu, 3)
                    if frequency.valid
                    else None
                ),
                "hf_nu": (
                    round(frequency.hf_nu, 3)
                    if frequency.valid
                    else None
                ),
                "lf_hf": (
                    round(frequency.lf_hf, 4)
                    if frequency.valid
                    else None
                ),
                "hf_lf": (
                    round(frequency.hf_lf, 4)
                    if frequency.valid
                    else None
                ),
                "spectral_agreement": (
                    round(
                        frequency.spectral_agreement,
                        4,
                    )
                    if frequency.spectral_agreement > 0
                    else None
                ),
                "spectral_agreement_raw": (
                    round(
                        frequency.spectral_agreement_raw,
                        4,
                    )
                    if frequency.spectral_agreement_raw > 0
                    else None
                ),
                "spectral_shape_agreement": (
                    round(
                        frequency.spectral_shape_agreement,
                        4,
                    )
                    if frequency.spectral_shape_agreement > 0
                    else None
                ),
                "band_power_agreement": (
                    round(
                        frequency.band_power_agreement,
                        4,
                    )
                    if frequency.band_power_agreement > 0
                    else None
                ),
                "interpolation_agreement": (
                    round(
                        frequency.interpolation_agreement,
                        4,
                    )
                    if frequency.interpolation_agreement > 0
                    else None
                ),
                "max_consecutive_artifacts": (
                    frequency.max_consecutive_artifacts
                ),
                "fiducial_quality_mean": round(
                    frequency.fiducial_quality_mean,
                    4,
                ),
                "fiducial_uncertainty_p95_ms": round(
                    frequency.fiducial_uncertainty_p95_ms,
                    3,
                ),
                "fiducial_shift_p95_ms": round(
                    frequency.fiducial_shift_p95_ms,
                    3,
                ),
                "fiducial_unstable_ratio": round(
                    frequency.fiducial_unstable_ratio,
                    5,
                ),
            },

            "signal_quality": {
                "sqi": round(
                    snapshot.signal_quality.sqi,
                    4,
                ),
                "status": (
                    snapshot.signal_quality.status
                ),
                "wear_ratio": round(
                    snapshot.signal_quality.wear_ratio,
                    4,
                ),
                "clip_low_ratio": round(
                    snapshot.signal_quality.clip_low_ratio,
                    4,
                ),
                "clip_high_ratio": round(
                    snapshot.signal_quality.clip_high_ratio,
                    4,
                ),
                "sequence_drop_ratio": round(
                    snapshot.signal_quality.sequence_drop_ratio,
                    5,
                ),
                "effective_sample_rate_hz": round(
                    snapshot.signal_quality.effective_sample_rate_hz,
                    3,
                ),
                "timing_jitter_p95_ms": round(
                    snapshot.signal_quality.timing_jitter_p95_ms,
                    4,
                ),
                "timing_overrun_ratio": round(
                    snapshot.signal_quality.timing_overrun_ratio,
                    5,
                ),
                "protocol_error_ratio": round(
                    snapshot.signal_quality.protocol_error_ratio,
                    5,
                ),
                "reasons": (
                    snapshot.signal_quality.reasons
                ),
            },

            "timeline_quality": {
                "raw_rr_count": (
                    snapshot.timeline_quality.raw_rr_count
                ),
                "accepted_nn_count": (
                    snapshot.timeline_quality.accepted_nn_count
                ),
                "detected_artifact_ratio": round(
                    snapshot.timeline_quality.detected_artifact_ratio,
                    5,
                ),
                "corrected_interval_ratio": round(
                    snapshot.timeline_quality.corrected_interval_ratio,
                    5,
                ),
                "unresolved_suspect_ratio": round(
                    snapshot.timeline_quality.unresolved_suspect_ratio,
                    5,
                ),
                "valid_nn_ratio": round(
                    snapshot.timeline_quality.valid_nn_ratio,
                    5,
                ),
                "max_consecutive_artifacts": (
                    snapshot.timeline_quality.max_consecutive_artifacts
                ),
                "fiducial_quality_mean": round(
                    snapshot.timeline_quality.fiducial_quality_mean,
                    4,
                ),
                "fiducial_uncertainty_p95_ms": round(
                    snapshot.timeline_quality.fiducial_uncertainty_p95_ms,
                    3,
                ),
                "fiducial_shift_p95_ms": round(
                    snapshot.timeline_quality.fiducial_shift_p95_ms,
                    3,
                ),
                "fiducial_unstable_ratio": round(
                    snapshot.timeline_quality.fiducial_unstable_ratio,
                    5,
                ),
            },

            "protocol_health": {
                "mode": snapshot.protocol_health.mode,
                "ok_frames": (
                    snapshot.protocol_health.ok_frames
                ),
                "crc_errors": (
                    snapshot.protocol_health.crc_errors
                ),
                "format_errors": (
                    snapshot.protocol_health.format_errors
                ),
                "resync_count": (
                    snapshot.protocol_health.resync_count
                ),
                "sample_seq_gaps": (
                    snapshot.protocol_health.sample_seq_gaps
                ),
                "error_ratio": round(
                    snapshot.protocol_health.error_ratio,
                    6,
                ),
            },

            "quality": {
                "sqi": round(
                    snapshot.quality.sqi,
                    4,
                ),
                "status": snapshot.quality.status,
                "time_status": (
                    snapshot.quality.time_status
                ),
                "frequency_status": (
                    snapshot.quality.frequency_status
                ),
                "reasons": snapshot.quality.reasons,
            },
        }
