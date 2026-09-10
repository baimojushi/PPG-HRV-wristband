"""
溯源日志（provenance trace）。

现有 SessionRecorder 只回答"队列有没有掉数据、串口有没有错误、最后的心搏是什么、
最后的 HRV 是多少"。它回答不了"算法为什么把 A 变成 B"。

本模块补齐 9 条独立 CSV，全部只记录、不改变任何算法：

  beat_provenance        每个心搏      固件心搏时间 / 波形峰时间 / 最终时间 / 偏移 /
                                  是否无固件匹配 / 是否恢复 / 原始波形评分 / 峰突出度 /
                                  峰极性 / 预期 RR / 匹配距离 / 恢复原因 / 模板版本
  beat_detector_state    每 5-10 秒   当前极性 / 模板相关度 / 自相关估计 RR /
                                  固件预期 RR / 候选峰数量 / 最终峰数量 /
                                  重新初始化原因
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
                                  各评分分项 / 质量系数 / 乘质量前得分 /
                                  最终得分 / 门槛 / 未匹配原因
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
        recovery_flags.append("waveform_inserted")
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
        "no_firmware_match": no_firmware_match,
        "inserted_by_smoother": int(inserted_by_smoother),
        "timing_recovered": int(timing_recovered),
        "low_prominence_rescue": int(low_prominence_rescue),
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


def build_beat_detector_state_row(
    detector: Any,
    firmware_beats: list[BeatFrame],
    last_committed_t_us: int,
    commit_until_t_us: int,
    reinit_reason: str | None = None,
) -> dict[str, Any]:
    """记录桌面 fixed-lag 波形检测器此刻的内部状态。

    FixedLagWaveformCorrector 把实时状态放在 ``last_diagnostics`` 中；
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
    3. fixed-lag 自相关与匹配器自身退化。
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
        "avg_p05": _p(avg, 5),
        "avg_p50": _p(avg, 50),
        "avg_p95": _p(avg, 95),
        "filtered_p05": _p(filtered, 5),
        "filtered_p50": _p(filtered, 50),
        "filtered_p95": _p(filtered, 95),
        "filtered_std": float(np.std(filtered)),
        "filtered_peak_to_peak": float(np.ptp(filtered)),
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
        "effective_sample_rate_hz": effective_rate,
        "timing_jitter_p95_ms": jitter_p95,
        "sqi": float(signal_quality.sqi),
        "sqi_wear_ratio": float(signal_quality.wear_ratio),
        "sqi_clip_low_ratio": float(signal_quality.clip_low_ratio),
        "sqi_clip_high_ratio": float(signal_quality.clip_high_ratio),
        "protocol_error_ratio": float(protocol_health.error_ratio),
        "protocol_seq_gaps": int(protocol_health.sample_seq_gaps),
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
) -> dict[str, Any]:
    """从 20 秒窗口的心搏构建 hrv_window_provenance 行。

    关键字段：
      window_start_t_us / window_end_t_us  窗口起止
      beat_count                            窗口内最终心搏数
      firmware_beat_count                   窗口内固件心搏数
      insertion_ratio                       补搏比例
      recovery_ratio                        恢复比例
      offset_p50_ms / offset_p95_ms         偏移 p50/p95
      adjacent_offset_change_p95_ms        相邻偏移变化 p95
      firmware_rr_rmssd_ms / firmware_rr_sdnn_ms
      final_rr_rmssd_ms / final_rr_sdnn_ms
      clipping_ratio                        削底比例
    """
    if not window_beats:
        return {
            "t_us": window_t_us,
            "window_start_t_us": 0,
            "window_end_t_us": 0,
            "beat_count": 0,
            "firmware_beat_count": 0,
            "insertion_ratio": 0.0,
            "recovery_ratio": 0.0,
            "offset_p50_ms": 0.0,
            "offset_p95_ms": 0.0,
            "offset_signed_p50_ms": 0.0,
            "adjacent_offset_change_p95_ms": 0.0,
            "firmware_rr_rmssd_ms": 0.0,
            "firmware_rr_sdnn_ms": 0.0,
            "final_rr_rmssd_ms": 0.0,
            "final_rr_sdnn_ms": 0.0,
            "clipping_ratio": 0.0,
        }
    window_start = int(window_beats[0].t_us)
    window_end = int(window_beats[-1].t_us)
    final_rrs = [
        (window_beats[i].t_us - window_beats[i - 1].t_us) / 1000.0
        for i in range(1, len(window_beats))
    ]
    firmware_window = [
        beat
        for beat in firmware_beats
        if window_start <= beat.t_us <= window_end
    ]
    firmware_rrs = [
        (firmware_window[i].t_us - firmware_window[i - 1].t_us) / 1000.0
        for i in range(1, len(firmware_window))
    ]
    insertion_ratio = (
        sum(1 for b in window_beats if b.inserted_by_smoother)
        / max(1, len(window_beats))
    )
    recovery_ratio = (
        sum(1 for b in window_beats if bool(b.timing_recovered))
        / max(1, len(window_beats))
    )
    offsets_signed = [
        float(b.timing_shift_ms)
        for b in window_beats
        if int(getattr(b, "matched_firmware_t_us", 0) or 0) > 0
    ]
    offsets_abs = [abs(value) for value in offsets_signed]
    adjacent_changes = [
        abs(offsets_signed[i] - offsets_signed[i - 1])
        for i in range(1, len(offsets_signed))
    ]
    # 原始 ADC 削底由 signal_input_trace / SignalQuality 记录；
    # low_prominence_rescue 不是削底，不能再借它冒充 clipping_ratio。
    clipping_ratio = 0.0
    return {
        "t_us": window_t_us,
        "window_start_t_us": window_start,
        "window_end_t_us": window_end,
        "beat_count": len(window_beats),
        "firmware_beat_count": len(firmware_window),
        "insertion_ratio": float(insertion_ratio),
        "recovery_ratio": float(recovery_ratio),
        # 兼容旧列名：offset_p50/p95 继续表示绝对偏移；另存 signed 中位数。
        "offset_p50_ms": _percentile(offsets_abs, 50),
        "offset_p95_ms": _percentile(offsets_abs, 95),
        "offset_signed_p50_ms": _percentile(offsets_signed, 50),
        "adjacent_offset_change_p95_ms": _percentile(
            adjacent_changes, 95
        ),
        "firmware_rr_rmssd_ms": _rmssd(firmware_rrs),
        "firmware_rr_sdnn_ms": _sdnn(firmware_rrs),
        "final_rr_rmssd_ms": _rmssd(final_rrs),
        "final_rr_sdnn_ms": _sdnn(final_rrs),
        "clipping_ratio": float(clipping_ratio),
    }


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
      1. QUALITY_CEILING   —— 质量系数封顶，乘质量前得分够不到门槛
      2. BASELINE_NOT_READY —— 个人基线尚未建立
      3. HF_MISSING        —— 高频带缺失
      4. SCORE_BELOW_THRESHOLD —— 得分本身低于门槛
      5. NO_MATCH          —— 其他未分类原因
    """
    ev_text = " ".join(str(e) for e in evidence)
    if not baseline_ready:
        return "NO_MATCH: BASELINE_NOT_READY"
    if quality <= 0.0:
        return "NO_MATCH: QUALITY_CEILING 0.00 < %.2f" % threshold
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
    if match is not None:
        no_match_reason = ""

    result_row: dict[str, Any] = {
        "t_us": int(row.get("t_us", row.get("t_end", row.get("t_start", 0))) or 0),
        "prototype_id": prototype_id,
        "quality_coefficient": float(quality),
        "score_before_quality": float(score / quality)
        if quality > 0 and score == score
        else 0.0,
        "final_score": float(score) if score == score else float("nan"),
        "threshold": float(threshold),
        "baseline_ready": 1 if baseline_ready else 0,
        "evidence": " | ".join(str(item) for item in evidence),
        "no_match_reason": no_match_reason,
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