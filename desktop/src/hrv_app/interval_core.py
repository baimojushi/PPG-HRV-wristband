from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

import numpy as np

from .beat_consensus import build_detector_consensus
from .beat_sequence_resolver import SequenceCandidateDecision, resolve_consensus_sequence
from .config import AnalysisConfig
from .models import BeatFrame, SampleFrame
from .ppg_preprocessor import preprocess_ppg
from .waveform_detectors import detect_elgendi_like, detect_multiscale_persistence


@dataclass(slots=True)
class IntervalPeakProposal:
    seq: int
    t_us: int
    waveform_score: float
    timing_uncertainty_ms: float
    reference_rr_ms: float
    polarity: int
    prominence: float = 0.0

    matched_firmware_t_us: int = 0
    matched_firmware_score: float = 0.0
    matched_firmware_flags: int = 0

    # Compatibility fields. inserted_by_smoother now means a true sequence rescue,
    # never "firmware did not match".
    inserted_by_smoother: bool = False
    low_prominence_rescue: bool = False

    detector_support_count: int = 0
    detector_names: str = ""
    detector_consensus: float = 0.0
    detector_time_spread_ms: float = 0.0
    single_detector: bool = False
    sequence_rescued: bool = False
    firmware_unmatched: bool = False
    local_clipped: bool = False


@dataclass(slots=True)
class IntervalCoreDiagnostics:
    reference_rr_ms: float = 0.0
    autocorr_confidence: float = 0.0  # kept for provenance compatibility
    polarity: int = 1
    candidate_count: int = 0
    selected_count: int = 0
    inserted_count: int = 0
    firmware_matched_count: int = 0
    waveform_amplitude: float = 0.0
    commit_until_t_us: int = 0
    latest_sample_t_us: int = 0

    primary_count: int = 0
    secondary_count: int = 0
    dual_detector_count: int = 0
    single_detector_count: int = 0
    detector_consensus_ratio: float = 0.0
    detector_time_spread_p95_ms: float = 0.0

    stable_reference_rr_ms: float = 0.0
    local_dual_rr_ms: float = 0.0
    local_dual_rr_robust_cv: float = 0.0
    reference_update_reason: str = ""
    rejected_candidate_count: int = 0
    long_gap_rescue_count: int = 0


class IntervalCore:
    """v0.4.2 authoritative PPG -> Beat candidate core.

    Firmware Accepted beats are diagnostic only. Formal beats are created from two
    heterogeneous waveform detectors, consensus evidence and a fixed-lag sequence
    resolver. The resolver may choose among real peaks, but it never synthesizes an
    expected timestamp.  Final RR authority still belongs to the downstream
    interval-artifact classifier, because two waveform detectors may share the same
    optical false peak.
    """

    def __init__(self, config: AnalysisConfig | None = None):
        self.config = config or AnalysisConfig()
        self.last_diagnostics = IntervalCoreDiagnostics()
        self._consumed_firmware_t_us: set[int] = set()
        self._stable_rr_ms: float = 0.0
        self._last_reference_reason: str = "bootstrap"
        self._last_local_dual_rr_ms: float = 0.0
        self._last_local_dual_rr_robust_cv: float = 0.0
        self.last_candidate_decisions: list[SequenceCandidateDecision] = []

    def reset(self) -> None:
        self.last_diagnostics = IntervalCoreDiagnostics()
        self._consumed_firmware_t_us.clear()
        self._stable_rr_ms = 0.0
        self._last_reference_reason = "reset"
        self._last_local_dual_rr_ms = 0.0
        self._last_local_dual_rr_robust_cv = 0.0
        self.last_candidate_decisions = []

    def _reference_rr(
        self,
        consensus: Sequence,
        rr_history_ms: Sequence[float],
    ) -> float:
        """Choose the RR search scale without letting a bad window poison the next.

        The local estimate is allowed to update the reference only when it comes
        from several dual-detector intervals and those intervals are internally
        coherent. This follows the same robustness principle used by mature
        adaptive PPG detectors: a low-quality window should lose decision power
        instead of becoming the prior for the following window.
        """

        cfg = self.config
        history = np.asarray(
            [
                float(v)
                for v in rr_history_ms
                if (
                    np.isfinite(v)
                    and cfg.waveform_min_rr_ms
                    <= float(v)
                    <= cfg.waveform_max_rr_ms
                )
            ],
            dtype=float,
        )
        history_prior = (
            float(np.median(history[-9:]))
            if history.size >= 3
            else 0.0
        )
        prior = (
            history_prior
            if history_prior > 0
            else float(self._stable_rr_ms)
        )

        dual = [
            item
            for item in consensus
            if int(getattr(item, "support_count", 0) or 0) >= 2
        ]
        dual_ratio = len(dual) / max(len(consensus), 1)
        dual_times = np.asarray(
            [int(item.t_us) for item in dual],
            dtype=float,
        )
        intervals = (
            np.diff(dual_times) / 1000.0
            if dual_times.size >= 2
            else np.asarray([], dtype=float)
        )
        intervals = intervals[
            np.isfinite(intervals)
            & (intervals >= cfg.waveform_min_rr_ms)
            & (intervals <= cfg.waveform_max_rr_ms)
        ]

        local = (
            float(np.median(intervals))
            if intervals.size >= cfg.interval_reference_min_dual_intervals
            else 0.0
        )
        if local > 0 and intervals.size:
            mad = float(np.median(np.abs(intervals - local)))
            robust_cv = 1.4826 * mad / max(local, 1.0)
        else:
            robust_cv = 1.0

        self._last_local_dual_rr_ms = float(local)
        self._last_local_dual_rr_robust_cv = float(robust_cv)

        ordinary_good = bool(
            local > 0
            and dual_ratio >= cfg.interval_reference_min_dual_ratio
            and robust_cv <= cfg.interval_reference_max_robust_cv
        )
        strong_good = bool(
            local > 0
            and dual_ratio >= cfg.interval_reference_strong_dual_ratio
            and robust_cv <= cfg.interval_reference_strong_max_robust_cv
        )

        if ordinary_good:
            relative_jump = (
                abs(local - prior) / max(prior, 1.0)
                if prior > 0
                else 0.0
            )
            if (
                prior <= 0
                or relative_jump <= cfg.interval_reference_max_jump_ratio
                or strong_good
            ):
                # Strong waveform agreement can follow a real HR transition.
                # The resolver uses the current local scale immediately, while
                # the persistent fallback is updated gradually.
                if self._stable_rr_ms > 0:
                    gain = float(
                        np.clip(cfg.interval_reference_update_gain, 0.0, 1.0)
                    )
                    self._stable_rr_ms = (
                        (1.0 - gain) * self._stable_rr_ms
                        + gain * local
                    )
                else:
                    self._stable_rr_ms = local
                self._last_reference_reason = (
                    "dual_strong_update"
                    if strong_good
                    else "dual_consensus_update"
                )
                return float(local)

        if prior > 0:
            if self._stable_rr_ms <= 0:
                self._stable_rr_ms = prior
            self._last_reference_reason = "hold_previous_good_window"
            return float(prior)

        if local > 0:
            # Bootstrap only: there is no earlier stable prior. We still allow
            # a plausible waveform-derived scale, but do not persist it unless
            # dual-detector quality passes the update rule.
            self._last_reference_reason = "bootstrap_local_untrusted"
            return float(local)

        self._last_reference_reason = "default_800ms"
        return 800.0

    def propose(
        self,
        samples: Sequence[SampleFrame],
        firmware_beats: Sequence[BeatFrame],
        last_committed_t_us: int,
        rr_history_ms: Sequence[float],
        commit_until_t_us: int,
    ) -> list[IntervalPeakProposal]:
        if not samples:
            return []

        latest_sample_t_us = int(samples[-1].t_us)
        history_start_t_us = int(
            commit_until_t_us - self.config.waveform_context_history_seconds * 1e6
        )
        if last_committed_t_us > 0:
            history_start_t_us = min(
                history_start_t_us,
                int(last_committed_t_us - 2.0 * self.config.waveform_max_rr_ms * 1000.0),
            )

        window = [s for s in samples if history_start_t_us <= s.t_us <= latest_sample_t_us]
        ppg = preprocess_ppg(window, self.config)
        if ppg is None:
            self.last_diagnostics = IntervalCoreDiagnostics(
                commit_until_t_us=int(commit_until_t_us),
                latest_sample_t_us=latest_sample_t_us,
            )
            return []

        primary = detect_multiscale_persistence(ppg, self.config)
        secondary = detect_elgendi_like(ppg, self.config)
        consensus = build_detector_consensus(primary, secondary, ppg.t_us, self.config)
        reference_rr_ms = self._reference_rr(consensus, rr_history_ms)
        candidate_decisions: list[SequenceCandidateDecision] = []
        selected = resolve_consensus_sequence(
            consensus,
            ppg,
            last_committed_t_us=last_committed_t_us,
            commit_until_t_us=commit_until_t_us,
            reference_rr_ms=reference_rr_ms,
            config=self.config,
            decision_sink=candidate_decisions,
        )
        self.last_candidate_decisions = candidate_decisions

        firmware_window = [
            beat for beat in firmware_beats
            if history_start_t_us <= beat.t_us <= latest_sample_t_us
        ]
        self._consumed_firmware_t_us = {
            t for t in self._consumed_firmware_t_us if t >= history_start_t_us
        }
        used_this_call: set[int] = set()

        proposals: list[IntervalPeakProposal] = []
        matched_count = 0
        for item in selected:
            radius_us = int(round(min(
                self.config.waveform_firmware_match_max_ms,
                reference_rr_ms * self.config.waveform_firmware_match_rr_ratio,
            ) * 1000.0))
            choices = [
                (i, beat, abs(int(beat.t_us) - int(item.t_us)))
                for i, beat in enumerate(firmware_window)
                if i not in used_this_call
                and int(beat.t_us) not in self._consumed_firmware_t_us
                and abs(int(beat.t_us) - int(item.t_us)) <= radius_us
            ]
            match_t = 0
            match_score = 0.0
            match_flags = 0
            if choices:
                i, beat, _ = min(choices, key=lambda row: row[2])
                used_this_call.add(i)
                match_t = int(beat.t_us)
                match_score = float(beat.score)
                match_flags = int(beat.flags)
                self._consumed_firmware_t_us.add(match_t)
                matched_count += 1

            sample_index = int(np.searchsorted(ppg.t_us, item.t_us))
            sample_index = min(max(sample_index, 0), len(window) - 1)
            local_radius = max(1, int(round(0.120 * ppg.sample_rate_hz)))
            local_left = max(0, sample_index - local_radius)
            local_right = min(len(window), sample_index + local_radius + 1)
            local_samples = window[local_left:local_right]
            local_clipped = any(
                (sample.raw <= self.config.adc_low)
                or (sample.raw >= self.config.adc_high)
                or bool(sample.flags & 0x02)
                or bool(sample.flags & 0x04)
                for sample in local_samples
            )

            spread = float(item.detector_time_spread_ms)
            if not np.isfinite(spread):
                spread = self.config.interval_single_detector_uncertainty_ms
            uncertainty = float(np.clip(
                5.0 + 0.55 * spread + (10.0 if item.support_count == 1 else 0.0),
                5.0,
                self.config.interval_max_timing_uncertainty_ms,
            ))
            consensus_score = float(np.clip(item.score, 0.0, 1.0))

            proposals.append(
                IntervalPeakProposal(
                    seq=int(window[sample_index].seq),
                    t_us=int(item.t_us),
                    waveform_score=consensus_score,
                    timing_uncertainty_ms=uncertainty,
                    reference_rr_ms=float(reference_rr_ms),
                    polarity=int(ppg.polarity),
                    prominence=float(item.prominence),
                    matched_firmware_t_us=match_t,
                    matched_firmware_score=match_score,
                    matched_firmware_flags=match_flags,
                    inserted_by_smoother=bool(item.sequence_rescued),
                    low_prominence_rescue=False,
                    detector_support_count=int(item.support_count),
                    detector_names=str(item.detector_names),
                    detector_consensus=consensus_score,
                    detector_time_spread_ms=spread,
                    single_detector=bool(item.support_count == 1),
                    sequence_rescued=bool(item.sequence_rescued),
                    firmware_unmatched=bool(match_t == 0),
                    local_clipped=bool(local_clipped),
                )
            )

        dual = [c for c in consensus if c.support_count >= 2]
        single = [c for c in consensus if c.support_count == 1]
        spreads = np.asarray([
            c.detector_time_spread_ms for c in dual if np.isfinite(c.detector_time_spread_ms)
        ], dtype=float)
        consensus_ratio = len(dual) / max(len(consensus), 1)
        self.last_diagnostics = IntervalCoreDiagnostics(
            reference_rr_ms=float(reference_rr_ms),
            autocorr_confidence=float(consensus_ratio),
            polarity=int(ppg.polarity),
            candidate_count=len(consensus),
            selected_count=len(proposals),
            inserted_count=sum(p.sequence_rescued for p in proposals),
            firmware_matched_count=int(matched_count),
            waveform_amplitude=float(ppg.robust_amplitude),
            commit_until_t_us=int(commit_until_t_us),
            latest_sample_t_us=latest_sample_t_us,
            primary_count=len(primary),
            secondary_count=len(secondary),
            dual_detector_count=len(dual),
            single_detector_count=len(single),
            detector_consensus_ratio=float(consensus_ratio),
            detector_time_spread_p95_ms=(
                float(np.percentile(spreads, 95))
                if spreads.size else 0.0
            ),
            stable_reference_rr_ms=float(self._stable_rr_ms),
            local_dual_rr_ms=float(self._last_local_dual_rr_ms),
            local_dual_rr_robust_cv=float(self._last_local_dual_rr_robust_cv),
            reference_update_reason=str(self._last_reference_reason),
            rejected_candidate_count=sum(
                decision.decision.startswith("rejected")
                for decision in candidate_decisions
            ),
            long_gap_rescue_count=sum(
                decision.decision == "selected_rescued"
                and decision.reason in {
                    "real_single_candidate_splits_long_gap",
                    "committed_waveform_candidate",
                }
                for decision in candidate_decisions
            ),
        )
        return proposals
