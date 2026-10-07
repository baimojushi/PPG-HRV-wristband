# v0.4.7 Beat 证据链与重采样审计加固

## 目标

本补丁针对真实长时佩戴中出现的“正式 HRV 时间线看起来质量满分，但 Beat 来源、固件相位或重采样链路已经发生明显变化”的可观测性缺口。它不重新定义 v0.4.1+ 的正式 Beat 权威关系：**双波形检测器 + 序列解析仍是正式 Beat 时间线，Firmware Beat 仍只作诊断参照**。

## 1. Timing Quality 不再等于 Waveform Score

旧路径在 `engine.py` 中把 `proposal.waveform_score` 同时写入 `waveform_score` 和 `timing_quality`。这会把“峰形像不像”与“时间戳是否有足够独立证据”混成一个量。

v0.4.7 新增 `evaluate_beat_timing_quality()`，把正式时间可信度拆成三个可导出分量：

- `waveform_quality`：波形形态本身；
- `detector_timing_quality`：按 `timing_uncertainty_ms` 与既有严格 / LIMITED 阈值形成；
- `timing_provenance_quality`：对单检测器、序列救援、低显著度救援和局部削底逐项降权。

最终 `timing_quality` 是三个分量的乘积。每拍同时导出 `timing_quality_reason`，不再需要从多个布尔列人工猜测降级原因。

## 2. Firmware 相位只做旁路诊断

`firmware_alignment_available / firmware_alignment_quality / firmware_alignment_reason` 单独记录 Firmware Beat 是否匹配及相位偏移程度。约数百毫秒的稳定相位差会被明确标成 `firmware_phase_large_offset`，但不会乘进正式 `timing_quality`。

这样既能保留固件↔桌面波形事件“相位突然改变”的证据，又不会违反 v0.4.1+ 已确定的权威关系：固件 Beat 不作为正式 HRV 时间线的裁判。

## 3. 31.25 Hz → 125 Hz 重采样可审计

`PreprocessedPPG` / `IntervalCoreDiagnostics` 新增：

- 输入时钟：`input_dt_mean_ms / input_dt_std_ms / input_jitter_p95_ms`；
- 实际变换：`resample_ratio / resample_up / resample_down`；
- 回投影误差：`regularization_backprojection_rms`、`resample_backprojection_rms`、`resample_backprojection_max_abs`。

回投影误差以**归一化 PPG 信号单位**表示：先把规则化信号或最终重采样信号插值回原始收到样本的时间戳，再与原始归一化输入比较。它不是 ECG 级 Beat ground truth，也不是独立的生理准确度指标；它只用于回答“重采样链本身改写了多少输入波形”。

`signal_input_trace.csv` 同时加入 raw / filtered 的线性斜率和 filtered 负值比例，用于把重采样失真与基线漂移、接触变化分开看。

## 4. 20 秒窗口显式记录状态突变

`hrv_window_provenance.csv` 继续沿用原有文件，不新增重复 CSV。每个当前 20 秒窗口现在与**紧邻的前一个非重叠 20 秒窗口**比较，增加：

- `firmware_match_ratio` 与 `firmware_match_ratio_delta`；
- `offset_p95_ms / previous_offset_p95_ms / offset_p95_delta_ms`；
- `timing_quality_mean / previous_timing_quality_mean / timing_quality_mean_delta`；
- Timing Quality p05、低质量比例、Firmware Alignment 平均值与可用比例；
- 正式 `time_status / time_validity_reason / frequency_status / frequency_validity_reason`。

这使“12–13 分钟附近突然换相位 / 匹配机制 / 检测状态”的证据可以直接按短窗追踪，而不是只看整段均值。

## 5. 导出兼容性

没有删除既有列。`beats_refined.csv` 和 `beats_cleaned.csv` 只追加时间质量分量和 Firmware Alignment 诊断列；已有读取器按列名读取时保持兼容。固件目录和协议格式均未修改。
