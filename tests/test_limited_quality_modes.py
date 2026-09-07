import math

from hrv_app.hrv_frequency import compute_frequency_domain
from hrv_app.hrv_time import compute_time_domain
from hrv_app.models import (
    BeatRecord,
    NNInterval,
    ProtocolHealth,
    SignalQuality,
)


def make_signal_quality(
    jitter_ms: float = 0.5,
) -> SignalQuality:
    return SignalQuality(
        sqi=0.90,
        status="VALID",
        wear_ratio=1.0,
        effective_sample_rate_hz=125.0,
        timing_jitter_p95_ms=jitter_ms,
        timing_overrun_ratio=0.0,
    )


def test_time_domain_moderate_isolated_artifacts_are_limited_not_hidden():
    records = []
    intervals = []

    # 60 个事件：
    # - 55 个直接 accepted；
    # - 2 个已修复漏搏；
    # - 3 个未解决异常。
    #
    # 这对应约 8.3% 总异常、5% 未解决，落在 v0.3.2 LIMITED 区间。
    corrected = {20, 40}
    unresolved = {10, 30, 31}

    t_us = 0

    for i in range(60):
        rr = (
            750.0
            + 45.0
            * math.sin(
                2.0
                * math.pi
                * i
                / 11.0
            )
        )
        t_us += int(
            round(
                rr * 1000.0
            )
        )

        if i in corrected:
            status = "missed_beat_repaired"
            is_corrected = True
            metric_eligible = False
        elif i in unresolved:
            status = "local_outlier"
            is_corrected = False
            metric_eligible = False
        else:
            status = "accepted"
            is_corrected = False
            metric_eligible = True

        records.append(
            BeatRecord(
                seq=i,
                t_us=t_us,
                rr_raw_ms=rr,
                nn_ms=(
                    rr
                    if status == "accepted"
                    else 0.0
                ),
                valid=(
                    status == "accepted"
                ),
                corrected=is_corrected,
                reason="",
                hr_bpm=80.0,
                flags=1,
                status=status,
                metric_eligible=metric_eligible,
            )
        )

        if status == "accepted":
            intervals.append(
                NNInterval(
                    t_us=t_us,
                    nn_ms=rr,
                    corrected=False,
                    metric_eligible=True,
                    source="raw",
                )
            )

    result = compute_time_domain(
        records,
        intervals,
        make_signal_quality(),
    )

    assert result.valid
    assert result.status == "LIMITED"
    assert result.rmssd_ms > 0
    assert result.unresolved_suspect_ratio <= 0.06
    assert result.max_consecutive_artifacts <= 2


def test_time_domain_bad_sampling_clock_stays_invalid():
    records = []
    intervals = []
    t_us = 0

    for i in range(60):
        rr = 750.0
        t_us += 750_000

        records.append(
            BeatRecord(
                seq=i,
                t_us=t_us,
                rr_raw_ms=rr,
                nn_ms=rr,
                valid=True,
                corrected=False,
                reason="",
                hr_bpm=80.0,
                flags=1,
                status="accepted",
                metric_eligible=True,
            )
        )
        intervals.append(
            NNInterval(
                t_us=t_us,
                nn_ms=rr,
            )
        )

    signal_quality = make_signal_quality(
        jitter_ms=58.0
    )

    result = compute_time_domain(
        records,
        intervals,
        signal_quality,
    )

    assert not result.valid
    assert result.status == "INVALID"
    assert "采样时基" in result.validity_reason


def build_frequency_case():
    records = []
    intervals = []

    t_s = 0.0

    # 约 6 分钟，保证最后完整 5 分钟窗口。
    # 0.10 Hz 呼吸样变化 + 0.025 Hz 慢变化，使 Welch / Lomb 都有稳定谱形。
    for i in range(500):
        rr = (
            750.0
            + 42.0
            * math.sin(
                2.0
                * math.pi
                * 0.10
                * t_s
            )
            + 18.0
            * math.sin(
                2.0
                * math.pi
                * 0.025
                * t_s
            )
        )

        t_s += rr / 1000.0
        t_us = int(
            round(
                t_s * 1e6
            )
        )

        # 每约 35 个事件放一个孤立未解决异常，约 3%。
        unresolved = (
            i > 40
            and i % 35 == 0
        )

        status = (
            "local_outlier"
            if unresolved
            else "accepted"
        )

        records.append(
            BeatRecord(
                seq=i,
                t_us=t_us,
                rr_raw_ms=rr,
                nn_ms=(
                    0.0
                    if unresolved
                    else rr
                ),
                valid=not unresolved,
                corrected=False,
                reason="",
                hr_bpm=80.0,
                flags=1,
                status=status,
                metric_eligible=not unresolved,
            )
        )

        if not unresolved:
            intervals.append(
                NNInterval(
                    t_us=t_us,
                    nn_ms=rr,
                    corrected=False,
                    metric_eligible=True,
                    source="raw",
                )
            )

    return records, intervals


def test_frequency_moderate_isolated_gaps_require_spectral_cross_validation():
    records, intervals = (
        build_frequency_case()
    )

    result = compute_frequency_domain(
        records,
        intervals,
        make_signal_quality(),
        ProtocolHealth(),
    )

    assert result.valid
    assert result.status == "LIMITED"
    assert result.total_power_ms2 > 0
    assert result.spectral_agreement >= 0.70
    assert result.interpolation_agreement >= 0.95
    assert result.unresolved_suspect_ratio <= 0.05


def test_frequency_bad_sampling_clock_stays_invalid():
    records, intervals = (
        build_frequency_case()
    )

    result = compute_frequency_domain(
        records,
        intervals,
        make_signal_quality(
            jitter_ms=58.0
        ),
        ProtocolHealth(),
    )

    assert not result.valid
    assert result.status == "INVALID"
    assert "采样时基" in result.validity_reason


def test_time_domain_low_fiducial_quality_is_invalid_even_with_clean_rr():
    records = []
    intervals = []
    t_us = 0

    for i in range(60):
        rr = 750.0
        t_us += 750_000

        records.append(
            BeatRecord(
                seq=i,
                t_us=t_us,
                rr_raw_ms=rr,
                nn_ms=rr,
                valid=True,
                corrected=False,
                reason="",
                hr_bpm=80.0,
                flags=1,
                status="accepted",
                metric_eligible=True,
                timing_quality=0.50,
                timing_uncertainty_ms=60.0,
                refined=True,
            )
        )
        intervals.append(
            NNInterval(
                t_us=t_us,
                nn_ms=rr,
            )
        )

    result = compute_time_domain(
        records,
        intervals,
        make_signal_quality(),
    )

    assert not result.valid
    assert result.status == "INVALID"
    assert "标志点" in result.validity_reason


def test_time_domain_moderate_fiducial_uncertainty_is_limited():
    records = []
    intervals = []
    t_us = 0

    for i in range(60):
        rr = (
            750.0
            + 15.0
            * math.sin(
                2.0
                * math.pi
                * i
                / 10.0
            )
        )
        t_us += int(rr * 1000)

        records.append(
            BeatRecord(
                seq=i,
                t_us=t_us,
                rr_raw_ms=rr,
                nn_ms=rr,
                valid=True,
                corrected=False,
                reason="",
                hr_bpm=80.0,
                flags=1,
                status="accepted",
                metric_eligible=True,
                timing_quality=0.80,
                timing_uncertainty_ms=36.0,
                refined=True,
            )
        )
        intervals.append(
            NNInterval(
                t_us=t_us,
                nn_ms=rr,
            )
        )

    result = compute_time_domain(
        records,
        intervals,
        make_signal_quality(),
    )

    assert result.valid
    assert result.status == "LIMITED"
    assert result.fiducial_uncertainty_p95_ms == 36.0
