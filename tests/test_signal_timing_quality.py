from hrv_app.models import SampleFrame
from hrv_app.signal_quality import evaluate_signal_quality


def test_periodic_long_gap_is_visible_as_low_effective_sample_rate():
    samples = []

    t_us = 0

    for i in range(1600):
        # 模拟实测 v0.3.1：
        # 15 个约 8 ms 后，第 16 个间隔约 66 ms。
        if i > 0:
            if i % 16 == 14:
                t_us += 66_000
            else:
                t_us += 8_000

        samples.append(
            SampleFrame(
                seq=i,
                t_us=t_us,
                raw=300,
                avg=290,
                filtered=50,
                peak=0,
                hr_bpm=80.0,
                flags=1,
            )
        )

    quality = evaluate_signal_quality(
        samples
    )

    assert quality.effective_sample_rate_hz < 100.0
    assert quality.timing_jitter_p95_ms > 20.0
    assert quality.timing_overrun_ratio > 0.05
    assert quality.status == "INVALID"
    assert quality.sqi < 0.65
    assert any(
        "设备采样时钟" in reason
        and "Hz" in reason
        for reason in quality.reasons
    )


def _regular_decimated_samples(count: int = 1000):
    return [
        SampleFrame(
            seq=index * 4,
            t_us=index * 32_000,
            raw=320,
            avg=315,
            filtered=55,
            peak=0,
            hr_bpm=75.0,
            flags=1,
        )
        for index in range(count)
    ]


def test_regular_bluetooth_decimation_preserves_source_clock_quality():
    quality = evaluate_signal_quality(_regular_decimated_samples())

    assert abs(quality.effective_sample_rate_hz - 31.25) < 0.01
    assert abs(quality.source_sample_rate_hz - 125.0) < 0.01
    assert quality.sample_stride == 4
    assert quality.sample_decimated
    assert quality.sequence_drop_ratio == 0.0
    assert quality.timing_jitter_p95_ms < 0.01
    assert quality.timing_overrun_ratio == 0.0
    assert quality.transport_status == "VALID"
    assert quality.status == "VALID"


def test_missing_bluetooth_forwarded_frame_is_not_counted_as_three_quarters_loss():
    samples = _regular_decimated_samples(500)
    # Remove one transmitted frame. seq/t_us continue to represent the 125 Hz
    # device source clock, so the local step becomes +8 / 64 ms exactly once.
    del samples[250]

    quality = evaluate_signal_quality(samples)

    assert quality.sample_stride == 4
    assert quality.sample_decimated
    assert 0.0 < quality.sequence_drop_ratio < 0.01
    assert quality.timing_jitter_p95_ms < 0.01
    assert abs(quality.source_sample_rate_hz - 125.0) < 0.01
