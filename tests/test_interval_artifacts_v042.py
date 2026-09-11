from __future__ import annotations

import math

import numpy as np

from hrv_app.beat_consensus import ConsensusPeak
from hrv_app.beat_sequence_resolver import resolve_consensus_sequence
from hrv_app.config import AnalysisConfig
from hrv_app.hrv_frequency import prepare_tachogram
from hrv_app.hrv_time import compute_time_domain
from hrv_app.interval_artifacts import IntervalArtifactClassifier
from hrv_app.models import (
    AnalysisSnapshot,
    BeatFrame,
    FrequencyDomainMetrics,
    NNInterval,
    QualityAssessment,
    SignalQuality,
    TimeDomainMetrics,
)
from hrv_app.ppg_preprocessor import PreprocessedPPG
from hrv_app.research_prototypes import (
    _build_personal_baseline,
    _timeline_score_rows,
    build_hour_experience,
    evaluate_research_state,
)
from hrv_app.rr_cleaner import BeatTimelineCleaner


def _beats(rrs: list[float], *, support: int = 2) -> list[BeatFrame]:
    t_us = 0
    result: list[BeatFrame] = []
    for seq, rr in enumerate(rrs, start=1):
        t_us += int(round(rr * 1000.0))
        result.append(
            BeatFrame(
                seq=seq,
                t_us=t_us,
                rr_ms=float(rr),
                hr_bpm=60000.0 / rr,
                flags=1,
                score=0.95,
                detector_support_count=support,
                detector_names=(
                    "multiscale+elgendi_like" if support >= 2 else "multiscale"
                ),
                detector_consensus=0.96 if support >= 2 else 0.72,
            )
        )
    return result


def _quality() -> SignalQuality:
    return SignalQuality(
        sqi=0.95,
        status="VALID",
        transport_score=0.99,
        transport_status="VALID",
        contact_score=0.95,
        contact_status="VALID",
    )


def test_dual_detector_extra_peak_pair_is_still_repaired_by_sequence_layer():
    rrs = [744, 752, 748, 746, 750, 742, 754, 336.004, 407.998, 746, 750, 748, 744]
    result = BeatTimelineCleaner().clean(_beats(rrs, support=2))

    pair = result.artifact_decisions[7:9]
    assert [item.status for item in pair] == ["false_peak", "false_peak_merged"]
    assert pair[0].resolved and pair[1].resolved
    assert math.isclose(pair[1].corrected_rr_ms, 744.002, abs_tol=0.01)
    assert result.quality.max_consecutive_unresolved == 0

    merged = [item for item in result.nn_intervals if item.source == "false_peak_merge"]
    assert len(merged) == 1
    assert math.isclose(merged[0].nn_ms, 744.002, abs_tol=0.01)


def test_dual_detector_missed_beat_is_split_for_corrected_nn_only():
    rrs = [648, 652, 646, 650, 654, 644, 648, 1296.004, 650, 646, 652, 648]
    result = BeatTimelineCleaner().clean(_beats(rrs, support=2))

    decision = result.artifact_decisions[7]
    assert decision.status == "missed_beat_repaired"
    assert decision.resolved
    assert decision.split_count == 2
    assert 645 <= decision.corrected_rr_ms <= 651

    split = [item for item in result.nn_intervals if item.source == "missed_beat_split"]
    assert len(split) == 2
    assert all(not item.metric_eligible for item in split)
    assert result.quality.max_consecutive_unresolved == 0


def test_compensating_long_short_pair_preserves_elapsed_time():
    rrs = [800, 805, 795, 802, 798, 804, 796, 1100, 500, 802, 798, 806, 794]
    result = BeatTimelineCleaner().clean(_beats(rrs))

    pair = result.artifact_decisions[7:9]
    assert [item.status for item in pair] == ["long_short_repaired", "long_short_repaired"]
    assert all(item.resolved for item in pair)
    assert all(math.isclose(item.corrected_rr_ms, 800.0, abs_tol=0.01) for item in pair)
    assert result.quality.max_consecutive_unresolved == 0


def test_coherent_real_rate_transition_does_not_create_reject_cascade():
    rrs = [800] * 7 + [760, 720, 680, 650, 630, 620, 618, 622, 620, 624, 618]
    result = BeatTimelineCleaner().clean(_beats(rrs))

    unresolved = [
        item for item in result.artifact_decisions
        if not item.resolved and item.status not in {"accepted"}
    ]
    assert len(unresolved) <= 1
    assert result.quality.max_consecutive_unresolved <= 1
    assert sum(record.status == "accepted" for record in result.records[-8:]) >= 7


def test_resolved_artifacts_do_not_trigger_consecutive_unresolved_time_gate():
    rrs = [800] * 12 + [336, 464] + [800] * 45
    cleaned = BeatTimelineCleaner().clean(_beats(rrs))
    metrics = compute_time_domain(cleaned.records, cleaned.nn_intervals, _quality())

    assert cleaned.quality.max_consecutive_artifacts >= 1
    assert cleaned.quality.max_consecutive_unresolved == 0
    assert metrics.max_consecutive_unresolved == 0
    assert "连续未解决异常" not in metrics.validity_reason


def _peak(t_ms: float, support: int, score: float) -> ConsensusPeak:
    return ConsensusPeak(
        t_us=int(round(t_ms * 1000.0)),
        index=int(round(t_ms / 8.0)),
        score=score,
        support_count=support,
        detector_names="dual" if support >= 2 else "multiscale",
        detector_time_spread_ms=2.0 if support >= 2 else float("nan"),
        prominence=1.0,
    )


def test_sequence_resolver_recovers_real_single_candidate_inside_long_gap_and_logs_it():
    cfg = AnalysisConfig()
    t_us = np.arange(0, 2400_000 + 8000, 8000, dtype=np.int64)
    signal = np.zeros(t_us.size, dtype=float)
    for center_ms in (0.0, 800.0, 1600.0, 2400.0):
        center = int(round(center_ms / 8.0))
        if 0 <= center < signal.size:
            signal[center] = 10.0
    ppg = PreprocessedPPG(
        t_us=t_us,
        signal=signal,
        sample_rate_hz=125.0,
        polarity=1,
        robust_amplitude=10.0,
    )
    # Middle candidate is intentionally below the first-pass single score but is
    # almost exactly at the missing sequence slot between dual anchors.
    consensus = [_peak(0, 2, 0.96), _peak(800, 1, 0.42), _peak(1600, 2, 0.96)]
    decisions = []

    selected = resolve_consensus_sequence(
        consensus,
        ppg,
        last_committed_t_us=-1,
        commit_until_t_us=1_600_000,
        reference_rr_ms=800.0,
        config=cfg,
        decision_sink=decisions,
    )

    selected_times = [item.t_us for item in selected]
    assert 800_000 in selected_times
    middle = next(item for item in decisions if item.t_us == 800_000)
    assert middle.decision == "selected_rescued"
    assert "single_detector" in middle.detector_names or middle.detector_names == "multiscale"


def test_mature_frequency_window_keeps_boundary_anchor_instead_of_rebuffering():
    cfg = AnalysisConfig()
    # 0.8 s NN cadence makes the first interval after an exact 300 s cutoff land
    # slightly after the boundary.  The previous interval is required as anchor.
    intervals: list[NNInterval] = []
    t_s = 0.0
    while t_s <= 620.0:
        t_s += 0.8
        intervals.append(NNInterval(t_us=int(round(t_s * 1e6)), nn_ms=800.0))

    prepared = prepare_tachogram(intervals, cfg)
    assert prepared is not None
    _, _, duration, usable = prepared
    assert duration >= cfg.frequency_window_seconds * 0.995
    assert usable[-1].t_us - usable[0].t_us >= 299_000_000


def _research_row(t_s: float, *, ready: bool = True, status: str = "VALID", hf: float = 300.0) -> dict:
    return {
        "t_us": int(t_s * 1e6),
        "hr_bpm": 70.0,
        "time_status": status,
        "frequency_status": status,
        "frequency_ready": ready,
        "frequency_progress": 1.0 if ready else min(t_s / 300.0, 0.99),
        "frequency_duration_seconds": 300.0 if ready else min(t_s, 299.0),
        "rmssd_ms": 30.0,
        "total_power_ms2": 1000.0 if ready else float("nan"),
        "vlf_ms2": 200.0 if ready else float("nan"),
        "lf_ms2": 500.0 if ready else float("nan"),
        "hf_ms2": hf if ready else float("nan"),
        "lf_nu": 62.5,
        "hf_nu": 37.5,
        "lf_hf": 1.67,
        "median_frequency_hz": 0.13,
        "thm_power_ms2": 180.0,
        "resonance_band_power_ms2": 120.0,
        "resonance_share": 0.15,
        "lf_peak_frequency_hz": 0.08,
        "lf_peak_prominence_ratio": 1.5,
        "spectral_agreement": 0.95,
        "band_power_agreement": 0.94,
        "interpolation_agreement": 0.99,
        "overall_status": status,
        "transport_score": 0.99,
        "transport_status": "VALID",
    }


def _research_snapshot(t_s: float, *, status: str = "LIMITED") -> AnalysisSnapshot:
    return AnalysisSnapshot(
        t_us=int(t_s * 1e6),
        hr_bpm=61.0,
        time=TimeDomainMetrics(valid=True, status=status, rmssd_ms=58.0, nn_count=60),
        frequency=FrequencyDomainMetrics(
            valid=True,
            status=status,
            progress=1.0,
            duration_seconds=300.0,
            total_power_ms2=1340.0,
            vlf_ms2=210.0,
            lf_ms2=370.0,
            hf_ms2=760.0,
            lf_nu=33.0,
            hf_nu=67.0,
            lf_hf=0.49,
            hf_lf=2.04,
            median_frequency_hz=0.14,
            spectral_agreement=0.90,
            band_power_agreement=0.88,
            interpolation_agreement=0.99,
            freqs_hz=np.linspace(0.0033, 0.4, 256),
            psd_ms2_hz=np.ones(256),
        ),
        signal_quality=SignalQuality(
            sqi=0.8,
            status=status,
            transport_score=0.99,
            transport_status="VALID",
            contact_score=0.7,
            contact_status=status,
        ),
        quality=QualityAssessment(
            sqi=0.8,
            status=status,
            time_status=status,
            frequency_status=status,
        ),
    )


def test_research_baseline_does_not_count_frequency_buffering_rows():
    buffering = [_research_row(t, ready=False, status="LIMITED") for t in (0, 120, 240, 360, 480)]
    baseline = _build_personal_baseline(buffering, int(600 * 1e6))
    assert not baseline["ready"]
    assert baseline["rows"] == []

    # v0.4.3 requires genuinely separated five-minute anchors spanning at
    # least fifteen minutes; four heavily overlapping rows are not a baseline.
    mature = [_research_row(t, ready=True) for t in (300, 600, 900, 1200)]
    baseline = _build_personal_baseline(mature, int(1380 * 1e6))
    assert baseline["ready"]
    assert len(baseline["rows"]) >= 4
    assert baseline["span_seconds"] >= 15 * 60


def test_research_baseline_uses_feature_unit_aware_scale_floors():
    # A perfectly flat short reference must not create near-zero dispersion for
    # differently-scaled features.  Otherwise tiny percentage-point changes can
    # become huge z-scores and make the user state jump.
    mature = [_research_row(t, ready=True) for t in (300, 600, 900, 1200)]
    baseline = _build_personal_baseline(mature, int(1380 * 1e6))

    assert baseline["ready"]
    assert baseline["features"]["hr_bpm"]["scale"] >= 1.5
    assert baseline["features"]["hf_nu"]["scale"] >= 3.0
    assert baseline["features"]["median_frequency_hz"]["scale"] >= 0.015
    assert baseline["features"]["resonance_share"]["scale"] >= 0.04


def test_limited_research_evidence_no_longer_has_mathematical_similarity_ceiling():
    history = []
    for t in range(0, 36 * 60, 20):
        row = _research_row(t)
        if t >= 24 * 60:
            row.update(
                hr_bpm=62.0,
                rmssd_ms=55.0,
                lf_ms2=380.0,
                hf_ms2=720.0,
                lf_nu=35.0,
                hf_nu=65.0,
                lf_hf=0.53,
            )
        history.append(row)

    snapshot = _research_snapshot(36 * 60, status="LIMITED")
    result = evaluate_research_state(snapshot, history)
    inward = next(item for item in result["matches"] if item["code"] == "INWARD_QUIET")

    assert inward["quality_multiplier"] < 0.70
    assert inward["evidence_score"] >= 0.90
    assert inward["score"] >= 0.70
    assert inward["lifecycle"] == "ACTIVE"
    assert "QUALITY_CEILING" not in inward["no_match_reason"]


def test_historical_research_timeline_is_causal_and_stable_when_future_rows_are_added():
    history = [_research_row(t) for t in range(0, 30 * 60 + 1, 20)]
    before = _timeline_score_rows(history)
    early_t = int(27 * 60 * 1e6)
    early_before = next(item for item in before if item["t_us"] == early_t)

    extended = history + [
        _research_row(t, hf=1800.0 if (t // 20) % 2 == 0 else 80.0)
        for t in range(30 * 60 + 20, 34 * 60 + 1, 20)
    ]
    after = _timeline_score_rows(extended)
    early_after = next(item for item in after if item["t_us"] == early_t)

    score_keys = [key for key in early_before if key.startswith("score_")]
    assert all(early_before[key] == early_after[key] for key in score_keys)
    assert early_after["latest_data_t_us"] <= early_after["t_us"]
    assert early_after["baseline_version"] <= early_after["t_us"]


def test_same_research_state_separated_by_neutral_gap_is_not_counted_as_self_transition(monkeypatch):
    # Unit-test the segmentation semantics without depending on the exact prototype
    # formula.  A -> neutral -> A must not produce "A 到 A".
    import hrv_app.research_prototypes as rp

    timeline = [
        {"t_us": 0, "primary_code": "INWARD_QUIET", "primary_score": 0.9},
        {"t_us": 20_000_000, "primary_code": "STABLE_NEUTRAL", "primary_score": 0.2},
        {"t_us": 40_000_000, "primary_code": "INWARD_QUIET", "primary_score": 0.85},
    ]

    monkeypatch.setattr(rp, "_timeline_score_rows", lambda history, baseline=None: timeline)
    snapshot = _research_snapshot(40, status="VALID")
    result = build_hour_experience(snapshot, [_research_row(0), _research_row(20), _research_row(40)])

    assert result["transition_count"] == 0
    assert "到安静向内" not in result["hour_summary"] or "从安静向内到安静向内" not in result["hour_summary"]


def test_many_resolved_structural_repairs_do_not_hard_gate_time_domain_by_artifact_ratio_alone():
    # Four repaired split pairs are >5% of a 60-RR window. They interrupt the raw
    # RMSSD chain but are not unresolved evidence, so the remaining long raw runs
    # are still allowed to support a time-domain result.
    rrs = [800] * 22
    for _ in range(4):
        rrs.extend([340, 460])
    rrs.extend([800] * 30)
    cleaned = BeatTimelineCleaner().clean(_beats(rrs))
    metrics = compute_time_domain(cleaned.records, cleaned.nn_intervals, _quality())

    assert metrics.detected_artifact_ratio > 0.05
    assert metrics.resolved_artifact_ratio > 0.05
    assert metrics.unresolved_suspect_ratio == 0.0
    assert metrics.max_consecutive_unresolved == 0
    assert metrics.valid


def test_analysis_history_timestamp_never_regresses_after_newer_forced_refresh():
    from hrv_app.engine import AnalysisEngine

    engine = AnalysisEngine()
    engine._last_snapshot = AnalysisSnapshot(t_us=10_000_000)
    with engine._lock:
        engine._update_metrics_locked(5_000_000, record_history=True)

    assert engine.snapshot().t_us == 10_000_000
    assert engine.metric_history()[-1]["t_us"] == 10_000_000


def test_artifact_provenance_keeps_pair_time_and_raw_rr_evidence():
    from hrv_app.provenance import build_interval_artifact_trace_row

    cleaned = BeatTimelineCleaner().clean(
        _beats([744, 752, 748, 746, 750, 742, 754, 336.004, 407.998, 746])
    )
    decision = cleaned.artifact_decisions[8]
    record = next(item for item in cleaned.records if item.t_us == decision.t_us)
    row = build_interval_artifact_trace_row(decision, record, revision=2)

    assert row["artifact_class"] == "extra_peak_merge"
    assert row["status"] == "false_peak_merged"
    assert row["resolved"] == 1
    assert row["paired_t_us"] > 0
    assert math.isclose(row["rr_raw_ms"], 407.998, abs_tol=0.01)
    assert math.isclose(row["corrected_rr_ms"], 744.002, abs_tol=0.01)
    assert row["revision"] == 2
