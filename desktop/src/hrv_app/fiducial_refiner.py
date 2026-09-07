from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .config import AnalysisConfig
from .models import BeatFrame, SampleFrame


@dataclass(slots=True)
class FiducialResult:
    """
    一次 PPG 心搏时间标志点细化结果。

    `quality` 是模板对齐的工程质量分，不表示医学概率。
    `uncertainty_ms` 来自互相关峰宽度。
    `recovered=True` 表示常规 Winner 周围搜索失配后，
    在独立周期预测附近重新找回了同一生理主峰。
    """

    t_us: int
    quality: float
    uncertainty_ms: float
    shift_ms: float
    correlation: float
    refined: bool
    polarity: int
    recovered: bool = False


class TemplateFiducialRefiner:
    """
    使用整段 PPG 波形模板统一 HRV fiducial。

    v0.3.5 的关键变化：

    1. 低分固件 Winner 不允许决定首个模板；
    2. 正常搜索仍只在 Winner ±120 ms 内运行；
    3. 正常搜索失配时，可围绕
       `上一统一 fiducial + 稳健 RR`
       做一次较宽恢复搜索；
    4. 周期预测只决定“去哪找波形”，不会直接把时间戳拉到预测位置；
    5. 连续模板失配时，只允许在高分 Winner 上重新启动模板。

    这直接针对实测中的“主峰 / 次级同极性局部峰分支切换”。
    """

    def __init__(
        self,
        config: AnalysisConfig | None = None,
    ) -> None:
        self.config = config or AnalysisConfig()

        self._template: np.ndarray | None = None
        self._template_updates = 0
        self._locked_polarity = 0
        self._bad_alignment_run = 0

        self._relative_ms = np.arange(
            -self.config.fiducial_template_pre_ms,
            self.config.fiducial_template_post_ms + 0.001,
            self.config.fiducial_template_step_ms,
            dtype=float,
        )

    def reset(self) -> None:
        self._template = None
        self._template_updates = 0
        self._locked_polarity = 0
        self._bad_alignment_run = 0

    @property
    def template_ready(self) -> bool:
        return self._template is not None

    @property
    def locked_polarity(self) -> int:
        return self._locked_polarity

    def required_future_us(self) -> int:
        required_ms = max(
            self.config.fiducial_future_context_ms,
            self.config.fiducial_template_post_ms
            + self.config.fiducial_search_ms,
        )

        return int(
            round(
                required_ms
                * 1000.0
            )
        )

    @staticmethod
    def _normalize(
        values: np.ndarray,
    ) -> np.ndarray | None:
        values = np.asarray(
            values,
            dtype=float,
        )

        if values.size < 8:
            return None

        median = float(
            np.median(values)
        )
        centered = values - median

        p10, p90 = np.percentile(
            centered,
            [10.0, 90.0],
        )

        scale = float(
            p90 - p10
        )

        if (
            not np.isfinite(scale)
            or scale <= 1e-6
        ):
            scale = float(
                np.std(centered)
            )

        if (
            not np.isfinite(scale)
            or scale <= 1e-6
        ):
            return None

        normalized = centered / scale
        normalized -= float(
            np.mean(normalized)
        )

        norm = float(
            np.linalg.norm(
                normalized
            )
        )

        if (
            not np.isfinite(norm)
            or norm <= 1e-9
        ):
            return None

        return (
            normalized
            / norm
        )

    def _extract(
        self,
        center_t_us: int,
        sample_t_us: np.ndarray,
        filtered: np.ndarray,
    ) -> np.ndarray | None:
        target_t_us = (
            float(center_t_us)
            + self._relative_ms
            * 1000.0
        )

        if (
            target_t_us[0]
            < sample_t_us[0]
            or target_t_us[-1]
            > sample_t_us[-1]
        ):
            return None

        segment = np.interp(
            target_t_us,
            sample_t_us,
            filtered,
        )

        return self._normalize(
            segment
        )

    def _local_anchor(
        self,
        beat_t_us: int,
        sample_t_us: np.ndarray,
        filtered: np.ndarray,
    ) -> tuple[int, int] | None:
        search_us = int(
            round(
                self.config.fiducial_bootstrap_search_ms
                * 1000.0
            )
        )

        left = int(
            np.searchsorted(
                sample_t_us,
                beat_t_us - search_us,
            )
        )
        right = int(
            np.searchsorted(
                sample_t_us,
                beat_t_us + search_us,
                side="right",
            )
        )

        if right - left < 3:
            return None

        local = filtered[
            left:right
        ]

        # 约一个 RR 尺度的上下文只用于确定“局部最大 / 局部最小”极性。
        context_us = 420_000

        context_left = int(
            np.searchsorted(
                sample_t_us,
                beat_t_us - context_us,
            )
        )
        context_right = int(
            np.searchsorted(
                sample_t_us,
                beat_t_us + context_us,
                side="right",
            )
        )

        context = filtered[
            context_left:context_right
        ]

        if context.size < 8:
            context = local

        baseline = float(
            np.median(
                context
            )
        )

        nearest = int(
            np.searchsorted(
                sample_t_us,
                beat_t_us,
            )
        )
        nearest = min(
            max(
                nearest,
                0,
            ),
            len(sample_t_us) - 1,
        )

        if (
            nearest > 0
            and abs(
                sample_t_us[nearest - 1]
                - beat_t_us
            )
            < abs(
                sample_t_us[nearest]
                - beat_t_us
            )
        ):
            nearest -= 1

        winner_offset = float(
            filtered[nearest]
            - baseline
        )

        if self._locked_polarity != 0:
            polarity = (
                self._locked_polarity
            )
        elif winner_offset >= 0:
            polarity = 1
        else:
            polarity = -1

        if polarity > 0:
            selected = int(
                np.argmax(
                    local
                )
            )
        else:
            selected = int(
                np.argmin(
                    local
                )
            )

        return (
            int(
                sample_t_us[
                    left + selected
                ]
            ),
            polarity,
        )

    @staticmethod
    def _correlation(
        first: np.ndarray,
        second: np.ndarray,
    ) -> float:
        if (
            first.size != second.size
            or first.size < 8
        ):
            return -1.0

        value = float(
            np.dot(
                first,
                second,
            )
        )

        if not np.isfinite(value):
            return -1.0

        return float(
            np.clip(
                value,
                -1.0,
                1.0,
            )
        )

    def _search(
        self,
        center_t_us: int,
        search_ms: float,
        step_ms: float,
        sample_t_us: np.ndarray,
        filtered: np.ndarray,
    ) -> tuple[
        int,
        float,
        float,
        float,
        np.ndarray | None,
    ] | None:
        if self._template is None:
            return None

        shifts = np.arange(
            -float(search_ms),
            float(search_ms) + 0.001,
            float(step_ms),
            dtype=float,
        )

        correlations = np.full(
            shifts.shape,
            -1.0,
            dtype=float,
        )

        for index, shift_ms in enumerate(
            shifts
        ):
            segment = self._extract(
                int(
                    round(
                        center_t_us
                        + shift_ms
                        * 1000.0
                    )
                ),
                sample_t_us,
                filtered,
            )

            if segment is not None:
                correlations[index] = (
                    self._correlation(
                        segment,
                        self._template,
                    )
                )

        best_index = int(
            np.argmax(
                correlations
            )
        )
        best_corr = float(
            correlations[
                best_index
            ]
        )

        if best_corr < -0.5:
            return None

        best_shift_ms = float(
            shifts[
                best_index
            ]
        )

        # 三点抛物线细化互相关峰。
        if (
            0 < best_index
            < len(shifts) - 1
        ):
            left_corr = float(
                correlations[
                    best_index - 1
                ]
            )
            center_corr = best_corr
            right_corr = float(
                correlations[
                    best_index + 1
                ]
            )

            denominator = (
                left_corr
                - 2.0
                * center_corr
                + right_corr
            )

            if abs(denominator) > 1e-9:
                fractional = (
                    0.5
                    * (
                        left_corr
                        - right_corr
                    )
                    / denominator
                )

                fractional = float(
                    np.clip(
                        fractional,
                        -1.0,
                        1.0,
                    )
                )

                best_shift_ms += (
                    fractional
                    * step_ms
                )

        refined_t_us = int(
            round(
                center_t_us
                + best_shift_ms
                * 1000.0
            )
        )

        refined_segment = self._extract(
            refined_t_us,
            sample_t_us,
            filtered,
        )

        plateau_level = (
            best_corr
            - self.config.fiducial_correlation_plateau_drop
        )

        plateau = shifts[
            correlations
            >= plateau_level
        ]

        if plateau.size >= 2:
            uncertainty_ms = float(
                max(
                    step_ms,
                    0.5
                    * (
                        plateau[-1]
                        - plateau[0]
                    ),
                )
            )
        else:
            uncertainty_ms = float(
                step_ms
            )

        return (
            refined_t_us,
            best_shift_ms,
            best_corr,
            uncertainty_ms,
            refined_segment,
        )

    def _quality(
        self,
        correlation: float,
        uncertainty_ms: float,
    ) -> float:
        sharpness_score = float(
            np.clip(
                1.0
                - uncertainty_ms
                / self.config.fiducial_uncertainty_fail_ms,
                0.0,
                1.0,
            )
        )

        correlation_score = float(
            np.clip(
                (correlation - 0.45)
                / 0.50,
                0.0,
                1.0,
            )
        )

        return float(
            np.clip(
                0.78
                * correlation_score
                + 0.22
                * sharpness_score,
                0.0,
                1.0,
            )
        )

    def _bootstrap_wait_result(
        self,
        beat: BeatFrame,
    ) -> FiducialResult:
        # 模板尚未建立时保留固件时间。
        # 质量明确低于正式 HRV 门，避免“尚未确定相位”被当成高质量。
        quality = float(
            np.clip(
                0.72
                * float(beat.score),
                0.30,
                0.58,
            )
        )

        return FiducialResult(
            t_us=int(
                beat.t_us
            ),
            quality=quality,
            uncertainty_ms=64.0,
            shift_ms=0.0,
            correlation=0.0,
            refined=False,
            polarity=self._locked_polarity,
            recovered=False,
        )

    def refine(
        self,
        beat: BeatFrame,
        samples: Sequence[SampleFrame],
        *,
        expected_t_us: int | None = None,
        expected_rr_ms: float | None = None,
    ) -> FiducialResult:
        if len(samples) < 16:
            return FiducialResult(
                t_us=int(
                    beat.t_us
                ),
                quality=0.0,
                uncertainty_ms=999.0,
                shift_ms=0.0,
                correlation=0.0,
                refined=False,
                polarity=self._locked_polarity,
                recovered=False,
            )

        sample_t_us = np.asarray(
            [
                sample.t_us
                for sample in samples
            ],
            dtype=float,
        )

        filtered = np.asarray(
            [
                sample.filtered
                for sample in samples
            ],
            dtype=float,
        )

        # ------------------------------------------------------------------
        # 1. 稳健模板启动
        # ------------------------------------------------------------------
        # 实测表明：错相位分支 Winner 平均分明显低于主峰。
        # 所以首个模板必须等待一个“主峰级 Winner”，不能由第一个可用 Beat 决定。
        if self._template is None:
            if (
                beat.score
                < self.config.fiducial_bootstrap_min_winner_score
            ):
                return (
                    self._bootstrap_wait_result(
                        beat
                    )
                )

            anchor = self._local_anchor(
                int(
                    beat.t_us
                ),
                sample_t_us,
                filtered,
            )

            if anchor is None:
                return (
                    self._bootstrap_wait_result(
                        beat
                    )
                )

            (
                anchor_t_us,
                polarity,
            ) = anchor

            segment = self._extract(
                anchor_t_us,
                sample_t_us,
                filtered,
            )

            if segment is None:
                return (
                    self._bootstrap_wait_result(
                        beat
                    )
                )

            self._template = (
                segment.copy()
            )
            self._template_updates = 1
            self._locked_polarity = (
                polarity
            )
            self._bad_alignment_run = 0

            shift_ms = (
                anchor_t_us
                - int(
                    beat.t_us
                )
            ) / 1000.0

            return FiducialResult(
                t_us=anchor_t_us,
                quality=0.86,
                uncertainty_ms=(
                    self.config.fiducial_template_step_ms
                ),
                shift_ms=float(
                    shift_ms
                ),
                correlation=1.0,
                refined=True,
                polarity=polarity,
                recovered=False,
            )

        # ------------------------------------------------------------------
        # 2. 常规 Winner 周围模板搜索
        # ------------------------------------------------------------------
        normal = self._search(
            int(
                beat.t_us
            ),
            self.config.fiducial_search_ms,
            self.config.fiducial_search_step_ms,
            sample_t_us,
            filtered,
        )

        if normal is None:
            normal_t_us = int(
                beat.t_us
            )
            normal_shift_ms = 0.0
            normal_corr = 0.0
            normal_uncertainty_ms = 999.0
            normal_segment = None
        else:
            (
                normal_t_us,
                normal_shift_ms,
                normal_corr,
                normal_uncertainty_ms,
                normal_segment,
            ) = normal

        chosen_t_us = normal_t_us
        chosen_corr = normal_corr
        chosen_uncertainty_ms = (
            normal_uncertainty_ms
        )
        chosen_segment = (
            normal_segment
        )
        recovered = False

        # ------------------------------------------------------------------
        # 3. 主峰 / 次级峰分支恢复
        # ------------------------------------------------------------------
        # 只在常规模板失配时启动。
        #
        # expected_t_us 由“上一统一 fiducial + 稳健 RR”给出。
        # 它只定义较宽的波形搜索区域，最终时间仍由真实 PPG 模板相关峰决定。
        if (
            normal_corr
            < self.config.fiducial_recovery_trigger_correlation
            and expected_t_us is not None
            and expected_rr_ms is not None
            and expected_rr_ms > 0
        ):
            recovery_window_ms = float(
                np.clip(
                    expected_rr_ms
                    * self.config.fiducial_recovery_expected_window_ratio,
                    self.config.fiducial_recovery_min_window_ms,
                    self.config.fiducial_recovery_max_window_ms,
                )
            )

            recovery = self._search(
                int(
                    expected_t_us
                ),
                recovery_window_ms,
                self.config.fiducial_recovery_step_ms,
                sample_t_us,
                filtered,
            )

            if recovery is not None:
                (
                    recovery_t_us,
                    _recovery_center_shift_ms,
                    recovery_corr,
                    recovery_uncertainty_ms,
                    recovery_segment,
                ) = recovery

                source_shift_ms = (
                    recovery_t_us
                    - int(
                        beat.t_us
                    )
                ) / 1000.0

                max_source_shift_ms = min(
                    self.config.fiducial_recovery_max_source_shift_ms,
                    expected_rr_ms
                    * self.config.fiducial_recovery_max_source_shift_ratio,
                )

                recovery_quality = (
                    self._quality(
                        recovery_corr,
                        recovery_uncertainty_ms,
                    )
                )

                if (
                    recovery_corr
                    >= self.config.fiducial_recovery_min_correlation
                    and recovery_quality
                    >= self.config.fiducial_recovery_min_quality
                    and abs(
                        source_shift_ms
                    )
                    <= max_source_shift_ms
                    and recovery_corr
                    >= normal_corr + 0.06
                ):
                    chosen_t_us = (
                        recovery_t_us
                    )
                    chosen_corr = (
                        recovery_corr
                    )
                    chosen_uncertainty_ms = (
                        recovery_uncertainty_ms
                    )
                    chosen_segment = (
                        recovery_segment
                    )
                    recovered = True

        # ------------------------------------------------------------------
        # 3.1 固件 Winner 周围的半周期宽恢复
        # ------------------------------------------------------------------
        # v0.3.4 实测中错误分支常比主峰早约 0.2–0.35 s，
        # 已经超过普通 ±120 ms 模板搜索。
        #
        # 这里的搜索半径严格小于 0.5×RR，并使用更高相关门。
        # 因此它可以跨过“同周期次级峰 → 主峰”的相位差，
        # 同时不主动跳到前后相邻心搏。
        if (
            normal_corr
            < self.config.fiducial_recovery_trigger_correlation
            and expected_t_us is not None
            and expected_rr_ms is not None
            and expected_rr_ms > 0
        ):
            source_recovery_ms = min(
                self.config.fiducial_recovery_max_source_shift_ms,
                expected_rr_ms
                * self.config.fiducial_recovery_max_source_shift_ratio,
            )

            source_recovery = self._search(
                int(
                    beat.t_us
                ),
                source_recovery_ms,
                self.config.fiducial_recovery_step_ms,
                sample_t_us,
                filtered,
            )

            if source_recovery is not None:
                (
                    source_recovery_t_us,
                    _source_center_shift_ms,
                    source_recovery_corr,
                    source_recovery_uncertainty_ms,
                    source_recovery_segment,
                ) = source_recovery

                source_recovery_quality = (
                    self._quality(
                        source_recovery_corr,
                        source_recovery_uncertainty_ms,
                    )
                )

                source_recovery_shift_ms = (
                    source_recovery_t_us
                    - int(
                        beat.t_us
                    )
                ) / 1000.0

                consistency_window_ms = float(
                    np.clip(
                        expected_rr_ms
                        * self.config.fiducial_recovery_consistency_ratio,
                        self.config.fiducial_recovery_consistency_min_ms,
                        self.config.fiducial_recovery_consistency_max_ms,
                    )
                )

                prediction_error_ms = abs(
                    source_recovery_t_us
                    - int(
                        expected_t_us
                    )
                ) / 1000.0

                if (
                    source_recovery_corr
                    >= self.config.fiducial_source_recovery_min_correlation
                    and source_recovery_quality
                    >= self.config.fiducial_recovery_min_quality
                    and abs(
                        source_recovery_shift_ms
                    )
                    <= source_recovery_ms
                    and prediction_error_ms
                    <= consistency_window_ms
                    and source_recovery_corr
                    > chosen_corr + 0.04
                ):
                    chosen_t_us = (
                        source_recovery_t_us
                    )
                    chosen_corr = (
                        source_recovery_corr
                    )
                    chosen_uncertainty_ms = (
                        source_recovery_uncertainty_ms
                    )
                    chosen_segment = (
                        source_recovery_segment
                    )
                    recovered = True

        quality = self._quality(
            chosen_corr,
            chosen_uncertainty_ms,
        )

        # ------------------------------------------------------------------
        # 4. 连续失配自恢复
        # ------------------------------------------------------------------
        if chosen_corr < 0.55:
            self._bad_alignment_run += 1
        else:
            self._bad_alignment_run = 0

        if (
            self._bad_alignment_run
            >= self.config.fiducial_rebootstrap_bad_run
            and beat.score
            >= self.config.fiducial_rebootstrap_min_winner_score
        ):
            anchor = self._local_anchor(
                int(
                    beat.t_us
                ),
                sample_t_us,
                filtered,
            )

            if anchor is not None:
                (
                    anchor_t_us,
                    polarity,
                ) = anchor

                segment = self._extract(
                    anchor_t_us,
                    sample_t_us,
                    filtered,
                )

                if segment is not None:
                    self._template = (
                        segment.copy()
                    )
                    self._template_updates += 1
                    self._locked_polarity = (
                        polarity
                    )
                    self._bad_alignment_run = 0

                    chosen_t_us = (
                        anchor_t_us
                    )
                    chosen_corr = 1.0
                    chosen_uncertainty_ms = (
                        self.config.fiducial_template_step_ms
                    )
                    chosen_segment = segment
                    quality = 0.84
                    recovered = True

        source_shift_ms = (
            chosen_t_us
            - int(
                beat.t_us
            )
        ) / 1000.0

        # ------------------------------------------------------------------
        # 5. 模板缓慢更新
        # ------------------------------------------------------------------
        rescued = bool(
            beat.flags
            & 0x10
        )

        if recovered:
            shift_ok_for_update = True
        else:
            shift_ok_for_update = (
                abs(
                    source_shift_ms
                )
                <= self.config.fiducial_template_update_max_shift_ms
            )

        if (
            chosen_segment is not None
            and chosen_corr
            >= self.config.fiducial_template_update_min_correlation
            and chosen_uncertainty_ms
            <= self.config.fiducial_template_update_max_uncertainty_ms
            and shift_ok_for_update
            and beat.score >= 0.55
            and not rescued
        ):
            alpha = float(
                self.config.fiducial_template_alpha
            )

            updated = (
                (1.0 - alpha)
                * self._template
                + alpha
                * chosen_segment
            )

            normalized = (
                self._normalize(
                    updated
                )
            )

            if normalized is not None:
                self._template = (
                    normalized
                )
                self._template_updates += 1

        return FiducialResult(
            t_us=int(
                chosen_t_us
            ),
            quality=float(
                quality
            ),
            uncertainty_ms=float(
                chosen_uncertainty_ms
            ),
            shift_ms=float(
                source_shift_ms
            ),
            correlation=float(
                chosen_corr
            ),
            refined=True,
            polarity=self._locked_polarity,
            recovered=bool(
                recovered
            ),
        )
