from __future__ import annotations

from pathlib import Path
import math

import numpy as np

from hrv_app.config import AnalysisConfig
from hrv_app.engine import AnalysisEngine
from hrv_app.fixed_lag_corrector import FixedLagWaveformCorrector
from hrv_app.models import BeatFrame, SampleFrame


def _sample(
    seq: int,
    t_us: int,
    filtered: float,
    *,
    candidate: int = 0,
) -> SampleFrame:
    return SampleFrame(
        seq=seq,
        t_us=t_us,
        raw=2000.0 + filtered,
        avg=2000.0,
        filtered=filtered,
        peak=candidate,
        hr_bpm=75.0,
        detector_score=0.5,
        expected_rr_ms=800.0,
        flags=1,
    )


def _synthetic_ppg(
    duration_s: float,
    rr_s: float = 0.80,
    fs: float = 125.0,
    *,
    weak_beat_index: int | None = None,
    double_peak: bool = False,
) -> tuple[list[SampleFrame], list[float]]:
    """
    生成有视觉主波的 PPG。

    每搏：
    - 主峰约 110 ms 宽；
    - 可选同一周期内较早、较弱的次级峰；
    - weak_beat_index 可把一搏幅度压低，测试长 gap 补峰。
    """
    t = np.arange(
        0.0,
        duration_s,
        1.0 / fs,
        dtype=float,
    )

    y = np.zeros_like(t)
    peaks: list[float] = []

    beat_time = 0.65
    beat_index = 0

    while beat_time < duration_s - 0.5:
        amplitude = (
            0.34
            if weak_beat_index == beat_index
            else 1.0
        )

        y += amplitude * np.exp(
            -0.5
            * (
                (
                    t - beat_time
                )
                / 0.055
            ) ** 2
        )

        if double_peak:
            # 同一物理周期里的早期弱峰，模拟腕部 PPG 常见双峰 / 肩峰。
            y += 0.55 * amplitude * np.exp(
                -0.5
                * (
                    (
                        t
                        - (
                            beat_time
                            - 0.23
                        )
                    )
                    / 0.045
                ) ** 2
            )

        peaks.append(
            beat_time
        )
        beat_time += rr_s
        beat_index += 1

    # 轻微慢漂移 + 确定性小噪声。
    y += 0.04 * np.sin(
        2.0
        * math.pi
        * 0.08
        * t
    )
    y += 0.008 * np.sin(
        2.0
        * math.pi
        * 7.0
        * t
    )

    samples = [
        _sample(
            index,
            int(
                round(
                    seconds
                    * 1e6
                )
            ),
            float(
                value
                * 180.0
            ),
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

    return (
        samples,
        peaks,
    )


def test_corrector_counts_one_main_wave_per_cycle_with_double_peak():
    cfg = AnalysisConfig()
    corrector = FixedLagWaveformCorrector(
        cfg
    )

    samples, truth = _synthetic_ppg(
        22.0,
        double_peak=True,
    )

    proposals = corrector.propose(
        samples=samples,
        firmware_beats=[],
        last_committed_t_us=0,
        rr_history_ms=[],
        commit_until_t_us=int(
            20.0 * 1e6
        ),
    )

    predicted_s = np.asarray(
        [
            proposal.t_us
            / 1e6
            for proposal in proposals
        ],
        dtype=float,
    )

    # propose() 单次只分析成熟点之前约 12 s 的历史；
    # 在线 Engine 会每 0.2 s 连续调用，所以更早 Beat 已在前次运行提交。
    truth_s = np.asarray(
        [
            value
            for value in truth
            if (
                8.0
                <= value
                <= 20.0
            )
        ],
        dtype=float,
    )

    assert abs(
        len(predicted_s)
        - len(truth_s)
    ) <= 1

    # 每个预测主波必须落在真实视觉主峰附近；
    # 较早的 -230 ms 次级峰不应成为正式 Beat。
    distances = [
        float(
            np.min(
                np.abs(
                    truth_s
                    - predicted
                )
            )
        )
        for predicted in predicted_s
    ]

    assert np.percentile(
        distances,
        95,
    ) < 0.07


def test_corrector_can_insert_waveform_beat_without_firmware_source():
    cfg = AnalysisConfig()
    corrector = FixedLagWaveformCorrector(
        cfg
    )

    samples, truth = _synthetic_ppg(
        18.0,
        weak_beat_index=8,
    )

    # Firmware 故意漏掉第 8 个主波。
    firmware = [
        BeatFrame(
            seq=index,
            t_us=int(
                round(
                    beat_time
                    * 1e6
                )
            ),
            rr_ms=800.0,
            hr_bpm=75.0,
            score=0.85,
            flags=1,
        )
        for index, beat_time in enumerate(
            truth
        )
        if index != 8
    ]

    proposals = corrector.propose(
        samples=samples,
        firmware_beats=firmware,
        last_committed_t_us=0,
        rr_history_ms=[
            800.0,
            805.0,
            795.0,
        ],
        commit_until_t_us=int(
            16.0 * 1e6
        ),
    )

    target_t_us = int(
        round(
            truth[8]
            * 1e6
        )
    )

    nearest = min(
        proposals,
        key=lambda proposal:
            abs(
                proposal.t_us
                - target_t_us
            ),
    )

    assert abs(
        nearest.t_us
        - target_t_us
    ) <= 80_000

    # 该正式 Beat 没有 Firmware source，说明漏检可以由波形层独立补回。
    assert nearest.inserted_by_smoother
    assert nearest.matched_firmware_t_us == 0


def test_engine_does_not_commit_formal_beat_before_fixed_lag_matures():
    cfg = AnalysisConfig()
    engine = AnalysisEngine(
        cfg
    )

    samples, _ = _synthetic_ppg(
        16.0
    )

    # 只送前 6 秒，不够 7.25 秒未来证据。
    for sample in samples:
        if sample.t_us > 6_000_000:
            break
        engine.ingest_sample(
            sample
        )

    early = engine.export_bundle()

    assert len(
        early[
            "raw_beats"
        ]
    ) == 0

    # 继续送完整 16 秒。
    for sample in samples:
        if sample.t_us <= 6_000_000:
            continue
        engine.ingest_sample(
            sample
        )

    mature = engine.export_bundle()
    beats = mature[
        "raw_beats"
    ]

    assert len(beats) >= 8

    latest_sample_t_us = samples[
        -1
    ].t_us

    assert all(
        beat.t_us
        <= latest_sample_t_us
        - int(
            round(
                cfg.correction_output_lag_seconds
                * 1e6
            )
        )
        + 300_000
        for beat in beats
    )


def test_firmware_beat_alone_never_enters_formal_hrv_timeline():
    engine = AnalysisEngine(
        AnalysisConfig()
    )

    firmware = BeatFrame(
        seq=1,
        t_us=1_000_000,
        rr_ms=800.0,
        hr_bpm=75.0,
        score=0.95,
        flags=1,
    )

    engine.ingest_beat(
        firmware
    )

    bundle = engine.export_bundle()

    assert len(
        bundle[
            "firmware_beats"
        ]
    ) == 1
    assert len(
        bundle[
            "raw_beats"
        ]
    ) == 0


def test_ui_has_only_ppg_and_formal_beat_continuous_series():
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
    assert "self.annotation_line =" not in ui

    # 人工标签仍保留为区间阴影。
    assert "self.annotation_region =" in ui
