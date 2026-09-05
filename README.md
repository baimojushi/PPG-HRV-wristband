# PPG / HRV 实时分析系统 v0.3.3

v0.3.3 基于 v0.3.2 的稳定 125 Hz 采集链，优化缓峰、波形变缓和轻微事件时间抖动下的频谱互证。

**本版没有修改 ESP32 固件。已烧录 v0.3.2 固件可以继续使用，无需重新烧录。**

## 本次实测

```text
实际采样率            125.00 Hz
采样 p95 抖动        0.0040 ms
SQI                   99.83%
未解决 RR             0.402%
有效 NN               99.598%
```

采样和心搏时间线已经稳定。

v0.3.2 的滚动 5 分钟窗口仍出现：

```text
Welch/Lomb 原始逐频点相关
52.0% – 83.7%
```

同时 VLF/LF/HF 频带分布一致性保持：

```text
86.9% – 98.8%
```

说明主要问题是两种谱估计器的窄峰存在轻微频率偏移，逐频点 Pearson 对这类变化过于敏感。

## v0.3.3 稳健频谱互证

正式 Welch/Lomb 门改为：

```text
稳健一致性 =
0.70 × 约 0.02 Hz 平滑谱形相关
+ 0.30 × VLF/LF/HF 频带分布一致性
```

同时保留独立硬门：

```text
频带一致性 ≥82%
插值一致性 ≥95%
```

严格 VALID：

```text
稳健一致性 ≥90%
频带一致性 ≥90%
插值一致性 ≥98%
```

原始逐频点相关仍然：

```text
显示
导出
保存到 hrv_windows.csv
```

只用于 Debug。

## 实测回放结果

旧 v0.3.2 完整频域窗口：

```text
VALID      3
LIMITED    5
INVALID    4
```

相同 RR 数据用 v0.3.3 互证：

```text
VALID      7
LIMITED    5
INVALID    0
```

稳健一致性范围：

```text
81.5% – 97.2%
```

这里没有修改 Welch 的绝对功率，也没有修改 RR。

## 缓峰时间戳

已对以下方案做离线 A/B：

```text
原始峰值
二次插值峰值
最大上升斜率
半幅上升沿
切线足点
```

它们没有稳定提高频谱一致性，并且部分方案明显改变 LF/HF。

所以 v0.3.3 保留当前 Accepted Beat 时间戳，不为了提高一致性而重写 RR 时间轴。

## CNN

当前不加入一维卷积神经网络。

原因：

- 当前未解决 RR 仅约 0.40%；
- 当前问题位于频域估计器互证，不在 Candidate 分类；
- 小 CNN 在 ESP32 上计算量可接受，真正成本是独立标注和跨会话验证。

详细见：

```text
docs/CNN_ENGINEERING_ROI_v0.3.3.md
```

未来若引入 CNN，建议只作为：

```text
Candidate morphology scorer
```

不替代极性锁、周期预测、Candidate 竞争和 RR/HRV 质量门。

## UI

频域行现在显示：

```text
稳健Welch/Lomb
原始逐点
频带一致
插值一致
```

## 协议

仍为 v4。

## 关键文档

```text
docs/VALIDATION_v0.3.3_ROBUST_SPECTRUM.md
docs/CNN_ENGINEERING_ROI_v0.3.3.md
docs/QUALITY_CONFIDENCE.md
docs/TINY_CNN_PLAN.md
```

## 测试

```bash
python -m pytest -q tests
```
