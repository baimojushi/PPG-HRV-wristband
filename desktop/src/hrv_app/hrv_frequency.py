from __future__ import annotations

from collections.abc import Sequence
import numpy as np
from scipy import signal
from scipy.interpolate import PchipInterpolator

from .config import AnalysisConfig
from .models import (
    INVALID,
    LIMITED,
    VALID,
    BeatRecord,
    FrequencyDomainMetrics,
    NNInterval,
    ProtocolHealth,
    SignalQuality,
)


def _band_power(
    freqs: np.ndarray,
    psd: np.ndarray,
    low: float,
    high: float,
) -> float:
    mask = (freqs >= low) & (freqs < high)
    if np.count_nonzero(mask) < 2:
        return 0.0
    return float(np.trapezoid(psd[mask], freqs[mask]))


def prepare_tachogram(
    nn_intervals: Sequence[NNInterval],
    config: AnalysisConfig,
) -> tuple[np.ndarray, np.ndarray, float, list[NNInterval]] | None:
    """
    修复后的 NN 时间轴 → 4 Hz tachogram。

    关键变化：
    - 伪峰已经从事件时间轴删除；
    - 漏搏已经插入合成时间点；
    - 无法修复的异常不再被“局部中位数 + 原错误时间戳”混入频谱。
    """
    usable = [
        interval
        for interval in nn_intervals
        if interval.nn_ms > 0 and np.isfinite(interval.nn_ms)
    ]
    if len(usable) < 20:
        return None

    latest_s = usable[-1].t_us / 1e6
    start_s = latest_s - config.frequency_window_seconds
    usable = [
        interval
        for interval in usable
        if (interval.t_us / 1e6) >= start_s
    ]

    if len(usable) < 20:
        return None

    times = np.asarray(
        [interval.t_us / 1e6 for interval in usable],
        dtype=float,
    )
    values = np.asarray(
        [interval.nn_ms for interval in usable],
        dtype=float,
    )

    times = times - times[0]
    duration = float(times[-1] - times[0])

    if duration <= 0:
        return None

    uniform_t = np.arange(
        0.0,
        duration,
        1.0 / config.resample_hz,
        dtype=float,
    )
    if uniform_t.size < 16:
        return None

    interpolator = PchipInterpolator(
        times,
        values,
        extrapolate=False,
    )
    tachogram = interpolator(uniform_t)

    finite = np.isfinite(tachogram)
    if np.count_nonzero(finite) < 16:
        return None

    if not np.all(finite):
        tachogram = np.interp(
            uniform_t,
            uniform_t[finite],
            tachogram[finite],
        )

    return uniform_t, tachogram.astype(float), duration, usable


def compute_frequency_domain(
    records: Sequence[BeatRecord],
    nn_intervals: Sequence[NNInterval],
    signal_quality: SignalQuality,
    protocol_health: ProtocolHealth,
    config: AnalysisConfig | None = None,
) -> FrequencyDomainMetrics:
    cfg = config or AnalysisConfig()
    prepared = prepare_tachogram(nn_intervals, cfg)

    if prepared is None:
        return FrequencyDomainMetrics(
            valid=False,
            status=LIMITED,
            validity_reason="频域窗口积累中",
        )

    uniform_t, tachogram, duration, usable = prepared
    progress = float(np.clip(
        duration / cfg.frequency_window_seconds,
        0.0,
        1.0,
    ))

    if duration < cfg.frequency_window_seconds * 0.995:
        return FrequencyDomainMetrics(
            valid=False,
            status=LIMITED,
            validity_reason=(
                f"频域窗口积累中：{duration:.0f}/"
                f"{cfg.frequency_window_seconds:.0f} 秒"
            ),
            progress=progress,
            duration_seconds=duration,
        )

    latest_us = usable[-1].t_us
    start_us = latest_us - int(cfg.frequency_window_seconds * 1e6)

    record_window = [
        record
        for record in records
        if start_us <= record.t_us <= latest_us
    ]

    total_records = max(len(record_window), 1)
    unresolved_records = sum(
        record.status in {
            "hard_outlier",
            "local_outlier",
            "no_wear",
            "unresolved",
        }
        for record in record_window
    )

    # 修复比例按“实际进入频谱的 NN 时间轴”计算。
    # 漏搏会插入多个合成 NN，不能只按一个原始 BeatRecord 计数。
    corrected_ratio = (
        sum(interval.corrected for interval in usable)
        / max(len(usable), 1)
    )
    unresolved_ratio = unresolved_records / total_records

    gate_reasons: list[str] = []
    if signal_quality.sqi < cfg.frequency_min_sqi:
        gate_reasons.append(
            f"SQI {signal_quality.sqi * 100:.0f}% < "
            f"{cfg.frequency_min_sqi * 100:.0f}%"
        )
    if corrected_ratio > cfg.frequency_max_corrected_ratio:
        gate_reasons.append(
            f"频域修复比例 {corrected_ratio * 100:.1f}% > "
            f"{cfg.frequency_max_corrected_ratio * 100:.1f}%"
        )
    if unresolved_ratio > cfg.frequency_max_unresolved_ratio:
        gate_reasons.append(
            f"未解决异常 {unresolved_ratio * 100:.1f}% > "
            f"{cfg.frequency_max_unresolved_ratio * 100:.1f}%"
        )
    if protocol_health.error_ratio > cfg.protocol_max_error_ratio:
        gate_reasons.append(
            f"协议错误 {protocol_health.error_ratio * 100:.2f}% > "
            f"{cfg.protocol_max_error_ratio * 100:.2f}%"
        )

    # 质量门失败后，不继续生成“看起来精确”的 LF/HF 数值。
    if gate_reasons:
        return FrequencyDomainMetrics(
            valid=False,
            status=INVALID,
            validity_reason="；".join(gate_reasons),
            progress=1.0,
            duration_seconds=duration,
            corrected_ratio=corrected_ratio,
            unresolved_suspect_ratio=unresolved_ratio,
        )

    detrended = signal.detrend(tachogram, type="linear")

    nperseg = min(1024, len(detrended))
    noverlap = nperseg // 2

    freqs, psd = signal.welch(
        detrended,
        fs=cfg.resample_hz,
        window="hann",
        nperseg=nperseg,
        noverlap=noverlap,
        detrend=False,
        scaling="density",
    )

    analysis_mask = (
        (freqs >= cfg.vlf_low_hz)
        & (freqs <= cfg.hf_high_hz)
    )
    freqs_use = freqs[analysis_mask]
    psd_use = psd[analysis_mask]

    total_power = _band_power(
        freqs,
        psd,
        cfg.vlf_low_hz,
        cfg.hf_high_hz,
    )
    vlf = _band_power(
        freqs,
        psd,
        cfg.vlf_low_hz,
        cfg.vlf_high_hz,
    )
    lf = _band_power(
        freqs,
        psd,
        cfg.lf_low_hz,
        cfg.lf_high_hz,
    )
    hf = _band_power(
        freqs,
        psd,
        cfg.hf_low_hz,
        cfg.hf_high_hz,
    )

    lf_hf = float(lf / hf) if hf > 1e-12 else 0.0
    hf_lf = float(hf / lf) if lf > 1e-12 else 0.0

    normalized_denominator = lf + hf
    lf_nu = (
        float(lf / normalized_denominator * 100.0)
        if normalized_denominator > 1e-12
        else 0.0
    )
    hf_nu = (
        float(hf / normalized_denominator * 100.0)
        if normalized_denominator > 1e-12
        else 0.0
    )

    # Lomb–Scargle 只作为形状交叉验证；最终绝对功率仍来自 Welch。
    irregular_t = np.asarray(
        [interval.t_us / 1e6 for interval in usable],
        dtype=float,
    )
    irregular_y = np.asarray(
        [interval.nn_ms for interval in usable],
        dtype=float,
    )

    spectral_agreement = 0.0
    if irregular_t.size >= 30 and freqs_use.size >= 5:
        irregular_t = irregular_t - irregular_t[0]
        irregular_y = signal.detrend(
            irregular_y,
            type="linear",
        )

        angular = 2.0 * np.pi * freqs_use
        lomb = signal.lombscargle(
            irregular_t,
            irregular_y,
            angular,
            normalize=True,
        )

        welch_shape = psd_use / max(
            float(np.sum(psd_use)),
            1e-12,
        )
        lomb_shape = lomb / max(
            float(np.sum(lomb)),
            1e-12,
        )

        if np.std(welch_shape) > 0 and np.std(lomb_shape) > 0:
            corr = float(np.corrcoef(
                welch_shape,
                lomb_shape,
            )[0, 1])
            spectral_agreement = float(np.clip(
                corr,
                0.0,
                1.0,
            ))

    return FrequencyDomainMetrics(
        valid=True,
        status=VALID,
        validity_reason="",
        progress=1.0,
        duration_seconds=duration,
        total_power_ms2=total_power,
        vlf_ms2=vlf,
        lf_ms2=lf,
        hf_ms2=hf,
        lf_nu=lf_nu,
        hf_nu=hf_nu,
        lf_hf=lf_hf,
        hf_lf=hf_lf,
        corrected_ratio=corrected_ratio,
        unresolved_suspect_ratio=unresolved_ratio,
        spectral_agreement=spectral_agreement,
        freqs_hz=freqs_use,
        psd_ms2_hz=psd_use,
    )
