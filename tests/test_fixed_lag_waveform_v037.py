from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from hrv_app.config import AnalysisConfig
from hrv_app.engine import AnalysisEngine
from hrv_app.models import BeatFrame, SampleFrame
from hrv_app.rr_cleaner import BeatTimelineCleaner


def _pulse_samples(
    *,
    rr_ms: float = 800.0,
    duration_s: float = 20.0,
    amplitude: float = 100.0,
    secondary_ratio: float = 0.0,
) -> list[SampleFrame]:
    result: list[SampleFrame] = []

    sample_rate = 125.0

    for seq in range(
        int(
            duration_s
            * sample_rate
        )
    ):
        t_ms = (
            seq
            * 1000.0
            / sample_rate
        )
        phase = (
            t_ms
            % rr_ms
        )

        main = (
            amplitude
            * math.exp(
                -0.5
                * (
                    (
                        phase
                        - 0.32
                        * rr_ms
                    )
                    / (
                        0.085
                        * rr_ms
                    )
                ) ** 2
            )
        )

        secondary = (
            amplitude
            * secondary_ratio
            * math.exp(
                -0.5
                * (
                    (
                        phase
                        - 0.62
                        * rr_ms
                    )
                    / (
                        0.055
                        * rr_ms
                    )
                ) ** 2
            )
        )

        baseline = (
            8.0
            * math.sin(
                2.0
                * math.pi
                * t_ms
                / 6000.0
            )
        )

        result.append(
            SampleFrame(
                seq=seq,
                t_us=int(
                    round(
                        t_ms
                        * 1000.0
                    )
                ),
                raw=300.0,
                avg=290.0,
                filtered=(
                    main
                    + secondary
                    + baseline
                ),
                peak=0,
                hr_bpm=(
                    60000.0
                    / rr_ms
                ),
                detector_score=0.0,
                expected_rr_ms=rr_ms,
                flags=1,
            )
        )

    return result


def _feed(
    engine: AnalysisEngine,
    samples: list[SampleFrame],
    firmware: list[BeatFrame],
) -> None:
    beat_index = 0

    for sample in samples:
        engine.ingest_sample(
            sample
        )

        while (
            beat_index
            < len(
                firmware
            )
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


def test_formal_timeline_exists_even_when_firmware_reports_no_beats():
    engine = AnalysisEngine()

    samples = _pulse_samples(
        rr_ms=800.0,
        duration_s=12.0,
    )

    _feed(
        engine,
        samples,
        [],
    )

    engine.force_update()

    formal = engine.export_bundle()[
        "raw_beats"
    ]

    assert len(formal) >= 13

    rr = np.asarray(
        [
            beat.rr_ms
            for beat in formal
            if beat.rr_ms > 0
        ],
        dtype=float,
    )

    assert abs(
        float(
            np.median(
                rr
            )
        )
        - 800.0
    ) < 12.0

    assert all(
        beat.correction_method
        == "fixed_lag_waveform"
        for beat in formal
    )

    assert all(
        beat.matched_firmware_t_us
        == 0
        for beat in formal
    )


def test_same_cycle_secondary_peak_does_not_double_formal_rate():
    engine = AnalysisEngine()

    samples = _pulse_samples(
        rr_ms=800.0,
        duration_s=16.0,
        secondary_ratio=0.68,
    )

    # 模拟固件把主峰和同周期次级峰都报出来。
    firmware: list[BeatFrame] = []

    for cycle in range(1, 18):
        main_t = int(
            round(
                (
                    cycle
                    * 800.0
                    + 0.32
                    * 800.0
                )
                * 1000.0
            )
        )
        secondary_t = int(
            round(
                (
                    cycle
                    * 800.0
                    + 0.62
                    * 800.0
                )
                * 1000.0
            )
        )

        for t_us, score in (
            (
                main_t,
                0.88,
            ),
            (
                secondary_t,
                0.62,
            ),
        ):
            if (
                t_us
                < samples[-1].t_us
            ):
                firmware.append(
                    BeatFrame(
                        seq=len(
                            firmware
                        ),
                        t_us=t_us,
                        rr_ms=400.0,
                        hr_bpm=150.0,
                        score=score,
                        flags=0x09,
                    )
                )

    firmware.sort(
        key=lambda beat:
            beat.t_us
    )

    _feed(
        engine,
        samples,
        firmware,
    )

    engine.force_update()

    formal = engine.export_bundle()[
        "raw_beats"
    ]

    rr = np.asarray(
        [
            beat.rr_ms
            for beat in formal
            if beat.rr_ms > 0
        ],
        dtype=float,
    )

    assert 760.0 <= np.median(
        rr
    ) <= 840.0

    # 不允许因为次级峰把 75 bpm 变成约 150 bpm。
    assert np.percentile(
        rr,
        5,
    ) > 600.0


def test_fixed_lag_output_commit_is_within_eight_seconds():
    cfg = AnalysisConfig()
    engine = AnalysisEngine(
        cfg
    )

    samples = _pulse_samples(
        rr_ms=800.0,
        duration_s=24.0,
    )

    seen_count = 0
    observed_lags_s: list[
        float
    ] = []

    for sample in samples:
        engine.ingest_sample(
            sample
        )

        # 测试实时提交时刻，不调用 export_bundle()，避免每个 Sample
        # 都触发整段 RR 清洗 / HRV 统计。
        current_count = len(
            engine._raw_beats
        )

        if current_count <= seen_count:
            continue

        new_beats = list(
            engine._raw_beats
        )[
            seen_count:
            current_count
        ]

        for beat in new_beats:
            observed_lags_s.append(
                (
                    sample.t_us
                    - beat.t_us
                )
                / 1e6
            )

        seen_count = current_count

    assert observed_lags_s

    # 0.20 s 运行周期 + 7.25 s 目标滞后，应给 8 s 硬约束留余量。
    assert max(
        observed_lags_s
    ) <= (
        cfg.correction_max_output_lag_seconds
        + 0.05
    )


def test_future_aware_cleaner_does_not_cascade_after_stable_rate_step():
    cleaner = BeatTimelineCleaner(
        AnalysisConfig()
    )

    rr_series = (
        [800.0] * 24
        + [900.0] * 24
    )

    beats: list[
        BeatFrame
    ] = []

    t_us = 0

    for index, rr_ms in enumerate(
        rr_series
    ):
        t_us += int(
            round(
                rr_ms
                * 1000.0
            )
        )

        beats.append(
            BeatFrame(
                seq=index,
                t_us=t_us,
                rr_ms=rr_ms,
                hr_bpm=(
                    60000.0
                    / rr_ms
                ),
                score=0.95,
                flags=1,
                timing_quality=0.95,
                timing_uncertainty_ms=8.0,
                refined=True,
                correction_method=(
                    "fixed_lag_waveform"
                ),
                waveform_score=0.95,
                reference_rr_ms=rr_ms,
            )
        )

    cleaned = cleaner.clean(
        beats
    )

    unresolved = [
        record
        for record in cleaned.records
        if record.status
        not in {
            "accepted",
        }
    ]

    assert len(
        unresolved
    ) <= 1
    assert cleaned.quality.max_consecutive_artifacts <= 1


def test_ui_has_only_ppg_and_formal_beat_continuous_curves():
    root = (
        Path(__file__)
        .resolve()
        .parents[1]
    )

    ui = (
        root
        / "desktop"
        / "src"
        / "hrv_app"
        / "ui_app.py"
    ).read_text(
        encoding="utf-8"
    )

    assert "self.signal_curve =" in ui
    assert "self.accepted_beat_curve =" in ui

    assert "self.detector_score_curve =" not in ui
    assert "self.candidate_curve =" not in ui
    assert "self.firmware_accepted_curve =" not in ui

    # 人工标注保留半透明区，不再增加第三根竖线。
    assert "self.annotation_region =" in ui
    assert "self.annotation_line =" not in ui


def test_v037_firmware_detector_source_is_unchanged_from_v036():
    """
    失败版 v0.3.7 的 HOLD / trusted-state 固件改动必须彻底撤销。

    这里只做结构硬门，完整制包阶段还会做整个 firmware/ 的字节哈希比较。
    """
    root = (
        Path(__file__)
        .resolve()
        .parents[1]
    )

    detector = (
        root
        / "firmware"
        / "lib"
        / "zeezPPG"
        / "src"
        / "zeez_detector.cpp"
    ).read_text(
        encoding="utf-8"
    )

    assert "rhythm_hold_active_" not in detector
    assert "trusted_state_update" not in detector
    assert "STATE_UPDATE_HELD" not in detector



def test_fixed_lag_waveform_preserves_real_rr_variation():
    """
    Hard negative：
    8 秒未来窗口只能帮助找“真实波顶”，不能把真实 HRV 拉成等间隔。
    """
    fs = 125.0
    rr_ms_series = [
        760.0,
        840.0,
        720.0,
        900.0,
        780.0,
        860.0,
        740.0,
        880.0,
        800.0,
        830.0,
        750.0,
        910.0,
        790.0,
        850.0,
        730.0,
        890.0,
        810.0,
        770.0,
        870.0,
        760.0,
        840.0,
        720.0,
        900.0,
        780.0,
        860.0,
        740.0,
        880.0,
        800.0,
    ]

    beat_times_s = [
        0.65
    ]

    for rr_ms in rr_ms_series:
        beat_times_s.append(
            beat_times_s[-1]
            + rr_ms
            / 1000.0
        )

    duration_s = (
        beat_times_s[-1]
        + 1.5
    )

    t = np.arange(
        0.0,
        duration_s,
        1.0 / fs,
        dtype=float,
    )

    y = np.zeros_like(t)

    for beat_time in beat_times_s:
        y += 120.0 * np.exp(
            -0.5
            * (
                (
                    t
                    - beat_time
                )
                / 0.055
            ) ** 2
        )

    samples = [
        SampleFrame(
            seq=index,
            t_us=int(
                round(
                    seconds
                    * 1e6
                )
            ),
            raw=300.0,
            avg=290.0,
            filtered=float(
                value
            ),
            peak=0,
            hr_bpm=75.0,
            detector_score=0.0,
            expected_rr_ms=800.0,
            flags=1,
        )
        for index, (
            seconds,
            value,
        )
        in enumerate(
            zip(
                t,
                y,
                strict=False,
            )
        )
    ]

    engine = AnalysisEngine()

    for sample in samples:
        engine.ingest_sample(
            sample
        )

    engine.force_update()

    formal = engine.export_bundle()[
        "raw_beats"
    ]

    predicted_t = np.asarray(
        [
            beat.t_us
            / 1e6
            for beat in formal
        ],
        dtype=float,
    )

    truth_t = np.asarray(
        beat_times_s,
        dtype=float,
    )

    # 边界保护允许少量首尾差异；内部波顶必须跟随真实不规则时刻。
    offsets = []

    for value in predicted_t:
        offsets.append(
            float(
                np.min(
                    np.abs(
                        truth_t
                        - value
                    )
                )
            )
        )

    assert len(
        predicted_t
    ) >= len(
        truth_t
    ) - 2

    assert np.percentile(
        offsets,
        95,
    ) < 0.03

    predicted_rr = np.diff(
        predicted_t
    ) * 1000.0

    # 真正 RR 变化必须仍然存在，不能被 reference RR 正则化掉。
    assert np.std(
        predicted_rr
    ) > 45.0
    assert np.percentile(
        predicted_rr,
        95,
    ) - np.percentile(
        predicted_rr,
        5,
    ) > 120.0


def test_future_aware_cleaner_preserves_smooth_physiological_hrv():
    cfg = AnalysisConfig()
    cleaner = BeatTimelineCleaner(
        cfg
    )

    beats: list[
        BeatFrame
    ] = []

    t_us = 0
    raw_rr: list[float] = []

    for index in range(72):
        rr_ms = (
            800.0
            + 70.0
            * math.sin(
                2.0
                * math.pi
                * index
                / 13.0
            )
        )

        raw_rr.append(
            rr_ms
        )
        t_us += int(
            round(
                rr_ms
                * 1000.0
            )
        )

        beats.append(
            BeatFrame(
                seq=index,
                t_us=t_us,
                rr_ms=rr_ms,
                hr_bpm=(
                    60000.0
                    / rr_ms
                ),
                score=0.95,
                flags=1,
                timing_quality=0.95,
                timing_uncertainty_ms=8.0,
                refined=True,
                correction_method=(
                    "fixed_lag_waveform"
                ),
                waveform_score=0.95,
                reference_rr_ms=800.0,
            )
        )

    cleaned = cleaner.clean(
        beats
    )

    accepted = [
        record
        for record
        in cleaned.records
        if (
            record.status
            == "accepted"
            and record.nn_ms
            > 0
        )
    ]

    assert len(
        accepted
    ) >= 68

    accepted_rr = np.asarray(
        [
            record.nn_ms
            for record
            in accepted
        ],
        dtype=float,
    )

    # 未来感知清洗只做质量判断，不把生理 HRV 压平成 reference RR。
    assert np.std(
        accepted_rr
    ) > 40.0
    assert (
        np.percentile(
            accepted_rr,
            95,
        )
        - np.percentile(
            accepted_rr,
            5,
        )
    ) > 100.0
