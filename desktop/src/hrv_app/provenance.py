"""
溯源日志（provenance trace）。

现有 SessionRecorder 只回答"队列有没有掉数据、串口有没有错误、最后的心搏是什么、
最后的 HRV 是多少"。它回答不了"算法为什么把 A 变成 B"。

本模块补齐 8 条独立 CSV，全部只记录、不改变任何算法：

  beat_provenance        每个心搏      固件心搏时间 / 波形峰时间 / 最终时间 / 偏移 /
                                  是否无固件匹配 / 是否恢复 / 原始波形评分 / 峰突出度 /
                                  峰极性 / 预期 RR / 匹配距离 / 恢复原因 / 模板版本
  beat_detector_state    每 5-10 秒   当前极性 / 模板相关度 / 自相关估计 RR /
                                  固件预期 RR / 候选峰数量 / 最终峰数量 /
                                  重新初始化原因
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
    BeatFrame,
    BeatRecord,
    AnalysisSnapshot,
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

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def record_beat_provenance(self, row: dict[str, Any]) -> None:
        self._write_row("beat_provenance", row)

    def record_beat_detector_state(self, row: dict[str, Any]) -> None:
        self._write_row("beat_detector_state", row)

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
            for w in self._writers.values():
                w.flush()

    def close(self) -> None:
        with self._lock:
            for f in self._files.values():
                f.close()
            self._files.clear()
            self._writers.clear()
            self._flushed = True

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
    recovered = (
        1 if beat.inserted_by_smoother else 0
    )
    recovery_reason = (
        beat.recovery_reason
        if hasattr(beat, "recovery_reason")
        else None
    )
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
        "recovered": recovered,
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
        "recovery_reason": recovery_reason or "",
        "template_version": template_version,
    }


def build_beat_detector_state_row(
    detector: Any,
    firmware_beats: list[BeatFrame],
    last_committed_t_us: int,
    commit_until_t_us: int,
    reinit_reason: str | None = None,
) -> dict[str, Any]:
    """从检测器当前状态构建 beat_detector_state 行。

    关键字段：
      polarity                当前极性
      template_correlation    模板相关度（autocorr_confidence）
      autocorr_estimated_rr_ms 自相关估计 RR
      firmware_expected_rr_ms  固件预期 RR
      candidate_peak_count    候选峰数量
      final_peak_count        最终峰数量
      reinit_reason           重新初始化原因（None 则为空）
    """
    autocorr_rr = (
        float(getattr(detector, "autocorr_rr_ms", 0.0) or 0.0)
    )
    firmware_rr = 0.0
    if firmware_beats:
        recent = [
            b
            for b in firmware_beats
            if b.t_us <= commit_until_t_us
        ]
        if len(recent) >= 2:
            rrs = [
                (recent[i].t_us - recent[i - 1].t_us) / 1000.0
                for i in range(1, len(recent))
            ]
            import numpy as _np
            firmware_rr = float(_np.median(rrs))
    # 若外部传入了原因（wear 丢失），优先用；否则读检测器内部字段
    detection_reason = reinit_reason or (
        getattr(detector, "_last_reinit_reason", "") or ""
    )
    return {
        "t_us": commit_until_t_us,
        "polarity": int(getattr(detector, "locked_polarity", 1) or 1),
        "template_correlation": float(
            getattr(detector, "autocorr_confidence", 0.0) or 0.0
        ),
        "autocorr_estimated_rr_ms": autocorr_rr,
        "firmware_expected_rr_ms": firmware_rr,
        "candidate_peak_count": int(
            getattr(detector, "candidate_count", 0) or 0
        ),
        "final_peak_count": int(
            getattr(detector, "accepted_count", 0) or 0
        ),
        "reinit_reason": detection_reason,
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
    firmware_rrs = [
        (firmware_beats[i].t_us - firmware_beats[i - 1].t_us) / 1000.0
        for i in range(1, len(firmware_beats))
    ]
    insertion_ratio = (
        sum(1 for b in window_beats if b.inserted_by_smoother)
        / max(1, len(window_beats))
    )
    recovery_ratio = (
        sum(
            1
            for b in window_beats
            if getattr(b, "recovery_reason", None)
        )
        / max(1, len(window_beats))
    )
    offsets = [
        abs(
            (int(b.t_us) - int(getattr(b, "firmware_t_us", b.t_us)))
        )
        / 1000.0
        for b in window_beats
        if getattr(b, "firmware_t_us", None)
    ]
    adjacent_changes = [
        abs(offsets[i] - offsets[i - 1])
        for i in range(1, len(offsets))
    ]
    clipping_ratio = (
        sum(1 for b in window_beats if b.low_prominence_rescue)
        / max(1, len(window_beats))
    )
    return {
        "t_us": window_t_us,
        "window_start_t_us": window_start,
        "window_end_t_us": window_end,
        "beat_count": len(window_beats),
        "firmware_beat_count": len(firmware_beats),
        "insertion_ratio": float(insertion_ratio),
        "recovery_ratio": float(recovery_ratio),
        "offset_p50_ms": _percentile(offsets, 50),
        "offset_p95_ms": _percentile(offsets, 95),
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
        "welch_peak_hz": _dominant_freq(freqs, psd),
        "lomb_peak_hz": _dominant_freq(lomb_freqs, lomb),
        "spectral_agreement": float(
            stats.get("spectral_agreement", 0.0) or 0.0
        ),
        "pchip_vs_linear_diff": float(
            stats.get("pchip_vs_linear_diff", 0.0) or 0.0
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
    """从基线构建 baseline_trace 行。

    关键字段：
      baseline_version     基线版本
      included_window_t_us 纳入的窗口时间
      center_*_vlf / center_*_lf / center_*_hf / center_*_rr_ms
                           各指标中心值
      scale_*_vlf / scale_*_lf / scale_*_hf / scale_*_rr_ms
                           各指标波动尺度
      delta_*_vlf / delta_*_lf / delta_*_hf / delta_*_rr_ms
                           与上一版差异
      source                VALID/LIMITED 来源
    """
    metrics = baseline.get("metrics", {})
    prev_metrics = (
        previous.get("metrics", {}) if previous is not None else None
    )
    row: dict[str, Any] = {
        "t_us": included_window_t_us,
        "baseline_version": int(baseline.get("version", 0)),
        "included_window_t_us": included_window_t_us,
        "source": source,
    }
    for key in ("vlf", "lf", "hf", "rr_ms"):
        center = float(metrics.get(f"center_{key}", 0.0) or 0.0)
        scale = float(metrics.get(f"scale_{key}", 0.0) or 0.0)
        row[f"center_{key}"] = center
        row[f"scale_{key}"] = scale
        if prev_metrics is not None:
            prev_center = float(
                prev_metrics.get(f"center_{key}", 0.0) or 0.0
            )
            row[f"delta_{key}"] = center - prev_center
        else:
            row[f"delta_{key}"] = 0.0
    return row


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
    """从单个原型评分构建 prototype_score_trace 行。

    每个字段都回答"为什么这个原型没有匹配"：
      input_present_<key>    每个输入值是否存在（1/0）
      raw_<key>              原始值
      deviation_<key>        相对近期常态的偏差
      z_<key>                各评分分项
      quality_coefficient    质量系数
      score_before_quality   乘质量前得分
      final_score            最终得分
      threshold              门槛
      no_match_reason        明确的未匹配原因
    """
    metrics = baseline.get("metrics", {})
    evidence_text = " ".join(str(e) for e in evidence)
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
        "t_us": int(row.get("t_end", row.get("t_start", 0)) or 0),
        "prototype_id": prototype_id,
        "quality_coefficient": float(quality),
        "score_before_quality": float(score / quality)
        if quality > 0
        else 0.0,
        "final_score": float(score),
        "threshold": float(threshold),
        "baseline_ready": 1 if baseline_ready else 0,
        "no_match_reason": no_match_reason,
    }
    for key in ("vlf", "lf", "hf", "rr_ms"):
        raw_key = f"raw_{key}"
        dev_key = f"deviation_{key}"
        z_key = f"z_{key}"
        present_key = f"input_present_{key}"
        raw = row.get(raw_key)
        center = float(getattr(metrics, f"center_{key}", 0.0) or 0.0)
        scale = float(getattr(metrics, f"scale_{key}", 0.0) or 0.0)
        result_row[present_key] = 1 if raw is not None else 0
        result_row[raw_key] = float(raw) if raw is not None else 0.0
        result_row[dev_key] = (
            (float(raw) - center) / scale
            if raw is not None and scale > 0
            else 0.0
        )
        result_row[z_key] = float(result_row[dev_key])
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