from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .beat_consensus import ConsensusPeak
from .config import AnalysisConfig
from .ppg_preprocessor import PreprocessedPPG


def _local_refine(ppg: PreprocessedPPG, candidate: ConsensusPeak, radius_ms: float) -> ConsensusPeak:
    radius = max(1, int(round(radius_ms / 1000.0 * ppg.sample_rate_hz)))
    center = int(candidate.index)
    left = max(0, center - radius)
    right = min(ppg.signal.size, center + radius + 1)
    if right - left < 3:
        return candidate
    idx = int(left + np.argmax(ppg.signal[left:right]))
    candidate.index = idx
    candidate.t_us = int(ppg.t_us[idx])
    return candidate


def _interval_fit(interval_ms: float, reference_rr_ms: float) -> float:
    if reference_rr_ms <= 0 or interval_ms <= 0:
        return 0.5
    relative = abs(interval_ms - reference_rr_ms) / reference_rr_ms
    return float(np.clip(1.0 - relative / 0.55, 0.0, 1.0))


def resolve_consensus_sequence(
    consensus: Sequence[ConsensusPeak],
    ppg: PreprocessedPPG,
    last_committed_t_us: int,
    commit_until_t_us: int,
    reference_rr_ms: float,
    config: AnalysisConfig | None = None,
) -> list[ConsensusPeak]:
    """Fixed-lag sequence resolver.

    It never creates a synthetic timestamp. RR prior is only used to decide between
    competing real waveform candidates and to rescue a strong single-detector peak
    inside an otherwise implausible long gap.
    """

    cfg = config or AnalysisConfig()
    candidates = [
        _local_refine(ppg, item, cfg.interval_local_refine_radius_ms)
        for item in consensus
        if int(item.t_us) <= int(commit_until_t_us)
        and (
            last_committed_t_us <= 0
            or int(item.t_us) > int(last_committed_t_us)
        )
    ]
    if not candidates:
        return []
    candidates.sort(key=lambda item: item.t_us)

    hard_min_ms = max(cfg.waveform_min_rr_ms, cfg.interval_sequence_min_rr_ms)

    # First pass: dual-detector candidates are authoritative; strong singles may pass.
    eligible: list[ConsensusPeak] = []
    for item in candidates:
        if item.support_count >= 2:
            eligible.append(item)
            continue

        previous_t = eligible[-1].t_us if eligible else last_committed_t_us
        interval_ms = (
            (item.t_us - previous_t) / 1000.0
            if previous_t > 0
            else reference_rr_ms
        )
        sequence_score = _interval_fit(interval_ms, reference_rr_ms)
        combined = 0.78 * item.score + 0.22 * sequence_score
        if combined >= cfg.interval_single_detector_min_score:
            item.score = float(np.clip(combined, 0.0, 1.0))
            item.sequence_rescued = True
            eligible.append(item)

    if not eligible:
        return []

    # Collapse physiologically impossible near-duplicates. Prefer dual support first,
    # then higher evidence; firmware is intentionally absent from this decision.
    compact: list[ConsensusPeak] = []
    for item in eligible:
        if not compact:
            if last_committed_t_us > 0:
                first_gap = (item.t_us - last_committed_t_us) / 1000.0
                if first_gap < hard_min_ms:
                    continue
            compact.append(item)
            continue

        gap_ms = (item.t_us - compact[-1].t_us) / 1000.0
        if gap_ms >= hard_min_ms:
            compact.append(item)
            continue

        previous = compact[-1]
        previous_key = (previous.support_count, previous.score)
        current_key = (item.support_count, item.score)
        if current_key > previous_key:
            compact[-1] = item

    # Second pass: if dual peaks surround a long gap, re-consider the strongest
    # rejected single inside the gap. It must correspond to an actual waveform peak.
    selected_ids = {id(item) for item in compact}
    singles = [
        item for item in candidates
        if item.support_count == 1 and id(item) not in selected_ids
    ]
    additions: list[ConsensusPeak] = []
    anchors: list[tuple[int, ConsensusPeak | None]] = []
    if last_committed_t_us > 0:
        anchors.append((int(last_committed_t_us), None))
    anchors.extend((int(item.t_us), item) for item in compact)

    for (left_t, _), (right_t, _) in zip(anchors[:-1], anchors[1:], strict=False):
        gap_ms = (right_t - left_t) / 1000.0
        if reference_rr_ms <= 0 or gap_ms < reference_rr_ms * cfg.interval_sequence_long_gap_ratio:
            continue
        inside = [s for s in singles if left_t < s.t_us < right_t]
        if not inside:
            continue

        def rescue_value(item: ConsensusPeak) -> float:
            left_rr = (item.t_us - left_t) / 1000.0
            right_rr = (right_t - item.t_us) / 1000.0
            fit = 0.5 * (_interval_fit(left_rr, reference_rr_ms) + _interval_fit(right_rr, reference_rr_ms))
            return 0.70 * item.score + 0.30 * fit

        best = max(inside, key=rescue_value)
        if rescue_value(best) >= cfg.interval_sequence_rescue_min_score:
            best.score = float(np.clip(rescue_value(best), 0.0, 1.0))
            best.sequence_rescued = True
            additions.append(best)

    if additions:
        compact.extend(additions)
        compact.sort(key=lambda item: item.t_us)
        # one final refractory collapse
        final: list[ConsensusPeak] = []
        for item in compact:
            if not final or (item.t_us - final[-1].t_us) / 1000.0 >= hard_min_ms:
                final.append(item)
            elif (item.support_count, item.score) > (final[-1].support_count, final[-1].score):
                final[-1] = item
        compact = final

    return compact
