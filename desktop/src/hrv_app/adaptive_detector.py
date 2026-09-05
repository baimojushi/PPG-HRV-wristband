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

    # v0.3.1：Accepted Beat 锁定到同一极性，防止一个 PPG 周期
    # 的局部最大值和局部最小值被交替计成两个心搏。
    accepted_polarity: int = 0
    locked_polarity: int = 0

    # v0.3.4 独立节律相位 Debug。
    predicted_beat_t_us: int = 0
    phase_error_ms: float = 0.0


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

    CANDIDATE_CLUSTER_MIN_MS = 80.0
    CANDIDATE_CLUSTER_MAX_MS = 180.0
    CANDIDATE_CLUSTER_RR_RATIO = 0.28

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

        # v0.3.4：周期相位与 Accepted fiducial 解耦。
        self.predicted_beat_t_us = 0
        self.last_phase_error_ms = 0.0

        # 0=尚未锁定，+1=局部最大值，-1=局部最小值。
        # 第一个稳定 Winner 决定本段佩戴区间的心搏极性。
        self.locked_polarity = 0

        self.expected_rr_ms = 0.0
        self.autocorr_rr_ms = 0.0
        self.autocorr_confidence = 0.0
        # v0.3.2：与固件一致的固定预算增量自相关。
        self.autocorr_scan_values: dict[int, float] = {}
        self.autocorr_scan_min_lag = 0
        self.autocorr_scan_max_lag = 0
        self.autocorr_scan_lag = 0
        self.autocorr_scan_active = False

        self.autocorr_lags_per_update = 4
        self.autocorr_max_pairs_per_lag = 96

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
        # v0.3.5：
        # Candidate 池的保留优先级更多看形态，时间只做弱上下文。
        # 避免“次级同极性峰刚好更接近预测时刻”把主峰挤出候选池。
        combined = self._clamp01(
            0.86 * morphology_score
            + 0.14 * timing
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

    def _phase_for_time(
        self,
        t_us: int,
    ) -> float:
        if self.expected_rr_ms <= 0:
            return 0.0

        if self.predicted_beat_t_us != 0:
            error_ms = (
                int(t_us)
                - self.predicted_beat_t_us
            ) / 1000.0

            return (
                1.0
                + error_ms
                / self.expected_rr_ms
            )

        if self.last_accepted_t_us != 0:
            return (
                (int(t_us) - self.last_accepted_t_us)
                / 1000.0
                / self.expected_rr_ms
            )

        return 0.0

    def _timing_score(
        self,
        candidate_t_us: int,
    ) -> float:
        if (
            self.expected_rr_ms <= 0
            or (
                self.predicted_beat_t_us == 0
                and self.last_accepted_t_us == 0
            )
        ):
            return 0.50

        phase = self._phase_for_time(
            candidate_t_us
        )

        sigma = 0.24
        z = (
            phase - 1.0
        ) / sigma

        return math.exp(
            -0.5 * z * z
        )

    def _candidate_cluster_window_ms(
        self,
    ) -> float:
        if self.expected_rr_ms <= 0:
            return 120.0

        return float(
            np.clip(
                self.expected_rr_ms
                * self.CANDIDATE_CLUSTER_RR_RATIO,
                self.CANDIDATE_CLUSTER_MIN_MS,
                self.CANDIDATE_CLUSTER_MAX_MS,
            )
        )

    @staticmethod
    def _prefer_cluster_representative(
        current: AdaptiveCandidate,
        incoming: AdaptiveCandidate,
    ) -> bool:
        value_margin = 0.5

        if incoming.polarity > 0:
            if incoming.value > current.value + value_margin:
                return True
        else:
            if incoming.value < current.value - value_margin:
                return True

        if (
            abs(incoming.value - current.value)
            <= value_margin
            and incoming.morphology_score
            > current.morphology_score
        ):
            return True

        return False

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
        # 同一宽峰内的同极性微小局部极值先合并成一个 Peak Complex。
        cluster_window_ms = (
            self._candidate_cluster_window_ms()
        )

        for index, current in enumerate(
            self.candidate_pool
        ):
            if (
                current.polarity
                != candidate.polarity
            ):
                continue

            distance_ms = abs(
                candidate.t_us
                - current.t_us
            ) / 1000.0

            if distance_ms > cluster_window_ms:
                continue

            if self._prefer_cluster_representative(
                current,
                candidate,
            ):
                self.candidate_pool[index] = candidate

            return

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

    def _start_autocorrelation_scan(
        self,
    ) -> bool:
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
            191,
        )

        # 与固件一致：最长 lag 后还要保留至少 32 对重叠样本。
        if (
            len(self.signal_points)
            < max_lag + 32
        ):
            return False

        self.autocorr_scan_values.clear()
        self.autocorr_scan_min_lag = min_lag
        self.autocorr_scan_max_lag = max_lag
        self.autocorr_scan_lag = min_lag
        self.autocorr_scan_active = True

        return True

    def _compute_autocorrelation_lag(
        self,
        lag: int,
    ) -> float | None:
        count = len(
            self.signal_points
        )

        if (
            lag <= 0
            or lag >= count
        ):
            return None

        pair_count = min(
            count - lag,
            self.autocorr_max_pairs_per_lag,
        )

        if pair_count < 32:
            return None

        values = np.asarray(
            [
                point[2]
                for point
                in list(self.signal_points)[
                    -(
                        pair_count
                        + lag
                    ):
                ]
            ],
            dtype=np.float64,
        )

        if (
            values.size
            < pair_count + lag
        ):
            return None

        mean = (
            self.signal_stats.mean()
        )

        a = (
            values[-pair_count:]
            - mean
        )
        b = (
            values[
                -pair_count - lag:
                -lag
            ]
            - mean
        )

        denominator = math.sqrt(
            float(np.dot(a, a))
            * float(np.dot(b, b))
        )

        if denominator <= 1e-9:
            return None

        corr = float(
            np.dot(a, b)
            / denominator
        )

        return (
            corr
            if np.isfinite(corr)
            else None
        )

    def _finalize_autocorrelation_scan(
        self,
    ) -> tuple[float, float] | None:
        if not self.autocorr_scan_values:
            return None

        valid = {
            lag: corr
            for lag, corr
            in self.autocorr_scan_values.items()
            if np.isfinite(corr)
        }

        if not valid:
            return None

        global_best_lag = max(
            valid,
            key=valid.get,
        )
        global_best_corr = valid[
            global_best_lag
        ]

        if global_best_corr < 0.12:
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

        for lag in range(
            self.autocorr_scan_min_lag + 1,
            self.autocorr_scan_max_lag,
        ):
            if (
                lag - 1 not in valid
                or lag not in valid
                or lag + 1 not in valid
            ):
                continue

            current = valid[lag]

            local_peak = (
                current >= valid[lag - 1]
                and current >= valid[lag + 1]
            )

            if (
                local_peak
                and current >= strong_threshold
                and current >= 0.18
            ):
                selected_lag = lag
                selected_corr = current
                break

        period_ms = (
            selected_lag
            * self.sample_period_ms
        )

        confidence = self._clamp01(
            (selected_corr - 0.10)
            / 0.75
        )

        return (
            float(period_ms),
            float(confidence),
        )

    def _update_expected_rr(
        self,
    ) -> None:
        rr_values = np.asarray(
            self.rr_history,
            dtype=float,
        )

        rr_median = (
            float(np.median(rr_values))
            if rr_values.size
            else 0.0
        )

        # v0.3.1：
        # Accepted Beat 已被“同极性锁”约束后，连续 RR 的可信度明显高于
        # 单纯波形自相关。实测 v0.3.0 的自相关曾锁到约 464 ms，
        # 同时局部最大值/最小值交替生成约 350 ms RR，形成 2:1 误计数。
        #
        # 一旦得到至少两个同极性 RR，并且它们本身足够稳定，
        # 直接让 RR 中位数成为主节律锚点；自相关只在两者接近时参与平滑。
        if (
            rr_values.size >= 2
            and rr_median > 0
        ):
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
                else 1.0
            )

            if robust_variability <= 0.20:
                expected = rr_median

                if (
                    self.autocorr_confidence
                    >= 0.35
                    and self.autocorr_rr_ms
                    > 0
                ):
                    ratio = (
                        self.autocorr_rr_ms
                        / rr_median
                    )

                    # 两个来源一致时轻度融合；差异明显时避免错误自相关
                    # 把已经稳定的同极性 RR 拉回伪周期。
                    if 0.82 <= ratio <= 1.22:
                        expected = (
                            0.80 * rr_median
                            + 0.20
                            * self.autocorr_rr_ms
                        )

                self.expected_rr_ms = float(
                    expected
                )
                return

        # 启动阶段或 RR 尚不稳定时，自相关仍负责给出初始时间尺度。
        if (
            self.autocorr_confidence
            >= 0.20
            and self.autocorr_rr_ms
            > 0
        ):
            self.expected_rr_ms = float(
                self.autocorr_rr_ms
            )
        elif rr_median > 0:
            self.expected_rr_ms = float(
                rr_median
            )

    def _maybe_update_autocorr(
        self,
    ) -> None:
        # 每个采样只处理固定数量的 lag。
        # 这和固件的 CPU 预算策略保持一致。
        if not self.autocorr_scan_active:
            if not self._start_autocorrelation_scan():
                return

        for _ in range(
            self.autocorr_lags_per_update
        ):
            if (
                not self.autocorr_scan_active
                or self.autocorr_scan_lag
                > self.autocorr_scan_max_lag
            ):
                break

            lag = (
                self.autocorr_scan_lag
            )

            corr = (
                self._compute_autocorrelation_lag(
                    lag
                )
            )

            if corr is not None:
                self.autocorr_scan_values[
                    lag
                ] = corr

            self.autocorr_scan_lag += 1

            if (
                self.autocorr_scan_lag
                > self.autocorr_scan_max_lag
            ):
                result = (
                    self._finalize_autocorrelation_scan()
                )

                if result is not None:
                    (
                        self.autocorr_rr_ms,
                        self.autocorr_confidence,
                    ) = result

                self.autocorr_scan_active = False
                self._update_expected_rr()
                break

    def _select_best_candidate(
        self,
        min_phase: float,
        max_phase: float,
        min_score: float,
    ) -> AdaptiveCandidate | None:
        if (
            (
                self.predicted_beat_t_us == 0
                and self.last_accepted_t_us == 0
            )
            or self.expected_rr_ms <= 0
        ):
            return None

        selected = None
        best_score = -1.0

        for candidate in self.candidate_pool:
            if (
                self.locked_polarity != 0
                and candidate.polarity
                != self.locked_polarity
            ):
                continue

            phase = self._phase_for_time(
                candidate.t_us
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
            # v0.3.5：
            # 实测错相位 Winner 平均分约 0.63，主峰约 0.85。
            # 周期内已经有足够未来上下文后，主峰形态应成为第一裁判。
            combined = self._clamp01(
                0.90
                * candidate.morphology_score
                + 0.10
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
            self.predicted_beat_t_us == 0
            or self.expected_rr_ms <= 0
            or len(self.signal_points) < 32
        ):
            return None

        start_us = (
            self.predicted_beat_t_us
            - int(
                self.expected_rr_ms
                * 0.32
                * 1000
            )
        )
        end_us = min(
            int(now_us),
            self.predicted_beat_t_us
            + int(
                self.expected_rr_ms
                * 1.20
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

        # v0.3.1：Rescue 也必须服从已锁定极性。
        # 否则常规 Candidate 虽然过滤了谷值，Rescue 仍可能把谷值重新捞回来。
        if self.locked_polarity > 0:
            best = max(
                eligible,
                key=lambda point:
                    point[2] - signal_mean,
            )
            best_z = (
                best[2] - signal_mean
            ) / signal_std

        elif self.locked_polarity < 0:
            best = min(
                eligible,
                key=lambda point:
                    point[2] - signal_mean,
            )
            best_z = (
                signal_mean - best[2]
            ) / signal_std

        else:
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
                self.locked_polarity
                if self.locked_polarity != 0
                else (
                    1
                    if best[2] >= signal_mean
                    else -1
                )
            ),
        )

    def _update_phase_tracker_after_accept(
        self,
        accepted_t_us: int,
        first: bool,
    ) -> None:
        if self.expected_rr_ms <= 0:
            self.predicted_beat_t_us = 0
            self.last_phase_error_ms = 0.0
            return

        rr_us = int(
            round(
                self.expected_rr_ms
                * 1000.0
            )
        )

        if (
            first
            or self.predicted_beat_t_us == 0
        ):
            self.predicted_beat_t_us = (
                int(accepted_t_us)
                + rr_us
            )
            self.last_phase_error_ms = 0.0
            return

        target_t_us = int(
            self.predicted_beat_t_us
        )
        phase_error_ms = (
            int(accepted_t_us)
            - target_t_us
        ) / 1000.0

        self.last_phase_error_ms = float(
            phase_error_ms
        )

        correction_us = 0

        if (
            abs(phase_error_ms)
            <= self.expected_rr_ms * 0.45
        ):
            bounded = float(
                np.clip(
                    phase_error_ms,
                    -40.0,
                    40.0,
                )
            )
            correction_us = int(
                round(
                    bounded
                    * 0.22
                    * 1000.0
                )
            )

        next_target = (
            target_t_us
            + rr_us
        )
        guard_us = int(
            round(
                self.expected_rr_ms
                * 0.35
                * 1000.0
            )
        )

        skipped_cycles = 0

        while (
            next_target
            <= int(accepted_t_us) + guard_us
            and skipped_cycles < 3
        ):
            next_target += rr_us
            skipped_cycles += 1

        self.predicted_beat_t_us = (
            next_target
            + correction_us
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

        if self.locked_polarity == 0:
            self.locked_polarity = int(
                selected.polarity
            )

        # 安全保护：常规路径不会把异极性 Candidate 送到这里。
        if (
            selected.polarity
            != self.locked_polarity
        ):
            return AdaptiveEvent(
                signal_score=float(
                    signal_score
                ),
                expected_rr_ms=float(
                    self.expected_rr_ms
                ),
                locked_polarity=int(
                    self.locked_polarity
                ),
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
        self._update_phase_tracker_after_accept(
            selected.t_us,
            first,
        )

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
            accepted_polarity=int(
                selected.polarity
            ),
            locked_polarity=int(
                self.locked_polarity
            ),
            predicted_beat_t_us=int(
                self.predicted_beat_t_us
            ),
            phase_error_ms=float(
                self.last_phase_error_ms
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
            locked_polarity=int(
                self.locked_polarity
            ),
            predicted_beat_t_us=int(
                self.predicted_beat_t_us
            ),
            phase_error_ms=float(
                self.last_phase_error_ms
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
            self.predicted_beat_t_us != 0
            and self.expected_rr_ms > 0
        ):
            phase = self._phase_for_time(
                t_us
            )

            selected = None

            # v0.3.5：
            # 不在预测中心刚过 6% 就立即做决定。
            # 额外等待约 0.40×RR，让同周期后面的真实主峰有机会进入 Candidate Pool。
            if phase >= 1.40:
                selected = (
                    self._select_best_candidate(
                        0.72,
                        1.55,
                        0.50
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
                and phase >= 1.50
            ):
                selected = (
                    self._select_best_candidate(
                        0.72,
                        2.20,
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
                and phase >= 1.65
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
