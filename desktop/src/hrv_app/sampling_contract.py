from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from collections.abc import Sequence

import numpy as np

from .models import SampleFrame


@dataclass(slots=True, frozen=True)
class SamplingContract:
    """Observed relationship between the device sample clock and the received stream.

    ``seq`` belongs to the device's source sampling clock.  A transport is allowed to
    forward only every Nth source sample (the current Bluetooth firmware uses N=4).
    That regular decimation must not be confused with packet loss or sample-clock
    jitter.
    """

    source_sample_rate_hz: float = 0.0
    received_sample_rate_hz: float = 0.0
    sample_stride: int = 1
    stride_confidence: float = 0.0
    intentional_decimation: bool = False
    sequence_drop_ratio: float = 0.0
    timing_jitter_p95_ms: float = 0.0
    timing_overrun_ratio: float = 0.0


def _mode_stride(dseq: np.ndarray) -> tuple[int, float, int]:
    positive = [int(value) for value in dseq if int(value) > 0]
    if not positive:
        return 1, 0.0, 0

    counts = Counter(positive)
    stride, count = max(counts.items(), key=lambda item: (item[1], -item[0]))
    confidence = count / max(len(positive), 1)
    return max(int(stride), 1), float(confidence), int(count)


def infer_sampling_contract_arrays(
    seq: np.ndarray,
    t_us: np.ndarray,
    nominal_source_rate_hz: float,
) -> SamplingContract:
    seq = np.asarray(seq, dtype=np.int64)
    t_us = np.asarray(t_us, dtype=np.int64)

    count = min(seq.size, t_us.size)
    if count < 2 or nominal_source_rate_hz <= 0:
        return SamplingContract()

    seq = seq[:count]
    t_us = t_us[:count]
    dseq = np.diff(seq)
    dt_us = np.diff(t_us.astype(np.float64))
    valid = (dseq > 0) & (dt_us > 0)

    if not np.any(valid):
        return SamplingContract()

    dseq_valid = dseq[valid].astype(np.int64)
    dt_ms = dt_us[valid] / 1000.0
    elapsed_s = float(t_us[-1] - t_us[0]) / 1e6

    received_rate = (
        float((count - 1) / elapsed_s)
        if elapsed_s > 0
        else 0.0
    )
    source_rate = (
        float((seq[-1] - seq[0]) / elapsed_s)
        if elapsed_s > 0 and seq[-1] > seq[0]
        else 0.0
    )

    candidate_stride, stride_confidence, mode_count = _mode_stride(dseq_valid)

    # A stride greater than one is accepted only when it repeats consistently and
    # the seq/t_us slope still agrees with the declared source clock.  This keeps a
    # random USB gap from being re-labelled as intentional decimation.
    source_rate_error = (
        abs(source_rate - nominal_source_rate_hz) / nominal_source_rate_hz
        if source_rate > 0
        else 1.0
    )
    stable_stride = bool(
        candidate_stride > 1
        and mode_count >= 4
        and stride_confidence >= 0.80
        and source_rate_error <= 0.05
    )
    sample_stride = int(candidate_stride if stable_stride else 1)

    expected_source_period_ms = 1000.0 / nominal_source_rate_hz
    timing_residual_ms = np.abs(
        dt_ms - dseq_valid.astype(float) * expected_source_period_ms
    )
    timing_jitter_p95_ms = float(np.percentile(timing_residual_ms, 95))

    # A source-clock residual of more than half one native sample is a real timing
    # discontinuity.  A normal BT step of seq+4 / 32 ms has zero residual.
    timing_overrun_ratio = float(
        np.mean(timing_residual_ms > expected_source_period_ms * 0.5)
    )

    # Count missing *received stream frames*, not skipped source samples.  With a
    # stable stride=4, +4 is complete and +8 means one forwarded frame was missed.
    missing_stream_frames = 0.0
    for delta in dseq_valid:
        delta = int(delta)
        if delta <= sample_stride:
            continue
        missing_stream_frames += max(delta / sample_stride - 1.0, 0.0)

    expected_stream_intervals = float(len(dseq_valid)) + missing_stream_frames
    sequence_drop_ratio = (
        float(missing_stream_frames / expected_stream_intervals)
        if expected_stream_intervals > 0
        else 0.0
    )

    return SamplingContract(
        source_sample_rate_hz=float(source_rate),
        received_sample_rate_hz=float(received_rate),
        sample_stride=sample_stride,
        stride_confidence=float(stride_confidence),
        intentional_decimation=bool(stable_stride),
        sequence_drop_ratio=float(sequence_drop_ratio),
        timing_jitter_p95_ms=float(timing_jitter_p95_ms),
        timing_overrun_ratio=float(timing_overrun_ratio),
    )


def infer_sampling_contract(
    samples: Sequence[SampleFrame],
    nominal_source_rate_hz: float,
) -> SamplingContract:
    if len(samples) < 2:
        return SamplingContract()
    return infer_sampling_contract_arrays(
        np.asarray([sample.seq for sample in samples], dtype=np.int64),
        np.asarray([sample.t_us for sample in samples], dtype=np.int64),
        nominal_source_rate_hz,
    )
