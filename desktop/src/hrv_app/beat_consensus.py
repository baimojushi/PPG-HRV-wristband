from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

import numpy as np

from .config import AnalysisConfig
from .waveform_detectors import DetectorPeak


@dataclass(slots=True)
class ConsensusPeak:
    t_us: int
    index: int
    score: float
    support_count: int
    detector_names: str
    detector_time_spread_ms: float
    prominence: float
    primary_t_us: int = 0
    secondary_t_us: int = 0
    sequence_rescued: bool = False


def build_detector_consensus(
    primary: Sequence[DetectorPeak],
    secondary: Sequence[DetectorPeak],
    t_us: np.ndarray,
    config: AnalysisConfig | None = None,
) -> list[ConsensusPeak]:
    """Pair heterogeneous detector outputs without firmware involvement."""

    cfg = config or AnalysisConfig()
    tolerance_us = int(round(cfg.interval_consensus_tolerance_ms * 1000.0))
    secondary_used: set[int] = set()
    result: list[ConsensusPeak] = []

    for p in primary:
        choices = [
            (i, s, abs(int(s.t_us) - int(p.t_us)))
            for i, s in enumerate(secondary)
            if i not in secondary_used
            and abs(int(s.t_us) - int(p.t_us)) <= tolerance_us
        ]
        if choices:
            i, s, distance = min(choices, key=lambda item: item[2])
            secondary_used.add(i)
            # Use the stronger detector's exact waveform peak, not the midpoint.
            winner = p if p.score >= s.score else s
            spread_ms = float(distance / 1000.0)
            agreement = 1.0 - min(spread_ms / max(cfg.interval_consensus_tolerance_ms, 1e-6), 1.0)
            score = float(np.clip(
                0.62
                + 0.23 * min(float(p.score), float(s.score))
                + 0.15 * agreement,
                0.0,
                1.0,
            ))
            result.append(
                ConsensusPeak(
                    t_us=int(winner.t_us),
                    index=int(winner.index),
                    score=score,
                    support_count=2,
                    detector_names="multiscale+elgendi_like",
                    detector_time_spread_ms=spread_ms,
                    prominence=float(max(p.prominence, s.prominence)),
                    primary_t_us=int(p.t_us),
                    secondary_t_us=int(s.t_us),
                )
            )
        else:
            score = float(np.clip(0.30 + 0.50 * p.score, 0.0, 0.82))
            result.append(
                ConsensusPeak(
                    t_us=int(p.t_us),
                    index=int(p.index),
                    score=score,
                    support_count=1,
                    detector_names="multiscale",
                    detector_time_spread_ms=float("nan"),
                    prominence=float(p.prominence),
                    primary_t_us=int(p.t_us),
                )
            )

    for i, s in enumerate(secondary):
        if i in secondary_used:
            continue
        score = float(np.clip(0.28 + 0.48 * s.score, 0.0, 0.80))
        result.append(
            ConsensusPeak(
                t_us=int(s.t_us),
                index=int(s.index),
                score=score,
                support_count=1,
                detector_names="elgendi_like",
                detector_time_spread_ms=float("nan"),
                prominence=float(s.prominence),
                secondary_t_us=int(s.t_us),
            )
        )

    result.sort(key=lambda item: item.t_us)
    return result
