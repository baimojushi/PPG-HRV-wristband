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
    """
    5 分钟 HRV 频域。

    v0.3.2 使用三重互证：
    1. PCHIP tachogram → Welch；
    2. 线性插值 tachogram → Welch；
    3. 原始不规则 NN 时间戳 → Lomb–Scargle。

    少量孤立异常不再仅凭“1% 未解决”直接否决整段 5 分钟。
    只有采样时基、异常拓扑或三条谱路径不一致时才判 INVALID。
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
    # -------------------------------------------------------------------
    spectral_agreement = 0.0

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
        )

        welch_shape = (
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

        lomb_shape = (
            lomb
            / max(
                float(
                    np.sum(
                        lomb
                    )
                ),
                1e-12,
            )
        )

        if (
            np.std(welch_shape) > 0
            and np.std(lomb_shape) > 0
        ):
            corr = float(
                np.corrcoef(
                    welch_shape,
                    lomb_shape,
                )[0, 1]
            )

            spectral_agreement = float(
                np.clip(
                    corr,
                    0.0,
                    1.0,
                )
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
            "Welch/Lomb 谱形一致性 "
            f"{spectral_agreement * 100:.0f}% < "
            f"{cfg.frequency_min_spectral_agreement * 100:.0f}%"
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
            "Welch/Lomb 一致性 "
            f"{spectral_agreement * 100:.0f}%"
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
        interpolation_agreement=(
            interpolation_agreement
        ),
        freqs_hz=freqs_use,
        psd_ms2_hz=psd_use,
    )

