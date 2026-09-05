from __future__ import annotations

from datetime import datetime
from pathlib import Path
import csv
import json
import threading

from .engine import AnalysisEngine
from .models import (
    BeatFrame,
    DiagnosticFrame,
    FirmwareMetricFrame,
    SampleFrame,
)


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


def export_engine_results(
    engine: AnalysisEngine,
    destination: str | Path,
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
    firmware_beats = bundle["firmware_beats"]
    raw_beats = bundle["raw_beats"]
    beats = bundle["beats"]
    nn_intervals = bundle["nn_intervals"]
    history = bundle["history"]
    frequency_statistics = bundle[
        "frequency_statistics"
    ]

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
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return destination
