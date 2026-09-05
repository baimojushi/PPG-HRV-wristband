from hrv_app.models import BeatFrame
from hrv_app.rr_cleaner import (
    BeatTimelineCleaner,
    RRCleaner,
)


def beat(index, rr):
    return BeatFrame(
        seq=index,
        t_us=index * 800_000,
        rr_ms=rr,
        hr_bpm=75.0,
        flags=1,
    )


def test_single_rr_compat_hard_short():
    cleaner = RRCleaner()

    for value in [
        800, 810, 790, 805,
        795, 802, 798, 804,
    ]:
        result = cleaner.clean(value)
        assert result.valid

    bad = cleaner.clean(216)

    assert not bad.valid
    assert bad.corrected
    assert "过短" in bad.reason


def test_false_peak_pair_is_merged_retroactively():
    cleaner = BeatTimelineCleaner()

    # 639 + 311 ≈ 950，前后节律约 800–950 ms。
    values = [
        820, 810, 830, 815, 825, 818, 822,
        951, 639, 311, 824, 816, 820,
    ]
    result = cleaner.clean(
        [
            beat(i, rr)
            for i, rr in enumerate(values, start=1)
        ]
    )

    statuses = [
        record.status
        for record in result.records
    ]

    assert "false_peak" in statuses
    assert "false_peak_merged" in statuses

    merged = [
        interval
        for interval in result.nn_intervals
        if interval.source == "false_peak_merge"
    ]

    assert len(merged) == 1
    assert 940 <= merged[0].nn_ms <= 960
    assert not merged[0].metric_eligible


def test_missed_beat_is_split_for_frequency_timeline():
    cleaner = BeatTimelineCleaner()

    values = [
        800, 805, 795, 810, 790, 802, 798,
        1600,
        804, 796, 806,
    ]
    result = cleaner.clean(
        [
            beat(i, rr)
            for i, rr in enumerate(values, start=1)
        ]
    )

    repaired = [
        interval
        for interval in result.nn_intervals
        if interval.source == "missed_beat_split"
    ]

    assert len(repaired) == 2
    assert all(
        790 <= interval.nn_ms <= 810
        for interval in repaired
    )
    assert all(
        not interval.metric_eligible
        for interval in repaired
    )
