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
