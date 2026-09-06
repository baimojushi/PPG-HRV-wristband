from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence
import math

import numpy as np
from scipy import signal

from .config import AnalysisConfig
from .models import BeatFrame, SampleFrame


@dataclass(slots=True)
class WaveformPeakProposal:
    """
    由完整 PPG 波形直接解析出的正式心搏候选。

    这不是 Firmware Candidate 的二次分类：
    - 可以匹配到固件 Beat；
    - 也可以在固件漏检时独立产生正式心搏。
    """

    seq: int
    t_us: int
    waveform_score: float
    timing_uncertainty_ms: float
    reference_rr_ms: float
    polarity: int

    matched_firmware_t_us: int = 0
    matched_firmware_score: float = 0.0
    matched_firmware_flags: int = 0
    inserted_by_smoother: bool = False
    low_prominence_rescue: bool = False


@dataclass(slots=True)
class CorrectorDiagnostics:
    reference_rr_ms: float = 0.0
    autocorr_confidence: float = 0.0
    polarity: int = 1
    candidate_count: int = 0
    selected_count: int = 0
    inserted_count: int = 0
    firmware_matched_count: int = 0
    waveform_amplitude: float = 0.0
    commit_until_t_us: int = 0
    latest_sample_t_us: int = 0


class FixedLagWaveformCorrector:
    """
    v0.3.7 固定滞后波形复核器。

    核心原则：
    1. 正式 HRV 时间线直接从 PPG 波形解析；
    2. 固件 Accepted 只作为诊断 / 匹配证据；
    3. 使用未来约 7.25 s 的完整 PPG 来解决漏检、重复峰和相位分支；
    4. 周期模型只决定“搜索尺度”，最终时间必须落在真实 PPG 局部波顶；
    5. 不把预测 RR 硬写成等间隔时间轴。

    当前实现是确定性数学基线，未来可以把 `_select_waveform_peaks()`
    换成视觉 Transformer / 一维时序模型，而 Engine / HRV / 导出接口不变。
    """

    def __init__(
        self,
        config: AnalysisConfig | None = None,
    ):
        self.config = config or AnalysisConfig()
        self.last_diagnostics = CorrectorDiagnostics()

    def reset(self) -> None:
        self.last_diagnostics = CorrectorDiagnostics()

    @staticmethod
    def _triangular_smooth(
        values: np.ndarray,
    ) -> np.ndarray:
        if values.size < 5:
            return values.astype(
                float,
                copy=True,
            )

        kernel = np.asarray(
            [1.0, 2.0, 3.0, 2.0, 1.0],
            dtype=float,
        )
        kernel /= float(
            np.sum(kernel)
        )

        return np.convolve(
            values,
            kernel,
            mode="same",
        )

    @staticmethod
    def _infer_polarity(
        values: np.ndarray,
    ) -> int:
        if values.size < 8:
            return 1

        median = float(
            np.median(values)
        )
        positive = float(
            np.percentile(
                values,
                95,
            )
            - median
        )
        negative = float(
            median
            - np.percentile(
                values,
                5,
            )
        )

        return (
            1
            if positive >= negative
            else -1
        )

    def _autocorr_rr(
        self,
        values: np.ndarray,
        sample_rate_hz: float,
        prior_rr_ms: float | None,
    ) -> tuple[float, float]:
        """
        用整段波形的自相关估计主周期。

        8 秒未来窗口的价值之一，就是这里不再只依赖上一搏：
        一个局部错误峰不会立刻把 reference RR 拉走。
        """
        if values.size < int(
            round(
                sample_rate_hz
                * 3.0
            )
        ):
            return (
                float(
                    prior_rr_ms
                    if prior_rr_ms is not None
                    else 800.0
                ),
                0.0,
            )

        smooth = self._triangular_smooth(
            values
        )

        baseline_window = max(
            5,
            int(
                round(
                    sample_rate_hz
                    * 1.60
                )
            ),
        )

        baseline = np.convolve(
            smooth,
            np.ones(
                baseline_window,
                dtype=float,
            )
            / baseline_window,
            mode="same",
        )

        centered = (
            smooth
            - baseline
        )
        centered -= float(
            np.mean(centered)
        )

        energy = float(
            np.dot(
                centered,
                centered,
            )
        )

        if energy <= 1e-9:
            return (
                float(
                    prior_rr_ms
                    if prior_rr_ms is not None
                    else 800.0
                ),
                0.0,
            )

        autocorr = signal.correlate(
            centered,
            centered,
            mode="full",
            method="fft",
        )[
            centered.size - 1:
        ]

        overlap = np.arange(
            centered.size,
            0,
            -1,
            dtype=float,
        )
        autocorr = (
            autocorr
            / np.maximum(
                overlap,
                1.0,
            )
        )

        if autocorr[0] <= 1e-9:
            return (
                float(
                    prior_rr_ms
                    if prior_rr_ms is not None
                    else 800.0
                ),
                0.0,
            )

        autocorr = (
            autocorr
            / autocorr[0]
        )

        min_rr_ms = float(
            self.config.waveform_min_rr_ms
        )
        max_rr_ms = float(
            self.config.waveform_max_rr_ms
        )

        min_lag = max(
            1,
            int(
                round(
                    sample_rate_hz
                    * min_rr_ms
                    / 1000.0
                )
            ),
        )
        max_lag = min(
            autocorr.size - 1,
            int(
                round(
                    sample_rate_hz
                    * max_rr_ms
                    / 1000.0
                )
            ),
        )

        if max_lag <= min_lag:
            return (
                float(
                    prior_rr_ms
                    if prior_rr_ms is not None
                    else 800.0
                ),
                0.0,
            )

        segment = autocorr[
            min_lag:
            max_lag + 1
        ]

        peaks, _ = signal.find_peaks(
            segment,
            distance=max(
                1,
                int(
                    round(
                        sample_rate_hz
                        * 0.16
                    )
                ),
            ),
        )

        if peaks.size:
            values_at_peaks = (
                segment[
                    peaks
                ]
            )
            maximum = float(
                np.max(
                    values_at_peaks
                )
            )

            # Harmonic guard：
            # 在接近最大相关峰的候选中优先较短 lag，降低误选 2×RR。
            eligible = peaks[
                values_at_peaks
                >= maximum * 0.86
            ]

            local_index = int(
                eligible[0]
                if eligible.size
                else peaks[
                    int(
                        np.argmax(
                            values_at_peaks
                        )
                    )
                ]
            )
        else:
            local_index = int(
                np.argmax(
                    segment
                )
            )

        lag = (
            min_lag
            + local_index
        )

        rr_ms = float(
            lag
            / sample_rate_hz
            * 1000.0
        )

        confidence = float(
            np.clip(
                segment[
                    local_index
                ],
                0.0,
                1.0,
            )
        )

        if (
            prior_rr_ms is not None
            and np.isfinite(
                prior_rr_ms
            )
            and prior_rr_ms > 0
        ):
            prior = float(
                prior_rr_ms
            )

            # 检查自相关的 1/2 和 2 倍谐波。
            harmonic_options = [
                candidate
                for candidate in (
                    rr_ms,
                    rr_ms * 0.5,
                    rr_ms * 2.0,
                )
                if (
                    min_rr_ms
                    <= candidate
                    <= max_rr_ms
                )
            ]

            if harmonic_options:
                closest = min(
                    harmonic_options,
                    key=lambda candidate:
                        abs(
                            math.log(
                                candidate
                                / prior
                            )
                        ),
                )

                if (
                    confidence < 0.82
                    and abs(
                        math.log(
                            closest
                            / prior
                        )
                    )
                    < abs(
                        math.log(
                            rr_ms
                            / prior
                        )
                    )
                ):
                    rr_ms = float(
                        closest
                    )

            # 相邻窗口节律一致时轻量融合。
            # 差异明显时让完整波形自相关自己决定，避免旧状态拖住新心率。
            relative = abs(
                rr_ms
                - prior
            ) / max(
                prior,
                1.0,
            )

            if relative <= 0.25:
                rr_ms = float(
                    0.68
                    * rr_ms
                    + 0.32
                    * prior
                )

        return (
            float(
                np.clip(
                    rr_ms,
                    min_rr_ms,
                    max_rr_ms,
                )
            ),
            confidence,
        )

    @staticmethod
    def _quadratic_peak_time(
        t_us: np.ndarray,
        values: np.ndarray,
        index: int,
    ) -> int:
        """
        对离散局部最大值做三点抛物线细化。

        125 Hz 的原始采样间隔约 8 ms；
        这里最多只做 ±0.5 Sample 的局部插值，
        不允许跨波形周期移动。
        """
        if (
            index <= 0
            or index
            >= values.size - 1
        ):
            return int(
                t_us[index]
            )

        y0 = float(
            values[
                index - 1
            ]
        )
        y1 = float(
            values[
                index
            ]
        )
        y2 = float(
            values[
                index + 1
            ]
        )

        denominator = (
            y0
            - 2.0
            * y1
            + y2
        )

        if abs(
            denominator
        ) <= 1e-9:
            return int(
                t_us[index]
            )

        delta = 0.5 * (
            y0
            - y2
        ) / denominator

        delta = float(
            np.clip(
                delta,
                -0.5,
                0.5,
            )
        )

        dt_us = float(
            np.median(
                np.diff(
                    t_us.astype(
                        float
                    )
                )
            )
        )

        return int(
            round(
                float(
                    t_us[index]
                )
                + delta
                * dt_us
            )
        )

    def _select_waveform_peaks(
        self,
        t_us: np.ndarray,
        filtered: np.ndarray,
        sample_rate_hz: float,
        prior_rr_ms: float | None,
        last_committed_t_us: int,
    ) -> tuple[
        list[tuple[int, float, bool]],
        float,
        float,
        int,
        float,
    ]:
        """
        返回：
        [(peak_index, waveform_score, low_prominence_rescue), ...],
        reference_rr_ms,
        autocorr_confidence,
        polarity,
        robust_amplitude
        """
        if (
            t_us.size < 16
            or filtered.size
            != t_us.size
        ):
            return (
                [],
                float(
                    prior_rr_ms
                    if prior_rr_ms is not None
                    else 800.0
                ),
                0.0,
                1,
                0.0,
            )

        smooth = self._triangular_smooth(
            filtered
        )

        polarity = self._infer_polarity(
            smooth
        )
        signal_values = (
            smooth
            * polarity
        )

        reference_rr_ms, autocorr_confidence = (
            self._autocorr_rr(
                signal_values,
                sample_rate_hz,
                prior_rr_ms,
            )
        )

        robust_amplitude = max(
            float(
                np.percentile(
                    signal_values,
                    95,
                )
                - np.percentile(
                    signal_values,
                    5,
                )
            ),
            8.0,
        )

        normal_prominence = max(
            float(
                self.config.waveform_min_prominence_abs
            ),
            robust_amplitude
            * self.config.waveform_prominence_ratio,
        )

        minimum_distance_s = float(
            np.clip(
                reference_rr_ms
                / 1000.0
                * self.config.waveform_peak_distance_rr_ratio,
                self.config.waveform_peak_distance_min_s,
                self.config.waveform_peak_distance_max_s,
            )
        )

        peak_indices, properties = signal.find_peaks(
            signal_values,
            distance=max(
                1,
                int(
                    round(
                        sample_rate_hz
                        * minimum_distance_s
                    )
                ),
            ),
            prominence=normal_prominence,
        )

        if peak_indices.size == 0:
            return (
                [],
                reference_rr_ms,
                autocorr_confidence,
                polarity,
                robust_amplitude,
            )

        prominences = np.asarray(
            properties[
                "prominences"
            ],
            dtype=float,
        )

        baseline = float(
            np.percentile(
                signal_values,
                20,
            )
        )

        heights = np.maximum(
            signal_values[
                peak_indices
            ]
            - baseline,
            0.0,
        )

        scores = np.clip(
            0.62
            * prominences
            / (
                robust_amplitude
                * 0.42
                + 1e-6
            )
            + 0.38
            * heights
            / (
                robust_amplitude
                * 0.65
                + 1e-6
            ),
            0.0,
            1.0,
        )

        # --------------------------------------------------------------
        # 第一层：短 RR 竞争。
        # --------------------------------------------------------------
        # 同一个视觉主波内部即便有两个同极性极值，
        # 在约半周期以内只保留形态更强的一个。
        keep = list(
            range(
                peak_indices.size
            )
        )

        changed = True

        while (
            changed
            and len(keep) > 1
        ):
            changed = False
            compact: list[int] = []
            position = 0

            while position < len(
                keep
            ):
                if (
                    position + 1
                    < len(keep)
                ):
                    left = keep[
                        position
                    ]
                    right = keep[
                        position + 1
                    ]

                    interval_ms = (
                        int(
                            t_us[
                                peak_indices[
                                    right
                                ]
                            ]
                        )
                        - int(
                            t_us[
                                peak_indices[
                                    left
                                ]
                            ]
                        )
                    ) / 1000.0

                    if (
                        interval_ms
                        < max(
                            self.config.waveform_pair_min_ms,
                            reference_rr_ms
                            * self.config.waveform_short_pair_rr_ratio,
                        )
                    ):
                        compact.append(
                            left
                            if scores[left]
                            >= scores[right]
                            else right
                        )
                        position += 2
                        changed = True
                        continue

                compact.append(
                    keep[
                        position
                    ]
                )
                position += 1

            keep = compact

        selected_indices = [
            int(
                peak_indices[index]
            )
            for index in keep
        ]
        selected_scores = [
            float(
                scores[index]
            )
            for index in keep
        ]
        selected_rescue = [
            False
            for _ in keep
        ]

        # --------------------------------------------------------------
        # 第二层：长 gap 低门限补峰。
        # --------------------------------------------------------------
        # 固件漏检的核心难点是“没有 source Beat 可供修正”。
        # 这里直接从完整 PPG 中寻找被普通 prominence 门漏掉的低幅主波。
        low_prominence = max(
            self.config.waveform_min_prominence_abs
            * 0.60,
            robust_amplitude
            * self.config.waveform_rescue_prominence_ratio,
        )

        low_indices, low_properties = signal.find_peaks(
            signal_values,
            distance=max(
                1,
                int(
                    round(
                        sample_rate_hz
                        * self.config.waveform_rescue_peak_distance_s
                    )
                ),
            ),
            prominence=low_prominence,
        )

        low_prominence_map = {
            int(index): float(
                prominence
            )
            for index, prominence in zip(
                low_indices,
                low_properties[
                    "prominences"
                ],
                strict=False,
            )
        }

        # 使用已提交正式 Beat 作为左侧锚点。
        anchors: list[
            tuple[int, int]
        ] = []

        if last_committed_t_us > 0:
            anchors.append(
                (
                    -1,
                    int(
                        last_committed_t_us
                    ),
                )
            )

        anchors.extend(
            (
                position,
                int(
                    t_us[index]
                ),
            )
            for position, index
            in enumerate(
                selected_indices
            )
        )

        rescue_additions: list[
            tuple[int, float]
        ] = []

        for anchor_index in range(
            len(anchors) - 1
        ):
            left_position, left_t_us = (
                anchors[
                    anchor_index
                ]
            )
            right_position, right_t_us = (
                anchors[
                    anchor_index + 1
                ]
            )

            gap_ms = (
                right_t_us
                - left_t_us
            ) / 1000.0

            if (
                gap_ms
                <= reference_rr_ms
                * self.config.waveform_long_gap_trigger_ratio
            ):
                continue

            cycles = int(
                round(
                    gap_ms
                    / max(
                        reference_rr_ms,
                        1.0,
                    )
                )
            )

            if not (
                2
                <= cycles
                <= self.config.waveform_rescue_max_cycles
            ):
                continue

            step_us = (
                right_t_us
                - left_t_us
            ) / cycles

            for cycle in range(
                1,
                cycles
            ):
                expected_t_us = int(
                    round(
                        left_t_us
                        + step_us
                        * cycle
                    )
                )

                radius_us = int(
                    round(
                        reference_rr_ms
                        * self.config.waveform_rescue_search_rr_ratio
                        * 1000.0
                    )
                )

                candidates = [
                    int(index)
                    for index in low_indices
                    if (
                        abs(
                            int(
                                t_us[
                                    int(index)
                                ]
                            )
                            - expected_t_us
                        )
                        <= radius_us
                        and int(index)
                        not in selected_indices
                    )
                ]

                if not candidates:
                    continue

                def candidate_quality(
                    candidate_index: int,
                ) -> float:
                    prominence = (
                        low_prominence_map.get(
                            candidate_index,
                            0.0,
                        )
                    )

                    time_error = abs(
                        int(
                            t_us[
                                candidate_index
                            ]
                        )
                        - expected_t_us
                    ) / max(
                        radius_us,
                        1,
                    )

                    morphology = float(
                        np.clip(
                            prominence
                            / (
                                robust_amplitude
                                * 0.28
                                + 1e-6
                            ),
                            0.0,
                            1.0,
                        )
                    )

                    return float(
                        morphology
                        - 0.22
                        * time_error
                    )

                best = max(
                    candidates,
                    key=candidate_quality,
                )
                quality = candidate_quality(
                    best
                )

                if (
                    quality
                    >= self.config.waveform_rescue_min_score
                ):
                    rescue_additions.append(
                        (
                            best,
                            float(
                                np.clip(
                                    quality,
                                    0.0,
                                    1.0,
                                )
                            ),
                        )
                    )

        for index, score in rescue_additions:
            if index in selected_indices:
                continue
            selected_indices.append(
                int(index)
            )
            selected_scores.append(
                float(score)
            )
            selected_rescue.append(
                True
            )

        order = np.argsort(
            np.asarray(
                selected_indices,
                dtype=int,
            )
        )

        selected_indices = [
            selected_indices[
                int(index)
            ]
            for index in order
        ]
        selected_scores = [
            selected_scores[
                int(index)
            ]
            for index in order
        ]
        selected_rescue = [
            selected_rescue[
                int(index)
            ]
            for index in order
        ]

        # --------------------------------------------------------------
        # 第三层：补峰后再做一次短 pair 冲突消解。
        # --------------------------------------------------------------
        final: list[
            tuple[
                int,
                float,
                bool,
            ]
        ] = []

        for index, score, rescued in zip(
            selected_indices,
            selected_scores,
            selected_rescue,
            strict=False,
        ):
            if not final:
                final.append(
                    (
                        int(index),
                        float(score),
                        bool(rescued),
                    )
                )
                continue

            previous_index, previous_score, previous_rescued = (
                final[-1]
            )

            interval_ms = (
                int(
                    t_us[
                        index
                    ]
                )
                - int(
                    t_us[
                        previous_index
                    ]
                )
            ) / 1000.0

            if (
                interval_ms
                < max(
                    self.config.waveform_pair_min_ms,
                    reference_rr_ms
                    * self.config.waveform_short_pair_rr_ratio,
                )
            ):
                if score > previous_score:
                    final[-1] = (
                        int(index),
                        float(score),
                        bool(rescued),
                    )
                continue

            final.append(
                (
                    int(index),
                    float(score),
                    bool(rescued),
                )
            )

        return (
            final,
            reference_rr_ms,
            autocorr_confidence,
            polarity,
            robust_amplitude,
        )

    def propose(
        self,
        samples: Sequence[SampleFrame],
        firmware_beats: Sequence[BeatFrame],
        last_committed_t_us: int,
        rr_history_ms: Sequence[float],
        commit_until_t_us: int,
    ) -> list[WaveformPeakProposal]:
        if not samples:
            self.last_diagnostics = (
                CorrectorDiagnostics()
            )
            return []

        latest_sample_t_us = int(
            samples[-1].t_us
        )

        history_start_t_us = int(
            commit_until_t_us
            - self.config.waveform_context_history_seconds
            * 1e6
        )

        # 前一个正式 Beat 必须包含在窗口中，便于做左侧 gap 判断。
        if last_committed_t_us > 0:
            history_start_t_us = min(
                history_start_t_us,
                int(
                    last_committed_t_us
                    - 2.0
                    * self.config.waveform_max_rr_ms
                    * 1000.0
                ),
            )

        selected_samples = [
            sample
            for sample in samples
            if (
                history_start_t_us
                <= sample.t_us
                <= latest_sample_t_us
            )
        ]

        if len(
            selected_samples
        ) < 24:
            self.last_diagnostics = CorrectorDiagnostics(
                commit_until_t_us=int(
                    commit_until_t_us
                ),
                latest_sample_t_us=(
                    latest_sample_t_us
                ),
            )
            return []

        t_us = np.asarray(
            [
                sample.t_us
                for sample
                in selected_samples
            ],
            dtype=np.int64,
        )
        filtered = np.asarray(
            [
                sample.filtered
                for sample
                in selected_samples
            ],
            dtype=float,
        )

        dt_us = np.diff(
            t_us.astype(
                float
            )
        )
        positive_dt = dt_us[
            dt_us > 0
        ]

        if positive_dt.size:
            sample_rate_hz = float(
                1e6
                / np.median(
                    positive_dt
                )
            )
        else:
            sample_rate_hz = float(
                self.config.sample_rate_hz
            )

        prior_rr_ms: float | None

        rr_array = np.asarray(
            [
                rr
                for rr in rr_history_ms
                if (
                    np.isfinite(rr)
                    and self.config.waveform_min_rr_ms
                    <= rr
                    <= self.config.waveform_max_rr_ms
                )
            ],
            dtype=float,
        )

        if rr_array.size >= 3:
            prior_rr_ms = float(
                np.median(
                    rr_array[
                        -min(
                            rr_array.size,
                            9,
                        ):
                    ]
                )
            )
        else:
            prior_rr_ms = None

        (
            selected,
            reference_rr_ms,
            autocorr_confidence,
            polarity,
            robust_amplitude,
        ) = self._select_waveform_peaks(
            t_us,
            filtered,
            sample_rate_hz,
            prior_rr_ms,
            last_committed_t_us,
        )

        if not selected:
            self.last_diagnostics = CorrectorDiagnostics(
                reference_rr_ms=(
                    reference_rr_ms
                ),
                autocorr_confidence=(
                    autocorr_confidence
                ),
                polarity=polarity,
                waveform_amplitude=(
                    robust_amplitude
                ),
                commit_until_t_us=int(
                    commit_until_t_us
                ),
                latest_sample_t_us=(
                    latest_sample_t_us
                ),
            )
            return []

        smooth = (
            self._triangular_smooth(
                filtered
            )
            * polarity
        )

        firmware_window = [
            beat
            for beat in firmware_beats
            if (
                history_start_t_us
                <= beat.t_us
                <= latest_sample_t_us
            )
        ]

        used_firmware: set[int] = set()
        proposals: list[
            WaveformPeakProposal
        ] = []

        minimum_new_gap_ms = max(
            self.config.waveform_pair_min_ms,
            reference_rr_ms
            * self.config.waveform_commit_refractory_rr_ratio,
        )

        matched_count = 0
        inserted_count = 0

        for (
            peak_index,
            waveform_score,
            low_prominence_rescue,
        ) in selected:
            peak_t_us = (
                self._quadratic_peak_time(
                    t_us,
                    smooth,
                    peak_index,
                )
            )

            if (
                peak_t_us
                > commit_until_t_us
            ):
                continue

            if (
                last_committed_t_us > 0
                and peak_t_us
                <= last_committed_t_us
                + int(
                    round(
                        minimum_new_gap_ms
                        * 1000.0
                    )
                )
            ):
                continue

            # 找最接近的 Firmware Accepted。
            match_radius_us = int(
                round(
                    min(
                        self.config.waveform_firmware_match_max_ms,
                        reference_rr_ms
                        * self.config.waveform_firmware_match_rr_ratio,
                    )
                    * 1000.0
                )
            )

            available_matches = [
                (
                    index,
                    beat,
                    abs(
                        int(
                            beat.t_us
                        )
                        - peak_t_us
                    ),
                )
                for index, beat
                in enumerate(
                    firmware_window
                )
                if (
                    index
                    not in used_firmware
                    and abs(
                        int(
                            beat.t_us
                        )
                        - peak_t_us
                    )
                    <= match_radius_us
                )
            ]

            matched_t_us = 0
            matched_score = 0.0
            matched_flags = 0

            if available_matches:
                match_index, match, _ = min(
                    available_matches,
                    key=lambda item:
                        item[2],
                )

                used_firmware.add(
                    int(
                        match_index
                    )
                )

                matched_t_us = int(
                    match.t_us
                )
                matched_score = float(
                    match.score
                )
                matched_flags = int(
                    match.flags
                )
                matched_count += 1
            else:
                inserted_count += 1

            sequence_index = int(
                np.searchsorted(
                    t_us,
                    peak_t_us,
                )
            )
            sequence_index = min(
                max(
                    sequence_index,
                    0,
                ),
                len(
                    selected_samples
                ) - 1,
            )

            proposal = WaveformPeakProposal(
                seq=int(
                    selected_samples[
                        sequence_index
                    ].seq
                ),
                t_us=int(
                    peak_t_us
                ),
                waveform_score=float(
                    waveform_score
                ),
                timing_uncertainty_ms=float(
                    np.clip(
                        7.0
                        + (
                            1.0
                            - waveform_score
                        )
                        * 28.0,
                        6.0,
                        36.0,
                    )
                ),
                reference_rr_ms=float(
                    reference_rr_ms
                ),
                polarity=int(
                    polarity
                ),
                matched_firmware_t_us=(
                    matched_t_us
                ),
                matched_firmware_score=(
                    matched_score
                ),
                matched_firmware_flags=(
                    matched_flags
                ),
                inserted_by_smoother=(
                    matched_t_us == 0
                ),
                low_prominence_rescue=bool(
                    low_prominence_rescue
                ),
            )

            proposals.append(
                proposal
            )

        self.last_diagnostics = CorrectorDiagnostics(
            reference_rr_ms=float(
                reference_rr_ms
            ),
            autocorr_confidence=float(
                autocorr_confidence
            ),
            polarity=int(
                polarity
            ),
            candidate_count=int(
                len(
                    selected
                )
            ),
            selected_count=int(
                len(
                    proposals
                )
            ),
            inserted_count=int(
                inserted_count
            ),
            firmware_matched_count=int(
                matched_count
            ),
            waveform_amplitude=float(
                robust_amplitude
            ),
            commit_until_t_us=int(
                commit_until_t_us
            ),
            latest_sample_t_us=int(
                latest_sample_t_us
            ),
        )

        return proposals
