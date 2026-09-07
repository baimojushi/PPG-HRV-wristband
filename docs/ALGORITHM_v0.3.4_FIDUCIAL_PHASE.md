# v0.3.4 心搏相位与 HRV 时间标志点算法

## 目标

解决两类已经由实机波形确认的问题：

- 宽峰 / 平顶峰内部多个同极性局部极值导致 Accepted 时间左右漂移；
- 上一搏 fiducial 偏早/偏晚后，下一周期 Candidate 时间门跟随漂移，引发漏检。

## 1. 三层职责

```text
Beat existence
    ↓
Cycle phase tracking
    ↓
HRV fiducial localization
```

### Beat existence

ESP32 判断当前周期存在心搏。

### Cycle phase tracking

节律目标独立维护，不把每搏局部极值时间直接作为下一周期原点。

### HRV fiducial localization

桌面端等待完整 PPG 波形后，使用模板互相关给 HRV 生成统一时间标志点。

## 2. Peak Complex

Candidate 层仍保留所有原始局部极值用于 Debug。

进入 Winner Pool 前，同极性邻近 Candidate 合并：

```text
window = clamp(0.28 × RR, 80, 180 ms)
```

合并规则：

- 正极性：保留更高的真实幅值极值；
- 负极性：保留更低的真实幅值极值；
- 幅值非常接近时，形态评分更高者胜出。

这降低了宽峰内微小噪声对 Winner 时间的影响，同时不提高原始 Candidate 检测阈值。

## 3. 独立相位跟踪

状态：

```text
predicted_beat_t_us
expected_rr_ms
last_phase_error_ms
```

初始化：

```text
predicted_next = accepted + expected_RR
```

稳定阶段：

```text
phase_error = accepted - predicted
```

只在：

```text
|phase_error| <= 0.45 × RR
```

时允许小相位校正。

```text
correction = 0.22 × clip(error, ±40 ms)
```

下一目标从旧目标继续加 RR，不从 Accepted 时间重新起算。

漏掉一整搏时，目标可以跨周期前进，不让相位跟踪器被单次漏检拉偏。

## 4. Candidate timing score

`timingScore()` 与 Candidate 选择全部围绕 `predicted_beat_t_us` 计算。

上一搏局部极值即使晚 100 ms，下一搏真实主峰仍然能落在正确的预测相位附近。

## 5. Rescue

Rescue 搜索同样以独立预测目标为中心：

```text
predicted - 0.32 RR
...
predicted + 1.20 RR
```

继续服从同极性锁。

## 6. 模板 fiducial

ESP32 Winner 通过协议到桌面端后，桌面端等待约 400 ms 后续 PPG。

模板：

```text
[-280, +280] ms
```

搜索：

```text
firmware Winner ±120 ms
```

每个候选平移都做：

1. PPG 插值到固定相对时间轴；
2. 中位数去中心；
3. 10–90% 范围鲁棒缩放；
4. 单位范数归一化；
5. 与模板点积相关；
6. 三点抛物线细化相关峰。

## 7. 模板更新

只使用高质量心搏慢速更新：

```text
correlation >= 0.82
uncertainty <= 36 ms
|shift| <= 96 ms
Winner score >= 0.55
非 Rescue
```

模板更新系数：

```text
alpha = 0.10
```

困难波形不会快速污染模板。

## 8. 不确定度

取互相关峰距最高相关 `0.015` 以内的平台宽度，换算为时间不确定度。

宽峰 / 平顶峰会自然得到更高 uncertainty。

## 9. 低质量回退

模板相关能够找到数学最大值，质量差时不应用该平移。

```text
quality < 0.62
或 uncertainty > 80 ms
或 |shift| > 96 ms
```

回退：

```text
HRV t_us = firmware t_us
refined = false
```

低质量证据仍然保存，供质量门判断。

## 10. Beat Timing Quality

时域 / 频域分别统计：

```text
fiducial_quality_mean
fiducial_uncertainty_p95_ms
fiducial_shift_p95_ms
fiducial_unstable_ratio
```

严格 VALID：

```text
mean quality >= 0.82
uncertainty p95 <= 28 ms
unstable ratio <= 5%
```

LIMITED 硬门：

```text
mean quality >= 0.68
uncertainty p95 <= 50 ms
unstable ratio <= 15%
```

超过 LIMITED 硬门则 HRV INVALID。

## 11. 导出

```text
beats_raw.csv       固件 Accepted 原始证据
beats_refined.csv   HRV 模板时间标志点
beats_cleaned.csv   RR/NN 清洗结果 + timing quality
```

这样可以逐级审计：固件是否找到心搏、桌面端如何移动时间、RR 清洗如何处理。
