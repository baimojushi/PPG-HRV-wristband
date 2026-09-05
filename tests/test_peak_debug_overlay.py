from hrv_app.engine import AnalysisEngine
from hrv_app.models import BeatFrame, SampleFrame


def test_recent_signal_debug_exposes_score_candidate_and_accepted():
    engine = AnalysisEngine()

    accepted_samples = {42, 162}

    for i in range(250):
        candidate = 1 if i in {40, 42, 160, 162} else 0
        score = 0.85 if candidate else 0.20

        engine.ingest_sample(
            SampleFrame(
                seq=i,
                t_us=i * 8000,
                raw=300,
                avg=280,
                filtered=100,
                peak=candidate,
                hr_bpm=62.5,
                detector_score=score,
                expected_rr_ms=960.0,
                flags=1,
            )
        )

        if i in accepted_samples:
            engine.ingest_beat(
                BeatFrame(
                    seq=i,
                    t_us=i * 8000,
                    rr_ms=0.0 if i == 42 else 960.0,
                    hr_bpm=62.5,
                    score=0.81,
                    flags=0x09,
                )
            )

    (
        x,
        y,
        detector_score,
        candidate,
        firmware_accepted,
        accepted,
        stats,
    ) = engine.recent_signal_debug(2.0)

    assert len(x) == len(y)
    assert len(x) == len(detector_score)
    assert len(x) == len(candidate)
    assert len(x) == len(firmware_accepted)
    assert len(x) == len(accepted)

    assert detector_score.max() <= 1.0
    assert detector_score.min() >= 0.0

    assert stats["candidate_count"] == 4
    assert stats["accepted_beat_count"] == 2
    assert stats["candidate_minus_accepted"] == 2
    assert stats["expected_rr_ms"] == 960.0
    assert stats["accepted_hr_bpm"] == 62.5
    assert stats["accepted_score_mean"] == 0.81

    assert engine.snapshot().hr_bpm == 62.5
