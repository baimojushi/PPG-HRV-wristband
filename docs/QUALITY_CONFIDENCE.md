# SQI、结果有效性与统计互证

## SQI

SQI 表示数据质量，范围 0–100%。

它由以下可审计分量组成：

- PPG 削底 / 饱和；
- 佩戴覆盖；
- 实际有效采样率；
- 采样时基 p95 抖动；
- 长采样停顿比例；
- Sample 序号完整性；
- 协议完整性。

SQI 不表示“结果正确概率”。

v0.3.2 增加时基硬封顶：

```text
有效采样率误差 >5%
或采样超时比例 >2%
→ SQI 最多 64% / INVALID
```

## 结果等级

```text
VALID
LIMITED
INVALID
```

### VALID

严格质量门通过。

### LIMITED

数值允许正式显示，但存在明确的受限原因。

它不是简单放宽阈值：

- 时域只使用原始、连续、未修复 NN；
- 频域必须同时通过 Welch/Lomb 与双插值谱形互证；
- 采样时基超过硬门仍然 INVALID。

### INVALID

数学上即使可以计算，也不作为正式结果输出。

## 时域

LIMITED 最大范围：

```text
异常搏 ≤10%
未解决异常 ≤6%
连续异常 ≤2
连续有效 NN 差分 ≥30
采样 p95 ≤4 ms
```

RMSSD / pNN50 的修复 NN 不参与计算。

## 频域

LIMITED 最大范围：

```text
修复比例 ≤8%
未解决异常 ≤5%
连续未解决异常 ≤2
采样 p95 ≤4 ms
Welch/Lomb 稳健一致性 ≥80%
VLF/LF/HF 频带分布一致性 ≥82%
PCHIP/Linear 谱形一致性 ≥95%
```

频带绝对功率仍来自 Welch。

## RMSSD 统计区间

VALID / LIMITED 且有足够连续 NN 差分时输出：

```text
rmssd_ms
rmssd_95ci_ms
```

区间使用短块 bootstrap，用于表达有限窗口统计波动。

它不替代 SQI，也不表示医学诊断置信度。


## v0.3.3 Welch / Lomb 互证尺度

原始逐频点 Pearson：

```text
spectral_agreement_raw
```

继续作为调试量。

它不再直接决定 VALID / LIMITED / INVALID。

正式：

```text
spectral_agreement =
0.70 × spectral_shape_agreement
+ 0.30 × band_power_agreement
```

其中：

```text
spectral_shape_agreement
```

是在约 0.02 Hz 频率尺度平滑后比较 Welch 与 Lomb–Scargle。

```text
band_power_agreement
```

比较 VLF / LF / HF 三个归一化频带功率分布。

这样可以容忍有限窗泄漏和缓峰噪声造成的轻微谱峰错位，
同时保留对 LF↔HF 大尺度错误的独立约束。


## v0.3.4 Beat Timing Quality

PPG SQI 与 HRV 时间标志点质量分开。

单搏保存：

```text
source_t_us
t_us
timing_shift_ms
timing_quality
timing_uncertainty_ms
refined
```

低质量模板对齐不会改写 RR 时间轴，固件时间作为回退。
低质量证据仍参与聚合质量门。

严格 VALID：

```text
平均 timing quality >=82%
uncertainty p95 <=28 ms
低质量比例 <=5%
```

LIMITED 硬门：

```text
平均 timing quality >=68%
uncertainty p95 <=50 ms
低质量比例 <=15%
```

超过 LIMITED 门时，HRV 为 INVALID，即使采样 SQI=100%。


## v0.3.5 相位分支恢复证据

单搏增加：

```text
timing_recovered
```

它只表示该搏通过宽范围模板搜索从次级相位分支恢复到模板相位。

大偏移恢复不会自动获得高质量，仍需满足：

```text
高模板相关
低不确定度
独立节律一致
<0.5×RR 的源时间偏移
```

`timing_recovered` 主要用于 Debug、导出和后续难例统计。
HRV 是否 VALID 仍由 Timing Quality、RR 异常比例和频域互证共同决定。


## v0.3.6 软件人工标注

人工标注是调试证据，不是 SQI 组成部分。

它不会直接改变：

```text
Signal Quality
Time Domain
Frequency Domain
Winner
Rescue
RR cleaner
```

人工语义：

```text
“用户在当前 UI 可见的数据中观察到问题，
问题发生在软件标记前约 3 秒内。”
```

`device_t_us` 来自最近一次实际绘制到屏幕的设备时间，
`host_monotonic_ns` 和 `ui_data_lag_ms` 只用于审计标注延迟。

使用人工标注做算法评估时，需要保留未标注正常时段作为对照，
避免只在问题段寻找特征造成伪相关。

## v0.3.7 PPG 观测真值层

本版首先解决：

```text
算法输出
≈
PPG 中可重复辨认的主波波顶
```

这属于 PPG 观测层一致性。

没有同步 ECG 时，不能进一步声称：

```text
正式 PPG 波顶
=
ECG 生理真值
```

`waveform_score` 描述整窗 PPG 主波形态质量，也不是医学概率。

`inserted_by_smoother=True` 表示固件没有给出附近 Accepted，而完整 PPG 仍存在可识别主波。

`matched_firmware_t_us` 用于审计固件时间与正式波顶之间的差异。
