from pathlib import Path

from hrv_app.engine import AnalysisEngine
from hrv_app.models import BeatFrame, SampleFrame
from hrv_app.storage import export_engine_results


def test_analysis_export_contains_raw_debug_evidence(tmp_path: Path):
    engine = AnalysisEngine()

    for i in range(10):
        engine.ingest_sample(
            SampleFrame(
                seq=i,
                t_us=i * 8000,
                raw=300 + i,
                avg=290 + i,
                filtered=20 + i,
                peak=1 if i == 5 else 0,
                hr_bpm=80.0,
                detector_score=0.4,
                expected_rr_ms=750.0,
                flags=1,
            )
        )

    engine.ingest_beat(
        BeatFrame(
            seq=5,
            t_us=40_000,
            rr_ms=0.0,
            hr_bpm=80.0,
            score=0.8,
            flags=0x09,
        )
    )
    engine.ingest_beat(
        BeatFrame(
            seq=9,
            t_us=790_000,
            rr_ms=750.0,
            hr_bpm=80.0,
            score=0.82,
            flags=0x09,
        )
    )

    out = export_engine_results(
        engine,
        tmp_path / "export",
    )

    samples = (
        out / "samples_debug.csv"
    ).read_text(
        encoding="utf-8-sig"
    )
    beats = (
        out / "beats_raw.csv"
    ).read_text(
        encoding="utf-8-sig"
    )
    refined = (
        out / "beats_refined.csv"
    ).read_text(
        encoding="utf-8-sig"
    )
    cleaned = (
        out / "beats_cleaned.csv"
    ).read_text(
        encoding="utf-8-sig"
    )

    assert "detector_score" in samples
    assert "expected_rr_ms" in samples
    assert "300" in samples

    # beats_raw.csv 保持固件 Accepted Beat 的原始证据，便于回放。
    assert "score" in beats
    assert "750.0" in beats

    # v0.3.4 单独导出用于 HRV 的模板对齐时间线。
    assert "source_t_us" in refined
    assert "timing_shift_ms" in refined
    assert "timing_quality" in refined
    assert "timing_uncertainty_ms" in refined
    assert "refined" in refined

    # 清洗后的 Beat 继续保留时间标志点质量证据。
    assert "timing_quality" in cleaned
    assert "timing_uncertainty_ms" in cleaned
