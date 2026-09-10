from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

import numpy as np
from scipy import signal

from .config import AnalysisConfig
from .models import SampleFrame


@dataclass(slots=True)
class PreprocessedPPG:
    """固定滞后 interval core 使用的标准化 PPG 视图。

    不使用 firmware Beat 反馈，也不使用预期 RR 修改波形。
    只做零相位带通、稳健归一化和极性统一，确保后续两个检测器
    看到同一条、可比较但彼此独立判峰的波形。
    """

    t_us: np.ndarray
    signal: np.ndarray
    sample_rate_hz: float
    polarity: int
    robust_amplitude: float


def _infer_sample_rate_hz(t_us: np.ndarray, fallback: float) -> float:
    if t_us.size < 3:
        return float(fallback)
    dt = np.diff(t_us.astype(float))
    dt = dt[dt > 0]
    if dt.size == 0:
        return float(fallback)
    rate = 1e6 / float(np.median(dt))
    if not np.isfinite(rate) or rate <= 0:
        return float(fallback)
    return float(rate)


def _infer_polarity(values: np.ndarray) -> int:
    if values.size < 8:
        return 1
    median = float(np.median(values))
    up = float(np.percentile(values, 95) - median)
    down = float(median - np.percentile(values, 5))
    return 1 if up >= down else -1


def preprocess_ppg(
    samples: Sequence[SampleFrame],
    config: AnalysisConfig | None = None,
) -> PreprocessedPPG | None:
    """构建 interval core 的 PPG 视图。

    设计借鉴成熟 PPG pipelines 的一个共同点：检测前先将缓慢基线漂移
    和高频噪声从脉搏波形中隔离。这里使用 0.5--8 Hz 的低阶 Butterworth
    SOS + filtfilt。由于正式输出本来就有 7.25 s fixed lag，因此零相位处理
    不会造成“偷看未来”的额外语义问题。

    正式判峰优先使用设备输出的 filtered 通道，而不是 raw ADC。raw 仍由
    SensorContactQuality 负责审计；这样波谷削底不会自动把一个未被削顶的
    收缩峰判成 RR 不可信。
    """

    cfg = config or AnalysisConfig()
    if len(samples) < 24:
        return None

    t_us = np.asarray([s.t_us for s in samples], dtype=np.int64)
    values = np.asarray([s.filtered for s in samples], dtype=float)

    finite = np.isfinite(values)
    if np.count_nonzero(finite) < max(24, int(values.size * 0.95)):
        return None
    if not np.all(finite):
        idx = np.arange(values.size, dtype=float)
        values = np.interp(idx, idx[finite], values[finite])

    fs = _infer_sample_rate_hz(t_us, cfg.sample_rate_hz)

    # 去除常量偏置；如果 filtfilt 需要的点数不够，则退化为稳健中心化。
    centered = values - float(np.median(values))
    cleaned = centered
    nyquist = fs * 0.5
    low = 0.5 / nyquist
    high = min(8.0 / nyquist, 0.95)

    if 0 < low < high < 1.0 and values.size >= max(64, int(fs * 2.5)):
        try:
            sos = signal.butter(2, [low, high], btype="bandpass", output="sos")
            cleaned = signal.sosfiltfilt(sos, centered)
        except (ValueError, FloatingPointError):
            cleaned = centered

    polarity = _infer_polarity(cleaned)
    oriented = cleaned * polarity

    p05, p95 = np.percentile(oriented, [5, 95])
    robust_amplitude = max(float(p95 - p05), 1e-6)
    median = float(np.median(oriented))
    mad = float(np.median(np.abs(oriented - median)))
    scale = max(1.4826 * mad, robust_amplitude / 6.0, 1e-6)
    normalized = (oriented - median) / scale

    return PreprocessedPPG(
        t_us=t_us,
        signal=normalized.astype(float),
        sample_rate_hz=float(fs),
        polarity=int(polarity),
        robust_amplitude=float(robust_amplitude / scale),
    )
