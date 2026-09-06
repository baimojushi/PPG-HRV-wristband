import math

import numpy as np

from hrv_app.fiducial_refiner import TemplateFiducialRefiner
from hrv_app.models import BeatFrame, SampleFrame


def build_samples(
    rr_ms: float = 800.0,
    duration_s: float = 20.0,
    width_ratio: float = 0.10,
):
    samples = []

    for i in range(int(duration_s * 125)):
        t_ms = i * 8.0
        phase = t_ms % rr_ms

        main = 80.0 * math.exp(
            -0.5
            * (
                (
                    phase
                    - 0.32 * rr_ms
                )
                / (width_ratio * rr_ms)
            ) ** 2
        )

        baseline = (
            8.0
            * math.sin(
                2.0
                * math.pi
                * t_ms
                / 5000.0
            )
        )

        samples.append(
            SampleFrame(
                seq=i,
                t_us=int(t_ms * 1000),
                raw=300.0,
                avg=290.0,
                filtered=main + baseline,
                peak=0,
                hr_bpm=75.0,
                flags=1,
            )
        )

    return samples


def test_template_refiner_removes_alternating_peak_position_jitter():
    rr_ms = 800.0
    samples = build_samples(rr_ms=rr_ms)
    refiner = TemplateFiducialRefiner()

    true_times_ms = [
        cycle * rr_ms
        + 0.32 * rr_ms
        for cycle in range(1, 24)
        if cycle * rr_ms
        + 0.32 * rr_ms
        < 19500.0
    ]

    injected_shifts_ms = [
        -64.0,
        48.0,
        72.0,
        -40.0,
        0.0,
    ]

    errors = []
    qualities = []

    for index, true_t_ms in enumerate(
        true_times_ms
    ):
        raw_t_ms = (
            true_t_ms
            + injected_shifts_ms[
                index
                % len(injected_shifts_ms)
            ]
        )

        result = refiner.refine(
            BeatFrame(
                seq=index,
                t_us=int(raw_t_ms * 1000),
                rr_ms=rr_ms,
                hr_bpm=75.0,
                score=0.90,
                flags=0x09,
            ),
            samples,
        )

        errors.append(
            result.t_us / 1000.0
            - true_t_ms
        )
        qualities.append(
            result.quality
        )

    # 125 Hz 原始采样间隔是 8 ms；模板 + 抛物线相关峰细化后，
    # 绝大多数人工 ±40~72 ms 漂移应被压回一个采样以内。
    assert np.percentile(
        np.abs(errors),
        95,
    ) < 8.0

    assert np.mean(
        qualities[2:]
    ) > 0.85


def test_broad_flat_peak_reports_higher_timing_uncertainty():
    normal = build_samples(
        width_ratio=0.08
    )
    broad = build_samples(
        width_ratio=0.18
    )

    beat = BeatFrame(
        seq=1,
        t_us=int(1056.0 * 1000),
        rr_ms=800.0,
        hr_bpm=75.0,
        score=0.9,
        flags=0x09,
    )

    normal_refiner = TemplateFiducialRefiner()
    broad_refiner = TemplateFiducialRefiner()

    normal_refiner.refine(beat, normal)
    broad_refiner.refine(beat, broad)

    normal_second = normal_refiner.refine(
        BeatFrame(
            seq=2,
            t_us=int(1856.0 * 1000),
            rr_ms=800.0,
            hr_bpm=75.0,
            score=0.9,
            flags=0x09,
        ),
        normal,
    )
    broad_second = broad_refiner.refine(
        BeatFrame(
            seq=2,
            t_us=int(1856.0 * 1000),
            rr_ms=800.0,
            hr_bpm=75.0,
            score=0.9,
            flags=0x09,
        ),
        broad,
    )

    assert (
        broad_second.uncertainty_ms
        >= normal_second.uncertainty_ms
    )


def test_engine_keeps_firmware_evidence_but_formal_timeline_follows_waveform():
    from hrv_app.engine import AnalysisEngine

    rr_ms = 800.0
    samples = build_samples(
        rr_ms=rr_ms,
        duration_s=6.0,
    )

    # 故意只提供 5 个、且带 ±40~72 ms 偏移的 Firmware Beat。
    firmware_times_ms = [
        1056.0 - 64.0,
        1856.0 + 48.0,
        2656.0 + 72.0,
        3456.0 - 40.0,
        4256.0,
    ]

    beats = [
        BeatFrame(
            seq=1000 + index,
            t_us=int(
                t_ms
                * 1000
            ),
            rr_ms=(
                0.0
                if index == 0
                else rr_ms
            ),
            hr_bpm=75.0,
            score=0.9,
            flags=0x09,
        )
        for index, t_ms
        in enumerate(
            firmware_times_ms
        )
    ]

    engine = AnalysisEngine()
    beat_index = 0

    for sample in samples:
        engine.ingest_sample(
            sample
        )

        while (
            beat_index
            < len(beats)
            and beats[
                beat_index
            ].t_us
            <= sample.t_us
        ):
            engine.ingest_beat(
                beats[
                    beat_index
                ]
            )
            beat_index += 1

    engine.force_update()
    bundle = engine.export_bundle()

    firmware = bundle[
        "firmware_beats"
    ]
    formal = bundle[
        "raw_beats"
    ]

    assert len(firmware) == 5

    # 6 s 合成波形在 0.256, 1.056, ..., 5.856 s 有主峰。
    # force 模式保留 0.25 s 右边界，因此应提交前 7 个视觉主波。
    expected_ms = [
        256.0
        + cycle
        * rr_ms
        for cycle in range(7)
    ]

    assert len(formal) == len(
        expected_ms
    )

    errors_ms = [
        abs(
            beat.t_us
            / 1000.0
            - expected
        )
        for beat, expected
        in zip(
            formal,
            expected_ms,
        )
    ]

    assert np.percentile(
        errors_ms,
        95,
    ) < 8.0

    # Firmware 没有报告最早和部分边界主波，正式时间线仍可独立补回。
    assert any(
        beat.inserted_by_smoother
        for beat in formal
    )

    assert all(
        beat.correction_method
        == "fixed_lag_waveform"
        for beat in formal
    )

def test_engine_wrong_firmware_phase_cannot_move_visual_wave_top():
    from hrv_app.engine import AnalysisEngine

    engine = AnalysisEngine()

    for sample in build_samples(
        rr_ms=800.0,
        duration_s=3.0,
    ):
        engine.ingest_sample(
            sample
        )

    # 真正视觉主峰在 1.056 s；Firmware Winner 故意晚 120 ms。
    engine.ingest_beat(
        BeatFrame(
            seq=100,
            t_us=1_176_000,
            rr_ms=800.0,
            hr_bpm=75.0,
            score=0.95,
            flags=0x09,
        )
    )

    engine.force_update()

    formal = engine.export_bundle()[
        "raw_beats"
    ]

    target = min(
        formal,
        key=lambda beat:
            abs(
                beat.t_us
                - 1_056_000
            ),
    )

    assert abs(
        target.t_us
        - 1_056_000
    ) < 8_000

    # 固件位置只作为匹配证据，不拥有改写正式波顶的权力。
    assert target.matched_firmware_t_us == 1_176_000
    assert target.timing_shift_ms < -100.0
    assert target.refined

def test_refiner_waits_for_high_score_main_peak_before_bootstrap():
    samples = build_samples(
        rr_ms=800.0,
        duration_s=5.0,
    )
    refiner = TemplateFiducialRefiner()

    low = refiner.refine(
        BeatFrame(
            seq=1,
            t_us=1_056_000,
            rr_ms=0.0,
            hr_bpm=75.0,
            score=0.62,
            flags=0x09,
        ),
        samples,
    )

    assert not low.refined
    assert not refiner.template_ready
    assert low.quality < 0.62

    high = refiner.refine(
        BeatFrame(
            seq=2,
            t_us=1_856_000,
            rr_ms=800.0,
            hr_bpm=75.0,
            score=0.90,
            flags=0x09,
        ),
        samples,
    )

    assert high.refined
    assert refiner.template_ready
    assert high.quality >= 0.80


def test_refiner_recovers_secondary_peak_branch_near_expected_cycle():
    rr_ms = 800.0
    samples = build_samples(
        rr_ms=rr_ms,
        duration_s=8.0,
    )
    refiner = TemplateFiducialRefiner()

    # 第一搏用高分主峰建立模板。
    first_true_ms = 1_856.0

    first = refiner.refine(
        BeatFrame(
            seq=1,
            t_us=int(first_true_ms * 1000),
            rr_ms=0.0,
            hr_bpm=75.0,
            score=0.92,
            flags=0x09,
        ),
        samples,
    )

    assert first.refined

    # 第二搏故意把固件 Winner 放到主峰前 240 ms。
    second_true_ms = first_true_ms + rr_ms
    source_ms = second_true_ms - 240.0

    second = refiner.refine(
        BeatFrame(
            seq=2,
            t_us=int(source_ms * 1000),
            rr_ms=rr_ms,
            hr_bpm=75.0,
            score=0.64,
            flags=0x09,
        ),
        samples,
        expected_t_us=int(
            second_true_ms
            * 1000
        ),
        expected_rr_ms=rr_ms,
    )

    assert second.recovered
    assert second.refined
    assert abs(
        second.t_us / 1000.0
        - second_true_ms
    ) < 12.0
    assert second.shift_ms > 180.0
    assert second.quality >= 0.74


def test_engine_can_restore_a_beat_without_any_firmware_source():
    from hrv_app.engine import AnalysisEngine

    engine = AnalysisEngine()

    samples = build_samples(
        rr_ms=800.0,
        duration_s=4.0,
    )

    # 只提供第 1、3 个 Firmware Beat，中间 1.856 s 主波完全漏报。
    firmware = [
        BeatFrame(
            seq=100,
            t_us=1_056_000,
            rr_ms=0.0,
            hr_bpm=75.0,
            score=0.90,
            flags=0x09,
        ),
        BeatFrame(
            seq=102,
            t_us=2_656_000,
            rr_ms=1_600.0,
            hr_bpm=75.0,
            score=0.90,
            flags=0x09,
        ),
    ]

    beat_index = 0

    for sample in samples:
        engine.ingest_sample(
            sample
        )

        while (
            beat_index
            < len(firmware)
            and firmware[
                beat_index
            ].t_us
            <= sample.t_us
        ):
            engine.ingest_beat(
                firmware[
                    beat_index
                ]
            )
            beat_index += 1

    engine.force_update()

    formal = engine.export_bundle()[
        "raw_beats"
    ]

    restored = min(
        formal,
        key=lambda beat:
            abs(
                beat.t_us
                - 1_856_000
            ),
    )

    assert abs(
        restored.t_us
        - 1_856_000
    ) < 8_000
    assert restored.matched_firmware_t_us == 0
    assert restored.inserted_by_smoother
    assert restored.refined

