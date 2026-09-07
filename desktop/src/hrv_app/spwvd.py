from __future__ import annotations

from collections.abc import Sequence
import numpy as np
from scipy import signal
from scipy.ndimage import convolve1d

from .config import AnalysisConfig
from .hrv_frequency import prepare_tachogram
from .models import NNInterval, SPWVDResult


def compute_spwvd(
    nn_intervals: Sequence[NNInterval],
    frequency_valid: bool,
    frequency_reason: str = "",
    config: AnalysisConfig | None = None,
) -> SPWVDResult:
    """
    计算用于“时频结构观察”的 SPWVD 图。

    重要边界：
    - SPWVD 不再自己输出 VLF/LF/HF 绝对功率；
    - 绝对频带统计统一以 Welch 为准；
    - 频域质量门失败时 SPWVD 同样停止，避免污染数据生成漂亮热图。
    """
    cfg = config or AnalysisConfig()

    if not frequency_valid:
        return SPWVDResult(
            valid=False,
            message=frequency_reason or "频域质量门未通过",
        )

    prepared = prepare_tachogram(nn_intervals, cfg)
    if prepared is None:
        return SPWVDResult(
            valid=False,
            message="NN 数据不足",
        )

    uniform_t, tachogram, duration, _ = prepared
    if duration < cfg.frequency_window_seconds * 0.995:
        return SPWVDResult(
            valid=False,
            message=(
                f"频域窗口积累中：{duration:.0f}/"
                f"{cfg.frequency_window_seconds:.0f} 秒"
            ),
        )

    x = signal.detrend(tachogram, type="linear")
    analytic = signal.hilbert(x)
    n = len(analytic)

    max_lag = min(
        int(round(
            cfg.spwvd_max_lag_seconds
            * cfg.resample_hz
        )),
        max((n - 1) // 2, 1),
    )

    lag_count = 2 * max_lag + 1
    autocorr = np.zeros(
        (n, lag_count),
        dtype=np.complex128,
    )

    for lag in range(0, max_lag + 1):
        valid_start = lag
        valid_end = n - lag

        if valid_end <= valid_start:
            continue

        center = np.arange(
            valid_start,
            valid_end,
        )
        values = (
            analytic[center + lag]
            * np.conj(analytic[center - lag])
        )

        positive_col = max_lag + lag
        negative_col = max_lag - lag

        autocorr[center, positive_col] = values

        if lag > 0:
            autocorr[center, negative_col] = np.conj(values)

    # 时延方向 Hann 平滑，降低交叉项。
    lag_window = np.hanning(lag_count)
    autocorr *= lag_window[None, :]

    # 时间方向平滑。
    smooth_points = max(
        int(round(
            cfg.spwvd_time_smooth_seconds
            * cfg.resample_hz
        )),
        3,
    )
    if smooth_points % 2 == 0:
        smooth_points += 1

    time_window = np.hanning(smooth_points)
    time_window /= max(
        float(np.sum(time_window)),
        1e-12,
    )

    real_smoothed = convolve1d(
        autocorr.real,
        time_window,
        axis=0,
        mode="nearest",
    )
    imag_smoothed = convolve1d(
        autocorr.imag,
        time_window,
        axis=0,
        mode="nearest",
    )
    smoothed = real_smoothed + 1j * imag_smoothed

    nfft = 1
    while nfft < max(512, lag_count):
        nfft *= 2

    spectrum_signed = np.fft.fft(
        np.fft.ifftshift(
            smoothed,
            axes=1,
        ),
        n=nfft,
        axis=1,
    ).real

    freqs = np.fft.fftfreq(
        nfft,
        d=2.0 / cfg.resample_hz,
    )

    positive = (
        (freqs >= 0.0)
        & (freqs <= 0.50)
    )
    freqs = freqs[positive]
    spectrum_signed = spectrum_signed[:, positive]

    # Wigner-Ville 类分布可出现负交叉项。
    # UI 图只显示正能量结构；不再把截断后的矩阵当作定量频带功率。
    display_power = np.clip(
        spectrum_signed,
        0.0,
        None,
    )

    hop = max(
        int(round(
            cfg.spwvd_hop_seconds
            * cfg.resample_hz
        )),
        1,
    )
    centers = np.arange(0, n, hop)

    return SPWVDResult(
        valid=True,
        times_s=uniform_t[centers],
        freqs_hz=freqs,
        power=display_power[centers, :].T,
        message="SPWVD 仅用于时频结构观察；频带绝对功率以 Welch 为准",
    )
