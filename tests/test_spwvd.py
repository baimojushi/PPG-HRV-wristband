import math

from hrv_app.models import NNInterval
from hrv_app.spwvd import compute_spwvd


def synthetic_intervals(duration_s=310.0):
    intervals = []
    t = 0.0

    while t < duration_s:
        rr = (
            1000.0
            + 80.0 * math.sin(
                2.0 * math.pi * 0.10 * t
            )
        )
        t += rr / 1000.0

        intervals.append(
            NNInterval(
                t_us=int(t * 1e6),
                nn_ms=rr,
                corrected=False,
                metric_eligible=True,
            )
        )

    return intervals


def test_spwvd_shape_when_frequency_gate_passes():
    result = compute_spwvd(
        synthetic_intervals(),
        frequency_valid=True,
    )

    assert result.valid
    assert result.power.ndim == 2
    assert (
        result.power.shape[0]
        == result.freqs_hz.size
    )
    assert (
        result.power.shape[1]
        == result.times_s.size
    )


def test_spwvd_stops_when_frequency_invalid():
    result = compute_spwvd(
        synthetic_intervals(),
        frequency_valid=False,
        frequency_reason="SQI 过低",
    )

    assert not result.valid
    assert result.power.size == 0
    assert "SQI" in result.message
