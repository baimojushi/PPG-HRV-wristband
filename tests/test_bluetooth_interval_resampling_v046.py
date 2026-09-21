import math

from hrv_app.models import SampleFrame
from hrv_app.ppg_preprocessor import preprocess_ppg
from hrv_app.waveform_detectors import detect_elgendi_like, detect_multiscale_persistence


def _pulse_value(t_s: float, rr_s: float = 0.8) -> float:
    phase = (t_s % rr_s) / rr_s
    main = 90.0 * math.exp(-0.5 * ((phase - 0.30) / 0.075) ** 2)
    shoulder = 18.0 * math.exp(-0.5 * ((phase - 0.52) / 0.055) ** 2)
    baseline = 300.0 + 5.0 * math.sin(2.0 * math.pi * 0.12 * t_s)
    return baseline + main + shoulder


def _samples(rate_hz: float, seconds: float, seq_stride: int):
    count = int(rate_hz * seconds)
    out = []
    for index in range(count):
        t_s = index / rate_hz
        source_seq = index * seq_stride
        out.append(
            SampleFrame(
                seq=source_seq,
                t_us=int(round(source_seq * 8_000)),
                raw=_pulse_value(t_s),
                avg=_pulse_value(t_s),
                filtered=_pulse_value(t_s),
                peak=0,
                hr_bpm=75.0,
                flags=1,
            )
        )
    return out


def test_regular_31hz_bluetooth_waveform_is_rebuilt_on_125hz_analysis_grid():
    samples = _samples(31.25, 20.0, 4)
    ppg = preprocess_ppg(samples)

    assert ppg is not None
    assert abs(ppg.input_sample_rate_hz - 31.25) < 0.05
    assert abs(ppg.sample_rate_hz - 125.0) < 0.2
    assert ppg.resampled_for_interval
    assert len(ppg.t_us) > len(samples) * 3.8

    primary = detect_multiscale_persistence(ppg)
    secondary = detect_elgendi_like(ppg)
    # 20 s at 75 bpm contains about 25 beats.  Both independent detectors should
    # remain in the same order of magnitude after the transport decimation.
    assert 20 <= len(primary) <= 29
    assert 20 <= len(secondary) <= 29
