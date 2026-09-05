from __future__ import annotations

from datetime import datetime
from pathlib import Path
import csv
import json
import math
import shutil
import threading

from .annotation_analysis import build_annotation_context
from .engine import AnalysisEngine
from .models import (
    BeatFrame,
    DiagnosticFrame,
    FirmwareMetricFrame,
    SampleFrame,
    UserAnnotation,
)


def _json_safe(value):
    """递归把 NaN / Inf 转成严格 JSON 的 null。"""
    if isinstance(value, float):
        return (
            value
            if math.isfinite(value)
            else None
        )

    if isinstance(value, dict):
        return {
            key: _json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [
            _json_safe(item)
            for item in value
        ]

    return value


class SessionRecorder:
    """
    实时原始会话记录器。

    原始 Sample / Beat / FirmwareMetric / Diagnostic 永远先落盘；
    后处理错误不会覆盖原始证据。
    """

    def __init__(
        self,
        base_dir: str | Path,
    ):
        stamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )
        self.session_dir = (
            Path(base_dir)
            / stamp
        )
        self.session_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._lock = threading.Lock()
        self._files: dict[str, object] = {}
        self._writers: dict[str, csv.writer] = {}

        self._open_csv(
            "samples",
            [
                "seq",
                "t_us",
                "raw",
                "avg",
                "filtered",
                "peak",
                "detector_score",
                "expected_rr_ms",
                "hr_bpm",
                "flags",
            ],
        )
        self._open_csv(
            "annotations",
            [
                "annotation_id",
                "device_t_us",
                "latest_sample_t_us",
                "latest_sample_seq",
                "label_start_us",
                "label_end_us",
                "host_monotonic_ns",
                "label_type",
                "note",
                "source",
                "ui_data_lag_ms",
                "hr_bpm",
                "expected_rr_ms",
                "winner_score",
                "timing_quality",
                "timing_uncertainty_ms",
                "fiducial_shift_ms",
                "candidate_count_12s",
                "rescue_count_12s",
                "phase_recovery_count_12s",
                "sqi",
                "effective_sample_rate_hz",
                "timing_jitter_p95_ms",
            ],
        )
        self._open_csv(
            "beats",
            [
                "seq",
                "t_us",
                "rr_ms",
                "hr_bpm",
                "score",
                "flags",
            ],
        )
        self._open_csv(
            "firmware_metrics",
            [
                "t_us",
                "rmssd_ms",
                "valid_rr_count",
                "artifact_ratio",
                "valid",
            ],
        )
        self._open_csv(
            "diagnostics",
            [
                "t_us",
                "sample_drop_count",
                "beat_drop_count",
                "metric_drop_count",
                "sample_queue_depth",
                "sample_queue_high_water",
            ],
        )

    def _open_csv(
        self,
        name: str,
        header: list[str],
    ) -> None:
        handle = (
            self.session_dir
            / f"{name}.csv"
        ).open(
            "w",
            newline="",
            encoding="utf-8-sig",
        )
        writer = csv.writer(handle)
        writer.writerow(header)

        self._files[name] = handle
        self._writers[name] = writer

    def record(
        self,
        message: object,
    ) -> None:
        with self._lock:
            if isinstance(message, SampleFrame):
                self._writers["samples"].writerow([
                    message.seq,
                    message.t_us,
                    message.raw,
                    message.avg,
                    message.filtered,
                    message.peak,
                    message.detector_score,
                    message.expected_rr_ms,
                    message.hr_bpm,
                    message.flags,
                ])

            elif isinstance(message, BeatFrame):
                self._writers["beats"].writerow([
                    message.seq,
                    message.t_us,
                    message.rr_ms,
                    message.hr_bpm,
                    message.score,
                    message.flags,
                ])

            elif isinstance(
                message,
                FirmwareMetricFrame,
            ):
                self._writers[
                    "firmware_metrics"
                ].writerow([
                    message.t_us,
                    message.rmssd_ms,
                    message.valid_rr_count,
                    message.artifact_ratio,
                    int(message.valid),
                ])

            elif isinstance(
                message,
                DiagnosticFrame,
            ):
                self._writers[
                    "diagnostics"
                ].writerow([
                    message.t_us,
                    message.sample_drop_count,
                    message.beat_drop_count,
                    message.metric_drop_count,
                    message.sample_queue_depth,
                    message.sample_queue_high_water,
                ])

    def record_annotation(
        self,
        annotation: UserAnnotation,
    ) -> None:
        """
        软件人工标注非常稀疏，写入后立即 flush。

        即使之后 UI / Python 意外退出，这个关键人工标签也尽量不丢。
        """
        with self._lock:
            self._writers[
                "annotations"
            ].writerow([
                annotation.annotation_id,
                annotation.device_t_us,
                annotation.latest_sample_t_us,
                annotation.latest_sample_seq,
                annotation.label_start_us,
                annotation.label_end_us,
                annotation.host_monotonic_ns,
                annotation.label_type,
                annotation.note,
                annotation.source,
                annotation.ui_data_lag_ms,
                annotation.hr_bpm,
                annotation.expected_rr_ms,
                annotation.winner_score,
                annotation.timing_quality,
                annotation.timing_uncertainty_ms,
                annotation.fiducial_shift_ms,
                annotation.candidate_count_12s,
                annotation.rescue_count_12s,
                annotation.phase_recovery_count_12s,
                annotation.sqi,
                annotation.effective_sample_rate_hz,
                annotation.timing_jitter_p95_ms,
            ])

            try:
                self._files[
                    "annotations"
                ].flush()
                self._files[
                    "samples"
                ].flush()
            except Exception:
                pass

    def flush(self) -> None:
        with self._lock:
            for handle in self._files.values():
                try:
                    handle.flush()
                except Exception:
                    pass

    def close(self) -> None:
        with self._lock:
            for handle in self._files.values():
                try:
                    handle.flush()
                    handle.close()
                except Exception:
                    pass

            self._files.clear()
            self._writers.clear()


def _load_raw_session_samples(
    raw_session_dir: Path,
) -> list[SampleFrame]:
    path = (
        raw_session_dir
        / "samples.csv"
    )

    if not path.is_file():
        return []

    result: list[SampleFrame] = []

    with path.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        reader = csv.DictReader(
            handle
        )

        for row in reader:
            try:
                result.append(
                    SampleFrame(
                        seq=int(row["seq"]),
                        t_us=int(row["t_us"]),
                        raw=float(row["raw"]),
                        avg=float(row["avg"]),
                        filtered=float(
                            row["filtered"]
                        ),
                        peak=int(row["peak"]),
                        detector_score=float(
                            row["detector_score"]
                        ),
                        expected_rr_ms=float(
                            row["expected_rr_ms"]
                        ),
                        hr_bpm=float(
                            row["hr_bpm"]
                        ),
                        flags=int(
                            row["flags"]
                        ),
                    )
                )
            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                # 单行损坏不应让整个标注导出失败。
                continue

    return result


def export_engine_results(
    engine: AnalysisEngine,
    destination: str | Path,
    raw_session_dir: str | Path | None = None,
) -> Path:
    """
    导出同一冻结时刻的：
    - beats_cleaned.csv
    - nn_intervals.csv
    - hrv_windows.csv
    - summary.json
    - frequency_statistics.json

    export_bundle() 在同一个锁中冻结所有对象，解决 V0.2 导出不同步。
    """
    destination = Path(destination)
    destination.mkdir(
        parents=True,
        exist_ok=True,
    )

    bundle = engine.export_bundle()
    snapshot = bundle["snapshot"]
    samples = bundle["samples"]
    annotations = bundle.get(
        "annotations",
        [],
    )
    firmware_beats = bundle["firmware_beats"]
    raw_beats = bundle["raw_beats"]
    beats = bundle["beats"]
    nn_intervals = bundle["nn_intervals"]
    history = bundle["history"]
    frequency_statistics = bundle[
        "frequency_statistics"
    ]

    # ------------------------------------------------------------------
    # v0.3.6：人工标注分析优先使用整段实时会话 Sample。
    # ------------------------------------------------------------------
    annotation_samples = samples
    annotation_sample_source = (
        "engine_recent_samples"
    )

    if raw_session_dir is not None:
        raw_session_path = Path(
            raw_session_dir
        )

        if raw_session_path.is_dir():
            raw_export = (
                destination
                / "raw_session"
            )
            raw_export.mkdir(
                parents=True,
                exist_ok=True,
            )

            for source in raw_session_path.glob(
                "*.csv"
            ):
                try:
                    shutil.copy2(
                        source,
                        raw_export
                        / source.name,
                    )
                except OSError:
                    pass

            full_session_samples = (
                _load_raw_session_samples(
                    raw_session_path
                )
            )

            if full_session_samples:
                annotation_samples = (
                    full_session_samples
                )
                annotation_sample_source = (
                    "raw_session/samples.csv"
                )

    # v0.3.2：把用于算法复盘的原始证据一起导出。
    with (
        destination
        / "samples_debug.csv"
    ).open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "seq",
            "t_us",
            "raw",
            "avg",
            "filtered",
            "candidate",
            "detector_score",
            "expected_rr_ms",
            "hr_bpm",
            "flags",
        ])

        for sample in samples:
            writer.writerow([
                sample.seq,
                sample.t_us,
                sample.raw,
                sample.avg,
                sample.filtered,
                sample.peak,
                sample.detector_score,
                sample.expected_rr_ms,
                sample.hr_bpm,
                sample.flags,
            ])

    with (
        destination
        / "annotations.csv"
    ).open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "annotation_id",
            "device_t_us",
            "latest_sample_t_us",
            "latest_sample_seq",
            "label_start_us",
            "label_end_us",
            "host_monotonic_ns",
            "label_type",
            "note",
            "source",
            "ui_data_lag_ms",
            "hr_bpm",
            "expected_rr_ms",
            "winner_score",
            "timing_quality",
            "timing_uncertainty_ms",
            "fiducial_shift_ms",
            "candidate_count_12s",
            "rescue_count_12s",
            "phase_recovery_count_12s",
            "sqi",
            "effective_sample_rate_hz",
            "timing_jitter_p95_ms",
        ])

        for annotation in annotations:
            writer.writerow([
                annotation.annotation_id,
                annotation.device_t_us,
                annotation.latest_sample_t_us,
                annotation.latest_sample_seq,
                annotation.label_start_us,
                annotation.label_end_us,
                annotation.host_monotonic_ns,
                annotation.label_type,
                annotation.note,
                annotation.source,
                annotation.ui_data_lag_ms,
                annotation.hr_bpm,
                annotation.expected_rr_ms,
                annotation.winner_score,
                annotation.timing_quality,
                annotation.timing_uncertainty_ms,
                annotation.fiducial_shift_ms,
                annotation.candidate_count_12s,
                annotation.rescue_count_12s,
                annotation.phase_recovery_count_12s,
                annotation.sqi,
                annotation.effective_sample_rate_hz,
                annotation.timing_jitter_p95_ms,
            ])

    with (
        destination
        / "beats_raw.csv"
    ).open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "seq",
            "t_us",
            "rr_ms",
            "hr_bpm",
            "score",
            "flags",
        ])

        for beat in firmware_beats:
            writer.writerow([
                beat.seq,
                beat.t_us,
                beat.rr_ms,
                beat.hr_bpm,
                beat.score,
                beat.flags,
            ])

    with (
        destination
        / "beats_refined.csv"
    ).open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "seq",
            "source_t_us",
            "t_us",
            "rr_ms",
            "hr_bpm",
            "score",
            "timing_shift_ms",
            "timing_quality",
            "timing_uncertainty_ms",
            "timing_recovered",
            "refined",
            "flags",
        ])

        for beat in raw_beats:
            writer.writerow([
                beat.seq,
                beat.source_t_us,
                beat.t_us,
                beat.rr_ms,
                beat.hr_bpm,
                beat.score,
                beat.timing_shift_ms,
                beat.timing_quality,
                beat.timing_uncertainty_ms,
                int(beat.timing_recovered),
                int(beat.refined),
                beat.flags,
            ])

    with (
        destination
        / "beats_cleaned.csv"
    ).open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "seq",
            "t_us",
            "rr_raw_ms",
            "nn_ms",
            "valid",
            "corrected",
            "metric_eligible",
            "status",
            "reason",
            "hr_bpm",
            "score",
            "rescued",
            "source_t_us",
            "timing_shift_ms",
            "timing_quality",
            "timing_uncertainty_ms",
            "timing_recovered",
            "refined",
            "flags",
        ])

        for beat in beats:
            writer.writerow([
                beat.seq,
                beat.t_us,
                beat.rr_raw_ms,
                beat.nn_ms,
                int(beat.valid),
                int(beat.corrected),
                int(beat.metric_eligible),
                beat.status,
                beat.reason,
                beat.hr_bpm,
                beat.score,
                int(beat.rescued),
                beat.source_t_us,
                beat.timing_shift_ms,
                beat.timing_quality,
                beat.timing_uncertainty_ms,
                int(beat.timing_recovered),
                int(beat.refined),
                beat.flags,
            ])

    with (
        destination
        / "nn_intervals.csv"
    ).open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "t_us",
            "nn_ms",
            "corrected",
            "metric_eligible",
            "source",
        ])

        for interval in nn_intervals:
            writer.writerow([
                interval.t_us,
                interval.nn_ms,
                int(interval.corrected),
                int(interval.metric_eligible),
                interval.source,
            ])

    with (
        destination
        / "hrv_windows.csv"
    ).open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        if history:
            fieldnames = list(
                history[0].keys()
            )
            writer = csv.DictWriter(
                handle,
                fieldnames=fieldnames,
            )
            writer.writeheader()
            writer.writerows(history)
        else:
            csv.writer(handle).writerow(
                ["t_us"]
            )

    annotation_context, annotation_summary = (
        build_annotation_context(
            annotation_samples,
            firmware_beats,
            raw_beats,
            beats,
            annotations,
            engine.config,
        )
    )

    with (
        destination
        / "annotation_context_1s.csv"
    ).open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        if annotation_context:
            fieldnames = list(
                annotation_context[0].keys()
            )
            writer = csv.DictWriter(
                handle,
                fieldnames=fieldnames,
            )
            writer.writeheader()
            writer.writerows(
                annotation_context
            )
        else:
            csv.writer(handle).writerow([
                "annotation_id",
                "relative_center_s",
                "inside_user_label_window",
            ])

    (
        destination
        / "annotation_summary.json"
    ).write_text(
        json.dumps(
            _json_safe(
                annotation_summary
            ),
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    summary = engine.summary_dict(
        snapshot=snapshot
    )
    (
        destination
        / "summary.json"
    ).write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    (
        destination
        / "frequency_statistics.json"
    ).write_text(
        json.dumps(
            frequency_statistics,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # 同一统计同时给 CSV，方便不写代码的情况下直接查看 VLF/LF/HF 会话统计。
    with (
        destination
        / "frequency_statistics.csv"
    ).open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "metric",
            "count",
            "mean",
            "median",
            "std",
            "p25",
            "p75",
            "min",
            "max",
        ])

        for name, stats in frequency_statistics["metrics"].items():
            writer.writerow([
                name,
                stats["count"],
                stats["mean"],
                stats["median"],
                stats["std"],
                stats["p25"],
                stats["p75"],
                stats["min"],
                stats["max"],
            ])

    protocol = bundle["protocol_health"]
    (
        destination
        / "protocol_health.json"
    ).write_text(
        json.dumps(
            {
                "mode": protocol.mode,
                "ok_frames": protocol.ok_frames,
                "crc_errors": protocol.crc_errors,
                "format_errors": protocol.format_errors,
                "resync_count": protocol.resync_count,
                "sample_seq_gaps": protocol.sample_seq_gaps,
                "legacy_frames": protocol.legacy_frames,
                "error_ratio": protocol.error_ratio,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # 额外写 snapshot_id，方便外部脚本核对所有导出文件是否来自同一时刻。
    (
        destination
        / "export_snapshot.json"
    ).write_text(
        json.dumps(
            {
                "snapshot_t_us": snapshot.t_us,
                "history_last_t_us": (
                    history[-1]["t_us"]
                    if history
                    else None
                ),
                "annotation_count": len(
                    annotations
                ),
                "annotation_sample_source": (
                    annotation_sample_source
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return destination
