# v0.3.2 Patch：采样时基与时频可用性

## 修复 1：周期性采样阻塞

v0.3.1：

```text
每 16 sample
→ 完整 autocorrelation lag scan
→ 约 58 ms 停顿
```

v0.3.2：

```text
每 sample
→ 最多 4 lag
→ 每 lag 最多 96 pair
```

完整相关扫描被均匀摊开。

## 修复 2：SQI 不再掩盖采样时基故障

增加：

```text
effective_sample_rate_hz
timing_jitter_p95_ms
timing_overrun_ratio
```

严重时基错误直接将 SQI 封顶到 INVALID。

## 修复 3：时域 LIMITED

严格门不通过、硬门仍通过时：

```text
VALID → LIMITED
```

允许输出 RMSSD / SDNN / pNN50。

计算只使用原始连续 accepted NN，不使用修复值。

## 修复 4：频域 LIMITED

频域在输出前进行：

```text
Welch(PCHIP)
Welch(Linear)
Lomb–Scargle(irregular)
```

双重谱形一致性通过后，少量孤立异常窗口可以 LIMITED 输出。

## 修复 5：UI

PPG Debug 行新增：

```text
实时有效采样率
p95 采样抖动
采样超时比例
```

频域显示：

```text
VALID / LIMITED
Welch/Lomb 一致性
插值一致性
```

## 协议

仍为 v4，无帧格式变化。
