from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
import math

import numpy as np

from .config import AnalysisConfig
from .literature_registry import (
    get_source,
    render_source_facts_html,
)
from .models import AnalysisSnapshot, FrequencyDomainMetrics


# 匹配门槛常量。
# `_parse_no_match_reason` 会用到这个名字；只存一个引用，不改任何阈值。
_MATCH_THRESHOLD_ACTIVE = 0.70
_MATCH_THRESHOLD_CANDIDATE = 0.50


PROTOTYPE_DEFINITIONS: dict[str, dict] = {
    "INWARD_QUIET": {
        "name": "向内安静",
        "priority": 40,
        "source_ids": [1, 5],
        "test_state": (
            "静止、注意向内时，心率趋缓，RMSSD与HF相对个人近期稳定基线增强，"
            "同时LF/HF谱形比下降。"
        ),
        "user_narrative": (
            "这段时间，心跳整体稍慢，较快、常跟呼吸一起变化的起伏更明显，"
            "较慢与较快起伏的相对比例也在下降。研究中，静坐并把注意力转向身体内部时出现过相似组合。"
        ),
    },
    "RESONANCE_0P1": {
        "name": "缓慢而规律",
        "priority": 100,
        "source_ids": [2, 6],
        "test_state": (
            "Welch在约0.075–0.11 Hz形成窄而突出的主峰，"
            "连续窗口主峰频率稳定，表现为低频规则振荡结构。"
        ),
        "user_narrative": (
            "心跳起伏逐渐集中成一个缓慢而规律的节奏，大约每10秒完成一次起伏。"
            "慢呼吸和部分冥想研究里出现过相似节律。"
        ),
    },
    "PHASED_VIPASSANA": {
        "name": "分阶段变化",
        "priority": 80,
        "source_ids": [4],
        "test_state": (
            "十几到几十分钟内出现可重复的阶段结构：早段频带能量下降、"
            "中段LF与HF共同增强、后段再次回落。"
        ),
        "user_narrative": (
            "过去十几分钟出现了明显的阶段变化：前段起伏收窄，"
            "中段较慢和较快的起伏一起变明显，随后再次回落。"
        ),
    },
    "TRAINED_VIPASSANA_SHIFT": {
        "name": "呼吸起伏更明显",
        "priority": 55,
        "source_ids": [3],
        "test_state": (
            "HF标准化贡献相对近期基线增加，同时0.06–0.10 Hz "
            "Traube–Hering–Mayer子带功率下降。"
        ),
        "user_narrative": (
            "与刚才相比，较快、常跟呼吸一起变化的起伏更明显，"
            "同时一部分较慢起伏减弱，整个节律的重心正在移动。"
        ),
    },
    "AROUSAL_MEDITATION": {
        "name": "活跃而有序",
        "priority": 70,
        "source_ids": [5],
        "test_state": (
            "数据稳定时HF相对个人基线下降，心率没有同步减慢，"
            "形成与安静高频增强型不同的有组织状态。"
        ),
        "user_narrative": (
            "较快、常跟呼吸一起变化的起伏变弱，心率没有一起变慢，整体节律仍较有组织。"
            "研究中的部分清醒、活跃冥想练习出现过相似组合。"
        ),
    },
    "SLOW_RECOVERY_VLF": {
        "name": "缓慢恢复中",
        "priority": 50,
        "source_ids": [7],
        "test_state": (
            "较快的HF和LF/HF已回到个人基线附近，"
            "VLF仍持续偏离，形成更慢时间尺度的恢复拖尾。"
        ),
        "user_narrative": (
            "较快的起伏已经接近你这次记录里的近期常态，最慢的背景变化还没有完全回来，"
            "身体可能仍处在一个更慢的恢复过程里。"
        ),
    },
}


# v0.4.3 research temporal model.  The five-minute HRV estimate is an
# observation primitive, not a one-point "state".  Each prototype therefore
# has its own evidence horizon before its similarity can move the one-hour
# trajectory.  These windows deliberately differ because the prototypes
# describe phenomena at different time scales.
PROTOTYPE_TEMPORAL_MODEL: dict[str, dict[str, float]] = {
    "INWARD_QUIET": {
        "observation_minutes": 8.0,
        "minimum_span_minutes": 6.0,
        "activation_hold_minutes": 3.0,
        "exit_hold_minutes": 2.0,
        "state_rise_tau_minutes": 6.0,
        "state_fall_tau_minutes": 4.0,
    },
    "RESONANCE_0P1": {
        "observation_minutes": 5.0,
        "minimum_span_minutes": 4.0,
        "activation_hold_minutes": 2.0,
        "exit_hold_minutes": 1.5,
        "state_rise_tau_minutes": 5.0,
        "state_fall_tau_minutes": 4.0,
    },
    "PHASED_VIPASSANA": {
        "observation_minutes": 24.0,
        "minimum_span_minutes": 14.0,
        "activation_hold_minutes": 5.0,
        "exit_hold_minutes": 3.0,
        "state_rise_tau_minutes": 10.0,
        "state_fall_tau_minutes": 7.0,
    },
    "TRAINED_VIPASSANA_SHIFT": {
        "observation_minutes": 10.0,
        "minimum_span_minutes": 8.0,
        "activation_hold_minutes": 4.0,
        "exit_hold_minutes": 2.5,
        "state_rise_tau_minutes": 7.0,
        "state_fall_tau_minutes": 5.0,
    },
    "AROUSAL_MEDITATION": {
        "observation_minutes": 8.0,
        "minimum_span_minutes": 6.0,
        "activation_hold_minutes": 3.0,
        "exit_hold_minutes": 2.0,
        "state_rise_tau_minutes": 6.0,
        "state_fall_tau_minutes": 4.0,
    },
    "SLOW_RECOVERY_VLF": {
        "observation_minutes": 20.0,
        "minimum_span_minutes": 14.0,
        "activation_hold_minutes": 6.0,
        "exit_hold_minutes": 4.0,
        "state_rise_tau_minutes": 12.0,
        "state_fall_tau_minutes": 8.0,
    },
}

_BASELINE_EXCLUDE_RECENT_SECONDS = 3.0 * 60.0
_BASELINE_MINIMUM_GAP_SECONDS = 5.0 * 60.0
_BASELINE_MINIMUM_SPAN_SECONDS = 15.0 * 60.0
_BASELINE_MINIMUM_REFERENCE_WINDOWS = 4
_BASELINE_LOOKBACK_SECONDS = 2.0 * 60.0 * 60.0
_TEMPORAL_MINIMUM_COVERAGE = 0.68

def research_state_display_name(code: str) -> str:
    definition = PROTOTYPE_DEFINITIONS.get(str(code))
    if definition is not None:
        return str(definition["name"])

    return {
        "STABLE_NEUTRAL": "暂无突出节律",
        "REFERENCE_BUILDING": "正在形成长期参照",
        "DATA_UNSTABLE": "暂时看不清",
    }.get(str(code), str(code))


def _coalesce_meaningful_segments(segments: Sequence[dict]) -> list[dict]:
    """Remove non-research gaps and merge the same research state across them.

    A -> neutral/unavailable -> A is one interrupted observation of A, not a
    physiological transition from A to A.  Keep the raw ``segments`` for
    audit/UI shading, but use this coalesced view for transition language.
    """
    merged: list[dict] = []
    for raw in segments:
        code = str(raw.get("code", ""))
        if code in {"STABLE_NEUTRAL", "REFERENCE_BUILDING", "DATA_UNSTABLE"}:
            continue
        segment = dict(raw)
        if merged and str(merged[-1].get("code", "")) == code:
            merged[-1]["end_t_us"] = int(segment.get("end_t_us", merged[-1].get("end_t_us", 0)))
            merged[-1]["minutes"] = float(merged[-1].get("minutes", 0.0)) + float(segment.get("minutes", 0.0))
            merged[-1]["max_score"] = max(
                float(merged[-1].get("max_score", 0.0)),
                float(segment.get("max_score", 0.0)),
            )
        else:
            merged.append(segment)
    return merged


def _hour_trajectory_summary(
    elapsed_minutes: float,
    state_minutes: dict[str, float],
    segments: Sequence[dict],
) -> str:
    period_name = (
        "过去一小时"
        if elapsed_minutes >= 60.0
        else "这段记录"
    )

    meaningful_distribution = [
        (code, float(minutes))
        for code, minutes in sorted(
            state_minutes.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        if code not in {
            "STABLE_NEUTRAL",
            "REFERENCE_BUILDING",
            "DATA_UNSTABLE",
        }
        and float(minutes) > 0.0
    ]

    meaningful_segments = _coalesce_meaningful_segments(segments)

    if not meaningful_distribution:
        unstable_minutes = float(
            state_minutes.get("DATA_UNSTABLE", 0.0)
        )
        stable_minutes = float(
            state_minutes.get("STABLE_NEUTRAL", 0.0)
        )
        if unstable_minutes > stable_minutes:
            return (
                f"{period_name}里，能连续看清的时间还不够多，先不急着给变化下结论。"
            )
        return (
            f"{period_name}大部分时间没有出现特别突出的节律组合，整体变化较平缓。"
        )

    dominant_code, dominant_minutes = meaningful_distribution[0]
    dominant_name = research_state_display_name(dominant_code)

    if len(meaningful_segments) >= 2:
        previous_name = research_state_display_name(
            str(meaningful_segments[-2].get("code", ""))
        )
        current_name = research_state_display_name(
            str(meaningful_segments[-1].get("code", ""))
        )
        return (
            f"{period_name}里，{dominant_name}累计最久，约{dominant_minutes:.1f}分钟；"
            f"最近一次明显变化是从{previous_name}到{current_name}。"
        )

    return (
        f"{period_name}里，{dominant_name}是最持续的相似节律，"
        f"累计约{dominant_minutes:.1f}分钟。"
    )


FEATURE_TRANSFORMS: dict[str, str] = {
    "hr_bpm": "linear",
    "rmssd_ms": "log",
    "total_power_ms2": "log",
    "vlf_ms2": "log",
    "lf_ms2": "log",
    "hf_ms2": "log",
    "lf_nu": "linear",
    "hf_nu": "linear",
    "lf_hf": "log",
    "median_frequency_hz": "linear",
    "thm_power_ms2": "log",
    "resonance_share": "linear",
    "lf_peak_frequency_hz": "linear",
    "lf_peak_prominence_ratio": "log",
}

# Minimum robust scales are expressed in each feature's transformed unit.
# A single universal floor is dimensionally wrong here: 0.08 is tiny for
# HFnu measured in percentage points but enormous for a frequency in Hz.
# Unit-aware floors stop an unusually quiet baseline from turning a trivial
# numerical change into a multi-sigma research-state jump.
FEATURE_ROBUST_SCALE_FLOORS: dict[str, float] = {
    "hr_bpm": 1.5,
    "rmssd_ms": 0.15,
    "total_power_ms2": 0.18,
    "vlf_ms2": 0.18,
    "lf_ms2": 0.18,
    "hf_ms2": 0.18,
    "lf_nu": 3.0,
    "hf_nu": 3.0,
    "lf_hf": 0.18,
    "median_frequency_hz": 0.015,
    "thm_power_ms2": 0.18,
    "resonance_share": 0.04,
    "lf_peak_frequency_hz": 0.008,
    "lf_peak_prominence_ratio": 0.18,
}


def _band_power(
    frequency: FrequencyDomainMetrics,
    low_hz: float,
    high_hz: float,
) -> float:
    freqs = np.asarray(
        frequency.freqs_hz,
        dtype=float,
    )
    psd = np.asarray(
        frequency.psd_ms2_hz,
        dtype=float,
    )

    if (
        freqs.size < 2
        or psd.size != freqs.size
    ):
        return 0.0

    mask = (
        np.isfinite(freqs)
        & np.isfinite(psd)
        & (freqs >= low_hz)
        & (freqs < high_hz)
    )

    if np.count_nonzero(mask) < 2:
        return 0.0

    return float(
        np.trapezoid(
            np.maximum(
                psd[mask],
                0.0,
            ),
            freqs[mask],
        )
    )


def extract_research_frequency_features(
    frequency: FrequencyDomainMetrics,
) -> dict:
    if not frequency.valid:
        return {
            "thm_power_ms2": np.nan,
            "resonance_band_power_ms2": np.nan,
            "resonance_share": np.nan,
            "lf_peak_frequency_hz": np.nan,
            "lf_peak_prominence_ratio": np.nan,
        }

    freqs = np.asarray(
        frequency.freqs_hz,
        dtype=float,
    )
    psd = np.asarray(
        frequency.psd_ms2_hz,
        dtype=float,
    )

    thm_power = _band_power(
        frequency,
        0.06,
        0.10,
    )
    resonance_power = _band_power(
        frequency,
        0.075,
        0.11,
    )

    # resonance_share 必须和当前 PSD 使用同一积分口径。
    # 直接拿 PSD 子带积分除以外部已汇总的 LF/HF 数值，在测试数据、
    # 插值频率轴或后续谱估计器切换时可能产生单位/尺度不一致。
    lf_hf_spectral_total = _band_power(
        frequency,
        0.04,
        0.40,
    )

    if lf_hf_spectral_total <= 1e-12:
        lf_hf_spectral_total = max(
            float(
                frequency.lf_ms2
                + frequency.hf_ms2
            ),
            1e-12,
        )

    resonance_share = float(
        np.clip(
            resonance_power
            / lf_hf_spectral_total,
            0.0,
            1.0,
        )
    )

    peak_frequency = np.nan
    peak_prominence_ratio = np.nan

    if (
        freqs.size >= 3
        and psd.size == freqs.size
    ):
        mask = (
            np.isfinite(freqs)
            & np.isfinite(psd)
            & (freqs >= 0.04)
            & (freqs <= 0.15)
        )

        if np.count_nonzero(mask) >= 3:
            lf_freqs = freqs[mask]
            lf_psd = np.maximum(
                psd[mask],
                0.0,
            )

            peak_index = int(
                np.argmax(
                    lf_psd
                )
            )
            peak_frequency = float(
                lf_freqs[
                    peak_index
                ]
            )

            background = float(
                np.median(
                    lf_psd
                )
            )

            peak_prominence_ratio = float(
                lf_psd[
                    peak_index
                ]
                / max(
                    background,
                    1e-12,
                )
            )

    return {
        "thm_power_ms2": float(
            thm_power
        ),
        "resonance_band_power_ms2": float(
            resonance_power
        ),
        "resonance_share": float(
            resonance_share
        ),
        "lf_peak_frequency_hz": float(
            peak_frequency
        ),
        "lf_peak_prominence_ratio": float(
            peak_prominence_ratio
        ),
    }


def _finite(
    value,
) -> bool:
    try:
        return bool(
            np.isfinite(
                float(value)
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        return False


def _transform(
    name: str,
    value: float,
) -> float:
    numeric = float(value)
    transform = FEATURE_TRANSFORMS.get(
        name,
        "linear",
    )

    if transform == "log":
        return float(
            math.log(
                max(
                    numeric,
                    1e-9,
                )
            )
        )

    return numeric


def _decimate_rows(
    rows: Sequence[dict],
    minimum_gap_seconds: float = 120.0,
) -> list[dict]:
    selected: list[dict] = []
    last_t_us: int | None = None
    minimum_gap_us = int(
        round(
            minimum_gap_seconds
            * 1e6
        )
    )

    for row in rows:
        t_us = int(
            row.get(
                "t_us",
                0,
            )
        )

        if (
            last_t_us is None
            or t_us
            - last_t_us
            >= minimum_gap_us
        ):
            selected.append(
                row
            )
            last_t_us = t_us

    return selected


def _valid_research_row(
    row: dict,
) -> bool:
    """Whether the row has analyzable HRV evidence.

    v0.4.1 intentionally stops using the clip-heavy legacy SQI as a second
    hidden gate. Time/frequency statuses already encode transport integrity and
    authoritative beat-timeline quality. Sensor-contact quality remains useful
    context, but trough clipping alone must not erase otherwise stable intervals.
    """
    transport_status = str(
        row.get("transport_status", "") or ""
    )
    transport_score = float(
        row.get("transport_score", 0.0) or 0.0
    )
    # Legacy/history rows created before v0.4.1 have no separate transport
    # evidence. Keep them backward compatible; once a transport score exists,
    # its status is authoritative.
    transport_ok = (
        transport_status != "INVALID"
        if transport_score > 0.0
        else True
    )
    # A LIMITED status during initial five-minute accumulation is not a usable
    # spectral observation.  v0.4.2 stores frequency_ready explicitly; legacy
    # rows fall back to the presence of finite spectral power.
    if "frequency_ready" in row:
        frequency_ready = bool(row.get("frequency_ready"))
    else:
        frequency_ready = _finite(row.get("total_power_ms2", np.nan))

    return bool(
        frequency_ready
        and row.get("frequency_status") in {"VALID", "LIMITED"}
        and row.get("time_status") in {"VALID", "LIMITED"}
        and transport_ok
    )


def _build_personal_baseline(
    history: Sequence[dict],
    current_t_us: int,
) -> dict:
    """Build a slow, causal within-session reference.

    A five-minute spectral row is highly overlapped with its neighbours.  The
    old implementation treated three rows two minutes apart as three separate
    reference observations and could declare a baseline after only four
    minutes of span.  v0.4.3 instead samples non-overlapping-ish five-minute
    anchors, requires at least fifteen minutes of actual anchor span, and keeps
    the most recent three minutes out of the reference so the current state does
    not immediately drag its own comparison point.
    """
    if not history:
        return {
            "ready": False,
            "rows": [],
            "features": {},
            "reason": "尚无可用于形成长期参照的记录",
        }

    current_t_us = int(current_t_us)
    cutoff_us = current_t_us - int(round(_BASELINE_EXCLUDE_RECENT_SECONDS * 1e6))
    lookback_start_us = current_t_us - int(round(_BASELINE_LOOKBACK_SECONDS * 1e6))

    candidates = [
        row
        for row in history
        if (
            lookback_start_us <= int(row.get("t_us", 0)) <= cutoff_us
            and _valid_research_row(row)
        )
    ]

    selected = _decimate_rows(
        candidates,
        minimum_gap_seconds=_BASELINE_MINIMUM_GAP_SECONDS,
    )

    if len(selected) < _BASELINE_MINIMUM_REFERENCE_WINDOWS:
        return {
            "ready": False,
            "rows": selected,
            "features": {},
            "reason": (
                "需要至少4段相隔约5分钟的清晰记录，"
                "先积累更长时间再形成个人参照"
            ),
        }

    span_seconds = (
        int(selected[-1].get("t_us", 0))
        - int(selected[0].get("t_us", 0))
    ) / 1e6

    if span_seconds < _BASELINE_MINIMUM_SPAN_SECONDS:
        return {
            "ready": False,
            "rows": selected,
            "features": {},
            "reason": "个人参照至少需要覆盖约15分钟的真实时间跨度",
            "span_seconds": float(span_seconds),
        }

    features: dict[str, dict] = {}

    for name in FEATURE_TRANSFORMS:
        values = np.asarray(
            [
                _transform(name, row[name])
                for row in selected
                if name in row and _finite(row[name])
            ],
            dtype=float,
        )

        if values.size < _BASELINE_MINIMUM_REFERENCE_WINDOWS:
            continue

        median = float(np.median(values))
        mad = float(np.median(np.abs(values - median)))
        scale = max(
            1.4826 * mad,
            float(FEATURE_ROBUST_SCALE_FLOORS.get(name, 0.12)),
        )

        features[name] = {
            "median": median,
            "scale": scale,
            "count": int(values.size),
        }

    if not features:
        return {
            "ready": False,
            "rows": selected,
            "features": {},
            "reason": "长期参照仍缺少足够完整的身体节律数据",
            "span_seconds": float(span_seconds),
        }

    return {
        "ready": True,
        "rows": selected,
        "features": features,
        "reason": "",
        "span_seconds": float(span_seconds),
        "minimum_gap_seconds": float(_BASELINE_MINIMUM_GAP_SECONDS),
        "excluded_recent_seconds": float(_BASELINE_EXCLUDE_RECENT_SECONDS),
    }

def _z(
    baseline: dict,
    name: str,
    value,
) -> float:
    if (
        not baseline.get(
            "ready"
        )
        or name
        not in baseline.get(
            "features",
            {},
        )
        or not _finite(
            value
        )
    ):
        return 0.0

    spec = baseline[
        "features"
    ][name]

    transformed = _transform(
        name,
        float(value),
    )

    return float(
        (
            transformed
            - spec[
                "median"
            ]
        )
        / max(
            spec[
                "scale"
            ],
            1e-9,
        )
    )


def _rise(
    z_value: float,
    start: float = 0.35,
    full: float = 1.20,
) -> float:
    return float(
        np.clip(
            (
                z_value
                - start
            )
            / max(
                full
                - start,
                1e-9,
            ),
            0.0,
            1.0,
        )
    )


def _fall(
    z_value: float,
    start: float = -0.35,
    full: float = -1.20,
) -> float:
    return _rise(
        -z_value,
        start=-start,
        full=-full,
    )


def _near_baseline(
    z_value: float,
    good: float = 0.45,
    bad: float = 1.20,
) -> float:
    return float(
        1.0
        - np.clip(
            (
                abs(
                    z_value
                )
                - good
            )
            / max(
                bad
                - good,
                1e-9,
            ),
            0.0,
            1.0,
        )
    )


def _quality_multiplier(
    snapshot: AnalysisSnapshot,
) -> float:
    if (
        not snapshot.frequency.valid
        or snapshot.frequency.status
        not in {
            "VALID",
            "LIMITED",
        }
    ):
        return 0.0

    if snapshot.quality.status == "INVALID":
        return 0.0

    if snapshot.frequency.status == "LIMITED":
        return 0.65

    if snapshot.quality.status == "LIMITED":
        return 0.72

    return 1.0


def _row_quality_multiplier(
    row: dict,
) -> float:
    if not _valid_research_row(
        row
    ):
        return 0.0

    if (
        row.get(
            "frequency_status"
        )
        == "LIMITED"
        or row.get(
            "overall_status"
        )
        == "LIMITED"
    ):
        return 0.68

    return 1.0


def _score_resonance(
    row: dict,
    recent_rows: Sequence[dict],
) -> tuple[float, list[str]]:
    frequency = float(
        row.get(
            "lf_peak_frequency_hz",
            np.nan,
        )
    )
    prominence = float(
        row.get(
            "lf_peak_prominence_ratio",
            np.nan,
        )
    )
    share = float(
        row.get(
            "resonance_share",
            np.nan,
        )
    )

    if not (
        _finite(
            frequency
        )
        and _finite(
            prominence
        )
        and _finite(
            share
        )
    ):
        return (
            0.0,
            [],
        )

    frequency_score = float(
        math.exp(
            -0.5
            * (
                (
                    frequency
                    - 0.095
                )
                / 0.018
            )
            ** 2
        )
    )

    prominence_score = float(
        np.clip(
            (
                prominence
                - 1.8
            )
            / 3.2,
            0.0,
            1.0,
        )
    )

    share_score = float(
        np.clip(
            (
                share
                - 0.22
            )
            / 0.33,
            0.0,
            1.0,
        )
    )

    recent_peaks = np.asarray(
        [
            float(
                item[
                    "lf_peak_frequency_hz"
                ]
            )
            for item in recent_rows[
                -5:
            ]
            if _finite(
                item.get(
                    "lf_peak_frequency_hz",
                    np.nan,
                )
            )
        ],
        dtype=float,
    )

    if recent_peaks.size >= 3:
        spread = float(
            np.percentile(
                recent_peaks,
                90,
            )
            - np.percentile(
                recent_peaks,
                10,
            )
        )

        stability_score = float(
            1.0
            - np.clip(
                (
                    spread
                    - 0.008
                )
                / 0.025,
                0.0,
                1.0,
            )
        )
    else:
        spread = np.nan
        stability_score = 0.45

    score = (
        0.36
        * frequency_score
        + 0.27
        * prominence_score
        + 0.25
        * share_score
        + 0.12
        * stability_score
    )

    evidence = [
        (
            f"LF主峰 {frequency:.3f} Hz"
        ),
        (
            f"主峰/背景 {prominence:.2f}×"
        ),
        (
            f"0.075–0.11 Hz占LF+HF {share * 100.0:.1f}%"
        ),
    ]

    if _finite(
        spread
    ):
        evidence.append(
            f"近期主峰频率跨度 {spread:.3f} Hz"
        )

    return (
        float(
            np.clip(
                score,
                0.0,
                1.0,
            )
        ),
        evidence,
    )


def _score_phased_pattern(
    history: Sequence[dict],
    current_t_us: int,
) -> tuple[float, list[str]]:
    start_us = (
        int(
            current_t_us
        )
        - 24
        * 60
        * 1_000_000
    )

    rows = [
        row
        for row in history
        if (
            int(
                row.get(
                    "t_us",
                    0,
                )
            )
            >= start_us
            and int(row.get("t_us", 0)) <= int(current_t_us)
            and _valid_research_row(
                row
            )
            and _finite(
                row.get(
                    "lf_ms2",
                    np.nan,
                )
            )
            and _finite(
                row.get(
                    "hf_ms2",
                    np.nan,
                )
            )
        )
    ]

    if len(
        rows
    ) < 15:
        return (
            0.0,
            [],
        )

    t_min = int(
        rows[0][
            "t_us"
        ]
    )
    t_max = int(
        rows[-1][
            "t_us"
        ]
    )
    span = (
        t_max
        - t_min
    )

    if span < 12 * 60 * 1e6:
        return (
            0.0,
            [],
        )

    first_cut = (
        t_min
        + span / 3.0
    )
    second_cut = (
        t_min
        + 2.0
        * span / 3.0
    )

    segments = [
        [
            row
            for row in rows
            if int(
                row[
                    "t_us"
                ]
            )
            <= first_cut
        ],
        [
            row
            for row in rows
            if (
                int(
                    row[
                        "t_us"
                    ]
                )
                > first_cut
                and int(
                    row[
                        "t_us"
                    ]
                )
                <= second_cut
            )
        ],
        [
            row
            for row in rows
            if int(
                row[
                    "t_us"
                ]
            )
            > second_cut
        ],
    ]

    if any(
        len(
            segment
        )
        < 3
        for segment in segments
    ):
        return (
            0.0,
            [],
        )

    def segment_mean(
        segment: Sequence[dict],
        name: str,
    ) -> float:
        return float(
            np.median(
                np.asarray(
                    [
                        float(
                            row[
                                name
                            ]
                        )
                        for row in segment
                        if _finite(
                            row.get(
                                name,
                                np.nan,
                            )
                        )
                    ],
                    dtype=float,
                )
            )
        )

    lf = [
        segment_mean(
            segment,
            "lf_ms2",
        )
        for segment in segments
    ]
    hf = [
        segment_mean(
            segment,
            "hf_ms2",
        )
        for segment in segments
    ]
    lf_hf = [
        segment_mean(
            segment,
            "lf_hf",
        )
        for segment in segments
    ]

    edge_lf = max(
        (
            lf[0]
            + lf[2]
        )
        / 2.0,
        1e-9,
    )
    edge_hf = max(
        (
            hf[0]
            + hf[2]
        )
        / 2.0,
        1e-9,
    )
    edge_ratio = max(
        (
            lf_hf[0]
            + lf_hf[2]
        )
        / 2.0,
        1e-9,
    )

    lf_gain = float(
        math.log(
            max(
                lf[1],
                1e-9,
            )
            / edge_lf
        )
    )
    hf_gain = float(
        math.log(
            max(
                hf[1],
                1e-9,
            )
            / edge_hf
        )
    )
    ratio_gain = float(
        math.log(
            max(
                lf_hf[1],
                1e-9,
            )
            / edge_ratio
        )
    )

    score = (
        0.40
        * float(
            np.clip(
                lf_gain
                / math.log(
                    1.35
                ),
                0.0,
                1.0,
            )
        )
        + 0.28
        * float(
            np.clip(
                hf_gain
                / math.log(
                    1.25
                ),
                0.0,
                1.0,
            )
        )
        + 0.32
        * float(
            np.clip(
                ratio_gain
                / math.log(
                    1.25
                ),
                0.0,
                1.0,
            )
        )
    )

    return (
        float(
            np.clip(
                score,
                0.0,
                1.0,
            )
        ),
        [
            f"中段LF相对两侧 {math.exp(lf_gain):.2f}×",
            f"中段HF相对两侧 {math.exp(hf_gain):.2f}×",
            f"中段LF/HF相对两侧 {math.exp(ratio_gain):.2f}×",
        ],
    )


def _score_row(
    code: str,
    row: dict,
    baseline: dict,
    history: Sequence[dict],
) -> tuple[float, list[str]]:
    quality = _row_quality_multiplier(
        row
    )

    if quality <= 0:
        return (
            0.0,
            [],
        )

    recent_rows = [
        item
        for item in history
        if (
            int(
                item.get(
                    "t_us",
                    0,
                )
            )
            <= int(
                row.get(
                    "t_us",
                    0,
                )
            )
            and int(
                row.get(
                    "t_us",
                    0,
                )
            )
            - int(
                item.get(
                    "t_us",
                    0,
                )
            )
            <= 180_000_000
        )
    ]

    if code == "RESONANCE_0P1":
        score, evidence = (
            _score_resonance(
                row,
                recent_rows,
            )
        )
        return (
            score,
            evidence,
        )

    if not baseline.get(
        "ready"
    ):
        return (
            0.0,
            [],
        )

    z_hr = _z(
        baseline,
        "hr_bpm",
        row.get(
            "hr_bpm"
        ),
    )
    z_rmssd = _z(
        baseline,
        "rmssd_ms",
        row.get(
            "rmssd_ms"
        ),
    )
    z_vlf = _z(
        baseline,
        "vlf_ms2",
        row.get(
            "vlf_ms2"
        ),
    )
    z_lf = _z(
        baseline,
        "lf_ms2",
        row.get(
            "lf_ms2"
        ),
    )
    z_hf = _z(
        baseline,
        "hf_ms2",
        row.get(
            "hf_ms2"
        ),
    )
    z_hf_nu = _z(
        baseline,
        "hf_nu",
        row.get(
            "hf_nu"
        ),
    )
    z_lf_hf = _z(
        baseline,
        "lf_hf",
        row.get(
            "lf_hf"
        ),
    )
    z_thm = _z(
        baseline,
        "thm_power_ms2",
        row.get(
            "thm_power_ms2"
        ),
    )

    if code == "INWARD_QUIET":
        score = (
            0.32
            * _rise(
                z_hf
            )
            + 0.26
            * _rise(
                z_rmssd
            )
            + 0.22
            * _fall(
                z_hr
            )
            + 0.20
            * _fall(
                z_lf_hf
            )
        )

        return (
            score,
            [
                f"HF z*={z_hf:+.2f}",
                f"RMSSD z*={z_rmssd:+.2f}",
                f"HR z*={z_hr:+.2f}",
                f"LF/HF z*={z_lf_hf:+.2f}",
            ],
        )

    if code == "TRAINED_VIPASSANA_SHIFT":
        score = (
            0.48
            * _rise(
                z_hf_nu
            )
            + 0.42
            * _fall(
                z_thm
            )
            + 0.10
            * _fall(
                z_lf
            )
        )

        return (
            score,
            [
                f"HFnu z*={z_hf_nu:+.2f}",
                f"0.06–0.10 Hz THM z*={z_thm:+.2f}",
                f"LF z*={z_lf:+.2f}",
            ],
        )

    if code == "AROUSAL_MEDITATION":
        no_slowdown = float(
            np.clip(
                (
                    z_hr
                    + 0.25
                )
                / 0.95,
                0.0,
                1.0,
            )
        )
        rmssd_nonrise = float(
            np.clip(
                (
                    0.25
                    - z_rmssd
                )
                / 1.10,
                0.0,
                1.0,
            )
        )

        score = (
            0.52
            * _fall(
                z_hf
            )
            + 0.28
            * no_slowdown
            + 0.20
            * rmssd_nonrise
        )

        return (
            score,
            [
                f"HF z*={z_hf:+.2f}",
                f"HR z*={z_hr:+.2f}",
                f"RMSSD z*={z_rmssd:+.2f}",
            ],
        )

    if code == "SLOW_RECOVERY_VLF":
        current_fast_recovery = (
            0.42
            * _near_baseline(
                z_hf
            )
            + 0.28
            * _near_baseline(
                z_lf_hf
            )
            + 0.30
            * _near_baseline(
                z_hr
            )
        )
        vlf_tail = _fall(
            z_vlf,
            start=-0.45,
            full=-1.15,
        )

        lookback_start = (
            int(
                row[
                    "t_us"
                ]
            )
            - 30
            * 60
            * 1_000_000
        )
        lookback_end = (
            int(
                row[
                    "t_us"
                ]
            )
            - 3
            * 60
            * 1_000_000
        )

        earlier = [
            item
            for item in history
            if (
                lookback_start
                <= int(
                    item.get(
                        "t_us",
                        0,
                    )
                )
                <= lookback_end
                and _valid_research_row(
                    item
                )
            )
        ]

        prior_activation = 0.0
        for item in earlier:
            item_hf = _z(
                baseline,
                "hf_ms2",
                item.get(
                    "hf_ms2"
                ),
            )
            item_vlf = _z(
                baseline,
                "vlf_ms2",
                item.get(
                    "vlf_ms2"
                ),
            )
            item_ratio = _z(
                baseline,
                "lf_hf",
                item.get(
                    "lf_hf"
                ),
            )

            candidate = (
                0.40
                * _fall(
                    item_hf
                )
                + 0.35
                * _fall(
                    item_vlf
                )
                + 0.25
                * _rise(
                    item_ratio
                )
            )
            prior_activation = max(
                prior_activation,
                candidate,
            )

        score = (
            0.50
            * current_fast_recovery
            + 0.30
            * vlf_tail
            + 0.20
            * prior_activation
        )

        return (
            score,
            [
                f"HF当前 z*={z_hf:+.2f}",
                f"LF/HF当前 z*={z_lf_hf:+.2f}",
                f"VLF当前 z*={z_vlf:+.2f}",
                f"前序激活证据={prior_activation:.2f}",
            ],
        )

    if code == "PHASED_VIPASSANA":
        score, evidence = (
            _score_phased_pattern(
                history,
                int(
                    row.get(
                        "t_us",
                        0,
                    )
                ),
            )
        )
        return (
            score,
            evidence,
        )

    return (
        0.0,
        [],
    )



def _inverse_transform(
    name: str,
    value: float,
) -> float:
    if FEATURE_TRANSFORMS.get(name, "linear") == "log":
        return float(math.exp(float(value)))
    return float(value)


def _history_cadence_seconds(history: Sequence[dict]) -> float:
    times = np.asarray(
        sorted({int(row.get("t_us", 0)) for row in history if int(row.get("t_us", 0)) > 0}),
        dtype=float,
    )
    if times.size < 2:
        return 20.0
    diffs = np.diff(times) / 1e6
    diffs = diffs[(diffs >= 5.0) & (diffs <= 90.0)]
    if diffs.size == 0:
        return 20.0
    return float(np.clip(np.median(diffs), 10.0, 60.0))


def _robust_temporal_feature(
    rows: Sequence[dict],
    name: str,
    current_t_us: int,
    half_life_minutes: float,
) -> float:
    samples: list[tuple[float, float]] = []
    for row in rows:
        value = row.get(name, np.nan)
        if not _finite(value):
            continue
        samples.append((float(_transform(name, float(value))), float(row.get("t_us", 0))))

    if not samples:
        return float("nan")

    transformed = np.asarray([item[0] for item in samples], dtype=float)
    sample_times = np.asarray([item[1] for item in samples], dtype=float)
    center = float(np.median(transformed))
    mad = float(np.median(np.abs(transformed - center)))
    # Use the same unit-aware scale family as the baseline.  Half of the
    # baseline floor is enough for outlier clipping while still allowing a
    # sustained physiological shift to move the aggregate.
    robust_scale = max(
        1.4826 * mad,
        0.5 * float(FEATURE_ROBUST_SCALE_FLOORS.get(name, 0.12)),
    )
    clipped = np.clip(
        transformed,
        center - 3.0 * robust_scale,
        center + 3.0 * robust_scale,
    )
    ages_minutes = np.maximum(0.0, (float(current_t_us) - sample_times) / 60e6)
    half_life = max(float(half_life_minutes), 1.0)
    weights = np.power(0.5, ages_minutes / half_life)
    if float(np.sum(weights)) <= 1e-12:
        aggregate = center
    else:
        aggregate = float(np.sum(clipped * weights) / np.sum(weights))
    return _inverse_transform(name, aggregate)


def _aggregate_research_rows(
    rows: Sequence[dict],
    current_t_us: int,
    observation_minutes: float,
) -> dict:
    """Aggregate physiological features before applying nonlinear prototype rules."""
    valid_rows = [row for row in rows if _valid_research_row(row)]
    if not valid_rows:
        return {"t_us": int(current_t_us)}

    half_life_minutes = max(float(observation_minutes) * 0.55, 2.0)
    aggregate: dict[str, object] = {
        "t_us": int(current_t_us),
        "time_status": "VALID",
        "frequency_status": "VALID",
        "frequency_ready": True,
        "overall_status": "VALID",
        "transport_status": "VALID",
        "transport_score": 1.0,
    }
    for name in FEATURE_TRANSFORMS:
        aggregate[name] = _robust_temporal_feature(
            valid_rows,
            name,
            int(current_t_us),
            half_life_minutes,
        )

    # Preserve a few non-scoring fields for diagnostics and future extensions.
    for name in (
        "resonance_band_power_ms2",
        "spectral_agreement",
        "band_power_agreement",
        "interpolation_agreement",
        "contact_score",
    ):
        values = [float(row[name]) for row in valid_rows if name in row and _finite(row[name])]
        aggregate[name] = float(np.median(values)) if values else float("nan")

    return aggregate


def _temporal_window_rows(
    history: Sequence[dict],
    current_t_us: int,
    observation_minutes: float,
) -> list[dict]:
    start_t_us = int(current_t_us) - int(round(float(observation_minutes) * 60e6))
    return [
        row
        for row in history
        if start_t_us <= int(row.get("t_us", 0)) <= int(current_t_us)
        and _valid_research_row(row)
    ]


def _temporal_window_coverage(
    rows: Sequence[dict],
    history: Sequence[dict],
    observation_minutes: float,
) -> tuple[float, float, float]:
    if not rows:
        return 0.0, 0.0, _history_cadence_seconds(history)
    observation_seconds = max(float(observation_minutes) * 60.0, 1.0)
    span_seconds = max(
        0.0,
        (int(rows[-1].get("t_us", 0)) - int(rows[0].get("t_us", 0))) / 1e6,
    )
    cadence_seconds = _history_cadence_seconds(history)
    expected_count = max(observation_seconds / max(cadence_seconds, 1.0) + 1.0, 1.0)
    count_coverage = float(np.clip(len(rows) / expected_count, 0.0, 1.0))
    span_coverage = float(np.clip(span_seconds / observation_seconds, 0.0, 1.0))
    coverage = float(math.sqrt(max(count_coverage * span_coverage, 0.0)))
    return coverage, span_seconds, cadence_seconds


def _score_aggregated_prototype(
    code: str,
    aggregate_row: dict,
    baseline: dict,
    causal_history: Sequence[dict],
    observation_rows: Sequence[dict],
) -> tuple[float, list[str]]:
    if code == "RESONANCE_0P1":
        return _score_resonance(aggregate_row, observation_rows)
    return _score_row(code, aggregate_row, baseline, causal_history)


def _temporal_observation_score(
    code: str,
    current_t_us: int,
    history: Sequence[dict],
    baseline: dict,
) -> dict:
    """Return a prototype score based on sustained physiological evidence.

    The key ordering is intentional: features are aggregated over the prototype's
    own time horizon first, then the nonlinear research-prototype score is
    applied.  Only after that do persistence/stability terms reduce confidence.
    This prevents a single 20-second update from becoming a one-hour state jump.
    """
    spec = PROTOTYPE_TEMPORAL_MODEL[code]
    observation_minutes = float(spec["observation_minutes"])
    minimum_span_minutes = float(spec["minimum_span_minutes"])

    if code != "RESONANCE_0P1" and not baseline.get("ready"):
        return {
            "ready": False,
            "raw_score": float("nan"),
            "state_score": float("nan"),
            "coverage_ratio": 0.0,
            "persistence_ratio": 0.0,
            "stability_score": 0.0,
            "observation_minutes": observation_minutes,
            "observed_span_minutes": 0.0,
            "evidence": ["长期个人参照仍在建立"],
            "reason": "BASELINE_NOT_READY",
        }

    causal_history = [
        row for row in history if int(row.get("t_us", 0)) <= int(current_t_us)
    ]
    observation_rows = _temporal_window_rows(
        causal_history,
        int(current_t_us),
        observation_minutes,
    )
    coverage, span_seconds, _ = _temporal_window_coverage(
        observation_rows,
        causal_history,
        observation_minutes,
    )
    span_minutes = span_seconds / 60.0

    if (
        span_minutes < minimum_span_minutes
        or coverage < _TEMPORAL_MINIMUM_COVERAGE
        or len(observation_rows) < 4
    ):
        return {
            "ready": False,
            "raw_score": float("nan"),
            "state_score": float("nan"),
            "coverage_ratio": float(coverage),
            "persistence_ratio": 0.0,
            "stability_score": 0.0,
            "observation_minutes": observation_minutes,
            "observed_span_minutes": float(span_minutes),
            "evidence": [
                f"持续观察 {span_minutes:.1f}/{minimum_span_minutes:.1f} 分钟",
                f"有效覆盖 {coverage * 100.0:.0f}%",
            ],
            "reason": "TEMPORAL_EVIDENCE_BUILDING",
        }

    aggregate_row = _aggregate_research_rows(
        observation_rows,
        int(current_t_us),
        observation_minutes,
    )
    raw_score, evidence = _score_aggregated_prototype(
        code,
        aggregate_row,
        baseline,
        causal_history,
        observation_rows,
    )
    raw_score = float(np.clip(raw_score, 0.0, 1.0))

    # For phased structure the score already describes a multi-segment pattern.
    # Other prototypes receive an additional persistence/stability check based
    # on four sub-periods, each of which is itself feature-aggregated first.
    segment_scores: list[float] = []
    if code == "PHASED_VIPASSANA":
        persistence_ratio = float(np.clip(raw_score / 0.70, 0.0, 1.0))
        stability_score = float(np.clip(span_minutes / observation_minutes, 0.0, 1.0))
    else:
        window_start_us = int(current_t_us) - int(round(observation_minutes * 60e6))
        segment_count = int(np.clip(round(observation_minutes), 4, 8))
        edges = np.linspace(
            float(window_start_us),
            float(current_t_us),
            segment_count + 1,
        )
        for index in range(segment_count):
            lower = int(edges[index])
            upper = int(edges[index + 1])
            segment = [
                row
                for row in observation_rows
                if lower <= int(row.get("t_us", 0)) <= upper
            ]
            if len(segment) < 2:
                continue
            segment_aggregate = _aggregate_research_rows(
                segment,
                upper,
                max(observation_minutes / 4.0, 1.0),
            )
            segment_history = [
                row for row in causal_history if int(row.get("t_us", 0)) <= upper
            ]
            score, _ = _score_aggregated_prototype(
                code,
                segment_aggregate,
                baseline,
                segment_history,
                segment,
            )
            if _finite(score):
                segment_scores.append(float(np.clip(score, 0.0, 1.0)))

        if segment_scores:
            segment_array = np.asarray(segment_scores, dtype=float)
            # Continuous support avoids 0.25-sized jumps when one quarter of
            # the observation window crosses a hard persistence threshold.
            persistence_ratio = float(
                np.mean(np.clip((segment_array - 0.20) / 0.55, 0.0, 1.0))
            )
            spread = float(np.percentile(segment_array, 90) - np.percentile(segment_array, 10))
            stability_score = float(1.0 - np.clip(spread / 0.60, 0.0, 1.0))
        else:
            persistence_ratio = 0.0
            stability_score = 0.0

    segment_level = (
        float(np.mean(np.asarray(segment_scores, dtype=float)))
        if segment_scores
        else raw_score
    )
    temporal_support = float(
        np.clip(
            0.70
            + 0.10 * persistence_ratio
            + 0.10 * stability_score
            + 0.10 * coverage,
            0.0,
            1.0,
        )
    )
    # Full-window amplitude and sub-period persistence are both calculated from
    # aggregated physiology.  Blending them is the evidence-accumulation step;
    # it is deliberately not a moving average of the plotted score.
    state_core = 0.55 * raw_score + 0.45 * segment_level
    state_score = float(np.clip(state_core * temporal_support, 0.0, 1.0))

    evidence = list(evidence) + [
        f"持续观察窗 {observation_minutes:.0f} 分钟",
        f"有效覆盖 {coverage * 100.0:.0f}%",
        f"持续证据 {persistence_ratio * 100.0:.0f}%",
        f"稳定程度 {stability_score * 100.0:.0f}%",
    ]

    return {
        "ready": True,
        "raw_score": raw_score,
        "state_score": state_score,
        "coverage_ratio": float(coverage),
        "persistence_ratio": float(persistence_ratio),
        "stability_score": float(stability_score),
        "observation_minutes": observation_minutes,
        "observed_span_minutes": float(span_minutes),
        "evidence": evidence,
        "reason": "",
    }



def _accumulate_state_similarity(
    code: str,
    previous: float | None,
    target: float,
    dt_seconds: float,
) -> float:
    """Integrate sustained evidence into a slow research-state similarity.

    This is deliberately *after* physiological features have been aggregated and
    scored over the prototype-specific observation window.  It is therefore a
    state-memory model, not plot smoothing.  Missing data never advances the
    state; when evidence returns, elapsed time is capped so a long gap cannot
    manufacture an instantaneous transition.
    """
    if not _finite(target):
        return float("nan")

    spec = PROTOTYPE_TEMPORAL_MODEL[code]
    prior = float(previous) if previous is not None and _finite(previous) else 0.0
    rising = float(target) >= prior
    tau_minutes = float(
        spec["state_rise_tau_minutes"] if rising else spec["state_fall_tau_minutes"]
    )
    # The display/state trajectory is evaluated about once per minute.  If a
    # quality gap lasts longer, do not infer unobserved physiological change.
    effective_dt = float(np.clip(dt_seconds, 10.0, 90.0))
    alpha = 1.0 - math.exp(-effective_dt / max(tau_minutes * 60.0, 1.0))
    value = prior + alpha * (float(target) - prior)
    return float(np.clip(value, 0.0, 1.0))

def _temporal_machine_state_from_detail(
    code: str,
    detail: dict,
    analyzable: bool,
    baseline_ready: bool,
    was_active_recently: bool = False,
) -> str:
    """Lifecycle from multi-minute evidence plus causal state memory.

    ``CANDIDATE`` and ``ACTIVE`` are intentionally separate: 0.50 means there
    is enough sustained similarity to mention gently, while 0.70 is reserved
    for a mature state.  ``EXITING`` is only legal after the same state was
    actually active; a newly rising 0.4-0.5 score must never be mislabeled as
    recovery/exit.
    """
    if not analyzable:
        return "INACTIVE"
    if code != "RESONANCE_0P1" and not baseline_ready:
        return "INACTIVE"
    if not detail.get("ready") or not _finite(detail.get("state_score", np.nan)):
        return "INACTIVE"

    score = float(detail.get("state_score", 0.0) or 0.0)
    spec = PROTOTYPE_TEMPORAL_MODEL[code]
    observation_minutes = float(spec["observation_minutes"])
    observed_span = float(detail.get("observed_span_minutes", 0.0) or 0.0)
    coverage = float(detail.get("coverage_ratio", 0.0) or 0.0)
    persistence = float(detail.get("persistence_ratio", 0.0) or 0.0)
    stability = float(detail.get("stability_score", 0.0) or 0.0)

    if score >= _MATCH_THRESHOLD_ACTIVE:
        mature = (
            observed_span >= observation_minutes * 0.88
            and coverage >= 0.75
            and persistence >= 0.65
            and stability >= 0.40
        )
        return "ACTIVE" if mature else "CANDIDATE"

    if score >= _MATCH_THRESHOLD_CANDIDATE:
        return "CANDIDATE"

    if (
        was_active_recently
        and 0.30 <= score < _MATCH_THRESHOLD_CANDIDATE
        and observed_span >= observation_minutes * 0.75
    ):
        return "EXITING"

    return "INACTIVE"


def _temporal_series_for_lifecycle(
    code: str,
    history: Sequence[dict],
    current_t_us: int,
) -> list[dict]:
    spec = PROTOTYPE_TEMPORAL_MODEL[code]
    memory_minutes = max(
        float(spec["activation_hold_minutes"]) + float(spec["exit_hold_minutes"]) + 2.0,
        8.0,
    )
    start_us = int(current_t_us) - int(round(memory_minutes * 60e6))
    points = [
        row for row in history
        if start_us <= int(row.get("t_us", 0)) <= int(current_t_us)
    ]
    series: list[dict] = []
    for point in points:
        point_t_us = int(point.get("t_us", 0))
        causal_history = [
            row for row in history if int(row.get("t_us", 0)) <= point_t_us
        ]
        point_baseline = _build_personal_baseline(causal_history, point_t_us)
        detail = _temporal_observation_score(
            code,
            point_t_us,
            causal_history,
            point_baseline,
        )
        series.append({"t_us": point_t_us, **detail})
    return series


def _temporal_machine_state(
    code: str,
    series: Sequence[dict],
    analyzable: bool,
    baseline_ready: bool,
) -> str:
    if not analyzable or not series:
        return "INACTIVE"
    if code != "RESONANCE_0P1" and not baseline_ready:
        return "INACTIVE"

    current = series[-1]
    if not current.get("ready") or not _finite(current.get("state_score", np.nan)):
        return "INACTIVE"
    current_score = float(current["state_score"])
    current_t_us = int(current.get("t_us", 0))
    spec = PROTOTYPE_TEMPORAL_MODEL[code]

    if current_score >= _MATCH_THRESHOLD_ACTIVE:
        hold_minutes = float(spec["activation_hold_minutes"])
        hold_start = current_t_us - int(round(hold_minutes * 60e6))
        recent = [
            item for item in series
            if int(item.get("t_us", 0)) >= hold_start
            and item.get("ready")
            and _finite(item.get("state_score", np.nan))
        ]
        if recent:
            span_minutes = (
                int(recent[-1].get("t_us", 0)) - int(recent[0].get("t_us", 0))
            ) / 60e6
            scores = np.asarray([float(item["state_score"]) for item in recent], dtype=float)
            sustained_ratio = float(np.mean(scores >= 0.65))
            if (
                span_minutes >= hold_minutes * 0.80
                and sustained_ratio >= 0.75
                and float(np.median(scores)) >= 0.68
            ):
                return "ACTIVE"
        return "CANDIDATE"

    if current_score < 0.45:
        exit_minutes = float(spec["exit_hold_minutes"])
        exit_start = current_t_us - int(round(exit_minutes * 60e6))
        recent_exit = [
            item for item in series
            if int(item.get("t_us", 0)) >= exit_start
            and item.get("ready")
            and _finite(item.get("state_score", np.nan))
        ]
        earlier = [
            item for item in series
            if int(item.get("t_us", 0)) < exit_start
            and item.get("ready")
            and _finite(item.get("state_score", np.nan))
        ]
        if recent_exit and earlier:
            exit_span = (
                int(recent_exit[-1].get("t_us", 0)) - int(recent_exit[0].get("t_us", 0))
            ) / 60e6
            if (
                exit_span >= exit_minutes * 0.75
                and float(np.mean([float(item["state_score"]) < 0.45 for item in recent_exit])) >= 0.75
                and max(float(item["state_score"]) for item in earlier) >= _MATCH_THRESHOLD_ACTIVE
            ):
                return "EXITING"

    return "INACTIVE"

def _current_row_from_snapshot(
    snapshot: AnalysisSnapshot,
) -> dict:
    frequency = snapshot.frequency
    time = snapshot.time

    row = {
        "t_us": int(
            snapshot.t_us
        ),
        "hr_bpm": float(
            snapshot.hr_bpm
        ),
        "time_status": time.status,
        "rmssd_ms": (
            float(
                time.rmssd_ms
            )
            if time.valid
            else np.nan
        ),
        "frequency_status": (
            frequency.status
        ),
        "frequency_ready": bool(frequency.valid),
        "frequency_progress": float(frequency.progress),
        "frequency_duration_seconds": float(frequency.duration_seconds),
        "total_power_ms2": (
            float(
                frequency.total_power_ms2
            )
            if frequency.valid
            else np.nan
        ),
        "vlf_ms2": (
            float(
                frequency.vlf_ms2
            )
            if frequency.valid
            else np.nan
        ),
        "lf_ms2": (
            float(
                frequency.lf_ms2
            )
            if frequency.valid
            else np.nan
        ),
        "hf_ms2": (
            float(
                frequency.hf_ms2
            )
            if frequency.valid
            else np.nan
        ),
        "lf_nu": (
            float(
                frequency.lf_nu
            )
            if frequency.valid
            else np.nan
        ),
        "hf_nu": (
            float(
                frequency.hf_nu
            )
            if frequency.valid
            else np.nan
        ),
        "lf_hf": (
            float(
                frequency.lf_hf
            )
            if frequency.valid
            else np.nan
        ),
        "median_frequency_hz": (
            float(
                frequency.median_frequency_hz
            )
            if frequency.valid
            else np.nan
        ),
        "sqi": float(
            snapshot.signal_quality.sqi
        ),
        "transport_score": float(
            getattr(snapshot.signal_quality, "transport_score", 0.0) or 0.0
        ),
        "transport_status": str(
            getattr(snapshot.signal_quality, "transport_status", "") or ""
        ),
        "contact_score": float(
            getattr(snapshot.signal_quality, "contact_score", 0.0) or 0.0
        ),
        "contact_status": str(
            getattr(snapshot.signal_quality, "contact_status", "") or ""
        ),
        "dual_detector_ratio": float(
            getattr(frequency, "dual_detector_ratio", 0.0) or 0.0
        ),
        "single_detector_ratio": float(
            getattr(frequency, "single_detector_ratio", 0.0) or 0.0
        ),
        "firmware_unmatched_ratio": float(
            getattr(frequency, "firmware_unmatched_ratio", 0.0) or 0.0
        ),
        "overall_status": (
            snapshot.quality.status
        ),
    }

    row.update(
        extract_research_frequency_features(
            frequency
        )
    )

    return row


def _machine_state(
    score_series: Sequence[float],
    analyzable: bool,
    baseline_ready: bool,
) -> str:
    if not analyzable:
        return "INACTIVE"

    scores = list(
        score_series
    )

    if not scores:
        return "INACTIVE"

    current = scores[-1]

    if (
        len(
            scores
        )
        >= 2
        and scores[-1]
        >= 0.70
        and scores[-2]
        >= 0.70
        and baseline_ready
    ):
        return "ACTIVE"

    if current >= 0.70:
        return "CANDIDATE"

    if (
        len(
            scores
        )
        >= 4
        and max(
            scores[-4:-2]
        )
        >= 0.70
        and scores[-1]
        < 0.45
        and scores[-2]
        < 0.45
    ):
        return "EXITING"

    return "INACTIVE"


def evaluate_research_state(
    snapshot: AnalysisSnapshot,
    history: Sequence[dict],
    config: AnalysisConfig | None = None,
    timeline: Sequence[dict] | None = None,
) -> dict:
    del config  # 预留给后续产品阈值配置。

    history_rows = [dict(row) for row in history]
    current_row = _current_row_from_snapshot(snapshot)

    if (
        not history_rows
        or int(history_rows[-1].get("t_us", 0)) != int(current_row["t_us"])
    ):
        history_rows.append(current_row)
    else:
        history_rows[-1].update(current_row)

    session_elapsed_minutes = 0.0
    if history_rows:
        session_elapsed_minutes = max(
            0.0,
            (
                int(current_row["t_us"])
                - int(history_rows[0].get("t_us", current_row["t_us"]))
            ) / 60e6,
        )

    if not snapshot.frequency.valid and snapshot.frequency.progress < 1.0:
        quality_state = "Q0_BUFFERING"
        analyzable = False
    elif _quality_multiplier(snapshot) <= 0:
        quality_state = "Q1_DATA_UNSTABLE"
        analyzable = False
    else:
        quality_state = "Q3_ANALYZABLE"
        analyzable = True

    baseline = _build_personal_baseline(
        history_rows,
        int(current_row["t_us"]),
    )

    if analyzable and not baseline["ready"]:
        quality_state = "Q2_BASELINE_BUILDING"

    matches: list[dict] = []
    current_t_us = int(current_row["t_us"])
    evidence_quality = float(_quality_multiplier(snapshot))

    state_timeline = list(timeline) if timeline is not None else _timeline_score_rows(history_rows)
    latest_state_row = next(
        (
            item for item in reversed(state_timeline)
            if int(item.get("t_us", 0)) <= current_t_us
        ),
        {},
    )

    for code, definition in PROTOTYPE_DEFINITIONS.items():
        detail = _temporal_observation_score(
            code,
            current_t_us,
            history_rows,
            baseline,
        )
        accumulated = latest_state_row.get(f"score_{code}", float("nan"))
        evidence_score = detail.get("state_score", float("nan"))
        raw_score = detail.get("raw_score", float("nan"))
        current_score = float(accumulated) if _finite(accumulated) else 0.0
        current_evidence_score = (
            float(evidence_score) if _finite(evidence_score) else 0.0
        )
        current_raw_score = float(raw_score) if _finite(raw_score) else 0.0

        lifecycle_detail = dict(detail)
        lifecycle_detail["state_score"] = (
            float(accumulated) if _finite(accumulated) else float("nan")
        )
        spec = PROTOTYPE_TEMPORAL_MODEL[code]
        active_lookback_minutes = max(
            float(spec["observation_minutes"]),
            3.0 * float(spec["exit_hold_minutes"]),
        )
        active_lookback_us = current_t_us - int(round(active_lookback_minutes * 60e6))
        was_active_recently = any(
            active_lookback_us <= int(item.get("t_us", 0)) < current_t_us
            and _finite(item.get(f"score_{code}", np.nan))
            and float(item.get(f"score_{code}", 0.0)) >= _MATCH_THRESHOLD_ACTIVE
            for item in state_timeline
        )
        lifecycle = _temporal_machine_state_from_detail(
            code,
            lifecycle_detail,
            analyzable=analyzable,
            baseline_ready=(baseline["ready"] or code == "RESONANCE_0P1"),
            was_active_recently=was_active_recently,
        )
        latest_evidence = list(detail.get("evidence", []))
        if detail.get("ready"):
            latest_evidence.append(f"状态证据累计 {current_score * 100.0:.0f}%")

        no_match_reason = ""
        if lifecycle in {"ACTIVE", "CANDIDATE", "EXITING"}:
            no_match_reason = ""
        elif evidence_quality <= 0:
            no_match_reason = "NO_MATCH: DATA_UNAVAILABLE"
        elif code != "RESONANCE_0P1" and not baseline["ready"]:
            no_match_reason = "NO_MATCH: BASELINE_NOT_READY"
        elif not detail.get("ready"):
            no_match_reason = "NO_MATCH: TEMPORAL_EVIDENCE_BUILDING"
        elif current_score < _MATCH_THRESHOLD_CANDIDATE:
            no_match_reason = (
                "NO_MATCH: STATE_SCORE_BELOW_CANDIDATE %.2f < %.2f"
                % (current_score, _MATCH_THRESHOLD_CANDIDATE)
            )
        else:
            no_match_reason = "NO_MATCH: DURATION_NOT_CONFIRMED"

        matches.append({
            "code": code,
            "name": definition["name"],
            # ``score`` is the user-facing state similarity from v0.4.3 onward.
            "score": current_score,
            "raw_score": current_raw_score,
            "evidence_score": current_evidence_score,
            "state_score": current_score,
            "lifecycle": lifecycle,
            "evidence": latest_evidence,
            "quality_multiplier": evidence_quality,
            "score_before_quality": current_evidence_score,
            "no_match_reason": no_match_reason,
            "baseline_ready": bool(baseline["ready"]),
            "temporal_ready": bool(detail.get("ready")),
            "observation_minutes": float(detail.get("observation_minutes", 0.0) or 0.0),
            "observed_span_minutes": float(detail.get("observed_span_minutes", 0.0) or 0.0),
            "coverage_ratio": float(detail.get("coverage_ratio", 0.0) or 0.0),
            "persistence_ratio": float(detail.get("persistence_ratio", 0.0) or 0.0),
            "stability_score": float(detail.get("stability_score", 0.0) or 0.0),
            "test_state": definition["test_state"],
            "user_narrative": definition["user_narrative"],
            "source_ids": list(definition["source_ids"]),
            "priority": int(definition["priority"]),
        })

    matches.sort(
        key=lambda item: (
            item["lifecycle"] == "ACTIVE",
            item["lifecycle"] == "CANDIDATE",
            item["score"],
            item["priority"],
        ),
        reverse=True,
    )

    active_matches = [item for item in matches if item["lifecycle"] == "ACTIVE"]
    candidate_matches = [item for item in matches if item["lifecycle"] == "CANDIDATE"]
    pool = active_matches if active_matches else candidate_matches
    primary = (
        max(pool, key=lambda item: (item["score"], item["priority"]))
        if pool
        else None
    )

    if quality_state == "Q1_DATA_UNSTABLE":
        state_machine_state = "Q1_DATA_UNSTABLE"
    elif quality_state == "Q0_BUFFERING":
        state_machine_state = "Q0_BUFFERING"
    elif quality_state == "Q2_BASELINE_BUILDING":
        # Resonance can still become a candidate before the personal baseline,
        # but the overall session remains explicit about reference maturity.
        state_machine_state = "Q4_STATE_CANDIDATE" if candidate_matches else "Q2_BASELINE_BUILDING"
    elif active_matches:
        state_machine_state = "Q5_STATE_ACTIVE"
    elif candidate_matches:
        state_machine_state = "Q4_STATE_CANDIDATE"
    elif any(item["lifecycle"] == "EXITING" for item in matches):
        state_machine_state = "Q6_STATE_EXITING"
    else:
        state_machine_state = "Q3_ANALYZABLE"

    source_ids: list[int] = []
    for item in matches:
        if item["lifecycle"] in {"ACTIVE", "CANDIDATE"}:
            for source_id in item["source_ids"]:
                if source_id not in source_ids:
                    source_ids.append(source_id)

    return {
        "state_machine_state": state_machine_state,
        "quality_state": quality_state,
        "session_elapsed_minutes": session_elapsed_minutes,
        "baseline_ready": bool(baseline["ready"]),
        "baseline": baseline,
        "baseline_reason": baseline["reason"],
        "baseline_reference_window_count": len(baseline["rows"]),
        "primary_state": primary,
        "matches": matches,
        "source_ids": source_ids,
        "source_facts_html": render_source_facts_html(source_ids) if source_ids else "",
        "primary_source_ids": list(primary.get("source_ids", [])) if isinstance(primary, dict) else [],
        "primary_source_facts_html": (
            render_source_facts_html(list(primary.get("source_ids", [])))
            if isinstance(primary, dict) and primary.get("source_ids")
            else ""
        ),
    }

def _session_stage(
    elapsed_minutes: float,
) -> tuple[
    str,
    str,
    float | None,
]:
    if elapsed_minutes < 5.0:
        return (
            "H0_ACQUIRING",
            "建立基础观察",
            5.0
            - elapsed_minutes,
        )

    if elapsed_minutes < 10.0:
        return (
            "H1_BASELINE",
            "了解你这次记录里的近期常态",
            10.0
            - elapsed_minutes,
        )

    if elapsed_minutes < 20.0:
        return (
            "H2_FIRST_PATTERN",
            "寻找开始重复出现的节律",
            20.0
            - elapsed_minutes,
        )

    if elapsed_minutes < 40.0:
        return (
            "H3_TRAJECTORY",
            "观察这些变化能持续多久",
            40.0
            - elapsed_minutes,
        )

    if elapsed_minutes < 60.0:
        return (
            "H4_HOUR_SCALE",
            "把这一小时的变化连成一条脉络",
            60.0
            - elapsed_minutes,
        )

    return (
        "H5_EXTENDED",
        "已经形成完整的一小时变化脉络",
        None,
    )


def _timeline_score_rows(
    history: Sequence[dict],
    baseline: dict | None = None,
) -> list[dict]:
    """Build a causal one-hour research *state* trajectory.

    Each plotted value has three layers of evidence:

    1. ``raw_score_*``: nonlinear prototype score after robust aggregation of
       physiology over that prototype's own multi-minute observation horizon;
    2. ``evidence_score_*``: raw score reduced by coverage, persistence and
       within-window stability;
    3. ``score_*``: slow state memory used by the user-facing one-hour chart.

    The state memory is causal and only advances when analyzable evidence is
    present.  It is not a moving average of 20-second scores.
    """
    del baseline
    if not history:
        return []

    ordered_history = sorted(
        (dict(row) for row in history),
        key=lambda row: int(row.get("t_us", 0)),
    )
    latest_t_us = int(ordered_history[-1].get("t_us", 0))
    display_start_us = latest_t_us - 60 * 60 * 1_000_000

    # Warm state memory before the visible hour so sessions longer than an hour
    # do not restart every curve from zero at the left chart edge.
    max_tau_minutes = max(
        max(
            float(spec["state_rise_tau_minutes"]),
            float(spec["state_fall_tau_minutes"]),
        )
        for spec in PROTOTYPE_TEMPORAL_MODEL.values()
    )
    warmup_start_us = display_start_us - int(round(max(30.0, 2.5 * max_tau_minutes) * 60e6))
    process_source = [
        row for row in ordered_history
        if int(row.get("t_us", 0)) >= warmup_start_us
    ]

    # Keep all original 20-second rows available to temporal windows, but a
    # state trajectory only needs about one user-visible point per minute.
    rows = _decimate_rows(process_source, minimum_gap_seconds=60.0)
    if process_source and (
        not rows
        or int(rows[-1].get("t_us", 0)) != int(process_source[-1].get("t_us", 0))
    ):
        rows.append(process_source[-1])

    timeline: list[dict] = []
    state_memory: dict[str, float] = {}
    state_memory_t_us: dict[str, int] = {}

    for row in rows:
        row_t_us = int(row.get("t_us", 0))
        causal_history = [
            item for item in ordered_history
            if int(item.get("t_us", 0)) <= row_t_us
        ]
        row_baseline = _build_personal_baseline(causal_history, row_t_us)
        quality = _row_quality_multiplier(row)

        state_scores: dict[str, float] = {}
        evidence_scores: dict[str, float] = {}
        raw_scores: dict[str, float] = {}
        details: dict[str, dict] = {}

        if quality <= 0:
            for code in PROTOTYPE_DEFINITIONS:
                state_scores[code] = float("nan")
                evidence_scores[code] = float("nan")
                raw_scores[code] = float("nan")
                details[code] = {
                    "ready": False,
                    "coverage_ratio": 0.0,
                    "persistence_ratio": 0.0,
                    "stability_score": 0.0,
                    "observed_span_minutes": 0.0,
                }
            ranked: list[tuple[str, float]] = []
        else:
            for code in PROTOTYPE_DEFINITIONS:
                detail = _temporal_observation_score(
                    code,
                    row_t_us,
                    causal_history,
                    row_baseline,
                )
                details[code] = detail
                target_value = detail.get("state_score", float("nan"))
                raw_value = detail.get("raw_score", float("nan"))
                evidence_scores[code] = (
                    float(target_value) if _finite(target_value) else float("nan")
                )
                raw_scores[code] = (
                    float(raw_value) if _finite(raw_value) else float("nan")
                )

                if detail.get("ready") and _finite(target_value):
                    previous = state_memory.get(code)
                    previous_t = state_memory_t_us.get(code)
                    if previous_t is None:
                        dt_seconds = 60.0
                    else:
                        dt_seconds = max((row_t_us - previous_t) / 1e6, 10.0)
                    state_value = _accumulate_state_similarity(
                        code,
                        previous,
                        float(target_value),
                        dt_seconds,
                    )
                    state_memory[code] = state_value
                    state_memory_t_us[code] = row_t_us
                    state_scores[code] = state_value
                else:
                    # No new evidence: draw a gap and keep latent memory intact.
                    state_scores[code] = float("nan")

            ranked = sorted(
                [
                    (code, score)
                    for code, score in state_scores.items()
                    if _finite(score)
                ],
                key=lambda item: (
                    item[1],
                    PROTOTYPE_DEFINITIONS[item[0]]["priority"],
                ),
                reverse=True,
            )

        if row_t_us < display_start_us:
            # Warm-up rows only establish the causal state memory.
            continue

        if quality <= 0:
            primary_code = "DATA_UNSTABLE"
            primary_score = 0.0
        elif ranked and ranked[0][1] >= _MATCH_THRESHOLD_ACTIVE:
            primary_code = ranked[0][0]
            primary_score = float(ranked[0][1])
        elif ranked:
            primary_code = "STABLE_NEUTRAL"
            primary_score = float(ranked[0][1])
        else:
            primary_code = "REFERENCE_BUILDING"
            primary_score = 0.0

        baseline_rows = list(row_baseline.get("rows", []) or [])
        baseline_version = int(baseline_rows[-1].get("t_us", 0)) if baseline_rows else 0
        timeline_row = {
            "t_us": row_t_us,
            "latest_data_t_us": row_t_us,
            "baseline_version": baseline_version,
            "baseline_ready": bool(row_baseline.get("ready")),
            "quality_multiplier": float(quality),
            "primary_code": primary_code,
            "primary_score": float(primary_score),
            "temporal_model_version": "v0.4.3",
        }
        for code in PROTOTYPE_DEFINITIONS:
            detail = details.get(code, {})
            timeline_row[f"score_{code}"] = float(state_scores.get(code, float("nan")))
            timeline_row[f"evidence_score_{code}"] = float(
                evidence_scores.get(code, float("nan"))
            )
            timeline_row[f"raw_score_{code}"] = float(raw_scores.get(code, float("nan")))
            timeline_row[f"temporal_ready_{code}"] = 1 if bool(detail.get("ready")) else 0
            timeline_row[f"coverage_{code}"] = float(detail.get("coverage_ratio", 0.0) or 0.0)
            timeline_row[f"persistence_{code}"] = float(
                detail.get("persistence_ratio", 0.0) or 0.0
            )
            timeline_row[f"stability_{code}"] = float(
                detail.get("stability_score", 0.0) or 0.0
            )
            timeline_row[f"observed_span_minutes_{code}"] = float(
                detail.get("observed_span_minutes", 0.0) or 0.0
            )
        timeline.append(timeline_row)

    if timeline:
        t0 = timeline[0]["t_us"]
        for item in timeline:
            item["elapsed_minutes"] = float((item["t_us"] - t0) / 60e6)
    return timeline

def build_hour_experience(
    snapshot: AnalysisSnapshot,
    history: Sequence[dict],
) -> dict:
    history_rows = [
        dict(
            row
        )
        for row in history
    ]
    current_row = _current_row_from_snapshot(
        snapshot
    )

    if (
        not history_rows
        or int(
            history_rows[-1].get(
                "t_us",
                0,
            )
        )
        != int(
            current_row[
                "t_us"
            ]
        )
    ):
        history_rows.append(
            current_row
        )
    else:
        history_rows[-1].update(
            current_row
        )

    if not history_rows:
        elapsed_minutes = 0.0
    else:
        elapsed_minutes = float(
            max(
                0,
                int(
                    history_rows[-1][
                        "t_us"
                    ]
                )
                - int(
                    history_rows[0][
                        "t_us"
                    ]
                ),
            )
            / 60e6
        )

    stage_code, stage_name, next_minutes = (
        _session_stage(
            elapsed_minutes
        )
    )

    baseline = _build_personal_baseline(
        history_rows,
        int(
            current_row[
                "t_us"
            ]
        ),
    )

    timeline = _timeline_score_rows(
        history_rows,
        baseline,
    )

    if timeline:
        interval_minutes = float(
            np.median(
                np.diff(
                    np.asarray(
                        [
                            row[
                                "t_us"
                            ]
                            for row in timeline
                        ],
                        dtype=float,
                    )
                )
            )
            / 60e6
        ) if len(
            timeline
        ) >= 2 else 0.3333

        interval_minutes = float(
            np.clip(
                interval_minutes,
                0.05,
                1.0,
            )
        )
    else:
        interval_minutes = 0.0

    state_minutes: defaultdict[
        str,
        float,
    ] = defaultdict(
        float
    )

    for row in timeline:
        state_minutes[
            row[
                "primary_code"
            ]
        ] += interval_minutes

    # 连续片段与转场。
    segments: list[dict] = []

    for row in timeline:
        code = row[
            "primary_code"
        ]

        if (
            not segments
            or segments[-1][
                "code"
            ]
            != code
        ):
            segments.append({
                "code": code,
                "start_t_us": row[
                    "t_us"
                ],
                "end_t_us": row[
                    "t_us"
                ],
                "minutes": interval_minutes,
                "max_score": row[
                    "primary_score"
                ],
            })
        else:
            segments[-1][
                "end_t_us"
            ] = row[
                "t_us"
            ]
            segments[-1][
                "minutes"
            ] += interval_minutes
            segments[-1][
                "max_score"
            ] = max(
                segments[-1][
                    "max_score"
                ],
                row[
                    "primary_score"
                ],
            )

    meaningful_segments = _coalesce_meaningful_segments(segments)

    transitions = max(
        len(
            meaningful_segments
        )
        - 1,
        0,
    )

    longest_segment = max(
        (
            segment[
                "minutes"
            ]
            for segment
            in meaningful_segments
        ),
        default=0.0,
    )

    quality_minutes = (
        state_minutes.get(
            "DATA_UNSTABLE",
            0.0,
        )
    )
    observed_minutes = sum(
        state_minutes.values()
    )

    valid_coverage = (
        1.0
        - quality_minutes
        / max(
            observed_minutes,
            1e-9,
        )
        if observed_minutes
        > 0
        else 0.0
    )

    research_state = (
        evaluate_research_state(
            snapshot,
            history_rows,
            timeline=timeline,
        )
    )

    source_ids: list[int] = []
    for match in research_state[
        "matches"
    ]:
        if (
            match[
                "lifecycle"
            ]
            in {
                "ACTIVE",
                "CANDIDATE",
            }
        ):
            for source_id in match[
                "source_ids"
            ]:
                if source_id not in source_ids:
                    source_ids.append(
                        source_id
                    )

    # 研究身份层只做“尚未开启”的显式产品状态。
    trait_reference_state = {
        "code": "T0_TRAIT_UNKNOWN",
        "enabled": False,
        "reason": (
            "目前只根据这次记录了解你的近期变化；"
            "是否存在长期习惯，需要多天记录后再观察。"
        ),
        "research_reference_source_ids": [
            6,
            8,
        ],
    }

    return {
        "stage_code": stage_code,
        "stage_name": stage_name,
        "elapsed_minutes": elapsed_minutes,
        "next_milestone_minutes": (
            None
            if next_minutes
            is None
            else max(
                0.0,
                float(
                    next_minutes
                ),
            )
        ),
        "valid_coverage": float(
            np.clip(
                valid_coverage,
                0.0,
                1.0,
            )
        ),
        "baseline_ready": bool(
            baseline[
                "ready"
            ]
        ),
        "baseline_reference_window_count": len(
            baseline[
                "rows"
            ]
        ),
        "state_minutes": dict(
            sorted(
                state_minutes.items(),
                key=lambda item:
                    item[1],
                reverse=True,
            )
        ),
        "state_distribution": [
            {
                "code": code,
                "name": research_state_display_name(code),
                "minutes": float(minutes),
            }
            for code, minutes in sorted(
                state_minutes.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        ],
        "hour_summary": _hour_trajectory_summary(
            elapsed_minutes,
            dict(state_minutes),
            segments,
        ),
        "transition_count": int(
            transitions
        ),
        "longest_research_state_minutes": float(
            longest_segment
        ),
        "segments": segments,
        "timeline": timeline,
        "current_research_state": (
            research_state
        ),
        "source_ids": source_ids,
        "source_facts_html": (
            render_source_facts_html(
                source_ids
            )
            if source_ids
            else ""
        ),
        "trait_reference_state": (
            trait_reference_state
        ),
    }


def research_state_table() -> list[dict]:
    table: list[dict] = []

    for code, definition in PROTOTYPE_DEFINITIONS.items():
        table.append({
            "code": code,
            "name": definition[
                "name"
            ],
            "priority": definition[
                "priority"
            ],
            "test_state": definition[
                "test_state"
            ],
            "user_narrative": definition[
                "user_narrative"
            ],
            "source_ids": list(
                definition[
                    "source_ids"
                ]
            ),
            "sources": [
                get_source(
                    source_id
                ).to_dict()
                for source_id
                in definition[
                    "source_ids"
                ]
            ],
        })

    return table
