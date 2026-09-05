from hrv_app.models import ProtocolHealth, SampleFrame
from hrv_app.signal_quality import evaluate_signal_quality


def make_samples(zero_ratio=0.0):
    samples = []
    count = 1000
    zero_count = int(count * zero_ratio)

    for i in range(count):
        raw = (
            0
            if i < zero_count
            else 300 + (i % 20)
        )
        flags = (
            0x01
            | (0x02 if raw == 0 else 0)
        )

        samples.append(
            SampleFrame(
                seq=i,
                t_us=i * 8000,
                raw=raw,
                avg=raw,
                filtered=raw,
                peak=0,
                hr_bpm=70,
                flags=flags,
            )
        )

    return samples


def test_clipping_lowers_sqi():
    good = evaluate_signal_quality(
        make_samples(0.0)
    )
    clipped = evaluate_signal_quality(
        make_samples(0.22)
    )

    assert good.sqi > clipped.sqi
    assert clipped.clip_low_ratio > 0.20
    assert "PPG 低端削底" in clipped.reasons


def test_protocol_errors_lower_sqi():
    samples = make_samples(0.0)

    good = evaluate_signal_quality(
        samples,
        ProtocolHealth(
            ok_frames=1000,
        ),
    )
    bad = evaluate_signal_quality(
        samples,
        ProtocolHealth(
            ok_frames=950,
            crc_errors=30,
            format_errors=20,
        ),
    )

    assert good.sqi > bad.sqi
    assert bad.protocol_error_ratio > 0.04
