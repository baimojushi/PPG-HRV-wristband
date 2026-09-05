from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisConfig:
    """统一保存分析常量；v0.3.2 的 PPG 检测算法完整位于项目内 zeezPPG。"""

    sample_rate_hz: float = 125.0

    # 原项目时域窗口继续使用最近 60 个 RR，至少 40 个可直接使用的 NN。
    time_window_rr_count: int = 60
    time_min_valid_rr_count: int = 40
    metric_update_seconds: float = 20.0

    # 频域标准短时窗口。
    frequency_window_seconds: float = 300.0
    resample_hz: float = 4.0

    vlf_low_hz: float = 0.0033
    vlf_high_hz: float = 0.04
    lf_low_hz: float = 0.04
    lf_high_hz: float = 0.15
    hf_low_hz: float = 0.15
    hf_high_hz: float = 0.40

    # RR 硬边界只负责拦截明显无效值。
    rr_hard_min_ms: float = 300.0
    rr_hard_max_ms: float = 2000.0


    # v0.3.2 zeezPPG 动态检测器兼容灵敏度中性点。
    # 11.0 只小范围缩放综合评分门，不再直接定义心搏阈值。
    detector_legacy_peak_factor: float = 11.0

    # 局部节律模型。
    rr_local_history: int = 15
    rr_local_min_history: int = 7
    rr_mad_z_limit: float = 3.5
    rr_relative_deviation_limit: float = 0.20
    rr_major_deviation_limit: float = 0.35
    rr_robust_scale_floor_ms: float = 35.0

    # “一个真实 RR 被额外伪峰切成两段”的识别。
    false_peak_merge_tolerance: float = 0.20
    false_peak_component_max_ratio: float = 0.90
    false_peak_lookahead_tolerance: float = 0.30

    # 漏搏修复：长 RR 可拆成 2–3 个接近局部节律的 NN。
    missed_beat_split_tolerance: float = 0.20
    missed_beat_lookahead_tolerance: float = 0.30

    # 时域是严格模式：修复值不直接进入 RMSSD；伪迹过多直接判整个窗口无效。
    time_max_artifact_ratio: float = 0.05
    time_max_unresolved_ratio: float = 0.02
    time_max_consecutive_artifacts: int = 1
    time_min_sqi: float = 0.70

    # v0.3.2 受限时域：
    # 只使用原始 accepted 且时间上真正相邻的 NN 对，不把修复值塞进 RMSSD。
    # 中等伪迹时可以输出 LIMITED，超过这些硬门仍然 INVALID。
    time_limited_max_artifact_ratio: float = 0.10
    time_limited_max_unresolved_ratio: float = 0.06
    time_limited_max_consecutive_artifacts: int = 2
    time_limited_min_contiguous_diffs: int = 30

    # 采样时基是硬证据。
    # 2 ms 内可进入严格 VALID，2–4 ms 只允许 LIMITED，超过 4 ms 禁止正式 HRV。
    analysis_strict_max_timing_jitter_p95_ms: float = 2.0
    analysis_limited_max_timing_jitter_p95_ms: float = 4.0

    # 频域严格门保持原有标准。
    frequency_max_corrected_ratio: float = 0.05
    frequency_max_unresolved_ratio: float = 0.01
    frequency_min_sqi: float = 0.75

    # v0.3.2 受限频域：
    # 小比例孤立异常可以通过不规则时间 Lomb–Scargle 与 Welch 互证后输出 LIMITED。
    frequency_limited_max_corrected_ratio: float = 0.08
    frequency_limited_max_unresolved_ratio: float = 0.05
    frequency_limited_max_consecutive_artifacts: int = 2

    # 两条独立计算路径必须有足够形状一致性。
    frequency_min_spectral_agreement: float = 0.70
    frequency_strict_min_spectral_agreement: float = 0.80
    frequency_min_interpolation_agreement: float = 0.95
    frequency_strict_min_interpolation_agreement: float = 0.98

    # 协议错误会直接影响完整性。
    protocol_max_error_ratio: float = 0.01

    # SQI 默认观察最近 30 秒。
    signal_quality_window_seconds: float = 30.0
    adc_low: float = 0.0
    adc_high: float = 1023.0

    # SQI 中削底/饱和的归一化上限。达到 20% 时该分量记为 0。
    sqi_clipping_fail_ratio: float = 0.20
    sqi_sequence_drop_fail_ratio: float = 0.02
    sqi_timing_jitter_fail_ms: float = 2.0
    sqi_protocol_error_fail_ratio: float = 0.02

    # 有效采样率 / 长停顿用于 SQI 硬封顶。
    # 这些量直接由设备 t_us 推导，不依赖协议是否丢帧。
    sqi_effective_rate_warn_ratio: float = 0.02
    sqi_effective_rate_fail_ratio: float = 0.05
    sqi_timing_overrun_warn_ratio: float = 0.01
    sqi_timing_overrun_fail_ratio: float = 0.02

    # SPWVD 只在频域质量门通过后运行。
    spwvd_hop_seconds: float = 5.0
    spwvd_max_lag_seconds: float = 30.0
    spwvd_time_smooth_seconds: float = 15.0
