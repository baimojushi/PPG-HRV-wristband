from __future__ import annotations

from collections import deque
import copy
import threading

import numpy as np

from .config import AnalysisConfig
from .confidence import compute_quality_assessment
from .frequency_stats import compute_frequency_statistics
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
)
from .rr_cleaner import BeatTimelineCleaner
from .signal_quality import evaluate_signal_quality
from .spwvd import compute_spwvd


class AnalysisEngine:
    """
    线程安全分析引擎。

    关键变化：
    - `_raw_beats` 永远保存原始 BeatFrame；
    - 每次指标更新都用 BeatTimelineCleaner 重建最近整段 NN 时间轴；
    - 因此伪峰可以回溯删除，漏搏可以插入合成时间点；
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
        self._raw_beats: deque[BeatFrame] = deque(
            maxlen=5000
        )

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
            self._raw_beats.clear()
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
            # v0.3.2 保留同极性锁并修复采样时基；这里仍保留采样帧 HR 作为实时 Debug 对照。
            if (
                np.isfinite(frame.hr_bpm)
                and frame.hr_bpm > 0
            ):
                self._latest_sample_hr_bpm = float(
                    frame.hr_bpm
                )

    def ingest_beat(
        self,
        frame: BeatFrame,
    ) -> None:
        # 调试要求保留“第一搏 rr=0”事件。
        # BeatTimelineCleaner 自己会过滤 rr<=0，因此保留第一搏不会污染 HRV；
        # 同时 UI 可以准确显示固件实际生成了多少个 BeatFrame。
        with self._lock:
            self._raw_beats.append(frame)

            if frame.hr_bpm > 0:
                self._latest_hr_bpm = frame.hr_bpm

            # 第一搏没有 RR，不触发 HRV 指标刷新。
            if frame.rr_ms <= 0:
                return

            if self._last_metric_us is None:
                self._last_metric_us = frame.t_us

            if (
                frame.t_us - self._last_metric_us
                >= self.config.metric_update_seconds * 1e6
            ):
                self._update_metrics_locked(
                    frame.t_us,
                    record_history=True,
                )
                self._last_metric_us = frame.t_us

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
        dict,
    ]:
        """
        返回 v0.3.2 动态检测器调试序列。

        右侧 0~1 轴：
        - detector_score：连续形态活跃度；
        - candidate：局部极值候选脉冲；
        - accepted：周期内 winner / rescue 的最终心搏脉冲。

        Candidate 可以多于 Accepted。
        最终 RR / HR / HRV 只使用 Accepted Beat。
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
                    {
                        "duration_s": 0.0,
                        "candidate_count": 0,
                        "accepted_beat_count": 0,
                        "rescue_count": 0,
                        "candidate_bpm_estimate": 0.0,
                        "accepted_bpm_estimate": 0.0,
                        "candidate_minus_accepted": 0,
                        "expected_rr_ms": 0.0,
                        "sample_hr_bpm": self._latest_sample_hr_bpm,
                        "accepted_hr_bpm": self._latest_hr_bpm,
                        "accepted_score_mean": 0.0,
                        "effective_sample_rate_hz": 0.0,
                        "timing_jitter_p95_ms": 0.0,
                        "timing_overrun_ratio": 0.0,
                    },
                )

            end_us = self._samples[-1].t_us
            start_us = end_us - int(
                seconds * 1e6
            )

            selected = [
                sample
                for sample in self._samples
                if sample.t_us >= start_us
            ]

            accepted_beats = [
                beat
                for beat in self._raw_beats
                if start_us <= beat.t_us <= end_us
            ]

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
                {
                    "duration_s": 0.0,
                    "candidate_count": 0,
                    "accepted_beat_count": 0,
                    "rescue_count": 0,
                    "candidate_bpm_estimate": 0.0,
                    "accepted_bpm_estimate": 0.0,
                    "candidate_minus_accepted": 0,
                    "expected_rr_ms": 0.0,
                    "sample_hr_bpm": sample_hr_bpm,
                    "accepted_hr_bpm": accepted_hr_bpm,
                    "accepted_score_mean": 0.0,
                    "effective_sample_rate_hz": 0.0,
                    "timing_jitter_p95_ms": 0.0,
                    "timing_overrun_ratio": 0.0,
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

        for beat in accepted_beats:
            index = int(
                np.searchsorted(
                    sample_times_us,
                    beat.t_us,
                )
            )

            candidates: list[int] = []

            if (
                0
                <= index
                < len(sample_times_us)
            ):
                candidates.append(
                    index
                )

            if (
                0
                <= index - 1
                < len(sample_times_us)
            ):
                candidates.append(
                    index - 1
                )

            if not candidates:
                continue

            nearest = min(
                candidates,
                key=lambda candidate_index:
                    abs(
                        int(
                            sample_times_us[
                                candidate_index
                            ]
                        )
                        - int(beat.t_us)
                    ),
            )

            accepted[nearest] = 1.0

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

        rescue_count = sum(
            bool(beat.flags & 0x10)
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

        expected_rr_ms = (
            float(expected_values[-1])
            if expected_values.size
            else 0.0
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

        return (
            t,
            filtered,
            detector_score,
            candidate,
            accepted,
            {
                "duration_s": duration_s,
                "candidate_count": candidate_count,
                "accepted_beat_count": accepted_count,
                "rescue_count": rescue_count,
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
                "effective_sample_rate_hz": float(
                    effective_sample_rate_hz
                ),
                "timing_jitter_p95_ms": float(
                    timing_jitter_p95_ms
                ),
                "timing_overrun_ratio": float(
                    timing_overrun_ratio
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

                # v0.3.1：分析导出同时冻结最近约 5 分钟原始 Sample / Beat。
                "samples": copy.deepcopy(
                    list(self._samples)
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

        return {
            "snapshot_t_us": snapshot.t_us,
            "hr_bpm": round(
                snapshot.hr_bpm,
                3,
            ),
            "result_status": (
                snapshot.quality.status
            ),

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
