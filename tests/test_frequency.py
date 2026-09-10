import math

from hrv_app.hrv_frequency import compute_frequency_domain
from hrv_app.models import (
    BeatRecord,
    NNInterval,
    ProtocolHealth,
    SignalQuality,
)


def synthetic_timeline(duration_s=330.0):
    records = []
    intervals = []

    t = 0.0
    seq = 0

    while t < duration_s:
        rr = (
            1000.0
            + 80.0 * math.sin(
                2.0 * math.pi * 0.10 * t
            )
            + 45.0 * math.sin(
                2.0 * math.pi * 0.25 * t
            )
        )

        t += rr / 1000.0
        t_us = int(t * 1e6)

        records.append(
            BeatRecord(
                seq=seq,
                t_us=t_us,
                rr_raw_ms=rr,
                nn_ms=rr,
                valid=True,
                corrected=False,
                reason="",
                hr_bpm=60000.0 / rr,
                flags=1,
                status="accepted",
                metric_eligible=True,
            )
        )
        intervals.append(
            NNInterval(
                t_us=t_us,
                nn_ms=rr,
                corrected=False,
                metric_eligible=True,
            )
        )
        seq += 1

    return records, intervals


def test_frequency_domain_after_five_minutes():
    records, intervals = synthetic_timeline()

    result = compute_frequency_domain(
        records,
        intervals,
        SignalQuality(
            sqi=0.95,
            status="VALID",
        ),
        ProtocolHealth(
            ok_frames=10000,
        ),
    )

    assert result.valid
    assert result.total_power_ms2 > 0
    assert result.lf_ms2 > 0
    assert result.hf_ms2 > 0
    assert 0 < result.lf_nu < 100
    assert 0 < result.hf_nu < 100
    assert result.median_frequency_hz > 0
    assert result.freqs_hz.size > 10


def test_frequency_is_blocked_by_low_sqi():
    records, intervals = synthetic_timeline()

    result = compute_frequency_domain(
        records,
        intervals,
        SignalQuality(
            sqi=0.50,
            status="INVALID",
        ),
        ProtocolHealth(
            ok_frames=10000,
        ),
    )

    assert not result.valid
    assert result.status == "INVALID"
    assert "SQI" in result.validity_reason
    assert result.lf_ms2 == 0.0


def test_frequency_is_blocked_when_timing_corrections_jump_between_beats():
    records, intervals = synthetic_timeline()

    # 模拟本次实测里出现的相位歧义：绝对偏移正负来回切换。
    # RR 值本身先保持不变，确保拒绝来自“重建负担”质量门，
    # 而不是人为制造一个坏 tachogram。
    for index, record in enumerate(records):
        record.matched_firmware_t_us = max(1, record.t_us - 1_000)
        record.timing_shift_ms = 140.0 if index % 2 == 0 else -140.0

    result = compute_frequency_domain(
        records,
        intervals,
        SignalQuality(
            sqi=0.95,
            status="VALID",
        ),
        ProtocolHealth(
            ok_frames=10000,
        ),
    )

    assert not result.valid
    assert result.status == "INVALID"
    assert result.timing_shift_delta_p95_ms >= 250.0
    assert "相邻心搏时间修正跳变" in result.validity_reason
