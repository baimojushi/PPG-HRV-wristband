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
Welch/Lomb 谱形一致性 ≥70%
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
