from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisConfig:
    """统一保存分析常量；v0.3.4 的 PPG 检测算法完整位于项目内 zeezPPG。"""

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


    # v0.3.4 zeezPPG 动态检测器兼容灵敏度中性点。
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

    # v0.3.4 受限时域：
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

    # v0.3.4 受限频域：
    # 小比例孤立异常可以通过不规则时间 Lomb–Scargle 与 Welch 互证后输出 LIMITED。
    frequency_limited_max_corrected_ratio: float = 0.08
    frequency_limited_max_unresolved_ratio: float = 0.05
    frequency_limited_max_consecutive_artifacts: int = 2

    # 两条独立计算路径必须有足够形状一致性。
    # v0.3.3：正式门使用多尺度稳健一致性。
    # 旧版逐频点 Pearson 会被 1~2 个频率 bin 的小偏移显著拉低。
    frequency_agreement_smoothing_hz: float = 0.020
    frequency_shape_agreement_weight: float = 0.70
    frequency_band_agreement_weight: float = 0.30

    frequency_min_spectral_agreement: float = 0.80
    frequency_strict_min_spectral_agreement: float = 0.90

    # 频带分布仍设置独立硬门，防止平滑掩盖 LF↔HF 的大尺度错位。
    frequency_min_band_power_agreement: float = 0.82
    frequency_strict_min_band_power_agreement: float = 0.90

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

    # ------------------------------------------------------------------
    # v0.3.4 PPG fiducial 模板对齐
    # ------------------------------------------------------------------
    # 固件负责判定“这一周期存在心搏”，桌面端再统一每搏的 PPG 时间相位。
    # 这套细化只平移 fiducial，不使用 RR 预测强行正则化时间轴。
    fiducial_future_context_ms: float = 120.0
    fiducial_bootstrap_search_ms: float = 120.0
    fiducial_search_ms: float = 120.0
    fiducial_search_step_ms: float = 4.0

    # v0.3.5：模板不能由一个低分 Winner 随机决定。
    # 本次实测中主峰 Winner 平均约 0.85，错相位分支平均约 0.63；
    # 0.74 可以显著降低“模板从次级局部峰启动”的概率。
    fiducial_bootstrap_min_winner_score: float = 0.74

    # 正常 ±120 ms 搜索找不到模板时，允许围绕“上一统一 fiducial + 稳健 RR”
    # 做一次更宽的恢复搜索。预测值只决定搜索窗口，不直接改写时间戳。
    fiducial_recovery_trigger_correlation: float = 0.70
    fiducial_recovery_min_correlation: float = 0.78

    # 围绕固件 Winner 做接近半周期的宽恢复时，必须使用更高相关门。
    # 半径仍严格 <0.5×RR，因此不会主动跨到相邻生理周期。
    fiducial_source_recovery_min_correlation: float = 0.88

    fiducial_recovery_min_quality: float = 0.74
    fiducial_recovery_expected_window_ratio: float = 0.30
    fiducial_recovery_min_window_ms: float = 150.0
    fiducial_recovery_max_window_ms: float = 260.0
    fiducial_recovery_max_source_shift_ratio: float = 0.48
    fiducial_recovery_max_source_shift_ms: float = 420.0

    # 大偏移恢复必须同时靠近独立周期预测。
    # 这防止同一主峰被两个错误固件事件重复吸附。
    fiducial_recovery_consistency_ratio: float = 0.22
    fiducial_recovery_consistency_min_ms: float = 100.0
    fiducial_recovery_consistency_max_ms: float = 180.0

    fiducial_recovery_step_ms: float = 4.0

    # 连续失配时允许在“高分 Winner”上重新启动模板。
    # 只在确定性检测器给出明显主峰级形态分时触发。
    fiducial_rebootstrap_bad_run: int = 6
    fiducial_rebootstrap_min_winner_score: float = 0.82

    fiducial_template_pre_ms: float = 280.0
    fiducial_template_post_ms: float = 280.0
    fiducial_template_step_ms: float = 8.0
    fiducial_template_alpha: float = 0.10

    fiducial_correlation_plateau_drop: float = 0.015
    fiducial_uncertainty_fail_ms: float = 80.0
    fiducial_template_update_min_correlation: float = 0.82
    fiducial_template_update_max_uncertainty_ms: float = 36.0
    fiducial_template_update_max_shift_ms: float = 96.0

    # 单搏模板对齐只有在质量足够且偏移未触及搜索边界时才真正改写 HRV 时间戳。
    # 低质量对齐保留固件时间，同时把低质量证据送入 Beat Timing Quality 门。
    fiducial_max_applied_shift_ms: float = 96.0

    # Beat Timing Quality 质量门。
    # 受限门保证宽峰时间不确定度不会被 SQI=100% 掩盖。
    fiducial_strict_min_mean_quality: float = 0.82
    fiducial_limited_min_mean_quality: float = 0.68
    fiducial_strict_max_uncertainty_p95_ms: float = 28.0
    fiducial_limited_max_uncertainty_p95_ms: float = 50.0
    fiducial_strict_max_unstable_ratio: float = 0.05
    fiducial_limited_max_unstable_ratio: float = 0.15
    fiducial_unstable_quality_threshold: float = 0.62

    # SPWVD 只在频域质量门通过后运行。
    spwvd_hop_seconds: float = 5.0
    spwvd_max_lag_seconds: float = 30.0
    spwvd_time_smooth_seconds: float = 15.0
