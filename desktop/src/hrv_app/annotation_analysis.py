from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
import math

import numpy as np

from .config import AnalysisConfig
from .models import (
    BeatFrame,
    BeatRecord,
    SampleFrame,
    UserAnnotation,
)


UNRESOLVED_STATUSES = {
    "hard_outlier",
    "local_outlier",
    "no_wear",
    "unresolved",
}


def _finite_array(values) -> np.ndarray:
    array = np.asarray(
        list(values),
        dtype=float,
    )
    return array[
        np.isfinite(array)
    ]


def _mean_or_nan(values) -> float:
    array = _finite_array(values)
    return (
        float(np.mean(array))
        if array.size
        else float("nan")
    )


def _median_or_nan(values) -> float:
    array = _finite_array(values)
    return (
        float(np.median(array))
        if array.size
        else float("nan")
    )


def _percentile_or_nan(
    values,
    percentile: float,
) -> float:
    array = _finite_array(values)
    return (
        float(
            np.percentile(
                array,
                percentile,
            )
        )
        if array.size
        else float("nan")
    )


def _slope_per_minute(
    x_seconds,
    y_values,
) -> float:
    x = np.asarray(
        list(x_seconds),
        dtype=float,
    )
    y = np.asarray(
        list(y_values),
        dtype=float,
    )

    valid = (
        np.isfinite(x)
        & np.isfinite(y)
    )

    if np.count_nonzero(valid) < 5:
        return float("nan")

    x = x[valid]
    y = y[valid]
    x = x - float(
        np.mean(x)
    )

    denominator = float(
        np.sum(
            x * x
        )
    )

    if denominator <= 1e-12:
        return float("nan")

    slope_per_second = float(
        np.sum(
            x
            * (
                y
                - float(
                    np.mean(y)
                )
            )
        )
        / denominator
    )

    return (
        slope_per_second
        * 60.0
    )


def _rolling_mean(
    rows: list[dict],
    index: int,
    field: str,
    window_seconds: float,
) -> float:
    current_t = float(
        rows[index][
            "relative_center_s"
        ]
    )
    minimum_t = (
        current_t
        - window_seconds
    )

    return _mean_or_nan(
        row[field]
        for row in rows[: index + 1]
        if (
            float(
                row[
                    "relative_center_s"
                ]
            )
            >= minimum_t
        )
    )


def _rolling_slope(
    rows: list[dict],
    index: int,
    field: str,
    window_seconds: float,
) -> float:
    current_t = float(
        rows[index][
            "relative_center_s"
        ]
    )
    minimum_t = (
        current_t
        - window_seconds
    )

    selected = [
        row
        for row in rows[: index + 1]
        if (
            float(
                row[
                    "relative_center_s"
                ]
            )
            >= minimum_t
        )
    ]

    return _slope_per_minute(
        [
            row[
                "relative_center_s"
            ]
            for row in selected
        ],
        [
            row[field]
            for row in selected
        ],
    )


def _auto_focus(
    annotation: UserAnnotation,
    cleaned_beats: Sequence[BeatRecord],
    refined_beats: Sequence[BeatFrame],
) -> tuple[int, str]:
    """
    人工标签只声明“问题发生在软件按键前 3 秒内”。

    auto_focus 是方便下一轮定位的算法候选点，
    不修改人工标签的原始语义。
    """
    cleaned = [
        beat
        for beat in cleaned_beats
        if (
            annotation.label_start_us
            <= beat.t_us
            <= annotation.label_end_us
        )
    ]

    artifacts = [
        beat
        for beat in cleaned
        if beat.status
        != "accepted"
    ]

    if artifacts:
        rr_values = _finite_array(
            beat.rr_raw_ms
            for beat in cleaned
            if beat.rr_raw_ms > 0
        )

        reference = (
            float(
                np.median(
                    rr_values
                )
            )
            if rr_values.size
            else 0.0
        )

        target = max(
            artifacts,
            key=lambda beat:
                abs(
                    float(
                        beat.rr_raw_ms
                    )
                    - reference
                )
                if reference > 0
                else 1.0,
        )

        return (
            int(
                target.t_us
            ),
            "cleaned_rr_artifact",
        )

    refined = [
        beat
        for beat in refined_beats
        if (
            annotation.label_start_us
            <= beat.t_us
            <= annotation.label_end_us
        )
    ]

    if refined:
        target = min(
            refined,
            key=lambda beat:
                float(
                    beat.timing_quality
                ),
        )

        return (
            int(
                target.t_us
            ),
            "minimum_fiducial_quality",
        )

    return (
        int(
            annotation.device_t_us
        ),
        "display_edge_no_algorithm_candidate",
    )


def build_annotation_context(
    samples: Sequence[SampleFrame],
    firmware_beats: Sequence[BeatFrame],
    refined_beats: Sequence[BeatFrame],
    cleaned_beats: Sequence[BeatRecord],
    annotations: Sequence[UserAnnotation],
    config: AnalysisConfig | None = None,
) -> tuple[
    list[dict],
    dict,
]:
    """
    以软件人工标注为中心生成长时程上下文。

    每个标注默认：
    - 前 120 秒：检查低频累积；
    - 前 3 秒：人工问题区间；
    - 后 5 秒：观察自动恢复。

    1 秒粒度同时保存 30 秒水平和 60 秒趋势斜率。
    """
    cfg = config or AnalysisConfig()

    before_s = float(
        cfg.user_annotation_context_before_seconds
    )
    after_s = float(
        cfg.user_annotation_context_after_seconds
    )
    bin_s = float(
        cfg.user_annotation_context_bin_seconds
    )

    rows: list[dict] = []
    summaries: list[dict] = []

    for annotation in annotations:
        event_samples = [
            sample
            for sample in samples
            if (
                annotation.device_t_us
                - before_s * 1e6
                <= sample.t_us
                <= annotation.device_t_us
                + after_s * 1e6
            )
        ]

        event_firmware = [
            beat
            for beat in firmware_beats
            if (
                annotation.device_t_us
                - before_s * 1e6
                <= beat.t_us
                <= annotation.device_t_us
                + after_s * 1e6
            )
        ]

        event_refined = [
            beat
            for beat in refined_beats
            if (
                annotation.device_t_us
                - before_s * 1e6
                <= beat.t_us
                <= annotation.device_t_us
                + after_s * 1e6
            )
        ]

        event_cleaned = [
            beat
            for beat in cleaned_beats
            if (
                annotation.device_t_us
                - before_s * 1e6
                <= beat.t_us
                <= annotation.device_t_us
                + after_s * 1e6
            )
        ]

        event_rows: list[dict] = []

        relative_edges = np.arange(
            -before_s,
            after_s + bin_s + 1e-9,
            bin_s,
            dtype=float,
        )

        for edge_index in range(
            len(relative_edges) - 1
        ):
            rel_start = float(
                relative_edges[
                    edge_index
                ]
            )
            rel_end = float(
                relative_edges[
                    edge_index + 1
                ]
            )

            bin_start_us = int(
                round(
                    annotation.device_t_us
                    + rel_start
                    * 1e6
                )
            )
            bin_end_us = int(
                round(
                    annotation.device_t_us
                    + rel_end
                    * 1e6
                )
            )

            sample_bin = [
                sample
                for sample in event_samples
                if (
                    bin_start_us
                    <= sample.t_us
                    < bin_end_us
                )
            ]

            firmware_bin = [
                beat
                for beat in event_firmware
                if (
                    bin_start_us
                    <= beat.t_us
                    < bin_end_us
                )
            ]

            refined_bin = [
                beat
                for beat in event_refined
                if (
                    bin_start_us
                    <= beat.t_us
                    < bin_end_us
                )
            ]

            cleaned_bin = [
                beat
                for beat in event_cleaned
                if (
                    bin_start_us
                    <= beat.t_us
                    < bin_end_us
                )
            ]

            filtered = _finite_array(
                sample.filtered
                for sample in sample_bin
            )

            row = {
                "annotation_id": (
                    annotation.annotation_id
                ),
                "label_type": (
                    annotation.label_type
                ),
                "device_t_us": int(
                    annotation.device_t_us
                ),
                "label_start_us": int(
                    annotation.label_start_us
                ),
                "label_end_us": int(
                    annotation.label_end_us
                ),
                "relative_start_s": rel_start,
                "relative_end_s": rel_end,
                "relative_center_s": (
                    0.5
                    * (
                        rel_start
                        + rel_end
                    )
                ),
                "inside_user_label_window": int(
                    (
                        bin_end_us
                        > annotation.label_start_us
                    )
                    and (
                        bin_start_us
                        <= annotation.label_end_us
                    )
                ),

                "sample_count": len(
                    sample_bin
                ),
                "filtered_baseline_median": (
                    float(
                        np.median(
                            filtered
                        )
                    )
                    if filtered.size
                    else float("nan")
                ),
                "filtered_amplitude_p90_p10": (
                    float(
                        np.percentile(
                            filtered,
                            90,
                        )
                        - np.percentile(
                            filtered,
                            10,
                        )
                    )
                    if filtered.size
                    else float("nan")
                ),
                "detector_score_mean": (
                    _mean_or_nan(
                        sample.detector_score
                        for sample
                        in sample_bin
                    )
                ),
                "detector_score_p90": (
                    _percentile_or_nan(
                        (
                            sample.detector_score
                            for sample
                            in sample_bin
                        ),
                        90.0,
                    )
                ),
                "candidate_count": int(
                    sum(
                        bool(
                            sample.peak
                        )
                        for sample
                        in sample_bin
                    )
                ),
                "candidate_rate_hz": float(
                    sum(
                        bool(
                            sample.peak
                        )
                        for sample
                        in sample_bin
                    )
                    / max(
                        rel_end
                        - rel_start,
                        1e-9,
                    )
                ),
                "expected_rr_median_ms": (
                    _median_or_nan(
                        sample.expected_rr_ms
                        for sample
                        in sample_bin
                        if (
                            sample.expected_rr_ms
                            > 0
                        )
                    )
                ),
                "sample_hr_median_bpm": (
                    _median_or_nan(
                        sample.hr_bpm
                        for sample
                        in sample_bin
                        if sample.hr_bpm > 0
                    )
                ),

                "firmware_beat_count": len(
                    firmware_bin
                ),
                "firmware_score_mean": (
                    _mean_or_nan(
                        beat.score
                        for beat
                        in firmware_bin
                    )
                ),
                "firmware_score_min": (
                    float(
                        np.min(
                            _finite_array(
                                beat.score
                                for beat
                                in firmware_bin
                            )
                        )
                    )
                    if firmware_bin
                    else float("nan")
                ),
                "firmware_rr_median_ms": (
                    _median_or_nan(
                        beat.rr_ms
                        for beat
                        in firmware_bin
                        if beat.rr_ms > 0
                    )
                ),

                "refined_beat_count": len(
                    refined_bin
                ),
                "timing_quality_mean": (
                    _mean_or_nan(
                        beat.timing_quality
                        for beat
                        in refined_bin
                    )
                ),
                "timing_quality_min": (
                    float(
                        np.min(
                            _finite_array(
                                beat.timing_quality
                                for beat
                                in refined_bin
                            )
                        )
                    )
                    if refined_bin
                    else float("nan")
                ),
                "timing_uncertainty_p95_ms": (
                    _percentile_or_nan(
                        (
                            beat.timing_uncertainty_ms
                            for beat
                            in refined_bin
                        ),
                        95.0,
                    )
                ),
                "timing_abs_shift_p95_ms": (
                    _percentile_or_nan(
                        (
                            abs(
                                beat.timing_shift_ms
                            )
                            for beat
                            in refined_bin
                        ),
                        95.0,
                    )
                ),
                "timing_recovery_count": int(
                    sum(
                        bool(
                            beat.timing_recovered
                        )
                        for beat
                        in refined_bin
                    )
                ),

                # v0.3.7 fixed-lag waveform evidence.
                "waveform_score_mean": (
                    _mean_or_nan(
                        beat.waveform_score
                        for beat
                        in refined_bin
                    )
                ),
                "waveform_reference_rr_median_ms": (
                    _median_or_nan(
                        beat.reference_rr_ms
                        for beat
                        in refined_bin
                        if (
                            beat.reference_rr_ms
                            > 0
                        )
                    )
                ),
                "waveform_inserted_count": int(
                    sum(
                        bool(
                            beat.inserted_by_smoother
                        )
                        for beat
                        in refined_bin
                    )
                ),
                "waveform_low_prominence_rescue_count": int(
                    sum(
                        bool(
                            beat.low_prominence_rescue
                        )
                        for beat
                        in refined_bin
                    )
                ),
                "waveform_firmware_matched_count": int(
                    sum(
                        bool(
                            beat.matched_firmware_t_us
                        )
                        for beat
                        in refined_bin
                    )
                ),

                # Firmware Rescue remains a diagnostic of the raw detector.
                "rescue_count": int(
                    sum(
                        bool(
                            beat.flags
                            & 0x10
                        )
                        for beat
                        in firmware_bin
                    )
                ),

                "cleaned_beat_count": len(
                    cleaned_bin
                ),
                "artifact_count": int(
                    sum(
                        beat.status
                        != "accepted"
                        for beat
                        in cleaned_bin
                    )
                ),
                "unresolved_count": int(
                    sum(
                        beat.status
                        in UNRESOLVED_STATUSES
                        for beat
                        in cleaned_bin
                    )
                ),
                "accepted_nn_count": int(
                    sum(
                        beat.status
                        == "accepted"
                        and beat.metric_eligible
                        for beat
                        in cleaned_bin
                    )
                ),
            }

            event_rows.append(
                row
            )

        trend_fields = [
            "filtered_baseline_median",
            "filtered_amplitude_p90_p10",
            "detector_score_mean",
            "candidate_rate_hz",
            "expected_rr_median_ms",
            "firmware_score_mean",
            "timing_quality_mean",
        ]

        for index, row in enumerate(
            event_rows
        ):
            for field in trend_fields:
                row[
                    f"{field}_roll30"
                ] = _rolling_mean(
                    event_rows,
                    index,
                    field,
                    30.0,
                )
                row[
                    f"{field}_slope60_per_min"
                ] = _rolling_slope(
                    event_rows,
                    index,
                    field,
                    60.0,
                )

        rows.extend(
            event_rows
        )

        far_rows = [
            row
            for row in event_rows
            if (
                -120.0
                <= row[
                    "relative_center_s"
                ]
                < -30.0
            )
        ]

        near_rows = [
            row
            for row in event_rows
            if (
                -30.0
                <= row[
                    "relative_center_s"
                ]
                <= 0.0
            )
        ]

        compare_fields = [
            "filtered_baseline_median",
            "filtered_amplitude_p90_p10",
            "detector_score_mean",
            "candidate_rate_hz",
            "expected_rr_median_ms",
            "firmware_score_mean",
            "timing_quality_mean",
        ]

        comparison: dict[str, dict] = {}

        for field in compare_fields:
            far = _mean_or_nan(
                row[field]
                for row in far_rows
            )
            near = _mean_or_nan(
                row[field]
                for row in near_rows
            )

            comparison[field] = {
                "far_mean": far,
                "near_mean": near,
                "near_minus_far": (
                    near - far
                    if (
                        math.isfinite(far)
                        and math.isfinite(near)
                    )
                    else float("nan")
                ),
            }

        focus_t_us, focus_basis = _auto_focus(
            annotation,
            cleaned_beats,
            refined_beats,
        )

        summaries.append({
            **asdict(
                annotation
            ),
            "auto_focus_t_us": int(
                focus_t_us
            ),
            "auto_focus_relative_s": float(
                (
                    focus_t_us
                    - annotation.device_t_us
                )
                / 1e6
            ),
            "auto_focus_basis": (
                focus_basis
            ),
            "far_vs_near": comparison,
        })

    # 多次标注只有在相同低频量反复同向变化时，才支持“长期积累”假设。
    aggregate_far_vs_near: dict[str, dict] = {}

    compare_fields = [
        "filtered_baseline_median",
        "filtered_amplitude_p90_p10",
        "detector_score_mean",
        "candidate_rate_hz",
        "expected_rr_median_ms",
        "firmware_score_mean",
        "timing_quality_mean",
    ]

    for field in compare_fields:
        deltas = _finite_array(
            item[
                "far_vs_near"
            ][field][
                "near_minus_far"
            ]
            for item in summaries
        )

        aggregate_far_vs_near[field] = {
            "count": int(
                deltas.size
            ),
            "mean_delta": (
                float(
                    np.mean(
                        deltas
                    )
                )
                if deltas.size
                else float("nan")
            ),
            "median_delta": (
                float(
                    np.median(
                        deltas
                    )
                )
                if deltas.size
                else float("nan")
            ),
            "positive_fraction": (
                float(
                    np.mean(
                        deltas > 0
                    )
                )
                if deltas.size
                else float("nan")
            ),
        }

    return (
        rows,
        {
            "annotation_count": len(
                annotations
            ),
            "label_semantics": (
                "user observed a problem within the "
                "3 seconds before the software mark"
            ),
            "timestamp_semantics": (
                "device_t_us is the right edge of the UI data "
                "actually visible when F8/button was pressed"
            ),
            "context_before_seconds": before_s,
            "context_after_seconds": after_s,
            "bin_seconds": bin_s,
            "annotations": summaries,
            "aggregate_far_vs_near": (
                aggregate_far_vs_near
            ),
        },
    )
