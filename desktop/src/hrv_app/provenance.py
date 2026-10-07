"""
溯源日志（provenance trace）。

现有 SessionRecorder 只回答"队列有没有掉数据、串口有没有错误、最后的心搏是什么、
最后的 HRV 是多少"。它回答不了"算法为什么把 A 变成 B"。

本模块补齐独立 CSV 证据链，全部只记录、不改变任何算法：

  beat_provenance        每个心搏      固件心搏时间 / 波形峰时间 / 最终时间 / 偏移 /
                                  是否无固件匹配 / 是否恢复 / 原始波形评分 / 峰突出度 /
                                  峰极性 / 预期 RR / 匹配距离 / 恢复原因 / 模板版本
  beat_detector_state    每 5-10 秒   当前极性 / 模板相关度 / 自相关估计 RR /
                                  固件预期 RR / 候选峰数量 / 最终峰数量 /
                                  重新初始化原因
  interval_candidate_trace 每个成熟候选  两检测器支持 / 波形分 / 序列分 / 选择或拒绝原因
  interval_artifact_trace  每个 RR 决策   原始 RR / 局部参考 / artifact 类别 / 修复前后 / 证据
  signal_input_trace     每约 5 秒     原始 ADC 分位数 / 削底 / wear / 采样时基 /
                                  协议与队列 / fixed-lag 自相关与候选统计
  hrv_window_provenance  每 20 秒     窗口与 5 分钟补搏比例 / 恢复比例 /
                                  偏移 p50/p95 / 相邻偏移变化 p95 /
                                  固件 RR 与最终 RR 各自 RMSSD/SDNN / 削底比例
  spectrum_5min_trace    每 5 分钟     起止时间 / RR 数量 / Welch 各频带功率与比例 /
                                  Lomb 各频带比例 / 各自主峰位置 / 两者差异 /
                                  PCHIP 与线性插值差异 / 质量统计 / 拒绝原因
  baseline_trace         每次基线更新  基线版本 / 窗口时间 / 各指标中心值与尺度 /
                                  与上一版差异 / VALID/LIMITED 来源
  prototype_score_trace  每个分析点x每个原型
                                  输入值是否存在 / 原始值 / 相对近期常态偏差 /
                                  各评分分项 / 证据质量系数 / 相似度得分 /
                                  门槛 / 未匹配原因
  causality_trace        每个历史评分  当前评分时间 / 使用到的最晚数据时间 /
                                  基线版本
  ui_explanation_trace   每次文案更新  底层状态 / 用户文案 / 触发依据 /
                                  数据可靠等级

所有 CSV 都是实时流式落盘，与会话一一对应。
"""
from __future__ import annotations

import csv
import os
import threading
from collections import defaultdict
from typing import Any

import numpy as np

from .models import (
    AnalysisSnapshot,
    BeatFrame,
    BeatRecord,
    DiagnosticFrame,
    ProtocolHealth,
    SampleFrame,
    SignalQuality,
)


class ProvenanceRecorder:
    """线程安全的溯源日志记录器。

    每条日志独立 CSV，首次写入时建表头。所有方法都是
    "只记录、不修改算法"，调用方传什么就记什么。
    """

    def __init__(self, session_dir: str):
        self._session_dir = session_dir
        self._lock = threading.RLock()
        self._files: dict[str, Any] = {}
        self._writers: dict[str, Any] = {}
        self._flushed = False
        self._closed = False

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def record_beat_provenance(self, row: dict[str, Any]) -> None:
        self._write_row("beat_provenance", row)

    def record_beat_detector_state(self, row: dict[str, Any]) -> None:
        self._write_row("beat_detector_state", row)

    def record_interval_candidate_trace(self, row: dict[str, Any]) -> None:
        self._write_row("interval_candidate_trace", row)

    def record_interval_artifact_trace(self, row: dict[str, Any]) -> None:
        self._write_row("interval_artifact_trace", row)

    def record_signal_input_trace(self, row: dict[str, Any]) -> None:
        self._write_row("signal_input_trace", row)

    def record_hrv_window_provenance(self, row: dict[str, Any]) -> None:
        self._write_row("hrv_window_provenance", row)

    def record_spectrum_5min_trace(self, row: dict[str, Any]) -> None:
        self._write_row("spectrum_5min_trace", row)

    def record_baseline_trace(self, row: dict[str, Any]) -> None:
        self._write_row("baseline_trace", row)

    def record_prototype_score_trace(self, row: dict[str, Any]) -> None:
        self._write_row("prototype_score_trace", row)

    def record_causality_trace(self, row: dict[str, Any]) -> None:
        self._write_row("causality_trace", row)

    def record_ui_explanation_trace(self, row: dict[str, Any]) -> None:
        self._write_row("ui_explanation_trace", row)

    def flush(self) -> None:
        with self._lock:
            for handle in self._files.values():
                handle.flush()
            self._flushed = True

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            for f in self._files.values():
                f.close()
            self._files.clear()
            self._writers.clear()
            self._flushed = True
            self._closed = True

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    def _path_for(self, name: str) -> str:
        return os.path.join(self._session_dir, f"{name}.csv")

    def _open_file(self, name: str) -> Any:
        path = self._path_for(name)
        f = open(path, "a", newline="", encoding="utf-8")
        self._files[name] = f
        self._writers[name] = csv.writer(f)
        return f

    def _write_row(self, name: str, row: dict[str, Any]) -> None:
        if not row:
            return
        with self._lock:
            if self._closed:
                return
            if name not in self._writers:
                self._open_file(name)
                self._writers[name].writerow(list(row.keys()))
            self._writers[name].writerow(
                [self._format(v) for v in row.values()]
            )

    @staticmethod
    def _format(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (int, float)):
            if isinstance(value, float):
                return f"{value:.6f}"
            return str(value)
        return str(value)


# ======================================================================
# 字段构建函数
# 每个函数从算法数据结构里提取字段，不修改任何算法逻辑。
# ======================================================================


def build_beat_provenance_row(
    beat: BeatRecord,
    firmware_match: BeatFrame | None,
    proposal: Any | None,
    prior_final_t_us: int | None,
    template_version: str = "unknown",
) -> dict[str, Any]:
    """从单个心搏构建 beat_provenance 行。

    关键字段：
      firmware_t_us      固件心搏时间（无匹配则为 0）
      waveform_t_us      波形峰时间（None 则为 0）
      final_t_us         最终提交时间
      timing_shift_ms    波形峰相对固件心搏的偏移
      no_firmware_match  1 = 该心搏没有固件匹配
      recovered          1 = 该心搏是恢复出来的
      waveform_score     原始波形评分
      peak_prominence    峰突出度（None 则为 0）
      peak_polarity      峰极性
      expected_rr_ms     预期 RR
      match_distance_ms  匹配距离（None 则为 0）
      recovery_reason    恢复原因（None 则为空）
      template_version   模板版本
    """
    firmware_t_us = (
        int(firmware_match.t_us) if firmware_match else 0
    )
    # WaveformPeakProposal 字段名是 t_us；外部某些调用方可能传 peak_t_us。
    proposal_t_us = (
        getattr(proposal, "t_us", None)
        or getattr(proposal, "peak_t_us", None)
    )
    waveform_t_us = int(proposal_t_us) if proposal_t_us else 0
    final_t_us = int(beat.t_us)
    timing_shift_ms = (
        (waveform_t_us - firmware_t_us) / 1000.0
        if firmware_t_us
        else 0.0
    )
    no_firmware_match = (
        1 if not firmware_match else 0
    )
    inserted_by_smoother = bool(beat.inserted_by_smoother)
    timing_recovered = bool(beat.timing_recovered)
    low_prominence_rescue = bool(beat.low_prominence_rescue)
    recovery_flags: list[str] = []
    if inserted_by_smoother:
        recovery_flags.append("sequence_rescued")
    if timing_recovered:
        recovery_flags.append("timing_recovered")
    if low_prominence_rescue:
        recovery_flags.append("low_prominence_rescue")
    recovery_reason = "+".join(recovery_flags)
    match_distance_ms = (
        abs(int(firmware_match.t_us) - waveform_t_us) / 1000.0
        if firmware_match and waveform_t_us
        else 0.0
    )
    return {
        "t_us": final_t_us,
        "firmware_t_us": firmware_t_us,
        "waveform_t_us": waveform_t_us,
        "final_t_us": final_t_us,
        "timing_shift_ms": timing_shift_ms,
        "timing_quality": float(getattr(beat, "timing_quality", 1.0) or 0.0),
        "detector_timing_quality": float(
            getattr(beat, "detector_timing_quality", 1.0) or 0.0
        ),
        "timing_provenance_quality": float(
            getattr(beat, "timing_provenance_quality", 1.0) or 0.0
        ),
        "timing_quality_reason": str(
            getattr(beat, "timing_quality_reason", "") or ""
        ),
        "firmware_alignment_available": int(
            bool(getattr(beat, "firmware_alignment_available", False))
        ),
        "firmware_alignment_quality": float(
            getattr(beat, "firmware_alignment_quality", 0.0) or 0.0
        ),
        "firmware_alignment_reason": str(
            getattr(beat, "firmware_alignment_reason", "") or ""
        ),
        "no_firmware_match": no_firmware_match,
        "inserted_by_smoother": int(inserted_by_smoother),
        "timing_recovered": int(timing_recovered),
        "low_prominence_rescue": int(low_prominence_rescue),
        "detector_support_count": int(
            getattr(beat, "detector_support_count", 0) or 0
        ),
        "detector_names": str(
            getattr(beat, "detector_names", "") or ""
        ),
        "detector_consensus": float(
            getattr(beat, "detector_consensus", 0.0) or 0.0
        ),
        "detector_time_spread_ms": float(
            getattr(beat, "detector_time_spread_ms", 0.0) or 0.0
        ),
        "single_detector": int(
            bool(getattr(beat, "single_detector", False))
        ),
        "sequence_rescued": int(
            bool(getattr(beat, "sequence_rescued", False))
        ),
        "firmware_unmatched": int(
            bool(getattr(beat, "firmware_unmatched", not firmware_match))
        ),
        "local_clipped": int(
            bool(getattr(beat, "local_clipped", False))
        ),
        "waveform_score": (
            float(proposal.waveform_score)
            if proposal
            else 0.0
        ),
        "peak_prominence": (
            float(getattr(proposal, "prominence", 0.0) or 0.0)
            if proposal
            else 0.0
        ),
        "peak_polarity": (
            int(getattr(proposal, "polarity", 1) or 1)
            if proposal
            else 1
        ),
        "expected_rr_ms": (
            float(getattr(proposal, "reference_rr_ms", 0.0) or 0.0)
            if proposal
            else 0.0
        ),
        "match_distance_ms": match_distance_ms,
        "recovery_reason": recovery_reason,
        "template_version": template_version,
    }


def build_interval_candidate_trace_row(
    decision: Any,
    observed_at_t_us: int,
) -> dict[str, Any]:
    """Serialize one mature detector candidate and its sequence decision."""
    return {
        "t_us": int(getattr(decision, "t_us", 0) or 0),
        "observed_at_t_us": int(observed_at_t_us),
        "candidate_index": int(getattr(decision, "index", 0) or 0),
        "support_count": int(getattr(decision, "support_count", 0) or 0),
        "detector_names": str(getattr(decision, "detector_names", "") or ""),
        "detector_score": float(getattr(decision, "detector_score", 0.0) or 0.0),
        "prominence": float(getattr(decision, "prominence", 0.0) or 0.0),
        "reference_rr_ms": float(getattr(decision, "reference_rr_ms", 0.0) or 0.0),
        "primary_t_us": int(getattr(decision, "primary_t_us", 0) or 0),
        "secondary_t_us": int(getattr(decision, "secondary_t_us", 0) or 0),
        "sequence_score": float(getattr(decision, "sequence_score", 0.0) or 0.0),
        "combined_score": float(getattr(decision, "combined_score", 0.0) or 0.0),
        "left_gap_ms": float(getattr(decision, "left_gap_ms", 0.0) or 0.0),
        "right_gap_ms": float(getattr(decision, "right_gap_ms", 0.0) or 0.0),
        "decision": str(getattr(decision, "decision", "") or ""),
        "reason": str(getattr(decision, "reason", "") or ""),
    }


def build_interval_artifact_trace_row(
    decision: Any,
    record: BeatRecord | None = None,
    revision: int = 1,
) -> dict[str, Any]:
    """Serialize the sequence-level decision for one raw RR interval."""
    return {
        "t_us": int(getattr(decision, "t_us", 0) or 0),
        "seq": int(getattr(decision, "seq", 0) or 0),
        "revision": int(revision),
        "rr_raw_ms": float(getattr(decision, "rr_raw_ms", 0.0) or 0.0),
        "reference_rr_ms": float(getattr(decision, "reference_rr_ms", 0.0) or 0.0),
        "robust_scale_ms": float(getattr(decision, "robust_scale_ms", 0.0) or 0.0),
        "artifact_class": str(getattr(decision, "artifact_class", "") or ""),
        "status": str(getattr(decision, "status", "") or ""),
        "resolved": int(bool(getattr(decision, "resolved", False))),
        "corrected_rr_ms": float(getattr(decision, "corrected_rr_ms", 0.0) or 0.0),
        "split_count": int(getattr(decision, "split_count", 1) or 1),
        "paired_index": int(getattr(decision, "paired_index", -1)),
        "paired_t_us": int(getattr(decision, "paired_t_us", 0) or 0),
        "confidence": float(getattr(decision, "confidence", 0.0) or 0.0),
        "metric_eligible": int(bool(getattr(record, "metric_eligible", False))) if record else 0,
        "detector_support_count": int(getattr(record, "detector_support_count", 0) or 0) if record else 0,
        "detector_consensus": float(getattr(record, "detector_consensus", 0.0) or 0.0) if record else 0.0,
        "local_clipped": int(bool(getattr(record, "local_clipped", False))) if record else 0,
        "reason": str(getattr(decision, "reason", "") or ""),
        "evidence": str(getattr(decision, "evidence", "") or ""),
    }


def build_beat_detector_state_row(
    detector: Any,
    firmware_beats: list[BeatFrame],
    last_committed_t_us: int,
    commit_until_t_us: int,
    reinit_reason: str | None = None,
) -> dict[str, Any]:
    """记录桌面 fixed-lag 波形检测器此刻的内部状态。

    IntervalCore / legacy corrector 都把实时状态放在 ``last_diagnostics`` 中；
    旧日志直接从 detector 本体读属性，因此大部分字段长期为 0。
    这里优先读取 last_diagnostics，并同时保留最近固件 RR 作为对照。
    """
    diag = getattr(detector, "last_diagnostics", detector)
    autocorr_rr = float(
        getattr(diag, "reference_rr_ms", 0.0) or 0.0
    )
    firmware_rr = 0.0
    recent = [
        beat
        for beat in firmware_beats
        if (
            beat.t_us <= commit_until_t_us
            and beat.t_us >= commit_until_t_us - 12_000_000
        )
    ]
    if len(recent) >= 2:
        import numpy as _np

        rrs = [
            (recent[i].t_us - recent[i - 1].t_us) / 1000.0
            for i in range(1, len(recent))
        ]
        firmware_rr = float(_np.median(rrs))

    detection_reason = reinit_reason or (
        getattr(detector, "_last_reinit_reason", "") or ""
    )
    return {
        "t_us": int(commit_until_t_us),
        "last_committed_t_us": int(last_committed_t_us),
        "polarity": int(getattr(diag, "polarity", 1) or 1),
        "template_correlation": float(
            getattr(diag, "autocorr_confidence", 0.0) or 0.0
        ),
        "autocorr_estimated_rr_ms": autocorr_rr,
        "firmware_expected_rr_ms": firmware_rr,
        "candidate_peak_count": int(
            getattr(diag, "candidate_count", 0) or 0
        ),
        "final_peak_count": int(
            getattr(diag, "selected_count", 0) or 0
        ),
        "inserted_peak_count": int(
            getattr(diag, "inserted_count", 0) or 0
        ),
        "firmware_matched_count": int(
            getattr(diag, "firmware_matched_count", 0) or 0
        ),
        "multiscale_peak_count": int(
            getattr(diag, "primary_count", 0) or 0
        ),
        "elgendi_peak_count": int(
            getattr(diag, "secondary_count", 0) or 0
        ),
        "dual_detector_peak_count": int(
            getattr(diag, "dual_detector_count", 0) or 0
        ),
        "single_detector_peak_count": int(
            getattr(diag, "single_detector_count", 0) or 0
        ),
        "detector_consensus_ratio": float(
            getattr(diag, "detector_consensus_ratio", 0.0) or 0.0
        ),
        "detector_time_spread_p95_ms": float(
            getattr(diag, "detector_time_spread_p95_ms", 0.0) or 0.0
        ),
        "stable_reference_rr_ms": float(
            getattr(diag, "stable_reference_rr_ms", 0.0) or 0.0
        ),
        "local_dual_rr_ms": float(
            getattr(diag, "local_dual_rr_ms", 0.0) or 0.0
        ),
        "local_dual_rr_robust_cv": float(
            getattr(diag, "local_dual_rr_robust_cv", 0.0) or 0.0
        ),
        "reference_update_reason": str(
            getattr(diag, "reference_update_reason", "") or ""
        ),
        "rejected_candidate_count": int(
            getattr(diag, "rejected_candidate_count", 0) or 0
        ),
        "long_gap_rescue_count": int(
            getattr(diag, "long_gap_rescue_count", 0) or 0
        ),
        "waveform_amplitude": float(
            getattr(diag, "waveform_amplitude", 0.0) or 0.0
        ),
        "commit_until_t_us": int(
            getattr(diag, "commit_until_t_us", commit_until_t_us) or commit_until_t_us
        ),
        "latest_sample_t_us": int(
            getattr(diag, "latest_sample_t_us", 0) or 0
        ),
        "reinit_reason": detection_reason,
    }


def build_signal_input_trace_row(
    samples: list[SampleFrame],
    detector: Any,
    signal_quality: SignalQuality,
    protocol_health: ProtocolHealth,
    diagnostic: DiagnosticFrame | None,
    window_t_us: int,
    adc_low: float = 0.0,
    adc_high: float = 1023.0,
) -> dict[str, Any]:
    """用最近约 5 秒原始输入记录传感器→算法第一现场。

    该日志专门区分三类退化：
    1. 原始 ADC 工作点/削底/佩戴状态变化；
    2. 设备时基或协议/队列异常；
    3. interval core 双检测器共识 / RR 参考先验自身退化。
    """
    import numpy as np

    if not samples:
        return {
            "t_us": int(window_t_us),
            "sample_count": 0,
        }

    raw = np.asarray([sample.raw for sample in samples], dtype=float)
    avg = np.asarray([sample.avg for sample in samples], dtype=float)
    filtered = np.asarray(
        [sample.filtered for sample in samples], dtype=float
    )
    flags = np.asarray([sample.flags for sample in samples], dtype=np.int64)
    detector_score = np.asarray(
        [sample.detector_score for sample in samples], dtype=float
    )
    expected_rr = np.asarray(
        [sample.expected_rr_ms for sample in samples], dtype=float
    )
    firmware_hr = np.asarray(
        [sample.hr_bpm for sample in samples], dtype=float
    )
    t_us = np.asarray([sample.t_us for sample in samples], dtype=np.int64)
    wear = (flags & 0x01) != 0
    clip_low = (raw <= adc_low) | ((flags & 0x02) != 0)
    clip_high = (raw >= adc_high) | ((flags & 0x04) != 0)

    wear_transitions = int(np.count_nonzero(wear[1:] != wear[:-1]))
    max_no_wear_run = 0
    current_run = 0
    for value in wear:
        if value:
            current_run = 0
        else:
            current_run += 1
            max_no_wear_run = max(max_no_wear_run, current_run)

    dt_ms = np.diff(t_us.astype(float)) / 1000.0
    positive_dt = dt_ms[dt_ms > 0]
    sample_period_ms = (
        float(np.median(positive_dt)) if positive_dt.size else 0.0
    )
    effective_rate = (
        1000.0 / sample_period_ms if sample_period_ms > 0 else 0.0
    )
    jitter_p95 = (
        float(
            np.percentile(
                np.abs(positive_dt - sample_period_ms),
                95,
            )
        )
        if positive_dt.size
        else 0.0
    )

    diag = getattr(detector, "last_diagnostics", detector)
    latest_diag = diagnostic

    def _p(values: np.ndarray, q: float) -> float:
        return float(np.percentile(values, q)) if values.size else 0.0

    def _slope_per_second(values: np.ndarray) -> float:
        if values.size < 3 or t_us.size != values.size:
            return 0.0
        seconds = (t_us.astype(float) - float(t_us[0])) / 1e6
        if seconds[-1] <= seconds[0]:
            return 0.0
        centered_t = seconds - float(np.mean(seconds))
        denominator = float(np.dot(centered_t, centered_t))
        if denominator <= 0:
            return 0.0
        centered_v = values - float(np.mean(values))
        return float(np.dot(centered_t, centered_v) / denominator)

    finite_rr = expected_rr[np.isfinite(expected_rr) & (expected_rr > 0)]
    finite_hr = firmware_hr[np.isfinite(firmware_hr) & (firmware_hr > 0)]

    return {
        "t_us": int(window_t_us),
        "window_start_t_us": int(t_us[0]),
        "window_end_t_us": int(t_us[-1]),
        "sample_count": int(len(samples)),
        "raw_min": float(np.min(raw)),
        "raw_p05": _p(raw, 5),
        "raw_p50": _p(raw, 50),
        "raw_p95": _p(raw, 95),
        "raw_max": float(np.max(raw)),
        "raw_slope_per_s": _slope_per_second(raw),
        "avg_p05": _p(avg, 5),
        "avg_p50": _p(avg, 50),
        "avg_p95": _p(avg, 95),
        "filtered_p05": _p(filtered, 5),
        "filtered_p50": _p(filtered, 50),
        "filtered_p95": _p(filtered, 95),
        "filtered_std": float(np.std(filtered)),
        "filtered_peak_to_peak": float(np.ptp(filtered)),
        "filtered_negative_ratio": float(np.mean(filtered < 0.0)),
        "filtered_slope_per_s": _slope_per_second(filtered),
        "clip_low_ratio": float(np.mean(clip_low)),
        "clip_high_ratio": float(np.mean(clip_high)),
        "wear_ratio": float(np.mean(wear)),
        "wear_transition_count": wear_transitions,
        "max_no_wear_run_ms": float(max_no_wear_run * sample_period_ms),
        "candidate_count": int(
            sum(1 for sample in samples if int(sample.peak) != 0)
        ),
        "detector_score_p50": _p(detector_score, 50),
        "expected_rr_ms_p50": (
            _p(finite_rr, 50) if finite_rr.size else 0.0
        ),
        "firmware_hr_bpm_p50": (
            _p(finite_hr, 50) if finite_hr.size else 0.0
        ),
        "firmware_hr_zero_ratio": float(
            np.mean(~np.isfinite(firmware_hr) | (firmware_hr <= 0))
        ),
        "effective_sample_rate_hz": float(
            getattr(signal_quality, "effective_sample_rate_hz", effective_rate)
            or effective_rate
        ),
        "source_sample_rate_hz": float(
            getattr(signal_quality, "source_sample_rate_hz", 0.0) or 0.0
        ),
        "sample_stride": int(
            getattr(signal_quality, "sample_stride", 1) or 1
        ),
        "sample_stride_confidence": float(
            getattr(signal_quality, "sample_stride_confidence", 0.0) or 0.0
        ),
        "sample_decimated": int(
            bool(getattr(signal_quality, "sample_decimated", False))
        ),
        "timing_jitter_p95_ms": float(
            getattr(signal_quality, "timing_jitter_p95_ms", jitter_p95)
        ),
        "sqi": float(signal_quality.sqi),
        "sqi_wear_ratio": float(signal_quality.wear_ratio),
        "sqi_clip_low_ratio": float(signal_quality.clip_low_ratio),
        "sqi_clip_high_ratio": float(signal_quality.clip_high_ratio),
        "transport_score": float(
            getattr(signal_quality, "transport_score", 0.0) or 0.0
        ),
        "transport_status": str(
            getattr(signal_quality, "transport_status", "") or ""
        ),
        "contact_score": float(
            getattr(signal_quality, "contact_score", 0.0) or 0.0
        ),
        "contact_status": str(
            getattr(signal_quality, "contact_status", "") or ""
        ),
        "protocol_error_ratio": float(protocol_health.error_ratio),
        "protocol_seq_gaps": int(protocol_health.sample_seq_gaps),
        "protocol_sample_stride": int(
            getattr(protocol_health, "sample_seq_stride", 1) or 1
        ),
        "protocol_stride_confidence": float(
            getattr(protocol_health, "sample_stride_confidence", 0.0) or 0.0
        ),
        "sample_drop_count": int(
            latest_diag.sample_drop_count if latest_diag else 0
        ),
        "sample_queue_depth": int(
            latest_diag.sample_queue_depth if latest_diag else 0
        ),
        "sample_queue_high_water": int(
            latest_diag.sample_queue_high_water if latest_diag else 0
        ),
        "corrector_reference_rr_ms": float(
            getattr(diag, "reference_rr_ms", 0.0) or 0.0
        ),
        "corrector_autocorr_confidence": float(
            getattr(diag, "autocorr_confidence", 0.0) or 0.0
        ),
        "corrector_polarity": int(getattr(diag, "polarity", 1) or 1),
        "corrector_candidate_count": int(
            getattr(diag, "candidate_count", 0) or 0
        ),
        "corrector_selected_count": int(
            getattr(diag, "selected_count", 0) or 0
        ),
        "corrector_inserted_count": int(
            getattr(diag, "inserted_count", 0) or 0
        ),
        "corrector_firmware_matched_count": int(
            getattr(diag, "firmware_matched_count", 0) or 0
        ),
        "interval_input_sample_rate_hz": float(
            getattr(diag, "input_sample_rate_hz", 0.0) or 0.0
        ),
        "interval_analysis_sample_rate_hz": float(
            getattr(diag, "analysis_sample_rate_hz", 0.0) or 0.0
        ),
        "interval_waveform_resampled": int(
            bool(getattr(diag, "waveform_resampled", False))
        ),
        "interval_input_dt_mean_ms": float(
            getattr(diag, "input_dt_mean_ms", 0.0) or 0.0
        ),
        "interval_input_dt_std_ms": float(
            getattr(diag, "input_dt_std_ms", 0.0) or 0.0
        ),
        "interval_input_jitter_p95_ms": float(
            getattr(diag, "input_jitter_p95_ms", 0.0) or 0.0
        ),
        "interval_resample_ratio": float(
            getattr(diag, "resample_ratio", 1.0) or 1.0
        ),
        "interval_resample_up": int(
            getattr(diag, "resample_up", 1) or 1
        ),
        "interval_resample_down": int(
            getattr(diag, "resample_down", 1) or 1
        ),
        "interval_regularization_backprojection_rms": float(
            getattr(diag, "regularization_backprojection_rms", 0.0) or 0.0
        ),
        "interval_resample_backprojection_rms": float(
            getattr(diag, "resample_backprojection_rms", 0.0) or 0.0
        ),
        "interval_resample_backprojection_max_abs": float(
            getattr(diag, "resample_backprojection_max_abs", 0.0) or 0.0
        ),
        "multiscale_peak_count": int(
            getattr(diag, "primary_count", 0) or 0
        ),
        "elgendi_peak_count": int(
            getattr(diag, "secondary_count", 0) or 0
        ),
        "dual_detector_peak_count": int(
            getattr(diag, "dual_detector_count", 0) or 0
        ),
        "single_detector_peak_count": int(
            getattr(diag, "single_detector_count", 0) or 0
        ),
        "detector_consensus_ratio": float(
            getattr(diag, "detector_consensus_ratio", 0.0) or 0.0
        ),
        "detector_time_spread_p95_ms": float(
            getattr(diag, "detector_time_spread_p95_ms", 0.0) or 0.0
        ),
        "stable_reference_rr_ms": float(
            getattr(diag, "stable_reference_rr_ms", 0.0) or 0.0
        ),
        "local_dual_rr_ms": float(
            getattr(diag, "local_dual_rr_ms", 0.0) or 0.0
        ),
        "local_dual_rr_robust_cv": float(
            getattr(diag, "local_dual_rr_robust_cv", 0.0) or 0.0
        ),
        "reference_update_reason": str(
            getattr(diag, "reference_update_reason", "") or ""
        ),
    }


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    import numpy as np
    return float(np.percentile(values, q))


def _rmssd(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    import numpy as np
    diffs = np.diff(values)
    return float(np.sqrt(np.mean(diffs ** 2)))


def _sdnn(values: list[float]) -> float:
    if not values:
        return 0.0
    import numpy as np
    return float(np.std(values, ddof=1))


def build_hrv_window_provenance_row(
    window_beats: list[BeatRecord],
    prior_beats: list[BeatRecord],
    firmware_beats: list[BeatFrame],
    window_t_us: int,
    unstable_timing_threshold: float = 0.62,
) -> dict[str, Any]:
    """Build one auditable short-window beat-integrity row.

    ``prior_beats`` is the immediately preceding non-overlapping window.  The
    delta fields make abrupt detector/firmware phase transitions visible without
    changing any HRV decision rule.
    """

    def _window_stats(beats: list[BeatRecord]) -> dict[str, Any]:
        if not beats:
            return {
                "beat_count": 0,
                "window_start_t_us": 0,
                "window_end_t_us": 0,
                "insertion_ratio": 0.0,
                "recovery_ratio": 0.0,
                "dual_detector_ratio": 0.0,
                "single_detector_ratio": 0.0,
                "detector_consensus_mean": 0.0,
                "detector_time_spread_p95_ms": 0.0,
                "sequence_rescue_ratio": 0.0,
                "local_clip_ratio": 0.0,
                "firmware_unmatched_ratio": 0.0,
                "firmware_match_ratio": 0.0,
                "timing_quality_mean": 0.0,
                "timing_quality_p05": 0.0,
                "timing_uncertainty_p95_ms": 0.0,
                "timing_degraded_ratio": 0.0,
                "firmware_alignment_quality_mean": 0.0,
                "firmware_alignment_available_ratio": 0.0,
                "offset_p50_ms": 0.0,
                "offset_p95_ms": 0.0,
                "offset_signed_p50_ms": 0.0,
                "adjacent_offset_change_p95_ms": 0.0,
                "final_rr_rmssd_ms": 0.0,
                "final_rr_sdnn_ms": 0.0,
            }

        final_rrs = [
            (beats[i].t_us - beats[i - 1].t_us) / 1000.0
            for i in range(1, len(beats))
        ]
        insertion_ratio = sum(bool(b.inserted_by_smoother) for b in beats) / len(beats)
        recovery_ratio = sum(bool(b.timing_recovered) for b in beats) / len(beats)
        interval_evidence = [
            b for b in beats
            if int(getattr(b, "detector_support_count", 0) or 0) > 0
        ]
        evidence_count = max(1, len(interval_evidence))
        dual_detector_ratio = (
            sum(int(getattr(b, "detector_support_count", 0) or 0) >= 2 for b in interval_evidence)
            / evidence_count
            if interval_evidence else 0.0
        )
        single_detector_ratio = (
            sum(
                bool(getattr(b, "single_detector", False))
                or int(getattr(b, "detector_support_count", 0) or 0) == 1
                for b in interval_evidence
            )
            / evidence_count
            if interval_evidence else 0.0
        )
        consensus_values = [
            float(getattr(b, "detector_consensus", 0.0) or 0.0)
            for b in interval_evidence
        ]
        spread_values = [
            float(getattr(b, "detector_time_spread_ms", 0.0) or 0.0)
            for b in interval_evidence
            if int(getattr(b, "detector_support_count", 0) or 0) >= 2
        ]
        sequence_rescue_ratio = (
            sum(bool(getattr(b, "sequence_rescued", False)) for b in interval_evidence)
            / evidence_count
            if interval_evidence else 0.0
        )
        local_clip_ratio = (
            sum(bool(getattr(b, "local_clipped", False)) for b in interval_evidence)
            / evidence_count
            if interval_evidence else 0.0
        )
        firmware_unmatched_ratio = (
            sum(bool(getattr(b, "firmware_unmatched", False)) for b in interval_evidence)
            / evidence_count
            if interval_evidence else 0.0
        )
        timing_quality_values = [
            float(getattr(b, "timing_quality", 1.0))
            for b in beats
            if np.isfinite(float(getattr(b, "timing_quality", 1.0)))
        ]
        timing_uncertainties = [
            float(getattr(b, "timing_uncertainty_ms", 0.0))
            for b in beats
            if np.isfinite(float(getattr(b, "timing_uncertainty_ms", 0.0)))
        ]
        firmware_alignment = [
            float(getattr(b, "firmware_alignment_quality", 0.0))
            for b in beats
            if bool(getattr(b, "firmware_alignment_available", False))
            and np.isfinite(float(getattr(b, "firmware_alignment_quality", 0.0)))
        ]
        offsets_signed = [
            float(b.timing_shift_ms)
            for b in beats
            if int(getattr(b, "matched_firmware_t_us", 0) or 0) > 0
        ]
        offsets_abs = [abs(value) for value in offsets_signed]
        adjacent_changes = [
            abs(offsets_signed[i] - offsets_signed[i - 1])
            for i in range(1, len(offsets_signed))
        ]

        return {
            "beat_count": len(beats),
            "window_start_t_us": int(beats[0].t_us),
            "window_end_t_us": int(beats[-1].t_us),
            "insertion_ratio": float(insertion_ratio),
            "recovery_ratio": float(recovery_ratio),
            "dual_detector_ratio": float(dual_detector_ratio),
            "single_detector_ratio": float(single_detector_ratio),
            "detector_consensus_mean": (
                float(sum(consensus_values) / len(consensus_values))
                if consensus_values else 0.0
            ),
            "detector_time_spread_p95_ms": _percentile(spread_values, 95),
            "sequence_rescue_ratio": float(sequence_rescue_ratio),
            "local_clip_ratio": float(local_clip_ratio),
            "firmware_unmatched_ratio": float(firmware_unmatched_ratio),
            "firmware_match_ratio": float(1.0 - firmware_unmatched_ratio)
            if interval_evidence else 0.0,
            "timing_quality_mean": (
                float(sum(timing_quality_values) / len(timing_quality_values))
                if timing_quality_values else 0.0
            ),
            "timing_quality_p05": _percentile(timing_quality_values, 5),
            "timing_uncertainty_p95_ms": _percentile(timing_uncertainties, 95),
            "timing_degraded_ratio": (
                sum(value < unstable_timing_threshold for value in timing_quality_values)
                / len(timing_quality_values)
                if timing_quality_values else 0.0
            ),
            "firmware_alignment_quality_mean": (
                float(sum(firmware_alignment) / len(firmware_alignment))
                if firmware_alignment else 0.0
            ),
            "firmware_alignment_available_ratio": (
                len(firmware_alignment) / len(beats) if beats else 0.0
            ),
            "offset_p50_ms": _percentile(offsets_abs, 50),
            "offset_p95_ms": _percentile(offsets_abs, 95),
            "offset_signed_p50_ms": _percentile(offsets_signed, 50),
            "adjacent_offset_change_p95_ms": _percentile(adjacent_changes, 95),
            "final_rr_rmssd_ms": _rmssd(final_rrs),
            "final_rr_sdnn_ms": _sdnn(final_rrs),
        }

    current = _window_stats(window_beats)
    previous = _window_stats(prior_beats)

    if window_beats:
        window_start = int(window_beats[0].t_us)
        window_end = int(window_beats[-1].t_us)
    else:
        window_start = 0
        window_end = 0

    firmware_window = [
        beat for beat in firmware_beats
        if window_start <= beat.t_us <= window_end
    ] if window_beats else []
    firmware_rrs = [
        (firmware_window[i].t_us - firmware_window[i - 1].t_us) / 1000.0
        for i in range(1, len(firmware_window))
    ]

    row = {
        "t_us": int(window_t_us),
        **current,
        "firmware_beat_count": len(firmware_window),
        "firmware_rr_rmssd_ms": _rmssd(firmware_rrs),
        "firmware_rr_sdnn_ms": _sdnn(firmware_rrs),
        "previous_beat_count": int(previous["beat_count"]),
        "previous_firmware_match_ratio": float(previous["firmware_match_ratio"]),
        "firmware_match_ratio_delta": float(
            current["firmware_match_ratio"] - previous["firmware_match_ratio"]
        ),
        "previous_offset_p95_ms": float(previous["offset_p95_ms"]),
        "offset_p95_delta_ms": float(
            current["offset_p95_ms"] - previous["offset_p95_ms"]
        ),
        "previous_timing_quality_mean": float(previous["timing_quality_mean"]),
        "timing_quality_mean_delta": float(
            current["timing_quality_mean"] - previous["timing_quality_mean"]
        ),
        "clipping_ratio": 0.0,
    }
    return row


def _dominant_freq(freqs: Any, psd: Any) -> float:
    if freqs is None or psd is None:
        return 0.0
    try:
        import numpy as np
        if len(freqs) == 0 or len(psd) == 0:
            return 0.0
        return float(freqs[int(np.argmax(psd))])
    except Exception:
        return 0.0


def build_spectrum_5min_trace_row(
    stats: dict[str, Any],
    window_t_us: int,
    rejection_reason: str | None = None,
) -> dict[str, Any]:
    """从 5 分钟频域统计构建 spectrum_5min_trace 行。

    关键字段：
      window_start_t_us / window_end_t_us  起止时间
      rr_count                               RR 数量
      welch_vlf_power / welch_lf_power /
      welch_hf_power / welch_lf_hf_ratio    Welch 各频带功率与比例
      lomb_vlf_ratio / lomb_lf_ratio /
      lomb_hf_ratio                          Lomb 各频带比例
      welch_peak_hz / lomb_peak_hz           各自主峰位置
      spectral_agreement                     两者差异
      pchip_vs_linear_diff                   PCHIP/线性插值差异
      quality                                5 分钟质量统计
      rejection_reason                       明确拒绝原因
    """
    freqs = stats.get("freqs")
    psd = stats.get("psd")
    lomb_freqs = stats.get("lomb_freqs")
    lomb = stats.get("lomb")
    return {
        "t_us": window_t_us,
        "window_start_t_us": int(stats.get("window_start_t_us", 0) or 0),
        "window_end_t_us": int(stats.get("window_end_t_us", 0) or 0),
        "rr_count": int(stats.get("rr_count", 0) or 0),
        "welch_vlf_power": float(stats.get("vlf", 0.0) or 0.0),
        "welch_lf_power": float(stats.get("lf", 0.0) or 0.0),
        "welch_hf_power": float(stats.get("hf", 0.0) or 0.0),
        "welch_lf_hf_ratio": float(stats.get("lf_hf", 0.0) or 0.0),
        "lomb_vlf_ratio": float(stats.get("lomb_vlf_ratio", 0.0) or 0.0),
        "lomb_lf_ratio": float(stats.get("lomb_lf_ratio", 0.0) or 0.0),
        "lomb_hf_ratio": float(stats.get("lomb_hf_ratio", 0.0) or 0.0),
        "welch_peak_hz": float(
            stats.get("welch_peak_hz", _dominant_freq(freqs, psd)) or 0.0
        ),
        "lomb_peak_hz": float(
            stats.get("lomb_peak_hz", _dominant_freq(lomb_freqs, lomb)) or 0.0
        ),
        "spectral_agreement": float(
            stats.get("spectral_agreement", 0.0) or 0.0
        ),
        "band_power_agreement": float(
            stats.get("band_power_agreement", 0.0) or 0.0
        ),
        "interpolation_agreement": float(
            stats.get("interpolation_agreement", 0.0) or 0.0
        ),
        "pchip_vs_linear_diff": float(
            stats.get("pchip_vs_linear_diff", 0.0) or 0.0
        ),
        "waveform_inserted_ratio": float(
            stats.get("waveform_inserted_ratio", 0.0) or 0.0
        ),
        "timing_recovered_ratio": float(
            stats.get("timing_recovered_ratio", 0.0) or 0.0
        ),
        "timing_shift_delta_p95_ms": float(
            stats.get("timing_shift_delta_p95_ms", 0.0) or 0.0
        ),
        "dual_detector_ratio": float(
            stats.get("dual_detector_ratio", 0.0) or 0.0
        ),
        "single_detector_ratio": float(
            stats.get("single_detector_ratio", 0.0) or 0.0
        ),
        "detector_consensus_mean": float(
            stats.get("detector_consensus_mean", 0.0) or 0.0
        ),
        "detector_time_spread_p95_ms": float(
            stats.get("detector_time_spread_p95_ms", 0.0) or 0.0
        ),
        "sequence_rescue_ratio": float(
            stats.get("sequence_rescue_ratio", 0.0) or 0.0
        ),
        "local_clip_ratio": float(
            stats.get("local_clip_ratio", 0.0) or 0.0
        ),
        "firmware_unmatched_ratio": float(
            stats.get("firmware_unmatched_ratio", 0.0) or 0.0
        ),
        "corrected_ratio": float(
            stats.get("corrected_ratio", 0.0) or 0.0
        ),
        "unresolved_suspect_ratio": float(
            stats.get("unresolved_suspect_ratio", 0.0) or 0.0
        ),
        "direct_interval_ratio": float(
            stats.get("direct_interval_ratio", 0.0) or 0.0
        ),
        "usable_interval_ratio": float(
            stats.get("usable_interval_ratio", 0.0) or 0.0
        ),
        "transport_status": str(stats.get("transport_status", "") or ""),
        "contact_status": str(stats.get("contact_status", "") or ""),
        "quality": str(stats.get("quality", "") or ""),
        "rejection_reason": rejection_reason or "",
    }


def build_baseline_trace_row(
    baseline: dict,
    previous: dict | None,
    included_window_t_us: int,
    source: str = "VALID",
) -> dict[str, Any]:
    """记录真实 research baseline 的参照窗口与稳健中心/尺度。"""
    rows = list(baseline.get("rows", []) or [])
    features = baseline.get("features", {}) or {}
    previous_features = (
        previous.get("features", {}) or {}
        if isinstance(previous, dict)
        else {}
    )
    reference_start = int(rows[0].get("t_us", 0)) if rows else 0
    reference_end = int(rows[-1].get("t_us", 0)) if rows else 0

    result: dict[str, Any] = {
        "t_us": int(included_window_t_us),
        # 没有显式 version 时用最后一个参照窗口时间作为稳定版本号。
        "baseline_version": reference_end,
        "baseline_ready": 1 if baseline.get("ready") else 0,
        "reference_window_count": len(rows),
        "reference_start_t_us": reference_start,
        "reference_end_t_us": reference_end,
        "span_seconds": float(baseline.get("span_seconds", 0.0) or 0.0),
        "included_window_t_us": int(included_window_t_us),
        "source": source,
        "reason": str(baseline.get("reason", "") or ""),
    }

    feature_names = (
        "hr_bpm",
        "rmssd_ms",
        "total_power_ms2",
        "vlf_ms2",
        "lf_ms2",
        "hf_ms2",
        "lf_nu",
        "hf_nu",
        "lf_hf",
        "median_frequency_hz",
        "resonance_share",
        "lf_peak_frequency_hz",
        "lf_peak_prominence_ratio",
    )
    for name in feature_names:
        feature = features.get(name, {}) or {}
        previous_feature = previous_features.get(name, {}) or {}
        median = float(feature.get("median", 0.0) or 0.0)
        scale = float(feature.get("scale", 0.0) or 0.0)
        previous_median = float(
            previous_feature.get("median", median) or median
        )
        result[f"median_{name}"] = median
        result[f"scale_{name}"] = scale
        result[f"delta_median_{name}"] = median - previous_median
        result[f"count_{name}"] = int(feature.get("count", 0) or 0)

    return result


# 门槛常量，与 research_prototypes._machine_state 保持一致。
# 只读，不改算法。
_MATCH_THRESHOLD_ACTIVE = 0.70
_MATCH_THRESHOLD_CANDIDATE = 0.70


def _parse_no_match_reason(
    evidence: list[str],
    final_score: float,
    quality: float,
    baseline_ready: bool,
    threshold: float,
) -> str:
    """从 _score_row 的 evidence 与最终得分解析 NO_MATCH 原因。

    优先级（与 research_prototypes.evaluate_research_state 一致）：
      1. BASELINE_NOT_READY —— 个人基线尚未建立
      2. DATA_UNAVAILABLE   —— 当前证据不可用于比较
      3. HF_MISSING         —— 高频带缺失
      4. SCORE_BELOW_THRESHOLD —— 相似度本身低于门槛
      5. NO_MATCH           —— 其他未分类原因

    v0.4.2 起 quality 是独立证据等级，不再乘进相似度，因此不存在
    0.65/0.68 质量系数把 0.70 匹配门槛数学封死的问题。
    """
    ev_text = " ".join(str(e) for e in evidence)
    if not baseline_ready:
        return "NO_MATCH: BASELINE_NOT_READY"
    if quality <= 0.0:
        return "NO_MATCH: DATA_UNAVAILABLE"
    if "hf" in ev_text.lower() and "missing" in ev_text.lower():
        return "NO_MATCH: HF_MISSING"
    if final_score < threshold:
        return (
            "NO_MATCH: SCORE_BELOW_THRESHOLD %.2f < %.2f"
            % (final_score, threshold)
        )
    return "NO_MATCH"


def build_prototype_score_trace_row(
    prototype_id: str,
    row: dict[str, Any],
    baseline: dict,
    score: float,
    evidence: list[str],
    quality: float,
    threshold: float,
    baseline_ready: bool,
    match: dict | None,
    temporal: dict | None = None,
) -> dict[str, Any]:
    """记录原型评分的输入存在性、基线偏差和未匹配原因。"""
    features = baseline.get("features", {}) or {}
    no_match_reason = _parse_no_match_reason(
        evidence,
        score,
        quality,
        baseline_ready,
        threshold,
    )
    explicit_reason = str((temporal or {}).get("no_match_reason", "") or "")
    if explicit_reason:
        no_match_reason = explicit_reason
    if match is not None:
        no_match_reason = ""

    result_row: dict[str, Any] = {
        "t_us": int(row.get("t_us", row.get("t_end", row.get("t_start", 0))) or 0),
        "prototype_id": prototype_id,
        "quality_coefficient": float(quality),
        "score_before_quality": float(score) if score == score else 0.0,
        "final_score": float(score) if score == score else float("nan"),
        "threshold": float(threshold),
        "baseline_ready": 1 if baseline_ready else 0,
        "evidence": " | ".join(str(item) for item in evidence),
        "no_match_reason": no_match_reason,
        "raw_score": float((temporal or {}).get("raw_score", score) or 0.0),
        "case_similarity": float((temporal or {}).get("case_similarity", score) or 0.0),
        "match_confidence": float((temporal or {}).get("match_confidence", 0.0) or 0.0),
        "rank_score": float((temporal or {}).get("rank_score", 0.0) or 0.0),
        "state_strength": float((temporal or {}).get("state_strength", (temporal or {}).get("state_score", score)) or 0.0),
        "evidence_score": float((temporal or {}).get("evidence_score", score) or 0.0),
        "state_score": float((temporal or {}).get("state_score", score) or 0.0),
        "baseline_maturity": str((temporal or {}).get("baseline_maturity", "NONE") or "NONE"),
        "temporal_ready": 1 if bool((temporal or {}).get("temporal_ready", False)) else 0,
        "observation_minutes": float((temporal or {}).get("observation_minutes", 0.0) or 0.0),
        "observed_span_minutes": float((temporal or {}).get("observed_span_minutes", 0.0) or 0.0),
        "coverage_ratio": float((temporal or {}).get("coverage_ratio", 0.0) or 0.0),
        "persistence_ratio": float((temporal or {}).get("persistence_ratio", 0.0) or 0.0),
        "stability_score": float((temporal or {}).get("stability_score", 0.0) or 0.0),
    }

    log_features = {
        "rmssd_ms",
        "total_power_ms2",
        "vlf_ms2",
        "lf_ms2",
        "hf_ms2",
        "lf_hf",
        "lf_peak_prominence_ratio",
    }
    feature_names = (
        "hr_bpm",
        "rmssd_ms",
        "total_power_ms2",
        "vlf_ms2",
        "lf_ms2",
        "hf_ms2",
        "lf_nu",
        "hf_nu",
        "lf_hf",
        "median_frequency_hz",
        "resonance_share",
        "lf_peak_frequency_hz",
        "lf_peak_prominence_ratio",
    )

    import math

    for name in feature_names:
        raw = row.get(name)
        present = False
        numeric = 0.0
        try:
            numeric = float(raw)
            present = math.isfinite(numeric)
        except (TypeError, ValueError):
            present = False

        feature = features.get(name, {}) or {}
        median = float(feature.get("median", 0.0) or 0.0)
        scale = float(feature.get("scale", 0.0) or 0.0)
        transformed = (
            math.log(max(numeric, 1e-9))
            if present and name in log_features
            else numeric
        )
        z_value = (
            (transformed - median) / scale
            if present and scale > 0
            else 0.0
        )
        result_row[f"input_present_{name}"] = 1 if present else 0
        result_row[f"raw_{name}"] = numeric if present else 0.0
        result_row[f"baseline_median_{name}"] = median
        result_row[f"baseline_scale_{name}"] = scale
        result_row[f"z_{name}"] = float(z_value)

    return result_row


def build_causality_trace_row(
    score_t_us: int,
    latest_data_t_us: int,
    baseline_version: int,
) -> dict[str, Any]:
    """从历史评分构建 causality_trace 行。

    关键字段：
      score_t_us          当前评分时间
      latest_data_t_us    使用到的最晚数据时间
      baseline_version    基线版本
      uses_future_data    1 = 评分时间早于最晚数据时间
    """
    return {
        "t_us": score_t_us,
        "score_t_us": score_t_us,
        "latest_data_t_us": latest_data_t_us,
        "baseline_version": int(baseline_version),
        "uses_future_data": 1 if latest_data_t_us > score_t_us else 0,
    }


def build_ui_explanation_trace_row(
    state_t_us: int,
    state_name: str,
    match: dict | None,
    user_text: str,
    trigger: str,
    reliability: str,
) -> dict[str, Any]:
    """从 UI 文案更新构建 ui_explanation_trace 行。

    关键字段：
      state_t_us           状态时间戳
      state                底层状态名
      user_text            采用的用户文案
      trigger              触发依据
      data_reliability     数据可靠等级
      match_score          匹配得分（None 则为 0）
      match_prototype      匹配原型（None 则为空）
    """
    match_score = 0.0
    match_proto = ""
    if match is not None:
        match_score = float(match.get("score", 0.0) or 0.0)
        match_proto = str(match.get("prototype_id", "") or "")
    return {
        "t_us": state_t_us,
        "state": state_name,
        "user_text": user_text,
        "trigger": trigger,
        "data_reliability": reliability,
        "match_score": match_score,
        "match_prototype": match_proto,
    }