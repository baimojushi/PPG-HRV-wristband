from pathlib import Path
import math

from hrv_app.engine import AnalysisEngine
from hrv_app.fixed_lag_corrector import WaveformPeakProposal
from hrv_app.models import BeatFrame, BeatRecord, SampleFrame
from hrv_app.provenance import build_beat_provenance_row
from hrv_app.storage import SessionRecorder


def test_session_recorder_writes_transport_and_engine_fast_provenance(tmp_path: Path):
    recorder = SessionRecorder(tmp_path)
    engine = AnalysisEngine()
    engine.attach_provenance_recorder(recorder.provenance)

    # 超过 7.25 s fixed-lag 后，即使没有正式 proposal，也必须留下
    # signal_input_trace 与 beat_detector_state，方便定位输入层退化。
    for seq in range(1150):
        t_s = seq / 125.0
        filtered = 80.0 * math.sin(2.0 * math.pi * t_s / 0.8)
        sample = SampleFrame(
            seq=seq,
            t_us=seq * 8000,
            raw=350.0 + filtered,
            avg=350.0,
            filtered=filtered,
            peak=1 if seq % 100 == 35 else 0,
            hr_bpm=75.0,
            detector_score=0.8,
            expected_rr_ms=800.0,
            flags=1,
        )
        engine.ingest_sample(sample)

    recorder.record_transport_io({
        "host_read_start_ns": 10,
        "host_read_end_ns": 20,
        "read_duration_ms": 0.01,
        "bytes_read": 512,
        "decoded_message_count": 8,
        "sample_count": 8,
        "first_sample_seq": 100,
        "last_sample_seq": 107,
        "first_sample_t_us": 800_000,
        "last_sample_t_us": 856_000,
        "serial_in_waiting": 0,
        "protocol_ok_frames": 100,
        "crc_errors": 0,
        "format_errors": 0,
        "resync_count": 0,
        "sample_seq_gaps": 0,
    })

    engine.attach_provenance_recorder(None)
    session_dir = recorder.session_dir
    recorder.close()

    signal_trace = (session_dir / "signal_input_trace.csv").read_text(
        encoding="utf-8"
    )
    detector_trace = (session_dir / "beat_detector_state.csv").read_text(
        encoding="utf-8"
    )
    transport = (session_dir / "transport_io.csv").read_text(
        encoding="utf-8-sig"
    )

    assert "raw_p05" in signal_trace
    assert "clip_low_ratio" in signal_trace
    assert "max_no_wear_run_ms" in signal_trace
    assert "autocorr_confidence" in signal_trace
    assert "autocorr_estimated_rr_ms" in detector_trace
    assert "firmware_matched_count" in detector_trace
    assert "read_duration_ms" in transport
    assert "512" in transport


def test_beat_provenance_separates_inserted_and_timing_recovered():
    firmware = BeatFrame(
        seq=7,
        t_us=1_000_000,
        rr_ms=800.0,
        hr_bpm=75.0,
        score=0.9,
    )
    beat = BeatRecord(
        seq=7,
        t_us=1_250_000,
        rr_raw_ms=800.0,
        nn_ms=800.0,
        valid=True,
        corrected=False,
        reason="",
        hr_bpm=75.0,
        timing_shift_ms=250.0,
        timing_recovered=True,
        matched_firmware_t_us=firmware.t_us,
        inserted_by_smoother=False,
        low_prominence_rescue=True,
    )
    proposal = WaveformPeakProposal(
        seq=7,
        t_us=1_250_000,
        waveform_score=0.82,
        timing_uncertainty_ms=7.0,
        reference_rr_ms=800.0,
        polarity=1,
        matched_firmware_t_us=firmware.t_us,
    )

    row = build_beat_provenance_row(
        beat=beat,
        firmware_match=firmware,
        proposal=proposal,
        prior_final_t_us=450_000,
        template_version="test",
    )

    assert row["inserted_by_smoother"] == 0
    assert row["timing_recovered"] == 1
    assert row["low_prominence_rescue"] == 1
    assert row["timing_shift_ms"] == 250.0
    assert "timing_recovered" in row["recovery_reason"]


def test_ui_connects_provenance_and_transport_trace_to_live_session():
    project = Path(__file__).resolve().parents[1]
    ui_source = (
        project / "desktop" / "src" / "hrv_app" / "ui_app.py"
    ).read_text(encoding="utf-8")

    assert "on_io_trace=self._on_transport_io_trace" in ui_source
    assert "self.engine.attach_provenance_recorder(" in ui_source
    assert "self.recorder.provenance" in ui_source
    assert "self.engine.attach_provenance_recorder(None)" in ui_source
