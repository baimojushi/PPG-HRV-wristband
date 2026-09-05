# SQI、有效性与统计区间

## SQI

SQI 表示数据质量，范围 0–100%。

它由以下可审计分量组成：

- PPG 削底/饱和；
- 佩戴覆盖；
- 采样时基；
- Sample 序号完整性；
- 协议完整性。

SQI 不表示“结果正确概率”。

## 结果有效性

```text
VALID
LIMITED
INVALID
```

时域、频域分别独立判断。

例如：

```text
时域 VALID
频域 LIMITED（还没积累满5分钟）
```

总体可显示 LIMITED。

## RMSSD 统计区间

只有时域质量门通过时，输出：

```text
rmssd_ms
rmssd_95ci_ms
```

当前使用短块 bootstrap 近似区间，用于表达有限窗口的统计波动。

它不替代传感器 SQI，也不表示医学诊断置信度。

## UI

首页：

```text
心率
HRV · RMSSD
数据质量 · SQI
```

当时域窗口无效：

```text
HRV = --
时域已暂停：具体原因
```

不展示 candidate RMSSD。
