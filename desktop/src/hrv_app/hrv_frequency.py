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



def _normalize_shape(
    values: np.ndarray,
) -> np.ndarray:
    values = np.asarray(
        values,
        dtype=float,
    )

    total = float(
        np.sum(
            np.clip(
                values,
                0.0,
                None,
            )
        )
    )

    if (
        not np.isfinite(total)
        or total <= 1e-12
    ):
        return np.zeros_like(
            values,
            dtype=float,
        )

    return (
        np.clip(
            values,
            0.0,
            None,
        )
        / total
    )


def _pearson_similarity(
    first: np.ndarray,
    second: np.ndarray,
) -> float:
    first = np.asarray(
        first,
        dtype=float,
    )
    second = np.asarray(
        second,
        dtype=float,
    )

    if (
        first.size < 3
        or second.size != first.size
        or np.std(first) <= 1e-12
        or np.std(second) <= 1e-12
    ):
        return 0.0

    corr = float(
        np.corrcoef(
            first,
            second,
        )[0, 1]
    )

    if not np.isfinite(corr):
        return 0.0

    return float(
        np.clip(
            corr,
            0.0,
            1.0,
        )
    )


def _frequency_smooth(
    freqs: np.ndarray,
    shape: np.ndarray,
    width_hz: float,
) -> np.ndarray:
    """
    在频率轴上做小尺度平滑，仅用于“谱形互证”。

    Welch 仍保留原始 PSD，VLF/LF/HF 绝对功率也仍从原始 Welch 积分。
    这里的平滑只降低：
    - 有限窗泄漏；
    - 1~2 个频率 bin 的轻微偏移；
    - 缓峰 / 采集噪声造成的窄带线抖动。

    v0.3.3 默认宽度约 0.02 Hz。
    """
    freqs = np.asarray(
        freqs,
        dtype=float,
    )
    shape = np.asarray(
        shape,
        dtype=float,
    )

    if (
        freqs.size < 3
        or shape.size != freqs.size
        or width_hz <= 0
    ):
        return shape.copy()

    spacing = float(
        np.median(
            np.diff(
                freqs
            )
        )
    )

    if (
        not np.isfinite(spacing)
        or spacing <= 0
    ):
        return shape.copy()

    bins = max(
        int(
            round(
                width_hz
                / spacing
            )
        ),
        1,
    )

    # 使用奇数窗口保证零相位中心。
    if bins % 2 == 0:
        bins += 1

    bins = min(
        bins,
        int(shape.size)
        if shape.size % 2 == 1
        else max(
            int(shape.size) - 1,
            1,
        ),
    )

    if bins <= 1:
        return shape.copy()

    kernel = (
        np.ones(
            bins,
            dtype=float,
        )
        / bins
    )

    return np.convolve(
        shape,
        kernel,
        mode="same",
    )


def _band_fraction_vector(
    freqs: np.ndarray,
    psd: np.ndarray,
    config: AnalysisConfig,
) -> np.ndarray:
    powers = np.asarray(
        [
            _band_power(
                freqs,
                psd,
                config.vlf_low_hz,
                config.vlf_high_hz,
            ),
            _band_power(
                freqs,
                psd,
                config.lf_low_hz,
                config.lf_high_hz,
            ),
            _band_power(
                freqs,
                psd,
                config.hf_low_hz,
                config.hf_high_hz,
            ),
        ],
        dtype=float,
    )

    total = float(
        np.sum(
            powers
        )
    )

    if (
        not np.isfinite(total)
        or total <= 1e-12
    ):
        return np.zeros(
            3,
            dtype=float,
        )

    return (
        powers
        / total
    )


def _band_distribution_agreement(
    first: np.ndarray,
    second: np.ndarray,
) -> float:
    """
    归一化频带分布的重叠度。

    1.0 = VLF/LF/HF 分布完全一致；
    0.0 = 两个分布完全落在不同频带。
    """
    first = np.asarray(
        first,
        dtype=float,
    )
    second = np.asarray(
        second,
        dtype=float,
    )

    if (
        first.size != 3
        or second.size != 3
    ):
        return 0.0

    distance = (
        0.5
        * float(
            np.sum(
                np.abs(
                    first
                    - second
                )
            )
        )
    )

    return float(
        np.clip(
            1.0 - distance,
            0.0,
            1.0,
        )
    )


def _spectral_agreement_metrics(
    freqs: np.ndarray,
    welch_psd: np.ndarray,
    lomb_psd: np.ndarray,
    config: AnalysisConfig,
) -> tuple[
    float,
    float,
    float,
    float,
]:
    """
    返回：
    robust, raw_pointwise, smoothed_shape, band_distribution

    正式门使用 robust；
    raw_pointwise 只保留作 Debug。
    """
    welch_shape = _normalize_shape(
        welch_psd
    )
    lomb_shape = _normalize_shape(
        lomb_psd
    )

    raw_pointwise = (
        _pearson_similarity(
            welch_shape,
            lomb_shape,
        )
    )

    welch_smooth = (
        _frequency_smooth(
            freqs,
            welch_shape,
            config.frequency_agreement_smoothing_hz,
        )
    )
    lomb_smooth = (
        _frequency_smooth(
            freqs,
            lomb_shape,
            config.frequency_agreement_smoothing_hz,
        )
    )

    smoothed_shape = (
        _pearson_similarity(
            welch_smooth,
            lomb_smooth,
        )
    )

    welch_bands = (
        _band_fraction_vector(
            freqs,
            welch_psd,
            config,
        )
    )
    lomb_bands = (
        _band_fraction_vector(
            freqs,
            lomb_psd,
            config,
        )
    )

    band_distribution = (
        _band_distribution_agreement(
            welch_bands,
            lomb_bands,
        )
    )

    weight_shape = float(
        np.clip(
            config.frequency_shape_agreement_weight,
            0.0,
            1.0,
        )
    )
    weight_band = float(
        np.clip(
            config.frequency_band_agreement_weight,
            0.0,
            1.0,
        )
    )

    weight_total = (
        weight_shape
        + weight_band
    )

    if weight_total <= 1e-12:
        robust = smoothed_shape
    else:
        robust = (
            weight_shape
            * smoothed_shape
            + weight_band
            * band_distribution
        ) / weight_total

    return (
        float(
            np.clip(
                robust,
                0.0,
                1.0,
            )
        ),
        raw_pointwise,
        smoothed_shape,
        band_distribution,
    )


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
    """
    5 分钟 HRV 频域。

    v0.3.3 使用多尺度三重互证：
    1. PCHIP tachogram → Welch；
    2. 线性插值 tachogram → Welch；
    3. 原始不规则 NN 时间戳 → Lomb–Scargle。

    少量孤立异常不再仅凭“1% 未解决”直接否决整段 5 分钟。
    逐频点相关仅作 Debug；正式门使用平滑谱形 + 频带分布 + 插值互证。
    """
    cfg = config or AnalysisConfig()

    prepared = prepare_tachogram(
        nn_intervals,
        cfg,
    )

    if prepared is None:
        return FrequencyDomainMetrics(
            valid=False,
            status=LIMITED,
            validity_reason="频域窗口积累中",
        )

    (
        uniform_t,
        tachogram,
        duration,
        usable,
    ) = prepared

    progress = float(
        np.clip(
            duration
            / cfg.frequency_window_seconds,
            0.0,
            1.0,
        )
    )

    if (
        duration
        < cfg.frequency_window_seconds
        * 0.995
    ):
        return FrequencyDomainMetrics(
            valid=False,
            status=LIMITED,
            validity_reason=(
                f"频域窗口积累中："
                f"{duration:.0f}/"
                f"{cfg.frequency_window_seconds:.0f} 秒"
            ),
            progress=progress,
            duration_seconds=duration,
        )

    latest_us = usable[-1].t_us
    start_us = (
        latest_us
        - int(
            cfg.frequency_window_seconds
            * 1e6
        )
    )

    record_window = [
        record
        for record in records
        if start_us
        <= record.t_us
        <= latest_us
    ]

    total_records = max(
        len(record_window),
        1,
    )

    unresolved_statuses = {
        "hard_outlier",
        "local_outlier",
        "no_wear",
        "unresolved",
    }

    unresolved_records = sum(
        record.status
        in unresolved_statuses
        for record in record_window
    )

    unresolved_ratio = (
        unresolved_records
        / total_records
    )

    # 连续异常比“同样数量但彼此孤立”更危险。
    max_consecutive = 0
    current_run = 0

    for record in record_window:
        if (
            record.status
            in unresolved_statuses
        ):
            current_run += 1
            max_consecutive = max(
                max_consecutive,
                current_run,
            )
        else:
            current_run = 0

    corrected_ratio = (
        sum(
            interval.corrected
            for interval in usable
        )
        / max(
            len(usable),
            1,
        )
    )

    # -------------------------------------------------------------------
    # Welch 主频谱：PCHIP tachogram
    # -------------------------------------------------------------------
    detrended = signal.detrend(
        tachogram,
        type="linear",
    )

    nperseg = min(
        1024,
        len(detrended),
    )
    noverlap = (
        nperseg // 2
    )

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

    freqs_use = (
        freqs[analysis_mask]
    )
    psd_use = (
        psd[analysis_mask]
    )

    # -------------------------------------------------------------------
    # 插值敏感性：同一 NN 时间轴改用线性插值，再做完全相同的 Welch。
    # 两者高度一致时，说明结果不是 PCHIP 形状“造出来”的。
    # -------------------------------------------------------------------
    irregular_t = np.asarray(
        [
            interval.t_us / 1e6
            for interval in usable
        ],
        dtype=float,
    )

    irregular_y = np.asarray(
        [
            interval.nn_ms
            for interval in usable
        ],
        dtype=float,
    )

    irregular_t = (
        irregular_t
        - irregular_t[0]
    )

    linear_tachogram = np.interp(
        uniform_t,
        irregular_t,
        irregular_y,
    )

    linear_detrended = (
        signal.detrend(
            linear_tachogram,
            type="linear",
        )
    )

    (
        linear_freqs,
        linear_psd,
    ) = signal.welch(
        linear_detrended,
        fs=cfg.resample_hz,
        window="hann",
        nperseg=nperseg,
        noverlap=noverlap,
        detrend=False,
        scaling="density",
    )

    linear_mask = (
        (linear_freqs >= cfg.vlf_low_hz)
        & (linear_freqs <= cfg.hf_high_hz)
    )

    linear_shape = (
        linear_psd[linear_mask]
    )

    interpolation_agreement = 0.0

    if (
        psd_use.size >= 5
        and linear_shape.size
        == psd_use.size
    ):
        pchip_norm = (
            psd_use
            / max(
                float(
                    np.sum(
                        psd_use
                    )
                ),
                1e-12,
            )
        )

        linear_norm = (
            linear_shape
            / max(
                float(
                    np.sum(
                        linear_shape
                    )
                ),
                1e-12,
            )
        )

        if (
            np.std(pchip_norm) > 0
            and np.std(linear_norm) > 0
        ):
            corr = float(
                np.corrcoef(
                    pchip_norm,
                    linear_norm,
                )[0, 1]
            )

            interpolation_agreement = float(
                np.clip(
                    corr,
                    0.0,
                    1.0,
                )
            )

    # -------------------------------------------------------------------
    # Lomb–Scargle：直接使用不规则 NN 时间戳，不经过 4 Hz 插值。
    #
    # v0.3.3 不再用“原始逐频点 Pearson”直接做硬门。
    # 两种谱估计器的有限窗泄漏不同，波形变缓或几毫秒事件抖动会让
    # 窄峰错开 1~2 个 bin，原始相关会被不成比例地拉低。
    # -------------------------------------------------------------------
    spectral_agreement = 0.0
    spectral_agreement_raw = 0.0
    spectral_shape_agreement = 0.0
    band_power_agreement = 0.0

    if (
        irregular_t.size >= 30
        and freqs_use.size >= 5
    ):
        lomb_y = signal.detrend(
            irregular_y,
            type="linear",
        )

        angular = (
            2.0
            * np.pi
            * freqs_use
        )

        lomb = signal.lombscargle(
            irregular_t,
            lomb_y,
            angular,
            normalize=True,
            floating_mean=True,
        )

        (
            spectral_agreement,
            spectral_agreement_raw,
            spectral_shape_agreement,
            band_power_agreement,
        ) = _spectral_agreement_metrics(
            freqs_use,
            psd_use,
            lomb,
            cfg,
        )

    # -------------------------------------------------------------------
    # 频带积分仍以 Welch 的绝对功率为主。
    # Lomb 用于独立谱形互证。
    # -------------------------------------------------------------------
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

    lf_hf = (
        float(
            lf / hf
        )
        if hf > 1e-12
        else 0.0
    )

    hf_lf = (
        float(
            hf / lf
        )
        if lf > 1e-12
        else 0.0
    )

    normalized_denominator = (
        lf + hf
    )

    lf_nu = (
        float(
            lf
            / normalized_denominator
            * 100.0
        )
        if normalized_denominator
        > 1e-12
        else 0.0
    )

    hf_nu = (
        float(
            hf
            / normalized_denominator
            * 100.0
        )
        if normalized_denominator
        > 1e-12
        else 0.0
    )

    # -------------------------------------------------------------------
    # 硬门：超过任一项都不正式输出。
    # -------------------------------------------------------------------
    hard_reasons: list[str] = []

    if (
        signal_quality.sqi
        < cfg.frequency_min_sqi
    ):
        hard_reasons.append(
            f"SQI {signal_quality.sqi * 100:.0f}% < "
            f"{cfg.frequency_min_sqi * 100:.0f}%"
        )

    if (
        signal_quality.timing_jitter_p95_ms
        > cfg.analysis_limited_max_timing_jitter_p95_ms
    ):
        hard_reasons.append(
            "采样时基 p95 "
            f"{signal_quality.timing_jitter_p95_ms:.1f} ms > "
            f"{cfg.analysis_limited_max_timing_jitter_p95_ms:.1f} ms"
        )

    if (
        corrected_ratio
        > cfg.frequency_limited_max_corrected_ratio
    ):
        hard_reasons.append(
            f"频域修复比例 {corrected_ratio * 100:.1f}% > "
            f"{cfg.frequency_limited_max_corrected_ratio * 100:.1f}%"
        )

    if (
        unresolved_ratio
        > cfg.frequency_limited_max_unresolved_ratio
    ):
        hard_reasons.append(
            f"未解决异常 {unresolved_ratio * 100:.1f}% > "
            f"{cfg.frequency_limited_max_unresolved_ratio * 100:.1f}%"
        )

    if (
        max_consecutive
        > cfg.frequency_limited_max_consecutive_artifacts
    ):
        hard_reasons.append(
            f"连续未解决异常 {max_consecutive} > "
            f"{cfg.frequency_limited_max_consecutive_artifacts}"
        )

    if (
        protocol_health.error_ratio
        > cfg.protocol_max_error_ratio
    ):
        hard_reasons.append(
            f"协议错误 {protocol_health.error_ratio * 100:.2f}% > "
            f"{cfg.protocol_max_error_ratio * 100:.2f}%"
        )

    if (
        spectral_agreement
        < cfg.frequency_min_spectral_agreement
    ):
        hard_reasons.append(
            "Welch/Lomb 稳健一致性 "
            f"{spectral_agreement * 100:.0f}% < "
            f"{cfg.frequency_min_spectral_agreement * 100:.0f}%"
        )

    if (
        band_power_agreement
        < cfg.frequency_min_band_power_agreement
    ):
        hard_reasons.append(
            "VLF/LF/HF 频带一致性 "
            f"{band_power_agreement * 100:.0f}% < "
            f"{cfg.frequency_min_band_power_agreement * 100:.0f}%"
        )

    if (
        interpolation_agreement
        < cfg.frequency_min_interpolation_agreement
    ):
        hard_reasons.append(
            "插值谱形一致性 "
            f"{interpolation_agreement * 100:.0f}% < "
            f"{cfg.frequency_min_interpolation_agreement * 100:.0f}%"
        )

    if hard_reasons:
        return FrequencyDomainMetrics(
            valid=False,
            status=INVALID,
            validity_reason="；".join(
                hard_reasons
            ),
            progress=1.0,
            duration_seconds=duration,
            corrected_ratio=(
                corrected_ratio
            ),
            unresolved_suspect_ratio=(
                unresolved_ratio
            ),
            max_consecutive_artifacts=(
                max_consecutive
            ),
            spectral_agreement=(
                spectral_agreement
            ),
            spectral_agreement_raw=(
                spectral_agreement_raw
            ),
            spectral_shape_agreement=(
                spectral_shape_agreement
            ),
            band_power_agreement=(
                band_power_agreement
            ),
            interpolation_agreement=(
                interpolation_agreement
            ),
        )

    # -------------------------------------------------------------------
    # 严格门：未达到时允许 LIMITED，并明确标记原因。
    # -------------------------------------------------------------------
    strict_reasons: list[str] = []

    if (
        signal_quality.timing_jitter_p95_ms
        > cfg.analysis_strict_max_timing_jitter_p95_ms
    ):
        strict_reasons.append(
            "采样时基 p95 "
            f"{signal_quality.timing_jitter_p95_ms:.1f} ms"
        )

    if (
        corrected_ratio
        > cfg.frequency_max_corrected_ratio
    ):
        strict_reasons.append(
            f"修复 {corrected_ratio * 100:.1f}%"
        )

    if (
        unresolved_ratio
        > cfg.frequency_max_unresolved_ratio
    ):
        strict_reasons.append(
            f"未解决异常 {unresolved_ratio * 100:.1f}%"
        )

    if max_consecutive > 1:
        strict_reasons.append(
            f"连续异常 {max_consecutive}"
        )

    if (
        spectral_agreement
        < cfg.frequency_strict_min_spectral_agreement
    ):
        strict_reasons.append(
            "Welch/Lomb 稳健一致性 "
            f"{spectral_agreement * 100:.0f}%"
        )

    if (
        band_power_agreement
        < cfg.frequency_strict_min_band_power_agreement
    ):
        strict_reasons.append(
            "频带一致性 "
            f"{band_power_agreement * 100:.0f}%"
        )

    if (
        interpolation_agreement
        < cfg.frequency_strict_min_interpolation_agreement
    ):
        strict_reasons.append(
            "插值一致性 "
            f"{interpolation_agreement * 100:.0f}%"
        )

    status = (
        VALID
        if not strict_reasons
        else LIMITED
    )

    reason = (
        ""
        if status == VALID
        else (
            "受限输出："
            + "；".join(
                strict_reasons
            )
        )
    )

    return FrequencyDomainMetrics(
        valid=True,
        status=status,
        validity_reason=reason,
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
        corrected_ratio=(
            corrected_ratio
        ),
        unresolved_suspect_ratio=(
            unresolved_ratio
        ),
        max_consecutive_artifacts=(
            max_consecutive
        ),
        spectral_agreement=(
            spectral_agreement
        ),
        spectral_agreement_raw=(
            spectral_agreement_raw
        ),
        spectral_shape_agreement=(
            spectral_shape_agreement
        ),
        band_power_agreement=(
            band_power_agreement
        ),
        interpolation_agreement=(
            interpolation_agreement
        ),
        freqs_hz=freqs_use,
        psd_ms2_hz=psd_use,
    )

