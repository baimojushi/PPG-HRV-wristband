import numpy as np

from hrv_app.config import AnalysisConfig
from hrv_app.hrv_frequency import (
    _spectral_agreement_metrics,
)


def gaussian(
    freqs: np.ndarray,
    center: float,
    width: float,
    amplitude: float = 1.0,
) -> np.ndarray:
    return (
        amplitude
        * np.exp(
            -0.5
            * (
                (freqs - center)
                / width
            ) ** 2
        )
    )


def test_small_frequency_shift_is_not_over_penalized():
    cfg = AnalysisConfig()

    freqs = np.arange(
        0.004,
        0.401,
        4.0 / 1024.0,
    )

    welch = (
        gaussian(
            freqs,
            0.030,
            0.007,
            1.0,
        )
        + gaussian(
            freqs,
            0.105,
            0.010,
            0.8,
        )
        + gaussian(
            freqs,
            0.245,
            0.016,
            0.45,
        )
    )

    # 模拟有限窗泄漏 / 事件时间轻微抖动：
    # 三个谱峰只移动约 0.008 Hz。
    lomb = (
        gaussian(
            freqs,
            0.038,
            0.007,
            1.0,
        )
        + gaussian(
            freqs,
            0.113,
            0.010,
            0.8,
        )
        + gaussian(
            freqs,
            0.253,
            0.016,
            0.45,
        )
    )

    (
        robust,
        raw,
        shape,
        band,
    ) = _spectral_agreement_metrics(
        freqs,
        welch,
        lomb,
        cfg,
    )

    assert raw < robust
    assert shape > raw
    assert band > 0.90
    assert robust >= cfg.frequency_min_spectral_agreement


def test_large_lf_to_hf_mismatch_still_fails():
    cfg = AnalysisConfig()

    freqs = np.arange(
        0.004,
        0.401,
        4.0 / 1024.0,
    )

    welch = (
        gaussian(
            freqs,
            0.095,
            0.012,
            1.0,
        )
    )

    lomb = (
        gaussian(
            freqs,
            0.285,
            0.014,
            1.0,
        )
    )

    (
        robust,
        _raw,
        _shape,
        band,
    ) = _spectral_agreement_metrics(
        freqs,
        welch,
        lomb,
        cfg,
    )

    assert band < cfg.frequency_min_band_power_agreement
    assert robust < cfg.frequency_min_spectral_agreement


def test_identical_spectra_are_near_one():
    cfg = AnalysisConfig()

    freqs = np.arange(
        0.004,
        0.401,
        4.0 / 1024.0,
    )

    spectrum = (
        gaussian(
            freqs,
            0.035,
            0.009,
            0.8,
        )
        + gaussian(
            freqs,
            0.12,
            0.018,
            1.0,
        )
        + gaussian(
            freqs,
            0.24,
            0.020,
            0.6,
        )
    )

    (
        robust,
        raw,
        shape,
        band,
    ) = _spectral_agreement_metrics(
        freqs,
        spectrum,
        spectrum.copy(),
        cfg,
    )

    assert robust > 0.999
    assert raw > 0.999
    assert shape > 0.999
    assert band > 0.999
