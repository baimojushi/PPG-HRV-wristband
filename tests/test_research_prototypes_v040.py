from __future__ import annotations

from pathlib import Path

import numpy as np

from hrv_app.literature_registry import (
    get_source,
    render_source_facts_html,
    sources_to_dict,
)
from hrv_app.models import (
    AnalysisSnapshot,
    FrequencyDomainMetrics,
    QualityAssessment,
    SignalQuality,
    TimeDomainMetrics,
)
from hrv_app.research_prototypes import (
    PROTOTYPE_DEFINITIONS,
    build_hour_experience,
    evaluate_research_state,
    extract_research_frequency_features,
    research_state_table,
)


def _row(
    t_s: float,
    *,
    hr: float = 70.0,
    rmssd: float = 30.0,
    vlf: float = 200.0,
    lf: float = 500.0,
    hf: float = 300.0,
    hf_nu: float = 37.5,
    lf_hf: float = 1.67,
    thm: float = 180.0,
    peak_hz: float = 0.08,
    prominence: float = 1.5,
    resonance_share: float = 0.15,
    status: str = "VALID",
) -> dict:
    return {
        "t_us": int(
            round(
                t_s
                * 1e6
            )
        ),
        "hr_bpm": hr,
        "time_status": status,
        "rmssd_ms": rmssd,
        "frequency_status": status,
        "total_power_ms2": (
            vlf
            + lf
            + hf
        ),
        "vlf_ms2": vlf,
        "lf_ms2": lf,
        "hf_ms2": hf,
        "lf_nu": 100.0 - hf_nu,
        "hf_nu": hf_nu,
        "lf_hf": lf_hf,
        "median_frequency_hz": 0.13,
        "thm_power_ms2": thm,
        "resonance_band_power_ms2": (
            resonance_share
            * (
                lf
                + hf
            )
        ),
        "resonance_share": resonance_share,
        "lf_peak_frequency_hz": peak_hz,
        "lf_peak_prominence_ratio": prominence,
        "spectral_agreement": 0.95,
        "band_power_agreement": 0.94,
        "interpolation_agreement": 0.99,
        "sqi": 0.95,
        "overall_status": status,
        "detected_artifact_ratio": 0.01,
        "unresolved_suspect_ratio": 0.0,
    }


def _snapshot(
    t_s: float,
    *,
    hr: float,
    rmssd: float,
    vlf: float,
    lf: float,
    hf: float,
    hf_nu: float,
    lf_hf: float,
    freqs: np.ndarray | None = None,
    psd: np.ndarray | None = None,
) -> AnalysisSnapshot:
    if freqs is None:
        freqs = np.linspace(
            0.0033,
            0.40,
            256,
        )

    if psd is None:
        psd = (
            1.0
            + 4.0
            * np.exp(
                -0.5
                * (
                    (
                        freqs
                        - 0.10
                    )
                    / 0.03
                )
                ** 2
            )
        )

    frequency = FrequencyDomainMetrics(
        valid=True,
        status="VALID",
        progress=1.0,
        duration_seconds=300.0,
        total_power_ms2=(
            vlf
            + lf
            + hf
        ),
        vlf_ms2=vlf,
        lf_ms2=lf,
        hf_ms2=hf,
        lf_nu=(
            100.0
            - hf_nu
        ),
        hf_nu=hf_nu,
        lf_hf=lf_hf,
        hf_lf=(
            1.0
            / max(
                lf_hf,
                1e-9,
            )
        ),
        median_frequency_hz=0.14,
        spectral_agreement=0.95,
        band_power_agreement=0.94,
        interpolation_agreement=0.99,
        freqs_hz=freqs,
        psd_ms2_hz=psd,
    )

    return AnalysisSnapshot(
        t_us=int(
            round(
                t_s
                * 1e6
            )
        ),
        hr_bpm=hr,
        time=TimeDomainMetrics(
            valid=True,
            status="VALID",
            rmssd_ms=rmssd,
            nn_count=300,
            detected_artifact_ratio=0.01,
            unresolved_suspect_ratio=0.0,
        ),
        frequency=frequency,
        signal_quality=SignalQuality(
            sqi=0.95,
            status="VALID",
        ),
        quality=QualityAssessment(
            sqi=0.95,
            status="VALID",
            time_status="VALID",
            frequency_status="VALID",
        ),
    )


def test_literature_registry_contains_clickable_number_and_subject_identity():
    source = get_source(
        1
    )
    html = render_source_facts_html(
        [1]
    )

    assert source.source_id == 1
    assert "10名" in source.study_detail
    assert "Zen" in source.study_detail
    assert "<a href=" in html
    assert ">[1]</a>" in html
    assert source.authors in html
    assert source.title in html
    assert len(
        sources_to_dict()
    ) >= 8


def test_literature_reference_uses_linked_number_then_title_and_author():
    source = get_source(1)
    html = source.ui_fact_line()

    expected = (
        f">[1]</a> 《{source.title}》 — {source.authors}"
    )
    assert expected in html
    assert html.endswith(
        f"《{source.title}》 — {source.authors}"
    )


def test_all_research_prototypes_have_separate_user_narrative():
    for code, definition in PROTOTYPE_DEFINITIONS.items():
        assert definition["test_state"].strip(), code
        assert definition["user_narrative"].strip(), code
        assert (
            definition["user_narrative"]
            != definition["test_state"]
        ), code

    table = research_state_table()
    assert all(
        item.get("user_narrative", "").strip()
        for item in table
    )


def test_user_facing_research_copy_avoids_engineering_jargon():
    forbidden = (
        "RMSSD", "VLF", "LF/HF", "HF", "Welch", "SPWVD",
        "频域", "频谱", "中位频率", "交感", "副交感",
    )

    for code, definition in PROTOTYPE_DEFINITIONS.items():
        narrative = definition["user_narrative"]
        for jargon in forbidden:
            assert jargon not in narrative, (code, jargon)

    for source in sources_to_dict():
        public_fact = source["study_detail"] + source["finding_detail"]
        for jargon in forbidden:
            assert jargon not in public_fact, (source["source_id"], jargon)


def test_extract_research_features_detects_narrow_0p1_hz_peak():
    freqs = np.linspace(
        0.0033,
        0.40,
        512,
    )
    psd = (
        0.4
        + 18.0
        * np.exp(
            -0.5
            * (
                (
                    freqs
                    - 0.095
                )
                / 0.006
            )
            ** 2
        )
    )

    frequency = FrequencyDomainMetrics(
        valid=True,
        status="VALID",
        vlf_ms2=20.0,
        lf_ms2=500.0,
        hf_ms2=120.0,
        freqs_hz=freqs,
        psd_ms2_hz=psd,
    )

    features = extract_research_frequency_features(
        frequency
    )

    assert 0.085 <= features[
        "lf_peak_frequency_hz"
    ] <= 0.105
    assert features[
        "lf_peak_prominence_ratio"
    ] > 4.0
    assert features[
        "resonance_share"
    ] > 0.20


def test_personal_baseline_does_not_mature_from_short_overlapping_history():
    history = [_row(float(seconds)) for seconds in range(0, 12 * 60, 20)]
    snapshot = _snapshot(
        12 * 60,
        hr=70.0,
        rmssd=30.0,
        vlf=200.0,
        lf=500.0,
        hf=300.0,
        hf_nu=37.5,
        lf_hf=1.67,
    )

    result = evaluate_research_state(snapshot, history)

    assert not result["baseline_ready"]
    assert result["baseline_reference_window_count"] < 4
    assert "5分钟" in result["baseline_reason"] or "15分钟" in result["baseline_reason"]


def test_inward_quiet_requires_long_baseline_and_sustained_evidence_window():
    history = []
    for seconds in range(0, 32 * 60, 20):
        if seconds < 24 * 60:
            history.append(_row(float(seconds)))
        else:
            history.append(
                _row(
                    float(seconds),
                    hr=62.0,
                    rmssd=55.0,
                    lf=380.0,
                    hf=720.0,
                    hf_nu=65.0,
                    lf_hf=0.53,
                )
            )

    snapshot = _snapshot(
        32 * 60,
        hr=61.0,
        rmssd=58.0,
        vlf=210.0,
        lf=370.0,
        hf=760.0,
        hf_nu=67.0,
        lf_hf=0.49,
    )

    result = evaluate_research_state(snapshot, history)
    inward = next(item for item in result["matches"] if item["code"] == "INWARD_QUIET")

    assert result["baseline_ready"]
    assert result["baseline"]["span_seconds"] >= 15 * 60
    assert inward["temporal_ready"]
    assert inward["observation_minutes"] == 8.0
    assert inward["observed_span_minutes"] >= 7.0
    # The physiological evidence is already strong, but the one-hour state
    # layer must accumulate it gradually instead of jumping from 0 to >0.7.
    assert inward["evidence_score"] >= 0.90
    assert 0.50 <= inward["score"] < 0.70
    assert inward["lifecycle"] == "CANDIDATE"
    assert 1 in inward["source_ids"]

    longer_history = []
    for seconds in range(0, 36 * 60, 20):
        if seconds < 24 * 60:
            longer_history.append(_row(float(seconds)))
        else:
            longer_history.append(
                _row(
                    float(seconds),
                    hr=62.0,
                    rmssd=55.0,
                    lf=380.0,
                    hf=720.0,
                    hf_nu=65.0,
                    lf_hf=0.53,
                )
            )
    longer = evaluate_research_state(
        _snapshot(
            36 * 60,
            hr=61.0,
            rmssd=58.0,
            vlf=210.0,
            lf=370.0,
            hf=760.0,
            hf_nu=67.0,
            lf_hf=0.49,
        ),
        longer_history,
    )
    longer_inward = next(item for item in longer["matches"] if item["code"] == "INWARD_QUIET")
    assert longer_inward["score"] >= 0.70
    assert longer_inward["lifecycle"] == "ACTIVE"


def test_resonance_needs_multi_minute_evidence_even_before_personal_baseline():
    freqs = np.linspace(0.0033, 0.40, 512)
    psd = 0.2 + 35.0 * np.exp(-0.5 * (((freqs - 0.095) / 0.004) ** 2))

    snapshot = _snapshot(
        330.0,
        hr=72.0,
        rmssd=45.0,
        vlf=30.0,
        lf=900.0,
        hf=120.0,
        hf_nu=12.0,
        lf_hf=7.5,
        freqs=freqs,
        psd=psd,
    )
    features = extract_research_frequency_features(snapshot.frequency)

    history = []
    for seconds in range(30, 330, 20):
        history.append({
            **_row(
                float(seconds),
                lf=900.0,
                hf=120.0,
                peak_hz=features["lf_peak_frequency_hz"],
                prominence=features["lf_peak_prominence_ratio"],
                resonance_share=features["resonance_share"],
            ),
            "thm_power_ms2": features["thm_power_ms2"],
        })

    result = evaluate_research_state(snapshot, history)
    resonance = next(item for item in result["matches"] if item["code"] == "RESONANCE_0P1")

    assert not result["baseline_ready"]
    assert resonance["temporal_ready"]
    assert resonance["observed_span_minutes"] >= 4.0
    assert resonance["evidence_score"] >= 0.90
    # Five minutes of sustained raw evidence starts the state memory, but it
    # cannot become ACTIVE in a single refresh.
    assert 0.20 <= resonance["score"] < 0.50
    assert resonance["lifecycle"] == "INACTIVE"
    assert 2 in resonance["source_ids"]

    later_snapshot = _snapshot(
        10 * 60,
        hr=72.0,
        rmssd=45.0,
        vlf=30.0,
        lf=900.0,
        hf=120.0,
        hf_nu=12.0,
        lf_hf=7.5,
        freqs=freqs,
        psd=psd,
    )
    later_history = []
    for seconds in range(30, 10 * 60, 20):
        later_history.append({
            **_row(
                float(seconds),
                lf=900.0,
                hf=120.0,
                peak_hz=features["lf_peak_frequency_hz"],
                prominence=features["lf_peak_prominence_ratio"],
                resonance_share=features["resonance_share"],
            ),
            "thm_power_ms2": features["thm_power_ms2"],
        })
    later = evaluate_research_state(later_snapshot, later_history)
    later_resonance = next(item for item in later["matches"] if item["code"] == "RESONANCE_0P1")
    assert later_resonance["score"] >= 0.70
    assert later_resonance["lifecycle"] == "ACTIVE"


def test_resonance_does_not_jump_from_one_fresh_window():
    freqs = np.linspace(0.0033, 0.40, 512)
    psd = 0.2 + 35.0 * np.exp(-0.5 * (((freqs - 0.095) / 0.004) ** 2))
    snapshot = _snapshot(
        330.0,
        hr=72.0,
        rmssd=45.0,
        vlf=30.0,
        lf=900.0,
        hf=120.0,
        hf_nu=12.0,
        lf_hf=7.5,
        freqs=freqs,
        psd=psd,
    )
    features = extract_research_frequency_features(snapshot.frequency)
    history = [{
        **_row(
            310.0,
            lf=900.0,
            hf=120.0,
            peak_hz=features["lf_peak_frequency_hz"],
            prominence=features["lf_peak_prominence_ratio"],
            resonance_share=features["resonance_share"],
        ),
        "thm_power_ms2": features["thm_power_ms2"],
    }]

    result = evaluate_research_state(snapshot, history)
    resonance = next(item for item in result["matches"] if item["code"] == "RESONANCE_0P1")

    assert not resonance["temporal_ready"]
    assert resonance["score"] == 0.0
    assert resonance["lifecycle"] == "INACTIVE"


def test_hour_experience_has_hour_stage_timeline_and_trait_gate():
    history = []

    for index in range(
        0,
        46 * 60,
        20,
    ):
        # 前半段稳定，后半段逐渐转向HF增强。
        if index < 30 * 60:
            row = _row(
                float(index),
            )
        else:
            row = _row(
                float(index),
                hr=63.0,
                rmssd=52.0,
                lf=410.0,
                hf=680.0,
                hf_nu=62.0,
                lf_hf=0.60,
            )

        history.append(
            row
        )

    snapshot = _snapshot(
        46 * 60,
        hr=62.0,
        rmssd=55.0,
        vlf=205.0,
        lf=400.0,
        hf=700.0,
        hf_nu=64.0,
        lf_hf=0.57,
    )

    result = build_hour_experience(
        snapshot,
        history,
    )

    assert result[
        "stage_code"
    ] == "H4_HOUR_SCALE"
    assert result[
        "elapsed_minutes"
    ] >= 45.0
    assert result[
        "valid_coverage"
    ] > 0.9
    assert result[
        "baseline_ready"
    ]
    assert len(
        result[
            "timeline"
        ]
    ) > 30
    assert result[
        "trait_reference_state"
    ][
        "code"
    ] == "T0_TRAIT_UNKNOWN"
    assert not result[
        "trait_reference_state"
    ][
        "enabled"
    ]
    assert result["hour_summary"].strip()
    assert result["state_distribution"]
    assert all(
        item.get("name", "").strip()
        for item in result["state_distribution"]
    )


def test_hour_research_curve_uses_temporal_state_not_pointwise_jump():
    history = []
    for seconds in range(0, 46 * 60, 20):
        if seconds < 30 * 60:
            history.append(_row(float(seconds)))
        else:
            history.append(
                _row(
                    float(seconds),
                    hr=63.0,
                    rmssd=52.0,
                    lf=410.0,
                    hf=680.0,
                    hf_nu=62.0,
                    lf_hf=0.60,
                )
            )

    snapshot = _snapshot(
        46 * 60,
        hr=62.0,
        rmssd=55.0,
        vlf=205.0,
        lf=400.0,
        hf=700.0,
        hf_nu=64.0,
        lf_hf=0.57,
    )
    result = build_hour_experience(snapshot, history)
    timeline = result["timeline"]

    state_scores = np.asarray(
        [row["score_INWARD_QUIET"] for row in timeline],
        dtype=float,
    )
    finite_diffs = np.abs(np.diff(state_scores))
    finite_diffs = finite_diffs[np.isfinite(finite_diffs)]
    raw_scores = np.asarray(
        [row["raw_score_INWARD_QUIET"] for row in timeline],
        dtype=float,
    )
    raw_diffs = np.abs(np.diff(raw_scores))
    raw_diffs = raw_diffs[np.isfinite(raw_diffs)]

    assert timeline
    assert all("raw_score_INWARD_QUIET" in row for row in timeline)
    assert finite_diffs.size and raw_diffs.size
    assert float(np.max(finite_diffs)) < 0.15
    assert float(np.max(finite_diffs)) < float(np.max(raw_diffs)) * 0.75
    # The one-hour state layer is intentionally coarser than the 20-second
    # physiological observation history, while still using all rows internally.
    assert len(timeline) < len(history) / 2


def test_ui_contains_hour_research_layer_and_clickable_sources():
    project = (
        Path(__file__)
        .resolve()
        .parents[1]
    )
    ui = (
        project
        / "desktop"
        / "src"
        / "hrv_app"
        / "ui_app.py"
    ).read_text(
        encoding="utf-8"
    )

    assert "过去一小时 · 身体节律" in ui
    assert "解读进度：" in ui
    assert "prototype_score_plot" in ui
    assert "setOpenExternalLinks" in ui
    assert "TextBrowserInteraction" in ui
    assert "T0_TRAIT_UNKNOWN" not in ui
    assert "narrativeText" in ui
    assert "primary_source_facts_html" in ui
    assert "研究来源只说明曾有人出现过相似的心跳节律" in ui
    assert "匹配度 {float(primary" not in ui
    assert 'f"{stage_code} · {stage_name}' not in ui


def test_main_tab_prioritizes_hour_narrative_and_analysis_owns_ppg_debug():
    project = Path(__file__).resolve().parents[1]
    ui = (
        project
        / "desktop"
        / "src"
        / "hrv_app"
        / "ui_app.py"
    ).read_text(encoding="utf-8")

    state_start = ui.index("def _build_state_tab")
    analysis_start = ui.index("def _build_analysis_tab")
    state_section = ui[state_start:analysis_start]
    analysis_section = ui[analysis_start:]

    assert "layout.addWidget(\n            self.hour_experience_frame" in state_section
    assert 'layout.addWidget(QLabel("实时 PPG + 8秒整窗波形复核"))' not in state_section
    assert 'layout.addWidget(QLabel("心跳波形（排查读数异常时查看）"))' in analysis_section
    assert "self.protocol_debug_label" in analysis_section
    assert "self.quality_debug_label" in analysis_section


def test_storage_exports_research_layer_files():
    project = (
        Path(__file__)
        .resolve()
        .parents[1]
    )
    storage = (
        project
        / "desktop"
        / "src"
        / "hrv_app"
        / "storage.py"
    ).read_text(
        encoding="utf-8"
    )

    for filename in [
        "research_prototype_snapshot.json",
        "hour_experience.json",
        "research_prototype_table.json",
        "literature_sources.json",
        "research_state_timeline.csv",
    ]:
        assert filename in storage


def test_hour_timeline_uses_nan_when_research_similarity_is_unavailable():
    history = []
    for seconds in range(0, 46 * 60, 20):
        status = "INVALID" if seconds == 36 * 60 else "VALID"
        history.append(_row(float(seconds), status=status))

    snapshot = _snapshot(
        46 * 60,
        hr=70.0,
        rmssd=30.0,
        vlf=200.0,
        lf=500.0,
        hf=300.0,
        hf_nu=37.5,
        lf_hf=1.67,
    )

    result = build_hour_experience(snapshot, history)
    unavailable = next(
        item
        for item in result["timeline"]
        if item["t_us"] == 36 * 60 * 1_000_000
    )

    assert unavailable["primary_code"] == "DATA_UNSTABLE"
    score_values = [
        value
        for key, value in unavailable.items()
        if key.startswith("score_")
    ]
    assert score_values
    assert all(np.isnan(value) for value in score_values)
