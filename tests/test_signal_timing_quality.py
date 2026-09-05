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
        "有效" in reason
        and "Hz" in reason
        for reason in quality.reasons
    )
