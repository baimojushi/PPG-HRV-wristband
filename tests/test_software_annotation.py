from __future__ import annotations

from pathlib import Path

from hrv_app.annotation_analysis import build_annotation_context
from hrv_app.engine import AnalysisEngine
from hrv_app.models import SampleFrame, UserAnnotation
from hrv_app.storage import SessionRecorder, export_engine_results


def make_sample(
    seq: int,
    t_us: int,
    *,
    filtered: float = 20.0,
    detector_score: float = 0.4,
    peak: int = 0,
) -> SampleFrame:
    return SampleFrame(
        seq=seq,
        t_us=t_us,
        raw=300.0,
        avg=290.0,
        filtered=filtered,
        peak=peak,
        hr_bpm=75.0,
        detector_score=detector_score,
        expected_rr_ms=800.0,
        flags=1,
    )


def test_annotation_uses_displayed_device_time_not_newest_sample():
    engine = AnalysisEngine()

    # 设备已经收到到 10.8 s，但 UI 最近一次真正绘制到 10.4 s。
    for index in range(101):
        engine.ingest_sample(
            make_sample(
                index,
                10_000_000
                + index
                * 8_000,
            )
        )

    displayed_t_us = 10_400_000

    before = engine.export_bundle()

    annotation = engine.add_user_annotation(
        device_t_us=displayed_t_us,
        host_monotonic_ns=123456789,
        label_type="峰位漂移",
    )

    assert annotation is not None
    assert annotation.device_t_us == displayed_t_us
    assert annotation.latest_sample_t_us == 10_800_000
    assert annotation.ui_data_lag_ms == 400.0

    assert annotation.label_start_us == 7_400_000
    assert annotation.label_end_us == 10_400_000
    assert annotation.label_type == "峰位漂移"
    assert annotation.source == "software_ui"

    after = engine.export_bundle()

    # 人工标注是单向观测，不改变 PPG / Beat / NN。
    assert len(after["samples"]) == len(before["samples"])
    assert len(after["firmware_beats"]) == len(before["firmware_beats"])
    assert len(after["raw_beats"]) == len(before["raw_beats"])
    assert len(after["nn_intervals"]) == len(before["nn_intervals"])
    assert len(after["annotations"]) == 1


def test_recent_debug_freezes_right_edge_for_ui_annotation():
    engine = AnalysisEngine()

    for index in range(200):
        engine.ingest_sample(
            make_sample(
                index,
                1_000_000
                + index
                * 8_000,
            )
        )

    *_, stats = engine.recent_signal_debug(
        12.0
    )

    assert stats["end_t_us"] == (
        1_000_000
        + 199
        * 8_000
    )
    assert stats["annotation_count"] == 0

    annotation = engine.add_user_annotation(
        device_t_us=stats["end_t_us"],
        host_monotonic_ns=99,
    )

    assert annotation is not None

    *_, stats_after = engine.recent_signal_debug(
        12.0
    )

    assert stats_after["annotation_count"] == 1
    assert stats_after["recent_annotation_count"] == 1
    assert stats_after["last_annotation_age_s"] == 0.0


def test_annotation_context_detects_slow_precursor_drift():
    engine = AnalysisEngine()
    cfg = engine.config

    annotation = UserAnnotation(
        annotation_id=1,
        device_t_us=120_000_000,
        latest_sample_t_us=120_100_000,
        latest_sample_seq=120,
        label_start_us=117_000_000,
        label_end_us=120_000_000,
        host_monotonic_ns=1,
        label_type="周期跳变",
        ui_data_lag_ms=100.0,
    )

    samples = []

    # 远期 0~90 s 稳定；最后 30 s 基线和 detector score 缓慢上升。
    # 这里只验证长时程特征提取，不代表实际生理根因。
    for second in range(126):
        drift = max(
            second - 90,
            0,
        )

        samples.append(
            make_sample(
                second,
                second
                * 1_000_000,
                filtered=20.0 + drift,
                detector_score=(
                    0.40
                    + 0.005
                    * drift
                ),
                peak=(
                    1
                    if second % 2 == 0
                    else 0
                ),
            )
        )

    rows, summary = build_annotation_context(
        samples=samples,
        firmware_beats=[],
        refined_beats=[],
        cleaned_beats=[],
        annotations=[
            annotation
        ],
        config=cfg,
    )

    assert rows
    assert summary["annotation_count"] == 1

    item = summary["annotations"][0]

    baseline = item[
        "far_vs_near"
    ][
        "filtered_baseline_median"
    ]

    score = item[
        "far_vs_near"
    ][
        "detector_score_mean"
    ]

    assert baseline["near_minus_far"] > 5.0
    assert score["near_minus_far"] > 0.02

    label_rows = [
        row
        for row in rows
        if row[
            "inside_user_label_window"
        ]
    ]

    assert len(label_rows) >= 3


def test_session_recorder_flushes_software_annotation_and_export_keeps_raw_session(
    tmp_path: Path,
):
    engine = AnalysisEngine()
    recorder = SessionRecorder(
        tmp_path / "sessions"
    )

    for index in range(20):
        sample = make_sample(
            index,
            5_000_000
            + index
            * 8_000,
        )
        recorder.record(sample)
        engine.ingest_sample(sample)

    *_, stats = engine.recent_signal_debug(
        12.0
    )

    annotation = engine.add_user_annotation(
        device_t_us=stats["end_t_us"],
        host_monotonic_ns=123,
        label_type="漏检",
    )

    assert annotation is not None

    recorder.record_annotation(
        annotation
    )

    live_text = (
        recorder.session_dir
        / "annotations.csv"
    ).read_text(
        encoding="utf-8-sig"
    )

    # record_annotation() 内部立即 flush。
    assert "software_ui" in live_text
    assert "漏检" in live_text

    recorder.close()

    out = export_engine_results(
        engine,
        tmp_path / "export",
        raw_session_dir=(
            recorder.session_dir
        ),
    )

    assert (
        out
        / "annotations.csv"
    ).is_file()

    assert (
        out
        / "annotation_context_1s.csv"
    ).is_file()

    assert (
        out
        / "annotation_summary.json"
    ).is_file()

    assert (
        out
        / "raw_session"
        / "samples.csv"
    ).is_file()

    assert (
        out
        / "raw_session"
        / "annotations.csv"
    ).is_file()

    summary_text = (
        out
        / "annotation_summary.json"
    ).read_text(
        encoding="utf-8"
    )

    assert '"annotation_count": 1' in summary_text
    assert "displayed" in summary_text or "right edge" in summary_text


def test_ui_contains_non_blocking_f8_software_mark():
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

    assert 'QKeySequence("F8")' in ui
    assert "标记异常 · F8" in ui
    assert "_displayed_end_t_us" in ui
    assert "time.monotonic_ns()" in ui
    assert "record_annotation" in ui

    # 软件标注入口不得触发检测器参数修改或固件写操作。
    mark_method = ui.split(
        "def _mark_annotation",
        1,
    )[1].split(
        "def _export_results",
        1,
    )[0]

    assert "setWearThreshold" not in mark_method
    assert "detector_legacy_peak_factor" not in mark_method
    assert "serial.write" not in mark_method
