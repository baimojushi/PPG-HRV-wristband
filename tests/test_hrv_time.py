from hrv_app.hrv_time import compute_time_domain
from hrv_app.models import (
    BeatRecord,
    NNInterval,
    SignalQuality,
)


def record(index, rr, status="accepted"):
    return BeatRecord(
        seq=index,
        t_us=index * 800_000,
        rr_raw_ms=rr,
        nn_ms=rr if status == "accepted" else 0.0,
        valid=(status == "accepted"),
        corrected=False,
        reason="",
        hr_bpm=75.0,
        flags=1,
        status=status,
        metric_eligible=(status == "accepted"),
    )


def interval(index, rr):
    return NNInterval(
        t_us=index * 800_000,
        nn_ms=rr,
        corrected=False,
        metric_eligible=True,
    )


def test_good_window_produces_rmssd_and_ci():
    records = []
    intervals = []

    for i in range(1, 61):
        rr = 800 + (i % 2) * 20
        records.append(record(i, rr))
        intervals.append(interval(i, rr))

    metrics = compute_time_domain(
        records,
        intervals,
        SignalQuality(
            sqi=0.95,
            status="VALID",
        ),
    )

    assert metrics.valid
    assert 15 <= metrics.rmssd_ms <= 25
    assert metrics.rmssd_ci_low_ms > 0
    assert metrics.rmssd_ci_high_ms >= metrics.rmssd_ci_low_ms


def test_artifact_over_five_percent_invalidates_entire_window():
    records = []
    intervals = []

    for i in range(1, 61):
        rr = 800 + (i % 2) * 20
        status = (
            "local_outlier"
            if i in {10, 20, 30, 40}
            else "accepted"
        )
        records.append(
            record(i, rr, status=status)
        )

        if status == "accepted":
            intervals.append(
                interval(i, rr)
            )

    metrics = compute_time_domain(
        records,
        intervals,
        SignalQuality(
            sqi=0.95,
            status="VALID",
        ),
    )

    assert not metrics.valid
    assert metrics.detected_artifact_ratio > 0.05
    assert "异常搏" in metrics.validity_reason
