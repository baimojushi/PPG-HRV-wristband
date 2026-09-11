from __future__ import annotations

"""Sequence-level RR artifact classification for the authoritative PPG timeline.

The waveform detectors answer "is there a plausible pulse here?".  This module
answers the different question "does the resulting interval sequence still make
sense as an NN timeline?".  The distinction is deliberate: two heterogeneous
PPG detectors can agree on the same motion/notch artifact because both observe
the same optical waveform.

The classifier is conservative:
- structural repairs require evidence on both sides of the event when available;
- a coherent run of changed RR values is treated as a possible real rate change,
  not as a chain of local outliers;
- corrected values are emitted only for the reconstructed NN timeline.  Beat
  timestamps are never moved and the raw beat timeline remains auditable.
"""

from dataclasses import dataclass
from collections.abc import Sequence
import numpy as np

from .config import AnalysisConfig
from .models import BeatFrame


@dataclass(slots=True)
class IntervalArtifactDecision:
    """Decision for one raw RR interval ending at ``t_us``."""

    index: int
    seq: int
    t_us: int
    rr_raw_ms: float
    reference_rr_ms: float
    robust_scale_ms: float
    artifact_class: str
    status: str
    resolved: bool
    corrected_rr_ms: float
    split_count: int = 1
    paired_index: int = -1
    paired_t_us: int = 0
    confidence: float = 0.0
    reason: str = ""
    evidence: str = ""


@dataclass(slots=True)
class _Reference:
    rr_ms: float
    scale_ms: float
    left_median_ms: float
    right_median_ms: float
    left_count: int
    right_count: int
    robust_cv: float
    side_difference_ratio: float
    stable: bool


class IntervalArtifactClassifier:
    """Classify extra/missed/phase-slip intervals using future-aware context."""

    def __init__(self, config: AnalysisConfig | None = None):
        self.config = config or AnalysisConfig()

    def classify(self, beats: Sequence[BeatFrame]) -> list[IntervalArtifactDecision]:
        source = [beat for beat in beats if float(beat.rr_ms) > 0]
        if not source:
            return []

        rrs = np.asarray([float(beat.rr_ms) for beat in source], dtype=float)
        decisions: list[IntervalArtifactDecision | None] = [None] * len(source)
        i = 0

        while i < len(source):
            beat = source[i]
            rr = float(rrs[i])
            wear = bool(beat.flags & 0x01) if beat.flags else True
            single_ref = self._reference(rrs, i, span=1)

            if not wear:
                decisions[i] = self._decision(
                    source, i, rr, single_ref, "no_wear", "no_wear", False, 0.0,
                    reason="未佩戴", evidence="wear flag inactive",
                )
                i += 1
                continue

            if not np.isfinite(rr) or rr <= 0:
                decisions[i] = self._decision(
                    source, i, rr, single_ref, "invalid_rr", "hard_outlier", False, 0.0,
                    reason="RR 无效", evidence="non-finite/non-positive interval",
                )
                i += 1
                continue

            # 1) One real cycle split by an extra optical peak.
            if i + 1 < len(source):
                pair_ref = self._reference(rrs, i, span=2)
                next_rr = float(rrs[i + 1])
                if self._extra_peak_pair(rr, next_rr, pair_ref):
                    merged = rr + next_rr
                    confidence = self._extra_pair_confidence(rr, next_rr, merged, pair_ref)
                    evidence = self._pair_evidence("extra_split", rr, next_rr, pair_ref)
                    decisions[i] = self._decision(
                        source, i, rr, pair_ref, "extra_peak_split", "false_peak", True, 0.0,
                        paired_index=i + 1, confidence=confidence,
                        reason="额外波峰：与下一间期合并", evidence=evidence,
                    )
                    decisions[i + 1] = self._decision(
                        source, i + 1, next_rr, pair_ref, "extra_peak_merge", "false_peak_merged",
                        True, merged, paired_index=i, confidence=confidence,
                        reason="额外波峰合并后的 NN", evidence=evidence,
                    )
                    i += 2
                    continue

            # 2) A long/short or short/long compensating pair.  This commonly
            # represents a fiducial phase slip or ectopic-like interval pair.  We
            # preserve elapsed time by assigning the pair mean to both corrected NN.
            if i + 1 < len(source):
                pair_ref = self._reference(rrs, i, span=2)
                next_rr = float(rrs[i + 1])
                if self._phase_slip_pair(rr, next_rr, pair_ref):
                    corrected = (rr + next_rr) / 2.0
                    confidence = self._phase_pair_confidence(rr, next_rr, pair_ref)
                    evidence = self._pair_evidence("long_short", rr, next_rr, pair_ref)
                    for j, raw in ((i, rr), (i + 1, next_rr)):
                        decisions[j] = self._decision(
                            source, j, raw, pair_ref, "long_short_pair", "long_short_repaired",
                            True, corrected, paired_index=(i + 1 if j == i else i),
                            confidence=confidence,
                            reason="相邻长短间期总时长正常，按一对修复", evidence=evidence,
                        )
                    i += 2
                    continue

            # 3) Missing one or two beats.  This fallback operates on the NN
            # timeline only; sequence resolver should prefer a real single-detector
            # waveform candidate when one is available.
            missed = self._missed_multiple(rr, single_ref)
            if missed >= 2:
                per_interval = rr / missed
                confidence = self._missed_confidence(rr, missed, single_ref)
                decisions[i] = self._decision(
                    source, i, rr, single_ref, "missed_beat", "missed_beat_repaired", True,
                    per_interval, split_count=missed, confidence=confidence,
                    reason=f"疑似漏搏：拆分为 {missed} 个 NN",
                    evidence=(
                        f"raw={rr:.1f}ms ref={single_ref.rr_ms:.1f}ms "
                        f"per={per_interval:.1f}ms anchors={single_ref.left_count}+{single_ref.right_count}"
                    ),
                )
                i += 1
                continue

            # 4) Hard bounds after structural missed-beat recovery was attempted.
            if rr < self.config.rr_hard_min_ms:
                decisions[i] = self._decision(
                    source, i, rr, single_ref, "hard_short", "hard_outlier", False, 0.0,
                    reason="RR 过短", evidence=f"raw={rr:.1f}ms",
                )
                i += 1
                continue
            if rr > self.config.rr_hard_max_ms:
                decisions[i] = self._decision(
                    source, i, rr, single_ref, "hard_long", "hard_outlier", False, 0.0,
                    reason="RR 过长", evidence=f"raw={rr:.1f}ms",
                )
                i += 1
                continue

            # 5) Only call an in-range value an unresolved local outlier when it
            # is isolated between stable anchors.  A coherent run is a possible
            # real rate transition and must not create a self-sustaining reject run.
            if self._isolated_outlier(rrs, i, single_ref):
                relative = abs(rr - single_ref.rr_ms) / max(single_ref.rr_ms, 1.0)
                robust_z = abs(rr - single_ref.rr_ms) / max(single_ref.scale_ms, 1.0)
                confidence = float(np.clip(0.45 + 0.30 * relative + 0.04 * robust_z, 0.0, 0.98))
                decisions[i] = self._decision(
                    source, i, rr, single_ref, "isolated_outlier", "local_outlier", False, 0.0,
                    confidence=confidence,
                    reason="孤立 RR 与前后稳定节律不一致",
                    evidence=(
                        f"raw={rr:.1f}ms ref={single_ref.rr_ms:.1f}ms "
                        f"relative={relative:.3f} robust_z={robust_z:.2f}"
                    ),
                )
                i += 1
                continue

            decisions[i] = self._decision(
                source, i, rr, single_ref, "accepted", "accepted", True, rr,
                confidence=self._accepted_confidence(rr, single_ref),
                reason="", evidence=self._reference_evidence(single_ref),
            )
            i += 1

        return [decision for decision in decisions if decision is not None]

    # ------------------------------------------------------------------
    # Local rhythm model
    # ------------------------------------------------------------------
    def _reference(self, rrs: np.ndarray, index: int, span: int) -> _Reference:
        cfg = self.config
        radius = int(max(4, cfg.interval_artifact_context_intervals))
        left = rrs[max(0, index - radius):index]
        right = rrs[index + span:index + span + radius]

        lo = max(float(cfg.rr_hard_min_ms), float(cfg.interval_artifact_reference_min_ms))
        hi = min(float(cfg.rr_hard_max_ms), float(cfg.interval_artifact_reference_max_ms))
        left = self._robust_valid(left, lo, hi)
        right = self._robust_valid(right, lo, hi)

        left_med = float(np.median(left)) if left.size else 0.0
        right_med = float(np.median(right)) if right.size else 0.0

        if left.size and right.size:
            side_diff = abs(left_med - right_med) / max((left_med + right_med) / 2.0, 1.0)
        else:
            side_diff = 0.0

        if left.size and right.size and side_diff <= cfg.interval_artifact_anchor_side_tolerance:
            data = np.concatenate([left, right])
        elif left.size >= right.size and left.size:
            data = left
        elif right.size:
            data = right
        else:
            data = np.asarray([800.0], dtype=float)

        median = float(np.median(data))
        mad = float(np.median(np.abs(data - median)))
        scale = max(1.4826 * mad, cfg.rr_robust_scale_floor_ms)
        robust_cv = 1.4826 * mad / max(median, 1.0)
        both_sides = left.size >= 2 and right.size >= 2
        stable = bool(
            data.size >= 4
            and robust_cv <= cfg.interval_artifact_anchor_max_robust_cv
            and (
                not both_sides
                or side_diff <= cfg.interval_artifact_anchor_side_tolerance
            )
        )
        return _Reference(
            rr_ms=median,
            scale_ms=float(scale),
            left_median_ms=left_med,
            right_median_ms=right_med,
            left_count=int(left.size),
            right_count=int(right.size),
            robust_cv=float(robust_cv),
            side_difference_ratio=float(side_diff),
            stable=stable,
        )

    @staticmethod
    def _robust_valid(values: np.ndarray, lo: float, hi: float) -> np.ndarray:
        values = np.asarray(values, dtype=float)
        values = values[np.isfinite(values) & (values >= lo) & (values <= hi)]
        if values.size < 4:
            return values
        median = float(np.median(values))
        mad = float(np.median(np.abs(values - median)))
        if mad <= 1e-9:
            return values
        scale = max(1.4826 * mad, 25.0)
        keep = np.abs(values - median) <= max(4.5 * scale, 0.35 * median)
        filtered = values[keep]
        return filtered if filtered.size >= 2 else values

    # ------------------------------------------------------------------
    # Structural classifiers
    # ------------------------------------------------------------------
    def _extra_peak_pair(self, first: float, second: float, ref: _Reference) -> bool:
        cfg = self.config
        if not ref.stable or ref.rr_ms <= 0 or not (np.isfinite(first) and np.isfinite(second)):
            return False
        if first <= 0 or second <= 0:
            return False
        merged = first + second
        sum_error = abs(merged - ref.rr_ms) / max(ref.rr_ms, 1.0)
        components_short = (
            first < ref.rr_ms * cfg.false_peak_component_max_ratio
            and second < ref.rr_ms * cfg.false_peak_component_max_ratio
        )
        # Avoid converting a genuine persistent HR acceleration into an extra peak.
        return bool(sum_error <= cfg.false_peak_merge_tolerance and components_short)

    def _phase_slip_pair(self, first: float, second: float, ref: _Reference) -> bool:
        cfg = self.config
        if not ref.stable or ref.rr_ms <= 0:
            return False
        if not (np.isfinite(first) and np.isfinite(second)):
            return False
        if min(first, second) < cfg.rr_hard_min_ms or max(first, second) > cfg.rr_hard_max_ms:
            return False
        d1 = (first - ref.rr_ms) / max(ref.rr_ms, 1.0)
        d2 = (second - ref.rr_ms) / max(ref.rr_ms, 1.0)
        opposite = d1 * d2 < 0
        substantial = max(abs(d1), abs(d2)) >= cfg.interval_phase_pair_min_deviation_ratio
        pair_error = abs((first + second) - 2.0 * ref.rr_ms) / max(2.0 * ref.rr_ms, 1.0)
        return bool(opposite and substantial and pair_error <= cfg.interval_phase_pair_sum_tolerance)

    def _missed_multiple(self, rr: float, ref: _Reference) -> int:
        cfg = self.config
        if not ref.stable or ref.rr_ms <= 0 or not np.isfinite(rr):
            return 0
        ratio = rr / ref.rr_ms
        multiple = int(round(ratio))
        if multiple < 2 or multiple > cfg.interval_missed_max_multiple:
            return 0
        per_interval = rr / multiple
        split_error = abs(per_interval - ref.rr_ms) / max(ref.rr_ms, 1.0)
        if split_error > cfg.missed_beat_split_tolerance:
            return 0
        # A long interval must be meaningfully longer than the local rhythm.  This
        # prevents round(1.55) from turning a large but plausible single interval
        # into a synthetic split.
        if ratio < cfg.interval_missed_min_ratio:
            return 0
        return multiple

    def _isolated_outlier(self, rrs: np.ndarray, index: int, ref: _Reference) -> bool:
        cfg = self.config
        if not ref.stable or ref.rr_ms <= 0:
            return False
        rr = float(rrs[index])
        relative = abs(rr - ref.rr_ms) / max(ref.rr_ms, 1.0)
        robust_z = abs(rr - ref.rr_ms) / max(ref.scale_ms, 1.0)
        suspicious = bool(
            relative > cfg.rr_major_deviation_limit
            or (
                relative > cfg.rr_relative_deviation_limit
                and robust_z > cfg.rr_mad_z_limit
            )
        )
        if not suspicious:
            return False

        tolerance = cfg.interval_artifact_neighbor_tolerance
        neighbours: list[float] = []
        if index > 0:
            neighbours.append(float(rrs[index - 1]))
        if index + 1 < rrs.size:
            neighbours.append(float(rrs[index + 1]))
        valid_neighbours = [
            value for value in neighbours
            if np.isfinite(value) and value > 0
        ]
        if len(valid_neighbours) < 2:
            return False
        neighbour_close = [
            abs(value - ref.rr_ms) / max(ref.rr_ms, 1.0) <= tolerance
            for value in valid_neighbours
        ]
        if not all(neighbour_close):
            # Consecutive changed intervals are a possible real transition.  Do not
            # create a reject cascade simply because a stale local median differs.
            return False
        return True

    # ------------------------------------------------------------------
    # Confidence / serialization helpers
    # ------------------------------------------------------------------
    def _accepted_confidence(self, rr: float, ref: _Reference) -> float:
        if ref.rr_ms <= 0:
            return 0.5
        fit = 1.0 - min(abs(rr - ref.rr_ms) / max(ref.rr_ms, 1.0), 1.0)
        anchor = 1.0 if ref.stable else 0.55
        return float(np.clip(0.45 + 0.35 * fit + 0.20 * anchor, 0.0, 1.0))

    def _extra_pair_confidence(self, first: float, second: float, merged: float, ref: _Reference) -> float:
        tol = max(self.config.false_peak_merge_tolerance, 1e-6)
        fit = 1.0 - min(abs(merged - ref.rr_ms) / max(ref.rr_ms, 1.0) / tol, 1.0)
        balance = min(first, second) / max(max(first, second), 1.0)
        return float(np.clip(0.58 + 0.30 * fit + 0.12 * balance, 0.0, 0.99))

    def _phase_pair_confidence(self, first: float, second: float, ref: _Reference) -> float:
        tol = max(self.config.interval_phase_pair_sum_tolerance, 1e-6)
        err = abs((first + second) - 2.0 * ref.rr_ms) / max(2.0 * ref.rr_ms, 1.0)
        fit = 1.0 - min(err / tol, 1.0)
        return float(np.clip(0.55 + 0.40 * fit, 0.0, 0.98))

    def _missed_confidence(self, rr: float, multiple: int, ref: _Reference) -> float:
        per = rr / max(multiple, 1)
        tol = max(self.config.missed_beat_split_tolerance, 1e-6)
        err = abs(per - ref.rr_ms) / max(ref.rr_ms, 1.0)
        fit = 1.0 - min(err / tol, 1.0)
        return float(np.clip(0.58 + 0.36 * fit, 0.0, 0.98))

    @staticmethod
    def _reference_evidence(ref: _Reference) -> str:
        return (
            f"ref={ref.rr_ms:.1f}ms scale={ref.scale_ms:.1f}ms "
            f"anchors={ref.left_count}+{ref.right_count} cv={ref.robust_cv:.3f} "
            f"side_diff={ref.side_difference_ratio:.3f} stable={int(ref.stable)}"
        )

    def _pair_evidence(self, kind: str, first: float, second: float, ref: _Reference) -> str:
        return (
            f"{kind} first={first:.1f}ms second={second:.1f}ms "
            f"sum={first + second:.1f}ms ref={ref.rr_ms:.1f}ms "
            f"anchors={ref.left_count}+{ref.right_count} side_diff={ref.side_difference_ratio:.3f}"
        )

    def _decision(
        self,
        source: Sequence[BeatFrame],
        index: int,
        rr: float,
        ref: _Reference,
        artifact_class: str,
        status: str,
        resolved: bool,
        corrected_rr_ms: float,
        *,
        split_count: int = 1,
        paired_index: int = -1,
        confidence: float = 0.0,
        reason: str = "",
        evidence: str = "",
    ) -> IntervalArtifactDecision:
        beat = source[index]
        return IntervalArtifactDecision(
            index=int(index),
            seq=int(beat.seq),
            t_us=int(beat.t_us),
            rr_raw_ms=float(rr),
            reference_rr_ms=float(ref.rr_ms),
            robust_scale_ms=float(ref.scale_ms),
            artifact_class=str(artifact_class),
            status=str(status),
            resolved=bool(resolved),
            corrected_rr_ms=float(corrected_rr_ms),
            split_count=int(split_count),
            paired_index=int(paired_index),
            paired_t_us=(
                int(source[paired_index].t_us)
                if 0 <= int(paired_index) < len(source)
                else 0
            ),
            confidence=float(confidence),
            reason=str(reason),
            evidence=str(evidence),
        )
