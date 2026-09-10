import math

from hrv_app.beat_consensus import ConsensusPeak
from hrv_app.engine import AnalysisEngine
from hrv_app.interval_core import IntervalCore
from hrv_app.hrv_frequency import compute_frequency_domain
from hrv_app.models import BeatRecord, NNInterval, ProtocolHealth, SampleFrame, SignalQuality
from hrv_app.storage import SessionRecorder


def _ppg_samples(duration_s: float = 70.0, rr_ms: float = 800.0):
    samples = []
    for i in range(int(duration_s * 125)):
        t_ms = i * 8.0
        phase = (t_ms % rr_ms) / rr_ms

        # Clean systolic pulse plus slow baseline movement.
        main = 85.0 * math.exp(-0.5 * ((phase - 0.32) / 0.085) ** 2)
        shoulder = 10.0 * math.exp(-0.5 * ((phase - 0.50) / 0.055) ** 2)
        baseline = 8.0 * math.sin(2.0 * math.pi * t_ms / 7000.0)
        filtered = main + shoulder + baseline

        # Deliberately clip the raw trough on many cycles. The formal systolic
        # fiducial itself remains far from the clipped region.
        raw = 0.0 if 0.66 <= phase <= 0.82 else 300.0 + filtered

        samples.append(
            SampleFrame(
                seq=i,
                t_us=int(t_ms * 1000),
                raw=raw,
                avg=290.0,
                filtered=filtered,
                peak=0,
                hr_bpm=75.0,
                flags=1,
            )
        )
    return samples


def _frequency_timeline(duration_s: float = 330.0, support: int = 2, firmware_unmatched: bool = True):
    records = []
    intervals = []
    t = 0.0
    seq = 0
    while t < duration_s:
        rr = (
            1000.0
            + 70.0 * math.sin(2.0 * math.pi * 0.10 * t)
            + 35.0 * math.sin(2.0 * math.pi * 0.24 * t)
        )
        t += rr / 1000.0
        t_us = int(t * 1e6)
        records.append(
            BeatRecord(
                seq=seq,
                t_us=t_us,
                rr_raw_ms=rr,
                nn_ms=rr,
                valid=True,
                corrected=False,
                reason="",
                hr_bpm=60000.0 / rr,
                flags=1,
                detector_support_count=support,
                detector_names=("multiscale+elgendi_like" if support >= 2 else "multiscale"),
                detector_consensus=(0.96 if support >= 2 else 0.72),
                detector_time_spread_ms=(4.0 if support >= 2 else 0.0),
                single_detector=(support == 1),
                sequence_rescued=False,
                firmware_unmatched=firmware_unmatched,
                local_clipped=False,
                status="accepted",
                metric_eligible=True,
            )
        )
        intervals.append(
            NNInterval(
                t_us=t_us,
                nn_ms=rr,
                corrected=False,
                metric_eligible=True,
            )
        )
        seq += 1
    return records, intervals


def test_interval_core_builds_formal_timeline_without_firmware_and_ignores_trough_clipping():
    engine = AnalysisEngine()

    for sample in _ppg_samples():
        engine.ingest_sample(sample)

    snapshot = engine.force_update()
    bundle = engine.export_bundle()
    beats = bundle["raw_beats"]

    assert len(beats) >= 75
    assert all(beat.matched_firmware_t_us == 0 for beat in beats)
    assert sum(beat.firmware_unmatched for beat in beats) / len(beats) > 0.95
    assert sum(beat.detector_support_count >= 2 for beat in beats) / len(beats) > 0.90

    # Raw trough clipping is not the same as clipping the beat fiducial itself.
    assert sum(beat.local_clipped for beat in beats) / len(beats) < 0.05
    assert snapshot.timeline_quality.dual_detector_ratio > 0.90
    assert snapshot.timeline_quality.firmware_unmatched_ratio > 0.95
    assert snapshot.time.valid


def test_firmware_unmatched_ratio_is_diagnostic_not_frequency_gate():
    records, intervals = _frequency_timeline(support=2, firmware_unmatched=True)

    result = compute_frequency_domain(
        records,
        intervals,
        SignalQuality(
            sqi=0.45,
            status="INVALID",
            transport_score=0.99,
            transport_status="VALID",
            contact_score=0.35,
            contact_status="INVALID",
        ),
        ProtocolHealth(ok_frames=10000),
    )

    assert result.valid
    assert result.firmware_unmatched_ratio > 0.95
    assert result.dual_detector_ratio > 0.95
    assert "固件" not in result.validity_reason


def test_single_detector_dominance_blocks_frequency_timeline():
    records, intervals = _frequency_timeline(support=1, firmware_unmatched=False)

    result = compute_frequency_domain(
        records,
        intervals,
        SignalQuality(
            sqi=0.95,
            status="VALID",
            transport_score=0.99,
            transport_status="VALID",
            contact_score=0.95,
            contact_status="VALID",
        ),
        ProtocolHealth(ok_frames=10000),
    )

    assert not result.valid
    assert result.status == "INVALID"
    assert (
        "双检测器一致心搏" in result.validity_reason
        or "单检测器心搏" in result.validity_reason
    )


def test_session_flush_flushes_provenance_files(tmp_path):
    recorder = SessionRecorder(tmp_path)
    try:
        recorder.provenance.record_beat_detector_state(
            {"t_us": 123, "detector_consensus_ratio": 0.95}
        )
        recorder.flush()
        path = recorder.session_dir / "beat_detector_state.csv"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "detector_consensus_ratio" in content
        assert "0.950000" in content
    finally:
        recorder.close()


def _consensus_peak(t_ms: float, support: int) -> ConsensusPeak:
    return ConsensusPeak(
        t_us=int(t_ms * 1000),
        index=int(t_ms / 8.0),
        score=0.96 if support >= 2 else 0.72,
        support_count=support,
        detector_names=("multiscale+elgendi_like" if support >= 2 else "multiscale"),
        detector_time_spread_ms=(3.0 if support >= 2 else float("nan")),
        prominence=1.0,
    )


def test_low_consensus_window_cannot_poison_rr_reference():
    core = IntervalCore()

    # Prior authoritative timeline is ~800 ms.
    history = [800.0] * 9

    # A bad current window contains a few dual peaks implying ~500 ms, but is
    # dominated by unmatched single-detector candidates. It must not replace
    # the previous stable search scale.
    current = [
        _consensus_peak(0.0, 2),
        _consensus_peak(500.0, 2),
        _consensus_peak(1000.0, 2),
        _consensus_peak(1500.0, 2),
        _consensus_peak(1800.0, 1),
        _consensus_peak(2050.0, 1),
        _consensus_peak(2300.0, 1),
        _consensus_peak(2550.0, 1),
        _consensus_peak(2800.0, 1),
        _consensus_peak(3050.0, 1),
        _consensus_peak(3300.0, 1),
        _consensus_peak(3550.0, 1),
    ]

    reference = core._reference_rr(current, history)

    assert abs(reference - 800.0) < 1e-6
    assert core._last_reference_reason == "hold_previous_good_window"
