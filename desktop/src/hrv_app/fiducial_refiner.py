from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math

import numpy as np

from .config import AnalysisConfig
from .models import BeatFrame, SampleFrame


@dataclass(slots=True)
class FiducialResult:
    """
    一次 PPG 心搏时间标志点细化结果。

    `quality` 是模板对齐的工程质量分，不表示医学概率。
    `uncertainty_ms` 来自互相关峰的宽度：峰越宽，时间位置越不唯一。
    """

    t_us: int
    quality: float
    uncertainty_ms: float
    shift_ms: float
    correlation: float
    refined: bool
    polarity: int


class TemplateFiducialRefiner:
    """
    用整段 PPG 波形模板统一每个 Accepted Beat 的时间相位。

    设计原则：
    1. 固件只负责“这个周期有没有心搏”；
    2. 桌面端使用完整 125 Hz PPG 再确定统一 fiducial；
    3. 不使用预测 RR 拉动时间戳，避免人为压低真实 HRV；
    4. 模板只在高质量对齐时缓慢更新，防止噪声污染模板。

    这样可以处理宽峰、平顶峰和峰内微小局部极值造成的时间漂移。
    """

    def __init__(
        self,
        config: AnalysisConfig | None = None,
    ) -> None:
        self.config = config or AnalysisConfig()

        self._template: np.ndarray | None = None
        self._template_updates = 0
        self._locked_polarity = 0

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

    @property
    def template_ready(self) -> bool:
        return self._template is not None

    @property
    def locked_polarity(self) -> int:
        return self._locked_polarity

    def required_future_us(self) -> int:
        # 为了允许向后搜索 search_ms，候选中心右侧还需要完整 template_post。
        # v0.3.4 默认约 400 ms 延迟，只发生在桌面 HRV 链，不影响固件实时心率。
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

        # 用 10–90% 范围做 robust scale，避免单个运动尖峰主导模板。
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
            np.linalg.norm(normalized)
        )

        if (
            not np.isfinite(norm)
            or norm <= 1e-9
        ):
            return None

        return normalized / norm

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

        local = filtered[left:right]

        # 极性不能用“窄峰窗口的中位数”判断。
        # 宽峰会占据窗口大部分时间，使中位数靠近峰顶，进而把正峰误判成负谷。
        # 这里用约一个 RR 尺度的上下文基线，再看固件 Winner 当时位于基线上方还是下方。
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
            np.median(context)
        )

        nearest = int(
            np.searchsorted(
                sample_t_us,
                beat_t_us,
            )
        )
        nearest = min(
            max(nearest, 0),
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
            polarity = self._locked_polarity
        elif winner_offset >= 0:
            polarity = 1
        else:
            polarity = -1

        if polarity > 0:
            selected = int(
                np.argmax(local)
            )
        else:
            selected = int(
                np.argmin(local)
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

    def refine(
        self,
        beat: BeatFrame,
        samples: Sequence[SampleFrame],
    ) -> FiducialResult:
        if len(samples) < 16:
            return FiducialResult(
                t_us=int(beat.t_us),
                quality=0.0,
                uncertainty_ms=999.0,
                shift_ms=0.0,
                correlation=0.0,
                refined=False,
                polarity=self._locked_polarity,
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
        # Bootstrap：先把固件 Accepted 吸附到同一类局部极值。
        # 这一步建立模板中心，不依赖 RR 预测。
        # ------------------------------------------------------------------
        if self._template is None:
            anchor = self._local_anchor(
                int(beat.t_us),
                sample_t_us,
                filtered,
            )

            if anchor is None:
                return FiducialResult(
                    t_us=int(beat.t_us),
                    quality=0.0,
                    uncertainty_ms=999.0,
                    shift_ms=0.0,
                    correlation=0.0,
                    refined=False,
                    polarity=0,
                )

            anchor_t_us, polarity = anchor
            segment = self._extract(
                anchor_t_us,
                sample_t_us,
                filtered,
            )

            if segment is None:
                return FiducialResult(
                    t_us=int(beat.t_us),
                    quality=0.0,
                    uncertainty_ms=999.0,
                    shift_ms=0.0,
                    correlation=0.0,
                    refined=False,
                    polarity=polarity,
                )

            self._template = segment.copy()
            self._template_updates = 1
            self._locked_polarity = polarity

            shift_ms = (
                anchor_t_us
                - int(beat.t_us)
            ) / 1000.0

            return FiducialResult(
                t_us=anchor_t_us,
                quality=0.82,
                uncertainty_ms=(
                    self.config.fiducial_template_step_ms
                ),
                shift_ms=float(shift_ms),
                correlation=1.0,
                refined=True,
                polarity=polarity,
            )

        # ------------------------------------------------------------------
        # Template alignment：在固件 Winner 周围只平移，不修改时间尺度。
        # ------------------------------------------------------------------
        search_ms = float(
            self.config.fiducial_search_ms
        )
        step_ms = float(
            self.config.fiducial_search_step_ms
        )

        shifts = np.arange(
            -search_ms,
            search_ms + 0.001,
            step_ms,
            dtype=float,
        )

        correlations = np.full(
            shifts.shape,
            -1.0,
            dtype=float,
        )
        segments: list[
            np.ndarray | None
        ] = []

        for index, shift_ms in enumerate(shifts):
            center_t_us = int(
                round(
                    beat.t_us
                    + shift_ms * 1000.0
                )
            )

            segment = self._extract(
                center_t_us,
                sample_t_us,
                filtered,
            )
            segments.append(segment)

            if segment is not None:
                correlations[index] = (
                    self._correlation(
                        segment,
                        self._template,
                    )
                )

        best_index = int(
            np.argmax(correlations)
        )
        best_corr = float(
            correlations[best_index]
        )

        if best_corr < -0.5:
            return FiducialResult(
                t_us=int(beat.t_us),
                quality=0.0,
                uncertainty_ms=999.0,
                shift_ms=0.0,
                correlation=0.0,
                refined=False,
                polarity=self._locked_polarity,
            )

        best_shift_ms = float(
            shifts[best_index]
        )

        # 三点抛物线细化互相关峰，得到亚采样时间偏移。
        if (
            0 < best_index < len(shifts) - 1
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
                - 2.0 * center_corr
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
                beat.t_us
                + best_shift_ms * 1000.0
            )
        )

        refined_segment = self._extract(
            refined_t_us,
            sample_t_us,
            filtered,
        )

        if refined_segment is None:
            refined_segment = segments[
                best_index
            ]

        # ------------------------------------------------------------------
        # 互相关峰宽度 = 时间标志点不确定度。
        # 宽峰 / 平顶峰会自然得到较大的 uncertainty。
        # ------------------------------------------------------------------
        plateau_level = (
            best_corr
            - self.config.fiducial_correlation_plateau_drop
        )

        plateau = shifts[
            correlations >= plateau_level
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
            uncertainty_ms = step_ms

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
                (best_corr - 0.45)
                / 0.50,
                0.0,
                1.0,
            )
        )

        quality = float(
            np.clip(
                0.78 * correlation_score
                + 0.22 * sharpness_score,
                0.0,
                1.0,
            )
        )

        # 只让高质量、新鲜波形缓慢进入模板。
        # Rescue / 低分 Winner 不更新模板，避免困难片段拖着模板跑。
        rescued = bool(
            beat.flags & 0x10
        )

        if (
            refined_segment is not None
            and best_corr
            >= self.config.fiducial_template_update_min_correlation
            and uncertainty_ms
            <= self.config.fiducial_template_update_max_uncertainty_ms
            and abs(best_shift_ms)
            <= self.config.fiducial_template_update_max_shift_ms
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
                * refined_segment
            )

            normalized = self._normalize(
                updated
            )

            if normalized is not None:
                self._template = normalized
                self._template_updates += 1

        return FiducialResult(
            t_us=refined_t_us,
            quality=quality,
            uncertainty_ms=uncertainty_ms,
            shift_ms=float(best_shift_ms),
            correlation=best_corr,
            refined=True,
            polarity=self._locked_polarity,
        )
