from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np


VALID = "VALID"
LIMITED = "LIMITED"
INVALID = "INVALID"


@dataclass(slots=True)
class SampleFrame:
    seq: int
    t_us: int
    raw: float
    avg: float
    filtered: float

    # v0.3.4：peak 表示动态形态候选脉冲，不等于最终心搏。
    peak: int
    hr_bpm: float

    # 连续动态形态评分和周期预测，供 Debug / 离线训练使用。
    detector_score: float = 0.0
    expected_rr_ms: float = 0.0

    flags: int = 0


@dataclass(slots=True)
class BeatFrame:
    seq: int
    t_us: int
    rr_ms: float
    hr_bpm: float

    # 周期内 winner 综合评分。
    score: float = 0.0

    flags: int = 0

    # v0.3.4 桌面端 PPG fiducial 细化证据。
    # source_t_us=固件原始 Accepted 时间；t_us=HRV 使用的统一相位时间。
    source_t_us: int = 0
    timing_shift_ms: float = 0.0
    timing_quality: float = 1.0
    timing_uncertainty_ms: float = 0.0

    # v0.3.5：
    # recovered=True 表示常规 ±120 ms 模板搜索失败后，
    # 在稳健周期预测附近找回了同一生理主峰。
    timing_recovered: bool = False
    refined: bool = False


@dataclass(slots=True)
class FirmwareMetricFrame:
    t_us: int
    rmssd_ms: float
    valid_rr_count: int
    artifact_ratio: float
    valid: bool


@dataclass(slots=True)
class DiagnosticFrame:
    t_us: int
    sample_drop_count: int
    beat_drop_count: int
    metric_drop_count: int
    sample_queue_depth: int
    sample_queue_high_water: int


@dataclass(slots=True)
class ProtocolHealth:
    """
    串口 / 蓝牙协议健康状态。

    error_ratio 不是概率置信度，只表示当前会话中已观察到的协议错误占比。
    sample_seq_gaps 独立记录 S 帧序号缺口，便于区分“协议坏帧”和“固件队列丢样”。
    """
    mode: str = "unknown"
    ok_frames: int = 0
    crc_errors: int = 0
    format_errors: int = 0
    resync_count: int = 0
    sample_seq_gaps: int = 0
    legacy_frames: int = 0

    @property
    def observed_frames(self) -> int:
        return self.ok_frames + self.crc_errors + self.format_errors

    @property
    def error_ratio(self) -> float:
        return (
            (self.crc_errors + self.format_errors) / self.observed_frames
            if self.observed_frames > 0
            else 0.0
        )


@dataclass(slots=True)
class BeatRecord:
    """
    保留每一个原始 Peak 事件的清洗结果。

    status:
    - accepted：原始 RR 可直接参与 HRV；
    - false_peak：该 Peak 被判为额外伪峰，必须删除；
    - false_peak_merged：与前一伪峰片段合并得到修复 NN；
    - missed_beat_repaired：疑似漏搏，拆成若干修复 NN；
    - hard_outlier / local_outlier：无法可靠修复，跳过；
    - no_wear：未佩戴。
    """
    seq: int
    t_us: int
    rr_raw_ms: float
    nn_ms: float
    valid: bool
    corrected: bool
    reason: str
    hr_bpm: float
    flags: int = 0

    # 从 BeatFrame 保留下来的检测器证据。
    score: float = 0.0
    rescued: bool = False

    # v0.3.4 心搏时间标志点质量。
    source_t_us: int = 0
    timing_shift_ms: float = 0.0
    timing_quality: float = 1.0
    timing_uncertainty_ms: float = 0.0
    timing_recovered: bool = False
    refined: bool = False

    status: str = "accepted"
    metric_eligible: bool = True


@dataclass(slots=True)
class NNInterval:
    """
    修复后的 NN 时间轴。

    corrected=True 的区间可用于“低伪迹比例下的频域连续性”，
    默认不参与严格时域 RMSSD，避免插值/合并值人为压低或抬高逐搏差。
    """
    t_us: int
    nn_ms: float
    corrected: bool = False
    metric_eligible: bool = True
    source: str = "raw"


@dataclass(slots=True)
class TimelineQuality:
    raw_rr_count: int = 0
    accepted_nn_count: int = 0
    detected_artifact_ratio: float = 1.0
    corrected_interval_ratio: float = 0.0
    unresolved_suspect_ratio: float = 1.0
    valid_nn_ratio: float = 0.0
    max_consecutive_artifacts: int = 0

    # PPG fiducial timing quality。
    fiducial_quality_mean: float = 1.0
    fiducial_uncertainty_p95_ms: float = 0.0
    fiducial_shift_p95_ms: float = 0.0
    fiducial_unstable_ratio: float = 0.0

    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SignalQuality:
    """
    数据质量指数 SQI，范围 0–1。

    SQI 是透明规则得到的质量分，不表示“结果有多少概率正确”。
    """
    sqi: float = 0.0
    status: str = INVALID
    wear_ratio: float = 0.0
    clip_low_ratio: float = 0.0
    clip_high_ratio: float = 0.0
    sequence_drop_ratio: float = 0.0

    # t_us 直接反推的真实采样时基。
    effective_sample_rate_hz: float = 0.0
    timing_jitter_p95_ms: float = 0.0
    timing_overrun_ratio: float = 0.0

    protocol_error_ratio: float = 0.0
    protocol_seq_gaps: int = 0
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TimeDomainMetrics:
    valid: bool = False
    status: str = INVALID
    validity_reason: str = ""
    nn_count: int = 0
    mean_nn_ms: float = 0.0
    mean_hr_bpm: float = 0.0
    rmssd_ms: float = 0.0
    rmssd_ci_low_ms: float = 0.0
    rmssd_ci_high_ms: float = 0.0
    sdnn_ms: float = 0.0
    pnn50_percent: float = 0.0

    # v0.3.4 心搏时间标志点稳定度。
    fiducial_quality_mean: float = 1.0
    fiducial_uncertainty_p95_ms: float = 0.0
    fiducial_shift_p95_ms: float = 0.0
    fiducial_unstable_ratio: float = 0.0

    # 保留 artifact_ratio 兼容旧导出字段，同时增加更明确的质量字段。
    artifact_ratio: float = 1.0
    detected_artifact_ratio: float = 1.0
    corrected_ratio: float = 0.0
    unresolved_suspect_ratio: float = 1.0
    max_consecutive_artifacts: int = 0


@dataclass(slots=True)
class FrequencyDomainMetrics:
    valid: bool = False
    status: str = INVALID
    validity_reason: str = ""
    progress: float = 0.0
    duration_seconds: float = 0.0

    total_power_ms2: float = 0.0
    vlf_ms2: float = 0.0
    lf_ms2: float = 0.0
    hf_ms2: float = 0.0
    lf_nu: float = 0.0
    hf_nu: float = 0.0
    lf_hf: float = 0.0
    hf_lf: float = 0.0

    # v0.3.4 频域窗口内的心搏时间标志点稳定度。
    fiducial_quality_mean: float = 1.0
    fiducial_uncertainty_p95_ms: float = 0.0
    fiducial_shift_p95_ms: float = 0.0
    fiducial_unstable_ratio: float = 0.0

    corrected_ratio: float = 0.0
    unresolved_suspect_ratio: float = 1.0
    max_consecutive_artifacts: int = 0

    # v0.3.3：
    # spectral_agreement 是“稳健 Welch/Lomb 一致性”，
    # 由约 0.02 Hz 频率尺度的谱形一致性 + VLF/LF/HF 频带分布一致性组成。
    spectral_agreement: float = 0.0

    # 原始逐频点 Pearson 相关，仅作 Debug。
    # 它对有限窗泄漏和轻微频率偏移很敏感，不再作为正式硬门。
    spectral_agreement_raw: float = 0.0

    # 频率轴平滑后的 Welch/Lomb 谱形相关。
    spectral_shape_agreement: float = 0.0

    # VLF/LF/HF 三频带归一化功率分布的一致性。
    band_power_agreement: float = 0.0

    # PCHIP vs 线性插值 Welch 谱形相关。
    # 用于判断频谱是否被某一种插值方式主导。
    interpolation_agreement: float = 0.0

    freqs_hz: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    psd_ms2_hz: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))


@dataclass(slots=True)
class QualityAssessment:
    """统一汇总 SQI 和结果有效性，不再伪装成概率置信度。"""
    sqi: float = 0.0
    status: str = INVALID
    time_status: str = INVALID
    frequency_status: str = INVALID
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AnalysisSnapshot:
    t_us: int = 0
    hr_bpm: float = 0.0
    time: TimeDomainMetrics = field(default_factory=TimeDomainMetrics)
    frequency: FrequencyDomainMetrics = field(default_factory=FrequencyDomainMetrics)
    signal_quality: SignalQuality = field(default_factory=SignalQuality)
    timeline_quality: TimelineQuality = field(default_factory=TimelineQuality)
    quality: QualityAssessment = field(default_factory=QualityAssessment)
    protocol_health: ProtocolHealth = field(default_factory=ProtocolHealth)


@dataclass(slots=True)
class SPWVDResult:
    valid: bool = False
    times_s: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    freqs_hz: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    power: np.ndarray = field(default_factory=lambda: np.empty((0, 0), dtype=float))
    message: str = ""
