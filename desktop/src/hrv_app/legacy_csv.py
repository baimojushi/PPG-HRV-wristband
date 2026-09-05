from __future__ import annotations

from pathlib import Path
from typing import Callable
import pandas as pd
import numpy as np

from .config import AnalysisConfig
from .engine import AnalysisEngine
from .models import BeatFrame, SampleFrame
from .adaptive_detector import AdaptivePPGDetector


def detect_encoding(path: Path) -> str:
    """历史中文 CSV 常见 GB18030；新文件统一 UTF-8。"""
    for encoding in ("utf-8-sig", "gb18030", "gbk", "latin1"):
        try:
            with path.open("r", encoding=encoding) as handle:
                handle.readline()
            return encoding
        except UnicodeDecodeError:
            continue
    return "latin1"


def _column_map(columns: list[str]) -> dict[str, str]:
    names = set(columns)

    # 新 samples.csv 格式。
    if {"seq", "t_us", "raw", "avg", "filtered", "peak", "hr_bpm"}.issubset(names):
        return {
            "seq": "seq",
            "t_us": "t_us",
            "raw": "raw",
            "avg": "avg",
            "filtered": "filtered",
            "peak": "peak",
            "hr": "hr_bpm",
            "detector_score": (
                "detector_score"
                if "detector_score" in names
                else ""
            ),
            "expected_rr_ms": (
                "expected_rr_ms"
                if "expected_rr_ms" in names
                else ""
            ),
            "flags": "flags" if "flags" in names else "",
        }

    # 原 record.csv：Channel 1...Channel 12。
    if {"Channel 1", "Channel 2", "Channel 3", "Channel 4", "Channel 5"}.issubset(names):
        return {
            "seq": "",
            "t_us": "",
            "raw": "Channel 1",
            "avg": "Channel 2",
            "filtered": "Channel 3",
            "peak": "Channel 4",
            "hr": "Channel 5",
            "detector_score": "",
            "expected_rr_ms": "",
            "flags": "",
        }

    # 中文历史导出。
    if {"原始数据", "中值滤波", "高斯滤波", "心跳", "心率"}.issubset(names):
        return {
            "seq": "",
            "t_us": "",
            "raw": "原始数据",
            "avg": "中值滤波",
            "filtered": "高斯滤波",
            "peak": "心跳",
            "hr": "心率",
            "detector_score": "",
            "expected_rr_ms": "",
            "flags": "",
        }

    raise ValueError(
        "无法识别 CSV 列。需要新 samples.csv、Channel 1... 或中文历史列名。"
    )


def load_csv_into_engine(
    path: str | Path,
    engine: AnalysisEngine,
    progress_callback: Callable[[float], None] | None = None,
) -> None:
    """
    将历史 CSV 回放到统一 AnalysisEngine。

    旧 CSV 的 timestamp 只有秒级或为 0，不能用于 RR 精确时基。
    因此旧格式按固定 125 Hz 用“行号 / 125”重建采样时间；
    新格式优先使用固件 `seq + t_us`。
    """
    path = Path(path)
    cfg = engine.config
    encoding = detect_encoding(path)

    # 只为进度条获取文件大小，不预读整表。
    total_bytes = max(path.stat().st_size, 1)
    processed_rows = 0

    # v0.3.0：历史 CSV 直接用 filtered PPG 重跑动态检测器。
    # 旧 peak/HR 只作为历史原始列保留，不参与新的 Accepted Beat 判定。
    detector = AdaptivePPGDetector(
        sample_rate_hz=cfg.sample_rate_hz,
        legacy_peak_factor=cfg.detector_legacy_peak_factor,
    )

    engine.reset()

    reader = pd.read_csv(
        path,
        encoding=encoding,
        chunksize=50000,
        low_memory=False,
    )

    mapping: dict[str, str] | None = None

    for chunk in reader:
        if mapping is None:
            mapping = _column_map(list(chunk.columns))

        n = len(chunk)

        raw = pd.to_numeric(chunk[mapping["raw"]], errors="coerce").fillna(0).to_numpy(float)
        avg = pd.to_numeric(chunk[mapping["avg"]], errors="coerce").fillna(0).to_numpy(float)
        filtered = pd.to_numeric(chunk[mapping["filtered"]], errors="coerce").fillna(0).to_numpy(float)
        peak = pd.to_numeric(chunk[mapping["peak"]], errors="coerce").fillna(0).to_numpy(float)
        hr = pd.to_numeric(
            chunk[mapping["hr"]],
            errors="coerce",
        ).fillna(0).to_numpy(float)

        if mapping.get("detector_score"):
            detector_score = pd.to_numeric(
                chunk[mapping["detector_score"]],
                errors="coerce",
            ).fillna(0).to_numpy(float)
        else:
            detector_score = np.zeros(n, dtype=float)

        if mapping.get("expected_rr_ms"):
            expected_rr_ms = pd.to_numeric(
                chunk[mapping["expected_rr_ms"]],
                errors="coerce",
            ).fillna(0).to_numpy(float)
        else:
            expected_rr_ms = np.zeros(n, dtype=float)

        if mapping["seq"]:
            seq = pd.to_numeric(chunk[mapping["seq"]], errors="coerce").fillna(0).to_numpy(np.int64)
        else:
            seq = np.arange(processed_rows, processed_rows + n, dtype=np.int64)

        if mapping["t_us"]:
            t_us = pd.to_numeric(chunk[mapping["t_us"]], errors="coerce").fillna(0).to_numpy(np.int64)
        else:
            # 用理论采样周期重建旧数据的“采样时基”，不使用接收端秒级 timestamp。
            t_us = np.rint(
                seq.astype(float) * 1e6 / cfg.sample_rate_hz
            ).astype(np.int64)

        if mapping["flags"]:
            flags = pd.to_numeric(chunk[mapping["flags"]], errors="coerce").fillna(0).to_numpy(np.int64)
        else:
            # 旧 CSV 没有独立 wear 标志。
            # 旧 HR 的“数值”不参与新算法，但 HR>0 可以作为当时库仍认为设备佩戴中的状态证据。
            # 不能直接用 raw>1：这些历史记录存在大量 ADC 低端削底，会让检测器被逐采样 reset。
            flags = np.where(hr > 0, 0x01, 0).astype(np.int64)
            flags |= np.where(raw <= cfg.adc_low, 0x02, 0).astype(np.int64)
            flags |= np.where(raw >= cfg.adc_high, 0x04, 0).astype(np.int64)

        for i in range(n):
            wear = bool(int(flags[i]) & 0x01)

            adaptive_event = detector.update(
                seq=int(seq[i]),
                t_us=int(t_us[i]),
                filtered=float(filtered[i]),
                wear=wear,
            )

            # 对历史回放，Sample 的 candidate/score/expected 采用新算法重算值。
            # 如果只是查看原始旧字段，原 CSV 本身仍然保留。
            sample = SampleFrame(
                seq=int(seq[i]),
                t_us=int(t_us[i]),
                raw=float(raw[i]),
                avg=float(avg[i]),
                filtered=float(filtered[i]),
                peak=1 if adaptive_event.candidate else 0,
                hr_bpm=float(adaptive_event.hr_bpm or detector.current_hr_bpm),
                detector_score=float(adaptive_event.signal_score),
                expected_rr_ms=float(adaptive_event.expected_rr_ms),
                flags=int(flags[i]),
            )
            engine.ingest_sample(sample)

            if adaptive_event.accepted:
                beat_flags = 0x01 | 0x08  # WEAR | PEAK_GATED

                if adaptive_event.first:
                    beat_flags |= 0x02

                if adaptive_event.rescued:
                    beat_flags |= 0x10

                if (
                    adaptive_event.rr_ms > 0
                    and (
                        adaptive_event.rr_ms < cfg.rr_hard_min_ms
                        or adaptive_event.rr_ms > cfg.rr_hard_max_ms
                    )
                ):
                    beat_flags |= 0x04

                engine.ingest_beat(
                    BeatFrame(
                        seq=adaptive_event.accepted_seq,
                        t_us=adaptive_event.accepted_t_us,
                        rr_ms=adaptive_event.rr_ms,
                        hr_bpm=adaptive_event.hr_bpm,
                        score=adaptive_event.accepted_score,
                        flags=beat_flags,
                    )
                )

        processed_rows += n

        if progress_callback:
            # pandas chunk 的字节位置不直接暴露，行数比例用文件读取阶段的粗略进度即可。
            # 最终强制回调 1.0。
            estimated = min(
                0.98,
                processed_rows / max(processed_rows + n, 1),
            )
            progress_callback(float(estimated))

    engine.force_update()

    if progress_callback:
        progress_callback(1.0)
