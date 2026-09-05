import math
import numpy as np

from hrv_app.adaptive_detector import AdaptiveCandidate, AdaptivePPGDetector


def pulse_wave(
    phase_ms: float,
    rr_ms: float,
    amplitude: float = 1.0,
) -> float:
    main_center = 0.32 * rr_ms
    shoulder_center = 0.53 * rr_ms

    main = amplitude * math.exp(
        -0.5
        * (
            (phase_ms - main_center)
            / (0.085 * rr_ms)
        ) ** 2
    )

    shoulder = 0.33 * amplitude * math.exp(
        -0.5
        * (
            (phase_ms - shoulder_center)
            / (0.055 * rr_ms)
        ) ** 2
    )

    return (
        80.0 * main
        + 22.0 * shoulder
    )


def run_detector(
    rr_ms: float,
    duration_s: float,
    amplitude_modulation: bool = False,
    baseline_drift: bool = False,
):
    detector = AdaptivePPGDetector(
        sample_rate_hz=125.0,
    )

    accepted = []
    candidates = 0

    sample_period_ms = 8.0
    total_samples = int(
        duration_s * 125
    )

    for i in range(total_samples):
        t_ms = i * sample_period_ms
        phase = t_ms % rr_ms

        amplitude = 1.0
        if amplitude_modulation:
            amplitude = (
                0.55
                + 0.55
                * (
                    0.5
                    + 0.5
                    * math.sin(
                        2 * math.pi
                        * t_ms
                        / 7000.0
                    )
                )
            )

        value = pulse_wave(
            phase,
            rr_ms,
            amplitude=amplitude,
        )

        if baseline_drift:
            value += (
                18.0
                * math.sin(
                    2 * math.pi
                    * t_ms
                    / 9000.0
                )
            )

        event = detector.update(
            seq=i,
            t_us=int(t_ms * 1000),
            filtered=value,
            wear=True,
        )

        if event.candidate:
            candidates += 1

        if event.accepted:
            accepted.append(event)

    return detector, accepted, candidates


def median_rr(accepted):
    values = np.asarray(
        [
            event.rr_ms
            for event in accepted
            if event.rr_ms > 0
        ],
        dtype=float,
    )

    assert values.size > 0
    return float(np.median(values))


def test_multiple_morphology_candidates_collapse_to_one_cycle_winner():
    detector, accepted, candidates = run_detector(
        rr_ms=900.0,
        duration_s=20.0,
    )

    rr = median_rr(accepted)

    assert 875 <= rr <= 925
    assert candidates > len(accepted)
    assert 18 <= len(accepted) <= 24
    assert 64 <= accepted[-1].hr_bpm <= 70


def test_dynamic_amplitude_and_baseline_drift_do_not_break_period():
    detector, accepted, _ = run_detector(
        rr_ms=820.0,
        duration_s=24.0,
        amplitude_modulation=True,
        baseline_drift=True,
    )

    rr = median_rr(accepted)

    assert 790 <= rr <= 850
    assert 68 <= accepted[-1].hr_bpm <= 78

    rr_values = [
        event.rr_ms
        for event in accepted
        if event.rr_ms > 0
    ]
    assert max(rr_values) < 1500


def test_high_heart_rate_180_bpm_is_supported():
    _, accepted, _ = run_detector(
        rr_ms=333.0,
        duration_s=12.0,
    )

    rr = median_rr(accepted)

    assert 315 <= rr <= 350
    assert 168 <= accepted[-1].hr_bpm <= 192


def test_autocorrelation_harmonic_guard_prefers_full_cycle():
    detector, accepted, candidates = run_detector(
        rr_ms=1000.0,
        duration_s=20.0,
    )

    assert candidates > len(accepted)
    assert 930 <= detector.expected_rr_ms <= 1070
    assert 930 <= median_rr(accepted) <= 1070


def test_weak_cycles_do_not_create_multi_cycle_gaps():
    detector = AdaptivePPGDetector(
        sample_rate_hz=125.0,
    )

    accepted = []
    rr_ms = 850.0

    for i in range(int(24.0 * 125)):
        t_ms = i * 8.0
        cycle = int(t_ms // rr_ms)
        phase = t_ms % rr_ms

        # 两个周期故意把幅值压到正常的 8%。
        amplitude = (
            0.08
            if cycle in {8, 15}
            else 1.0
        )

        value = pulse_wave(
            phase,
            rr_ms,
            amplitude=amplitude,
        )

        event = detector.update(
            seq=i,
            t_us=int(t_ms * 1000),
            filtered=value,
            wear=True,
        )

        if event.accepted:
            accepted.append(event)

    values = np.asarray(
        [
            event.rr_ms
            for event in accepted
            if event.rr_ms > 0
        ],
        dtype=float,
    )

    assert values.size >= 20
    assert np.max(values) < 1.5 * np.median(values)
    assert 825 <= float(np.median(values)) <= 875


def test_polarity_lock_blocks_opposite_extremum_alias():
    detector = AdaptivePPGDetector(
        sample_rate_hz=125.0,
    )

    detector.last_accepted_t_us = 1_000_000
    detector.last_accepted_seq = 100
    detector.locked_polarity = 1
    detector.expected_rr_ms = 464.0
    detector.autocorr_rr_ms = 464.0
    detector.autocorr_confidence = 1.0

    opposite = AdaptiveCandidate(
        seq=145,
        t_us=1_360_000,
        value=-50.0,
        morphology_score=0.92,
        timing_score=0.0,
        combined_score=0.0,
        amplitude_z=2.0,
        prominence_z=2.0,
        slope_z=2.0,
        curvature_z=1.0,
        polarity=-1,
    )
    true_peak = AdaptiveCandidate(
        seq=190,
        t_us=1_720_000,
        value=75.0,
        morphology_score=0.78,
        timing_score=0.0,
        combined_score=0.0,
        amplitude_z=1.8,
        prominence_z=1.8,
        slope_z=1.7,
        curvature_z=0.9,
        polarity=1,
    )

    detector.candidate_pool = [
        opposite,
        true_peak,
    ]

    selected = detector._select_best_candidate(
        0.72,
        2.20,
        0.24,
    )

    assert selected is not None
    assert selected.polarity == 1
    assert selected.t_us == true_peak.t_us


def test_stable_same_polarity_rr_overrides_bad_autocorrelation_anchor():
    detector = AdaptivePPGDetector(
        sample_rate_hz=125.0,
    )

    detector.locked_polarity = 1
    detector.autocorr_rr_ms = 464.0
    detector.autocorr_confidence = 1.0

    detector.rr_history.extend(
        [720.0, 728.0]
    )
    detector._update_expected_rr()

    assert 715.0 <= detector.expected_rr_ms <= 735.0


def test_same_polarity_candidates_inside_wide_peak_are_clustered():
    detector = AdaptivePPGDetector(
        sample_rate_hz=125.0,
    )
    detector.expected_rr_ms = 700.0
    detector.locked_polarity = 1

    candidates = [
        AdaptiveCandidate(
            seq=100 + index,
            t_us=1_000_000 + index * 30_000,
            value=value,
            morphology_score=score,
            timing_score=0.5,
            combined_score=score,
            amplitude_z=1.0,
            prominence_z=1.0,
            slope_z=1.0,
            curvature_z=1.0,
            polarity=1,
        )
        for index, (value, score)
        in enumerate(
            [
                (30.0, 0.70),
                (44.0, 0.80),
                (39.0, 0.90),
            ]
        )
    ]

    for candidate in candidates:
        detector._push_candidate(
            candidate
        )

    assert len(detector.candidate_pool) == 1
    assert detector.candidate_pool[0].value == 44.0


def test_phase_tracker_does_not_use_last_fiducial_as_next_window_origin():
    detector = AdaptivePPGDetector(
        sample_rate_hz=125.0,
    )

    detector.expected_rr_ms = 700.0
    detector.locked_polarity = 1

    # 上一搏的局部极值被选晚了 110 ms。
    detector.last_accepted_t_us = 1_110_000

    # 独立节律目标仍然在真实周期 1.700 s。
    detector.predicted_beat_t_us = 1_700_000

    true_candidate = AdaptiveCandidate(
        seq=200,
        t_us=1_700_000,
        value=50.0,
        morphology_score=0.80,
        timing_score=0.0,
        combined_score=0.0,
        amplitude_z=2.0,
        prominence_z=2.0,
        slope_z=1.5,
        curvature_z=1.0,
        polarity=1,
    )

    detector.candidate_pool = [
        true_candidate
    ]

    selected = detector._select_best_candidate(
        0.72,
        1.55,
        0.40,
    )

    assert selected is not None
    assert selected.t_us == 1_700_000
    assert selected.timing_score > 0.99


def test_single_late_fiducial_only_small_corrects_next_phase_target():
    detector = AdaptivePPGDetector(
        sample_rate_hz=125.0,
    )

    detector.expected_rr_ms = 700.0
    detector.predicted_beat_t_us = 1_700_000

    # 当前 fiducial 晚 80 ms。
    detector._update_phase_tracker_after_accept(
        1_780_000,
        first=False,
    )

    # 下一目标应接近 2.400 s，仅允许小增益修正，不能被拖到 2.480 s。
    assert 2_400_000 <= detector.predicted_beat_t_us <= 2_410_000
    assert detector.last_phase_error_ms == 80.0
