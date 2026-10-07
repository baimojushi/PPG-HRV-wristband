from types import SimpleNamespace
import math

from hrv_app.interval_quality import evaluate_beat_timing_quality
from hrv_app.models import BeatRecord, SampleFrame
from hrv_app.ppg_preprocessor import preprocess_ppg
from hrv_app.provenance import build_hrv_window_provenance_row


def _proposal(**overrides):
    values = {
        "waveform_score": 0.95,
        "timing_uncertainty_ms": 10.0,
        "single_detector": False,
        "sequence_rescued": False,
        "low_prominence_rescue": False,
        "local_clipped": False,
        "matched_firmware_t_us": 1_000_000,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_clean_dual_detector_beat_keeps_high_timing_quality():
    evidence = evaluate_beat_timing_quality(_proposal(), timing_shift_ms=5.0)

    assert evidence.timing_quality > 0.90
    assert evidence.detector_timing_quality == 1.0
    assert evidence.provenance_quality == 1.0
    assert evidence.firmware_alignment_available
    assert evidence.firmware_alignment_quality > 0.95
    assert evidence.timing_quality_reason == "direct_dual_detector"


def test_single_detector_and_sequence_rescue_reduce_timing_confidence():
    evidence = evaluate_beat_timing_quality(
        _proposal(
            timing_uncertainty_ms=30.4,
            single_detector=True,
            sequence_rescued=True,
        ),
        timing_shift_ms=8.0,
    )

    assert evidence.timing_quality < 0.68
    assert evidence.provenance_quality < 0.70
    assert "single_detector" in evidence.timing_quality_reason
    assert "sequence_rescued" in evidence.timing_quality_reason


def test_large_firmware_phase_offset_is_diagnostic_not_formal_hrv_gate():
    evidence = evaluate_beat_timing_quality(_proposal(), timing_shift_ms=330.0)

    # Formal timing quality is waveform/detector/provenance based in v0.4.1+.
    assert evidence.timing_quality > 0.90
    assert evidence.firmware_alignment_available
    assert evidence.firmware_alignment_quality < 0.40
    assert evidence.firmware_alignment_reason == "firmware_phase_large_offset"


def test_missing_firmware_match_is_explicit_but_does_not_penalize_waveform_timing():
    evidence = evaluate_beat_timing_quality(
        _proposal(matched_firmware_t_us=0),
        timing_shift_ms=0.0,
    )

    assert evidence.timing_quality > 0.90
    assert not evidence.firmware_alignment_available
    assert evidence.firmware_alignment_quality == 0.0
    assert evidence.firmware_alignment_reason == "firmware_unmatched"


def _bt_samples(seconds: float = 12.0):
    rate_hz = 31.25
    samples = []
    for index in range(int(rate_hz * seconds)):
        t_s = index / rate_hz
        phase = (t_s % 0.8) / 0.8
        pulse = 85.0 * math.exp(-0.5 * ((phase - 0.30) / 0.075) ** 2)
        baseline = 300.0 + 8.0 * math.sin(2.0 * math.pi * 0.08 * t_s)
        value = baseline + pulse
        samples.append(
            SampleFrame(
                seq=index * 4,
                t_us=index * 32_000,
                raw=value,
                avg=value,
                filtered=value,
                peak=0,
                hr_bpm=75.0,
                flags=1,
            )
        )
    return samples


def test_resampling_audit_quantifies_transform_error_on_regular_bt_stream():
    ppg = preprocess_ppg(_bt_samples())

    assert ppg is not None
    assert ppg.resampled_for_interval
    assert ppg.resample_up == 4
    assert ppg.resample_down == 1
    assert abs(ppg.resample_ratio - 4.0) < 0.02
    assert abs(ppg.input_dt_mean_ms - 32.0) < 0.01
    assert ppg.input_dt_std_ms < 0.01
    assert ppg.input_jitter_p95_ms < 0.01
    assert math.isfinite(ppg.regularization_backprojection_rms)
    assert math.isfinite(ppg.resample_backprojection_rms)
    assert math.isfinite(ppg.resample_backprojection_max_abs)
    assert ppg.regularization_backprojection_rms < 0.02
    assert ppg.resample_backprojection_rms < 0.20


def _record(
    t_us: int,
    shift_ms: float,
    timing_quality: float,
    matched: bool,
) -> BeatRecord:
    return BeatRecord(
        seq=t_us // 1_000_000,
        t_us=t_us,
        rr_raw_ms=1000.0,
        nn_ms=1000.0,
        valid=True,
        corrected=False,
        reason="",
        hr_bpm=60.0,
        detector_support_count=2,
        detector_names="multiscale+elgendi_like",
        detector_consensus=0.95,
        detector_time_spread_ms=4.0,
        matched_firmware_t_us=(t_us - int(shift_ms * 1000)) if matched else 0,
        firmware_unmatched=not matched,
        timing_shift_ms=shift_ms if matched else 0.0,
        timing_quality=timing_quality,
        timing_uncertainty_ms=8.0,
        firmware_alignment_available=matched,
        firmware_alignment_quality=(0.95 if matched and abs(shift_ms) < 20 else 0.25 if matched else 0.0),
        refined=True,
    )


def test_short_window_provenance_exposes_phase_transition_deltas():
    prior = [
        _record(1_000_000 * i, shift_ms=320.0, timing_quality=0.72, matched=(i % 2 == 0))
        for i in range(1, 11)
    ]
    current = [
        _record(20_000_000 + 1_000_000 * i, shift_ms=6.0, timing_quality=0.96, matched=True)
        for i in range(1, 11)
    ]

    row = build_hrv_window_provenance_row(
        current,
        prior,
        firmware_beats=[],
        window_t_us=current[-1].t_us,
    )

    assert row["firmware_match_ratio"] > row["previous_firmware_match_ratio"]
    assert row["firmware_match_ratio_delta"] > 0.40
    assert row["offset_p95_ms"] < 10.0
    assert row["previous_offset_p95_ms"] > 300.0
    assert row["offset_p95_delta_ms"] < -250.0
    assert row["timing_quality_mean_delta"] > 0.20
