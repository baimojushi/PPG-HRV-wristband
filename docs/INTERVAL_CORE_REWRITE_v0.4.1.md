# v0.4.1 Interval Core Rewrite

## 目标

本版本只处理正式间期链路：

```text
PPG → Beat → RR → interval quality → HRV
```

研究原型和普通用户 UI 不扩展。修复目标是消除“Firmware Beat 不稳定或原始波谷削底，
却把稳定的桌面波形 RR 一并 gate 掉”的参考源倒置。

## 核心设计

### 1. 两条异构波形检测器

`desktop/src/hrv_app/waveform_detectors.py` 同时运行：

- `detect_multiscale_persistence`：多尺度局部极大值持续性，设计思想来自 MSPTD 家族；
- `detect_elgendi_like`：短窗/心搏窗移动平均、自适应波段后取最强收缩峰。

两条路径共享同一条标准化 PPG，但不共享 firmware beat、预计 RR 或彼此的阈值。
这样“两个算法都在同一波形位置找到心搏”本身成为可观测质量证据。

相关公开设计参考：

- Charlton et al., *Detecting beats in the photoplethysmogram: benchmarking open-source algorithms*.
- Charlton et al., *The MSPTDfast photoplethysmography beat detection algorithm: design, benchmarking, and open-source distribution*.
- Goda et al./pyPPG, Aboy++ adaptive PPG peak detector.
- Elgendi-style systolic peak detection as implemented/documented by NeuroKit2.

本项目实现为独立代码，没有复制上述项目的源代码。

### 2. Beat consensus

`beat_consensus.py` 在 64 ms 容差内对两个检测器做一对一配对。

正式证据字段：

```text
detector_support_count
detector_names
detector_consensus
detector_time_spread_ms
single_detector
```

双检测器共同支持的峰优先。单检测器峰不会立即删除，而是交给 fixed-lag sequence
resolver 审核。

### 3. Fixed-lag sequence resolver

`beat_sequence_resolver.py` 保留原系统约 7.25 s 的未来窗口，但职责收窄为：

- 在真实波形候选中解决双峰/肩峰；
- 对明显长间期中的高质量单检测器峰做有限救援；
- 通过 RR 连贯性辅助排序。

硬原则：

> 预计 RR 只能帮助在真实波形候选中选择，不允许凭预计 RR 人工生成不存在的心搏。

因此 `inserted_by_smoother` 在 v0.4.1 重新定义为“真实单检测器候选被序列解析器救回”，
不再表示“没有 firmware match”。

### 4. Firmware Beat 降级为诊断证据

正式 Beat 先由 PPG 波形决定，随后才尝试与 Firmware Accepted Beat 配对。

```text
firmware_unmatched
matched_firmware_t_us
timing_shift_ms
```

都只用于诊断。Firmware 漏搏、重搏或相位漂移不再直接降低正式 HRV 质量。

### 5. 四层质量拆分

#### TransportQuality

回答：数据有没有丢、设备时间轴是否可靠。

来自：

- 实际采样率；
- 时间抖动/overrun；
- sample sequence；
- protocol error。

#### SensorContactQuality

回答：原始 ADC 接触/动态范围是否理想。

来自：

- wear；
- raw clip low/high。

它继续影响用户看到的“当前信号”，但不再直接决定 RR 是否可信。

#### BeatTimelineQuality

回答：正式间期本身是否有独立波形证据。

硬门使用：

```text
dual_detector_ratio
single_detector_ratio
detector_time_spread_p95_ms
sequence_rescue_ratio
local_clip_ratio
```

`firmware_unmatched_ratio` 仅记录，不 gate。

#### SpectralReliability

回答：同一条 RR 时间线用不同频率方法分析时是否稳定。

Welch/Lomb、频带分布或插值差异只把频率状态降为 `LIMITED`；
它们不再反向判定 BeatTimeline 错误。

## 代码边界

新增：

```text
desktop/src/hrv_app/ppg_preprocessor.py
desktop/src/hrv_app/waveform_detectors.py
desktop/src/hrv_app/beat_consensus.py
desktop/src/hrv_app/beat_sequence_resolver.py
desktop/src/hrv_app/interval_core.py
desktop/src/hrv_app/interval_quality.py
tests/test_interval_core_v041.py
```

主要修改：

```text
engine.py
models.py
config.py
rr_cleaner.py
signal_quality.py
hrv_time.py
hrv_frequency.py
provenance.py
storage.py
research_prototypes.py
```

## 溯源日志

v0.4.1 把新的逐搏证据写入：

```text
beat_provenance.csv
beat_detector_state.csv
signal_input_trace.csv
hrv_window_provenance.csv
spectrum_5min_trace.csv
beats_refined.csv
```

同时修复 `SessionRecorder.flush()` 未 flush provenance 文件的问题。

## 当前限制

1. 没有同步 ECG，因此“两个独立 PPG detector 高一致”只能证明 PPG 内部鲁棒性，
   不能证明绝对 ECG timing 真值。
2. 多尺度检测器是项目内简化、独立实现，不等同于 MSPTDfast 官方代码。
3. 当前 consensus 阈值来自项目实测与保守默认值，后续应在带 ECG ground truth 的
   公开数据和自采同步参考数据上校准。
4. 研究原型阈值、历史因果基线和 UI 解释不是本版本的修复范围。
