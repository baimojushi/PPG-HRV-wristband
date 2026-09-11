from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

import numpy as np

from .beat_consensus import ConsensusPeak
from .config import AnalysisConfig
from .ppg_preprocessor import PreprocessedPPG


@dataclass(slots=True)
class SequenceCandidateDecision:
    t_us: int
    index: int
    support_count: int
    detector_names: str
    detector_score: float
    prominence: float
    reference_rr_ms: float
    primary_t_us: int = 0
    secondary_t_us: int = 0
    decision: str = "candidate"
    reason: str = ""
    sequence_score: float = 0.0
    combined_score: float = 0.0
    left_gap_ms: float = 0.0
    right_gap_ms: float = 0.0


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
    decision_sink: list[SequenceCandidateDecision] | None = None,
) -> list[ConsensusPeak]:
    """Resolve real waveform candidates inside the fixed-lag window.

    v0.4.2 keeps detector agreement and sequence plausibility as separate pieces
    of evidence.  Dual support is strong but not an unconditional truth signal;
    later RR-artifact classification can still reject a dual-supported extra peak.

    The resolver never creates a timestamp.  For a long gap it may recover a
    previously rejected *real* single-detector candidate when that candidate
    splits the gap into two locally plausible intervals.
    """

    cfg = config or AnalysisConfig()
    candidates = [
        _local_refine(ppg, item, cfg.interval_local_refine_radius_ms)
        for item in consensus
        if int(item.t_us) <= int(commit_until_t_us)
        and (last_committed_t_us <= 0 or int(item.t_us) > int(last_committed_t_us))
    ]
    if not candidates:
        if decision_sink is not None:
            decision_sink.clear()
        return []
    candidates.sort(key=lambda item: item.t_us)

    decisions: dict[int, SequenceCandidateDecision] = {
        id(item): SequenceCandidateDecision(
            t_us=int(item.t_us),
            index=int(item.index),
            support_count=int(item.support_count),
            detector_names=str(item.detector_names),
            detector_score=float(item.score),
            prominence=float(item.prominence),
            reference_rr_ms=float(reference_rr_ms),
            primary_t_us=int(getattr(item, "primary_t_us", 0) or 0),
            secondary_t_us=int(getattr(item, "secondary_t_us", 0) or 0),
        )
        for item in candidates
    }

    hard_min_ms = max(cfg.waveform_min_rr_ms, cfg.interval_sequence_min_rr_ms)

    # First pass: dual candidates enter the sequence pool.  Singles need both
    # waveform evidence and a plausible interval from the preceding anchor.
    eligible: list[ConsensusPeak] = []
    for item in candidates:
        decision = decisions[id(item)]
        if item.support_count >= 2:
            decision.decision = "eligible_dual"
            decision.reason = "dual_detector_support"
            decision.combined_score = float(item.score)
            eligible.append(item)
            continue

        previous_t = eligible[-1].t_us if eligible else last_committed_t_us
        interval_ms = ((item.t_us - previous_t) / 1000.0 if previous_t > 0 else reference_rr_ms)
        sequence_score = _interval_fit(interval_ms, reference_rr_ms)
        combined = 0.78 * item.score + 0.22 * sequence_score
        decision.sequence_score = float(sequence_score)
        decision.combined_score = float(combined)
        decision.left_gap_ms = float(interval_ms if previous_t > 0 else 0.0)
        if combined >= cfg.interval_single_detector_min_score:
            item.score = float(np.clip(combined, 0.0, 1.0))
            item.sequence_rescued = True
            decision.decision = "eligible_single"
            decision.reason = "single_detector_waveform_plus_sequence"
            eligible.append(item)
        else:
            decision.decision = "rejected_single"
            decision.reason = f"combined_score={combined:.3f}"

    if not eligible:
        if decision_sink is not None:
            decision_sink[:] = list(decisions.values())
        return []

    # Collapse physiologically impossible near-duplicates. Prefer support count,
    # then evidence score.  This only handles the hard refractory case; wider
    # extra-peak split patterns are intentionally left to IntervalArtifactClassifier.
    compact: list[ConsensusPeak] = []
    for item in eligible:
        if not compact:
            if last_committed_t_us > 0:
                first_gap = (item.t_us - last_committed_t_us) / 1000.0
                if first_gap < hard_min_ms:
                    decision = decisions[id(item)]
                    decision.decision = "rejected_refractory"
                    decision.reason = f"gap={first_gap:.1f}ms < {hard_min_ms:.1f}ms"
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
            prev_decision = decisions[id(previous)]
            prev_decision.decision = "rejected_refractory"
            prev_decision.reason = f"replaced_by_stronger_candidate gap={gap_ms:.1f}ms"
            compact[-1] = item
        else:
            current_decision = decisions[id(item)]
            current_decision.decision = "rejected_refractory"
            current_decision.reason = f"weaker_near_duplicate gap={gap_ms:.1f}ms"

    # Reconsider rejected singles inside a long gap.  Sequence geometry gets the
    # majority of weight here because the candidate already corresponds to a real
    # optical local maximum; the question is whether it is the missing cycle.
    selected_ids = {id(item) for item in compact}
    singles = [item for item in candidates if item.support_count == 1 and id(item) not in selected_ids]
    additions: list[ConsensusPeak] = []
    anchors: list[tuple[int, ConsensusPeak | None]] = []
    if last_committed_t_us > 0:
        anchors.append((int(last_committed_t_us), None))
    anchors.extend((int(item.t_us), item) for item in compact)

    for (left_t, _), (right_t, _) in zip(anchors[:-1], anchors[1:], strict=False):
        gap_ms = (right_t - left_t) / 1000.0
        if reference_rr_ms <= 0 or gap_ms < reference_rr_ms * cfg.interval_sequence_long_gap_ratio:
            continue
        inside = [single for single in singles if left_t < single.t_us < right_t]
        if not inside:
            continue

        def rescue_components(item: ConsensusPeak) -> tuple[float, float]:
            left_rr = (item.t_us - left_t) / 1000.0
            right_rr = (right_t - item.t_us) / 1000.0
            fit = 0.5 * (
                _interval_fit(left_rr, reference_rr_ms)
                + _interval_fit(right_rr, reference_rr_ms)
            )
            # v0.4.2: a real single-detector waveform peak located almost exactly
            # at the missing slot should not be discarded merely because its local
            # amplitude score is modest in a clipped/contact-poor window.
            combined = 0.45 * item.score + 0.55 * fit
            return float(fit), float(combined)

        best = max(inside, key=lambda item: rescue_components(item)[1])
        fit, value = rescue_components(best)
        left_rr = (best.t_us - left_t) / 1000.0
        right_rr = (right_t - best.t_us) / 1000.0
        best_decision = decisions[id(best)]
        best_decision.sequence_score = float(fit)
        best_decision.combined_score = float(value)
        best_decision.left_gap_ms = float(left_rr)
        best_decision.right_gap_ms = float(right_rr)
        if value >= cfg.interval_sequence_rescue_min_score:
            best.score = float(np.clip(value, 0.0, 1.0))
            best.sequence_rescued = True
            best_decision.decision = "rescued_long_gap"
            best_decision.reason = "real_single_candidate_splits_long_gap"
            additions.append(best)
        else:
            best_decision.decision = "rejected_long_gap_candidate"
            best_decision.reason = f"rescue_score={value:.3f}"

    if additions:
        compact.extend(additions)
        compact.sort(key=lambda item: item.t_us)
        final: list[ConsensusPeak] = []
        for item in compact:
            if not final or (item.t_us - final[-1].t_us) / 1000.0 >= hard_min_ms:
                final.append(item)
            elif (item.support_count, item.score) > (final[-1].support_count, final[-1].score):
                dropped = final[-1]
                decisions[id(dropped)].decision = "rejected_refractory"
                decisions[id(dropped)].reason = "final_collapse_replaced"
                final[-1] = item
            else:
                decisions[id(item)].decision = "rejected_refractory"
                decisions[id(item)].reason = "final_collapse_weaker"
        compact = final

    final_ids = {id(item) for item in compact}
    for item in candidates:
        decision = decisions[id(item)]
        if id(item) in final_ids:
            decision.decision = "selected_rescued" if item.sequence_rescued else "selected"
            if not decision.reason or decision.reason.startswith("dual_"):
                decision.reason = "committed_waveform_candidate"
        elif decision.decision in {"candidate", "eligible_dual", "eligible_single"}:
            decision.decision = "rejected_sequence"
            decision.reason = "not_on_final_sequence"

    if decision_sink is not None:
        decision_sink[:] = sorted(decisions.values(), key=lambda row: row.t_us)
    return compact
