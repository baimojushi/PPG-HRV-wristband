from __future__ import annotations

from dataclasses import dataclass
from collections import deque
import math

import numpy as np


@dataclass(slots=True)
class AdaptiveCandidate:
    seq: int
    t_us: int
    value: float

    morphology_score: float
    timing_score: float
    combined_score: float

    amplitude_z: float
    prominence_z: float
    slope_z: float
    curvature_z: float

    polarity: int


@dataclass(slots=True)
class AdaptiveEvent:
    candidate: bool = False
    accepted: bool = False
    rescued: bool = False
    first: bool = False

    candidate_seq: int = 0
    candidate_t_us: int = 0

    accepted_seq: int = 0
    accepted_t_us: int = 0

    rr_ms: float = 0.0
    hr_bpm: float = 0.0

    signal_score: float = 0.0
    accepted_score: float = 0.0
    expected_rr_ms: float = 0.0


class RunningRing:
    """
    固定长度环形缓冲区。

    与 ESP32 版本相同，push 时同时维护 sum / sumsq，
    每个采样点 O(1) 得到动态均值和标准差。
    """

    def __init__(self, capacity: int):
        self.capacity = int(capacity)
        self.values = np.zeros(
            self.capacity,
            dtype=np.float64,
        )
        self.write_index = 0
        self.count = 0
        self.sum = 0.0
        self.sum_sq = 0.0

    def clear(self) -> None:
        self.values.fill(0.0)
        self.write_index = 0
        self.count = 0
        self.sum = 0.0
        self.sum_sq = 0.0

    def push(self, value: float) -> None:
        value = float(value)

        if self.count == self.capacity:
            old = float(
                self.values[
                    self.write_index
                ]
            )
            self.sum -= old
            self.sum_sq -= old * old
        else:
            self.count += 1

        self.values[
            self.write_index
        ] = value

        self.sum += value
        self.sum_sq += value * value

        self.write_index = (
            self.write_index + 1
        ) % self.capacity

    def mean(self) -> float:
        if self.count == 0:
            return 0.0

        return self.sum / self.count

    def std(self, floor: float) -> float:
        if self.count < 2:
            return float(floor)

        mean = self.mean()
        variance = (
            self.sum_sq / self.count
            - mean * mean
        )

        if variance < 0:
            variance = 0.0

        return max(
            math.sqrt(variance),
            float(floor),
        )

    def newest_array(
        self,
        count: int | None = None,
    ) -> np.ndarray:
        if self.count == 0:
            return np.array(
                [],
                dtype=np.float64,
            )

        n = self.count
        if count is not None:
            n = min(n, int(count))

        indices = (
            self.write_index
            - np.arange(1, n + 1)
        ) % self.capacity

        return self.values[indices]

    def chronological_array(
        self,
        count: int | None = None,
    ) -> np.ndarray:
        return self.newest_array(
            count
        )[::-1].copy()

    def min_last(self, n: int) -> float:
        values = self.newest_array(n)

        return (
            float(np.min(values))
            if values.size
            else 0.0
        )

    def max_last(self, n: int) -> float:
        values = self.newest_array(n)

        return (
            float(np.max(values))
            if values.size
            else 0.0
        )

    def max_abs_last(self, n: int) -> float:
        values = self.newest_array(n)

        return (
            float(np.max(np.abs(values)))
            if values.size
            else 0.0
        )


class AdaptivePPGDetector:
    """
    zeez_detector.cpp 的 Python 镜像。

    主要用途：
    - 历史 CSV 离线回放；
    - 参数/算法 A/B；
    - 未来 Tiny CNN 训练标签生成；
    - 固件算法回归。

    核心思想：
    动态形态评分负责“像不像一个真实脉搏极值”，
    周期预测负责“它是不是当前周期最合理的那个极值”。
    """

    SIGNAL_CAPACITY = 320
    RR_CAPACITY = 9
    CANDIDATE_CAPACITY = 16

    def __init__(
        self,
        sample_rate_hz: float = 125.0,
        legacy_peak_factor: float = 11.0,
    ):
        self.sample_rate_hz = float(
            sample_rate_hz
        )
        self.sample_period_ms = (
            1000.0
            / self.sample_rate_hz
        )

        self.signal_stats = RunningRing(
            self.SIGNAL_CAPACITY
        )
        self.slope_stats = RunningRing(
            self.SIGNAL_CAPACITY
        )

        self.signal_points: deque[
            tuple[int, int, float, float]
        ] = deque(
            maxlen=self.SIGNAL_CAPACITY
        )

        self.rr_history: deque[float] = deque(
            maxlen=self.RR_CAPACITY
        )
        self.candidate_pool: list[
            AdaptiveCandidate
        ] = []

        self.previous_value = 0.0
        self.previous_slope = 0.0
        self.previous_seq = 0
        self.previous_t_us = 0
        self.has_previous = False

        self.last_accepted_t_us = 0
        self.last_accepted_seq = 0

        self.expected_rr_ms = 0.0
        self.autocorr_rr_ms = 0.0
        self.autocorr_confidence = 0.0
        self.samples_since_autocorr = 0

        self.current_hr_bpm = 0.0

        self.candidate_count = 0
        self.accepted_count = 0
        self.rescue_count = 0

        self.score_threshold_scale = 1.0
        self.set_legacy_peak_factor(
            legacy_peak_factor
        )

    def reset(self) -> None:
        factor = (
            11.0
            * self.score_threshold_scale
        )

        self.__init__(
            sample_rate_hz=self.sample_rate_hz,
            legacy_peak_factor=factor,
        )

    def set_legacy_peak_factor(
        self,
        factor: float,
    ) -> None:
        if (
            not np.isfinite(factor)
            or factor <= 0
        ):
            return

        scale = float(factor) / 11.0

        self.score_threshold_scale = float(
            np.clip(
                scale,
                0.78,
                1.28,
            )
        )

    @staticmethod
    def _sigmoid(x: float) -> float:
        x = float(
            np.clip(
                x,
                -8.0,
                8.0,
            )
        )

        return 1.0 / (
            1.0 + math.exp(-x)
        )

    @staticmethod
    def _clamp01(
        value: float,
    ) -> float:
        return float(
            np.clip(
                value,
                0.0,
                1.0,
            )
        )

    def _signal_score(
        self,
        value: float,
        slope: float,
    ) -> float:
        if (
            self.signal_stats.count < 32
            or self.slope_stats.count < 32
        ):
            return 0.0

        signal_std = self.signal_stats.std(
            1.0
        )
        slope_std = self.slope_stats.std(
            0.20
        )

        amplitude_z = (
            abs(
                value
                - self.signal_stats.mean()
            )
            / signal_std
        )
        slope_z = (
            abs(slope)
            / slope_std
        )

        return self._clamp01(
            0.60
            * self._sigmoid(
                (amplitude_z - 0.60)
                * 1.4
            )
            + 0.40
            * self._sigmoid(
                (slope_z - 0.60)
                * 1.2
            )
        )

    def _morphology_features(
        self,
        seq: int,
        t_us: int,
        value: float,
        polarity: int,
    ) -> AdaptiveCandidate:
        signal_mean = (
            self.signal_stats.mean()
        )
        signal_std = (
            self.signal_stats.std(1.0)
        )
        slope_std = (
            self.slope_stats.std(0.20)
        )

        prominence_window = max(
            int(
                round(
                    0.28
                    * self.sample_rate_hz
                )
            ),
            3,
        )
        slope_window = max(
            int(
                round(
                    0.14
                    * self.sample_rate_hz
                )
            ),
            3,
        )

        local_min = (
            self.signal_stats.min_last(
                prominence_window
            )
        )
        local_max = (
            self.signal_stats.max_last(
                prominence_window
            )
        )

        if polarity > 0:
            prominence = (
                value - local_min
            )
        else:
            prominence = (
                local_max - value
            )

        max_abs_slope = (
            self.slope_stats.max_abs_last(
                slope_window
            )
        )

        amplitude_z = (
            abs(value - signal_mean)
            / signal_std
        )
        prominence_z = (
            prominence / signal_std
        )
        slope_z = (
            max_abs_slope / slope_std
        )
        curvature_z = (
            abs(self.previous_slope)
            / slope_std
        )

        amplitude_score = self._sigmoid(
            (amplitude_z - 0.55)
            * 1.45
        )
        prominence_score = self._sigmoid(
            (prominence_z - 0.70)
            * 1.35
        )
        slope_score = self._sigmoid(
            (slope_z - 0.75)
            * 1.20
        )
        curvature_score = self._sigmoid(
            (curvature_z - 0.15)
            * 1.00
        )

        morphology_score = self._clamp01(
            0.32 * amplitude_score
            + 0.32 * prominence_score
            + 0.24 * slope_score
            + 0.12 * curvature_score
        )

        timing = self._timing_score(
            t_us
        )
        combined = self._clamp01(
            0.68 * morphology_score
            + 0.32 * timing
        )

        return AdaptiveCandidate(
            seq=int(seq),
            t_us=int(t_us),
            value=float(value),
            morphology_score=morphology_score,
            timing_score=timing,
            combined_score=combined,
            amplitude_z=float(
                amplitude_z
            ),
            prominence_z=float(
                prominence_z
            ),
            slope_z=float(slope_z),
            curvature_z=float(
                curvature_z
            ),
            polarity=int(polarity),
        )

    def _timing_score(
        self,
        candidate_t_us: int,
    ) -> float:
        if (
            self.expected_rr_ms <= 0
            or self.last_accepted_t_us == 0
        ):
            return 0.50

        delta_ms = (
            candidate_t_us
            - self.last_accepted_t_us
        ) / 1000.0

        phase = (
            delta_ms
            / self.expected_rr_ms
        )

        sigma = 0.24
        z = (
            phase - 1.0
        ) / sigma

        return math.exp(
            -0.5 * z * z
        )

    def _detect_candidate(
        self,
        current_slope: float,
    ) -> AdaptiveCandidate | None:
        if (
            not self.has_previous
            or self.signal_stats.count < 48
            or self.slope_stats.count < 48
        ):
            return None

        is_maximum = (
            self.previous_slope > 0
            and current_slope <= 0
        )
        is_minimum = (
            self.previous_slope < 0
            and current_slope >= 0
        )

        if (
            not is_maximum
            and not is_minimum
        ):
            return None

        candidate = self._morphology_features(
            seq=self.previous_seq,
            t_us=self.previous_t_us,
            value=self.previous_value,
            polarity=(
                1
                if is_maximum
                else -1
            ),
        )

        if (
            candidate.morphology_score
            < (
                0.20
                * self.score_threshold_scale
            )
        ):
            return None

        return candidate

    def _push_candidate(
        self,
        candidate: AdaptiveCandidate,
    ) -> None:
        self.candidate_pool.append(
            candidate
        )

        if (
            len(self.candidate_pool)
            > self.CANDIDATE_CAPACITY
        ):
            self.candidate_pool.sort(
                key=lambda item: (
                    item.combined_score,
                    item.t_us,
                ),
                reverse=True,
            )
            del self.candidate_pool[
                self.CANDIDATE_CAPACITY:
            ]

    def _prune_candidates(
        self,
        now_us: int,
    ) -> None:
        minimum_t_us = (
            int(now_us)
            - 2_200_000
        )

        self.candidate_pool = [
            candidate
            for candidate in self.candidate_pool
            if candidate.t_us
            >= minimum_t_us
        ]

    def _estimate_autocorrelation(
        self,
    ) -> tuple[float, float] | None:
        count = len(
            self.signal_points
        )

        if (
            count
            < int(
                self.sample_rate_hz
                * 1.7
            )
        ):
            return None

        values = np.asarray(
            [
                point[2]
                for point in self.signal_points
            ],
            dtype=np.float64,
        )

        if values.size > 256:
            values = values[-256:]

        values = (
            values
            - np.mean(values)
        )

        min_lag = max(
            int(
                self.sample_rate_hz
                * 60.0
                / 220.0
            ),
            2,
        )

        max_lag = min(
            int(
                self.sample_rate_hz
                * 60.0
                / 40.0
            ),
            values.size - 8,
        )

        if min_lag >= max_lag:
            return None

        correlations: dict[
            int,
            float,
        ] = {}

        global_best_corr = -1.0
        global_best_lag = 0

        for lag in range(
            min_lag,
            max_lag + 1,
        ):
            a = values[lag:]
            b = values[:-lag]

            denominator = math.sqrt(
                float(np.dot(a, a))
                * float(np.dot(b, b))
            )

            if denominator <= 1e-9:
                continue

            corr = float(
                np.dot(a, b)
                / denominator
            )

            correlations[lag] = corr

            if corr > global_best_corr:
                global_best_corr = corr
                global_best_lag = lag

        if (
            global_best_lag == 0
            or global_best_corr < 0.12
        ):
            return None

        strong_threshold = (
            global_best_corr
            * 0.90
        )

        selected_lag = (
            global_best_lag
        )
        selected_corr = (
            global_best_corr
        )

        # 在“接近全局最强”的局部相关峰里选择最早一个，
        # 避免 333ms 的真实周期被 666/999ms 谐波抢走。
        for lag in range(
            min_lag + 1,
            max_lag,
        ):
            if (
                lag - 1
                not in correlations
                or lag
                not in correlations
                or lag + 1
                not in correlations
            ):
                continue

            current = correlations[
                lag
            ]

            local_peak = (
                current
                >= correlations[
                    lag - 1
                ]
                and current
                >= correlations[
                    lag + 1
                ]
            )

            if (
                local_peak
                and current
                >= strong_threshold
                and current >= 0.18
            ):
                selected_lag = lag
                selected_corr = current
                break

        period_ms = (
            selected_lag
            * self.sample_period_ms
        )

        confidence = (
            self._clamp01(
                (selected_corr - 0.10)
                / 0.75
            )
        )

        return (
            float(period_ms),
            float(confidence),
        )

    def _update_expected_rr(
        self,
    ) -> None:
        rr_median = (
            float(
                np.median(
                    np.asarray(
                        self.rr_history,
                        dtype=float,
                    )
                )
            )
            if self.rr_history
            else 0.0
        )

        if (
            len(self.rr_history) >= 3
            and rr_median > 0
        ):
            expected = rr_median

            if (
                self.autocorr_confidence
                >= 0.35
                and self.autocorr_rr_ms
                > 0
            ):
                rr_values = np.asarray(
                    self.rr_history,
                    dtype=float,
                )

                rr_mad = float(
                    np.median(
                        np.abs(
                            rr_values
                            - rr_median
                        )
                    )
                )

                robust_variability = (
                    1.4826
                    * rr_mad
                    / rr_median
                    if rr_median > 0
                    else 0.0
                )

                ratio = (
                    rr_median
                    / self.autocorr_rr_ms
                )

                if (
                    self.autocorr_confidence
                    >= 0.50
                    and (
                        ratio < 0.82
                        or ratio > 1.22
                        or robust_variability
                        > 0.14
                    )
                ):
                    expected = (
                        self.autocorr_rr_ms
                    )

                elif (
                    ratio > 1.55
                    or ratio < 0.65
                ):
                    expected = (
                        self.autocorr_rr_ms
                    )

                else:
                    expected = (
                        0.55 * rr_median
                        + 0.45
                        * self.autocorr_rr_ms
                    )

            self.expected_rr_ms = float(
                expected
            )
            return

        if (
            self.autocorr_confidence
            >= 0.20
            and self.autocorr_rr_ms
            > 0
        ):
            self.expected_rr_ms = float(
                self.autocorr_rr_ms
            )

    def _maybe_update_autocorr(
        self,
    ) -> None:
        self.samples_since_autocorr += 1

        if (
            self.samples_since_autocorr
            < 16
        ):
            return

        self.samples_since_autocorr = 0

        result = (
            self._estimate_autocorrelation()
        )

        if result is not None:
            (
                self.autocorr_rr_ms,
                self.autocorr_confidence,
            ) = result

        self._update_expected_rr()

    def _select_best_candidate(
        self,
        min_phase: float,
        max_phase: float,
        min_score: float,
    ) -> AdaptiveCandidate | None:
        if (
            self.last_accepted_t_us == 0
            or self.expected_rr_ms <= 0
        ):
            return None

        selected = None
        best_score = -1.0

        for candidate in self.candidate_pool:
            delta_ms = (
                candidate.t_us
                - self.last_accepted_t_us
            ) / 1000.0

            phase = (
                delta_ms
                / self.expected_rr_ms
            )

            if not (
                min_phase
                <= phase
                <= max_phase
            ):
                continue

            timing = self._timing_score(
                candidate.t_us
            )
            combined = self._clamp01(
                0.64
                * candidate.morphology_score
                + 0.36
                * timing
            )

            if (
                combined >= min_score
                and combined > best_score
            ):
                selected = AdaptiveCandidate(
                    seq=candidate.seq,
                    t_us=candidate.t_us,
                    value=candidate.value,
                    morphology_score=(
                        candidate.morphology_score
                    ),
                    timing_score=timing,
                    combined_score=combined,
                    amplitude_z=(
                        candidate.amplitude_z
                    ),
                    prominence_z=(
                        candidate.prominence_z
                    ),
                    slope_z=candidate.slope_z,
                    curvature_z=(
                        candidate.curvature_z
                    ),
                    polarity=(
                        candidate.polarity
                    ),
                )
                best_score = combined

        return selected

    def _bootstrap_candidate(
        self,
    ) -> AdaptiveCandidate | None:
        if (
            self.expected_rr_ms <= 0
            or self.autocorr_confidence < 0.20
            or not self.candidate_pool
            or not self.signal_points
        ):
            return None

        newest_t_us = (
            self.signal_points[-1][1]
        )
        minimum_t_us = (
            newest_t_us
            - int(
                self.expected_rr_ms
                * 1.15
                * 1000
            )
        )

        candidates = [
            candidate
            for candidate in self.candidate_pool
            if candidate.t_us
            >= minimum_t_us
        ]

        if not candidates:
            return None

        selected = max(
            candidates,
            key=lambda item:
                item.morphology_score,
        )

        if (
            selected.morphology_score
            < 0.34
        ):
            return None

        return selected

    def _waveform_rescue(
        self,
        now_us: int,
    ) -> AdaptiveCandidate | None:
        if (
            self.last_accepted_t_us == 0
            or self.expected_rr_ms <= 0
            or len(self.signal_points) < 32
        ):
            return None

        start_us = (
            self.last_accepted_t_us
            + int(
                self.expected_rr_ms
                * 0.58
                * 1000
            )
        )
        end_us = min(
            int(now_us),
            self.last_accepted_t_us
            + int(
                self.expected_rr_ms
                * 1.48
                * 1000
            ),
        )

        signal_mean = (
            self.signal_stats.mean()
        )
        signal_std = (
            self.signal_stats.std(1.0)
        )

        eligible = [
            point
            for point in self.signal_points
            if (
                start_us
                <= point[1]
                <= end_us
            )
        ]

        if not eligible:
            return None

        best = max(
            eligible,
            key=lambda point:
                abs(
                    point[2]
                    - signal_mean
                ),
        )

        best_z = (
            abs(
                best[2]
                - signal_mean
            )
            / signal_std
        )

        if best_z < 0.45:
            return None

        timing = self._timing_score(
            best[1]
        )
        morphology = self._clamp01(
            0.30
            + 0.18 * best_z
        )
        combined = self._clamp01(
            0.45 * morphology
            + 0.55 * timing
        )

        return AdaptiveCandidate(
            seq=int(best[0]),
            t_us=int(best[1]),
            value=float(best[2]),
            morphology_score=morphology,
            timing_score=timing,
            combined_score=combined,
            amplitude_z=best_z,
            prominence_z=best_z,
            slope_z=0.0,
            curvature_z=0.0,
            polarity=(
                1
                if best[2] >= signal_mean
                else -1
            ),
        )

    def _accept(
        self,
        selected: AdaptiveCandidate,
        rescued: bool,
        signal_score: float,
    ) -> AdaptiveEvent:
        first = (
            self.last_accepted_t_us == 0
        )

        if first:
            rr_ms = 0.0
        else:
            rr_ms = (
                selected.t_us
                - self.last_accepted_t_us
            ) / 1000.0

            if (
                220.0
                <= rr_ms
                <= 2000.0
            ):
                self.rr_history.append(
                    rr_ms
                )

        self.last_accepted_t_us = (
            selected.t_us
        )
        self.last_accepted_seq = (
            selected.seq
        )

        self.accepted_count += 1

        if rescued:
            self.rescue_count += 1

        self._update_expected_rr()

        if self.rr_history:
            median_rr = float(
                np.median(
                    np.asarray(
                        self.rr_history,
                        dtype=float,
                    )
                )
            )

            if median_rr > 0:
                self.current_hr_bpm = (
                    60000.0
                    / median_rr
                )

        self.candidate_pool.clear()

        return AdaptiveEvent(
            accepted=True,
            rescued=bool(rescued),
            first=bool(first),
            accepted_seq=selected.seq,
            accepted_t_us=selected.t_us,
            rr_ms=float(rr_ms),
            hr_bpm=float(
                self.current_hr_bpm
            ),
            signal_score=float(
                signal_score
            ),
            accepted_score=float(
                selected.combined_score
            ),
            expected_rr_ms=float(
                self.expected_rr_ms
            ),
        )

    def update(
        self,
        seq: int,
        t_us: int,
        filtered: float,
        wear: bool,
    ) -> AdaptiveEvent:
        if not wear:
            self.reset()
            return AdaptiveEvent()

        seq = int(seq)
        t_us = int(t_us)
        filtered = float(filtered)

        slope = (
            filtered
            - self.previous_value
            if self.has_previous
            else 0.0
        )

        signal_score = (
            self._signal_score(
                filtered,
                slope,
            )
        )

        self.signal_stats.push(
            filtered
        )
        self.slope_stats.push(
            slope
        )
        self.signal_points.append(
            (
                seq,
                t_us,
                filtered,
                slope,
            )
        )

        self._maybe_update_autocorr()
        self._prune_candidates(
            t_us
        )

        event = AdaptiveEvent(
            signal_score=signal_score,
            expected_rr_ms=(
                self.expected_rr_ms
            ),
        )

        candidate = (
            self._detect_candidate(
                slope
            )
        )

        if candidate is not None:
            self.candidate_count += 1
            self._push_candidate(
                candidate
            )

            event.candidate = True
            event.candidate_seq = (
                candidate.seq
            )
            event.candidate_t_us = (
                candidate.t_us
            )

        accepted: AdaptiveEvent | None = None

        if (
            self.last_accepted_t_us == 0
            and self.expected_rr_ms > 0
        ):
            bootstrap = (
                self._bootstrap_candidate()
            )

            if bootstrap is not None:
                accepted = self._accept(
                    bootstrap,
                    rescued=False,
                    signal_score=signal_score,
                )

        elif (
            self.last_accepted_t_us != 0
            and self.expected_rr_ms > 0
        ):
            elapsed_ms = (
                t_us
                - self.last_accepted_t_us
            ) / 1000.0

            phase = (
                elapsed_ms
                / self.expected_rr_ms
            )

            selected = None

            if phase >= 1.06:
                selected = (
                    self._select_best_candidate(
                        0.55,
                        1.38,
                        0.38
                        * self.score_threshold_scale,
                    )
                )

                if selected is not None:
                    accepted = self._accept(
                        selected,
                        rescued=False,
                        signal_score=signal_score,
                    )

            if (
                accepted is None
                and phase >= 1.35
            ):
                selected = (
                    self._select_best_candidate(
                        0.50,
                        1.50,
                        0.20
                        * self.score_threshold_scale,
                    )
                )

                if selected is not None:
                    accepted = self._accept(
                        selected,
                        rescued=True,
                        signal_score=signal_score,
                    )

            if (
                accepted is None
                and phase >= 1.58
            ):
                rescue = (
                    self._waveform_rescue(
                        t_us
                    )
                )

                if rescue is not None:
                    accepted = self._accept(
                        rescue,
                        rescued=True,
                        signal_score=signal_score,
                    )

        # 更新 previous 必须在 extremum 检测之后。
        self.has_previous = True
        self.previous_value = filtered
        self.previous_slope = slope
        self.previous_seq = seq
        self.previous_t_us = t_us

        if accepted is not None:
            accepted.candidate = (
                event.candidate
            )
            accepted.candidate_seq = (
                event.candidate_seq
            )
            accepted.candidate_t_us = (
                event.candidate_t_us
            )
            return accepted

        return event
