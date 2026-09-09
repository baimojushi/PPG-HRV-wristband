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


def test_inward_quiet_requires_personal_baseline_and_two_consecutive_windows():
    history = [
        _row(0.0),
        _row(120.0),
        _row(240.0),
        _row(360.0),
        _row(
            580.0,
            hr=62.0,
            rmssd=55.0,
            lf=380.0,
            hf=720.0,
            hf_nu=65.0,
            lf_hf=0.53,
        ),
    ]

    snapshot = _snapshot(
        600.0,
        hr=61.0,
        rmssd=58.0,
        vlf=210.0,
        lf=370.0,
        hf=760.0,
        hf_nu=67.0,
        lf_hf=0.49,
    )

    result = evaluate_research_state(
        snapshot,
        history,
    )

    inward = next(
        item
        for item in result[
            "matches"
        ]
        if item[
            "code"
        ]
        == "INWARD_QUIET"
    )

    assert result[
        "baseline_ready"
    ]
    assert inward[
        "score"
    ] >= 0.70
    assert inward[
        "lifecycle"
    ] == "ACTIVE"
    assert 1 in inward[
        "source_ids"
    ]


def test_resonance_can_be_candidate_before_personal_baseline_is_ready():
    freqs = np.linspace(
        0.0033,
        0.40,
        512,
    )
    psd = (
        0.2
        + 35.0
        * np.exp(
            -0.5
            * (
                (
                    freqs
                    - 0.095
                )
                / 0.004
            )
            ** 2
        )
    )

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

    features = extract_research_frequency_features(
        snapshot.frequency
    )

    history = [
        {
            **_row(
                310.0,
                lf=900.0,
                hf=120.0,
                peak_hz=features[
                    "lf_peak_frequency_hz"
                ],
                prominence=features[
                    "lf_peak_prominence_ratio"
                ],
                resonance_share=features[
                    "resonance_share"
                ],
            ),
            "thm_power_ms2": features[
                "thm_power_ms2"
            ],
        },
    ]

    result = evaluate_research_state(
        snapshot,
        history,
    )

    resonance = next(
        item
        for item in result[
            "matches"
        ]
        if item[
            "code"
        ]
        == "RESONANCE_0P1"
    )

    assert not result[
        "baseline_ready"
    ]
    assert resonance[
        "score"
    ] >= 0.70
    assert resonance[
        "lifecycle"
    ] in {
        "CANDIDATE",
        "ACTIVE",
    }
    assert 2 in resonance[
        "source_ids"
    ]


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
