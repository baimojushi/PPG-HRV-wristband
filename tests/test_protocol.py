from hrv_app.models import (
    BeatFrame,
    DiagnosticFrame,
    SampleFrame,
)
from hrv_app.protocol import (
    ProtocolParser,
    ProtocolStreamDecoder,
    build_framed_body,
    build_v3_frame,
)


def test_v2_v3_sample_compatibility():
    parser = ProtocolParser()

    msg = parser.parse(
        "S,12,100000,311,305,121,1,72.5,3"
    )

    assert isinstance(msg, SampleFrame)
    assert msg.seq == 12
    assert msg.detector_score == 0.0
    assert msg.expected_rr_ms == 0.0


def test_v4_sample_and_beat():
    parser = ProtocolParser()

    sample = parser.parse(
        build_framed_body(
            "S,12,100000,311,305,121,1,0.732,860.0,69.8,3"
        ).decode("ascii").strip()
    )
    beat = parser.parse(
        build_framed_body(
            "B,15,124000,860,69.8,0.811,9"
        ).decode("ascii").strip()
    )

    assert isinstance(sample, SampleFrame)
    assert sample.peak == 1
    assert sample.detector_score == 0.732
    assert sample.expected_rr_ms == 860.0
    assert sample.hr_bpm == 69.8

    assert isinstance(beat, BeatFrame)
    assert beat.rr_ms == 860
    assert beat.score == 0.811
    assert beat.flags == 9


def test_crc_helper_alias_is_still_compatible():
    assert build_v3_frame("B,12,100000,816,73.5,1") == (
        build_framed_body("B,12,100000,816,73.5,1")
    )


def test_stream_decoder_v4_split_and_coalesced():
    decoder = ProtocolStreamDecoder()

    frame1 = build_framed_body(
        "S,100,800000,300,301,80,1,0.70,900.0,66.7,1"
    )
    frame2 = build_framed_body(
        "S,101,808000,302,301,82,0,0.40,900.0,66.7,1"
    )

    first = decoder.feed(
        b"#PPGHRV,4\r\n"
        + frame1[:11]
    )
    second = decoder.feed(
        frame1[11:]
        + frame2
    )

    assert first == []
    assert len(second) == 2
    assert second[0].seq == 100
    assert second[1].seq == 101

    health = decoder.health()
    assert health.mode == "v4"
    assert health.crc_errors == 0
    assert health.format_errors == 0
    assert health.sample_seq_gaps == 0


def test_stream_decoder_resync_after_missing_newline():
    decoder = ProtocolStreamDecoder()

    bad_first = build_framed_body(
        "S,100,800000,300,301,80,1,0.7,900.0,66.7,1"
    ).rstrip(b"\r\n")

    good_second = build_framed_body(
        "S,103,824000,303,302,83,0,0.4,900.0,66.7,1"
    )

    messages = decoder.feed(
        b"#PPGHRV,4\r\n"
        + bad_first
        + good_second
    )

    assert len(messages) == 1
    assert messages[0].seq == 103

    health = decoder.health()
    assert health.format_errors >= 1
    assert health.resync_count >= 1


def test_legacy_sticky_frames_still_recovers_subframe():
    decoder = ProtocolStreamDecoder()

    sticky = (
        b"S,496129,3969032115,108,233,245,"
        b"S,496132,3969056114,211,132,230,0,57.3,1\n"
    )

    messages = decoder.feed(sticky)

    assert len(messages) == 1
    assert isinstance(messages[0], SampleFrame)
    assert messages[0].seq == 496132


def test_diagnostic_frame():
    parser = ProtocolParser()

    diag = parser.parse(
        "D,100000,2,1,0,12,40"
    )

    assert isinstance(diag, DiagnosticFrame)
    assert diag.sample_drop_count == 2
    assert diag.sample_queue_high_water == 40
