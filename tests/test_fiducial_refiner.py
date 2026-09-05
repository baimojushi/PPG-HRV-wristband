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


def test_engine_keeps_firmware_beats_and_uses_refined_timeline():
    from hrv_app.engine import AnalysisEngine

    rr_ms = 800.0
    samples = build_samples(
        rr_ms=rr_ms,
        duration_s=6.0,
    )

    true_times_ms = [
        1056.0,
        1856.0,
        2656.0,
        3456.0,
        4256.0,
    ]
    shifts_ms = [
        -64.0,
        48.0,
        72.0,
        -40.0,
        0.0,
    ]

    beats = [
        BeatFrame(
            seq=1000 + index,
            t_us=int(
                (
                    true_t
                    + shifts_ms[index]
                )
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
        for index, true_t
        in enumerate(true_times_ms)
    ]

    engine = AnalysisEngine()
    beat_index = 0

    for sample in samples:
        engine.ingest_sample(
            sample
        )

        while (
            beat_index < len(beats)
            and beats[beat_index].t_us
            <= sample.t_us
        ):
            engine.ingest_beat(
                beats[beat_index]
            )
            beat_index += 1

    engine.force_update()
    bundle = engine.export_bundle()

    firmware = bundle[
        "firmware_beats"
    ]
    refined = bundle[
        "raw_beats"
    ]

    assert len(firmware) == len(beats)
    assert len(refined) == len(beats)

    refined_errors = [
        abs(
            beat.t_us / 1000.0
            - true_t
        )
        for beat, true_t
        in zip(
            refined,
            true_times_ms,
        )
    ]

    assert np.percentile(
        refined_errors,
        95,
    ) < 8.0

    refined_rr = np.asarray(
        [
            beat.rr_ms
            for beat in refined[1:]
        ],
        dtype=float,
    )

    assert np.max(
        np.abs(
            refined_rr - rr_ms
        )
    ) < 12.0

    assert any(
        abs(
            refined[index].t_us
            - firmware[index].t_us
        )
        > 20_000
        for index in range(
            len(refined)
        )
    )


def test_engine_rejects_low_quality_template_shift_from_rr_timeline():
    from hrv_app.engine import AnalysisEngine
    from hrv_app.fiducial_refiner import FiducialResult

    engine = AnalysisEngine()

    # 先提供足够的前后 PPG，使 Beat 到达时可以立即进入细化路径。
    for sample in build_samples(
        rr_ms=800.0,
        duration_s=3.0,
    ):
        engine.ingest_sample(sample)

    source_t_us = 1_056_000

    # 模拟困难平顶峰：互相关数学最大值落到搜索边界，质量很低。
    # v0.3.4 必须保留固件时间，不允许这个不可靠偏移直接污染 RR。
    engine._fiducial_refiner.refine = lambda beat, samples, **kwargs: FiducialResult(
        t_us=source_t_us + 120_000,
        quality=0.20,
        uncertainty_ms=64.0,
        shift_ms=120.0,
        correlation=0.55,
        refined=True,
        polarity=1,
    )

    engine.ingest_beat(
        BeatFrame(
            seq=100,
            t_us=source_t_us,
            rr_ms=0.0,
            hr_bpm=75.0,
            score=0.70,
            flags=0x09,
        )
    )

    refined = engine.export_bundle()[
        "raw_beats"
    ][0]

    assert refined.t_us == source_t_us
    assert refined.source_t_us == source_t_us
    assert not refined.refined
    assert refined.timing_shift_ms == 0.0

    # 低质量证据仍然保留，用于后续 Beat Timing Quality 质量门。
    assert refined.timing_quality == 0.20
    assert refined.timing_uncertainty_ms == 64.0



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


def test_engine_accepts_high_quality_recovered_large_shift():
    from hrv_app.engine import AnalysisEngine
    from hrv_app.fiducial_refiner import FiducialResult

    engine = AnalysisEngine()

    for sample in build_samples(
        rr_ms=800.0,
        duration_s=4.0,
    ):
        engine.ingest_sample(sample)

    # 第一搏正常，建立 refined 时间历史。
    first_t_us = 1_056_000
    engine._fiducial_refiner.refine = (
        lambda beat, samples, **kwargs: FiducialResult(
            t_us=int(beat.t_us),
            quality=0.90,
            uncertainty_ms=8.0,
            shift_ms=0.0,
            correlation=0.95,
            refined=True,
            polarity=1,
            recovered=False,
        )
    )

    engine.ingest_beat(
        BeatFrame(
            seq=100,
            t_us=first_t_us,
            rr_ms=0.0,
            hr_bpm=75.0,
            score=0.90,
            flags=0x09,
        )
    )

    # 第二个固件 Winner 落在主峰前 240 ms。
    # recovered=True 且相关质量高时允许跨过旧版 ±96 ms 限制。
    source_t_us = 1_616_000
    target_t_us = 1_856_000

    engine._fiducial_refiner.refine = (
        lambda beat, samples, **kwargs: FiducialResult(
            t_us=target_t_us,
            quality=0.92,
            uncertainty_ms=12.0,
            shift_ms=240.0,
            correlation=0.96,
            refined=True,
            polarity=1,
            recovered=True,
        )
    )

    engine.ingest_beat(
        BeatFrame(
            seq=101,
            t_us=source_t_us,
            rr_ms=560.0,
            hr_bpm=75.0,
            score=0.64,
            flags=0x09,
        )
    )

    refined = engine.export_bundle()[
        "raw_beats"
    ]

    assert len(refined) == 2
    assert refined[-1].t_us == target_t_us
    assert refined[-1].timing_recovered
    assert refined[-1].refined
