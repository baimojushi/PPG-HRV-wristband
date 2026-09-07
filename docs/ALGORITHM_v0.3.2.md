# zeezPPG v0.3.2 动态心搏检测与时频质量架构

## 1. 本次实测根因

v0.3.1 已解决峰/谷双计数，实测心率回到约 82 bpm。

新的 `samples_debug.csv` 暴露出更底层的问题：

```text
目标采样率              125 Hz
实际平均采样率          ≈85.9 Hz
正常采样间隔            ≈8 ms
周期性长间隔            ≈66 ms
长间隔出现周期          每 16 个处理样本
```

v0.3.1 同样每 16 个样本执行一次完整自相关扫描。

因此：

```text
每16点
  ↓
完整 O(N×lag) 自相关
  ↓
采集任务阻塞约58 ms
  ↓
PPG 中产生周期性采样空洞
  ↓
局部峰时间偏移 / 弱峰漏检
  ↓
RR 异常
  ↓
时频质量门长期无法通过
```

## 2. v0.3.2 增量自相关

完整扫描被拆成固定预算工作单元：

```text
每个 PPG sample
   ↓
最多计算 4 个 lag
   ↓
每个 lag 最多 96 对样本
   ↓
扫描完成后只做一次轻量局部峰搜索
```

一个完整 40–220 bpm lag 范围会跨几十个采样逐步完成。

125 Hz 主循环不再承担一次性几万次浮点运算。

### 固定内存

```text
autocorr_scan_values[192]
autocorr_scan_valid[192]
```

没有在实时采集循环中申请动态内存。

## 3. 同极性锁继续保留

Candidate 层：

```text
局部最大值 + 局部最小值
```

Accepted 层：

```text
首个稳定 Winner
      ↓
locked_polarity = +1 / -1
      ↓
只允许同极性 Winner
```

Rescue 也服从同一极性。

## 4. 节律锚点

获得两个以上稳定同极性 RR 后：

```text
RR median = 主节律锚点
```

自相关只在和 RR 接近时做轻度融合。

这防止错误周期重新拖动已经稳定的 Accepted RR。

## 5. 采样时基成为硬质量证据

桌面端直接从 Sample `t_us` 计算：

```text
effective_sample_rate_hz
timing_jitter_p95_ms
timing_overrun_ratio
```

严重采样时基偏差会对 SQI 做硬封顶。

```text
有效采样率误差 >5%
或长停顿 >2%
→ SQI 最多 0.64 / INVALID
```

HRV 还有独立硬门：

```text
timing jitter p95 > 4 ms
→ 时域 INVALID
→ 频域 INVALID
```

因此不会再出现“实际只有 86 Hz，SQI 仍显示 85%”的情况。

## 6. 时域三级质量门

### VALID

沿用严格条件：

```text
异常搏 ≤5%
未解决异常 ≤2%
连续异常 ≤1
采样 p95 ≤2 ms
```

### LIMITED

只在以下全部成立时：

```text
有效 NN ≥40
连续原始 NN 差分 ≥30
异常搏 ≤10%
未解决异常 ≤6%
连续异常 ≤2
SQI ≥70%
采样 p95 ≤4 ms
```

LIMITED RMSSD / pNN50 仍只使用：

```text
原始 accepted
+
时间上真正相邻
+
未修复
```

的 NN 对。

插值值不进入时域指标。

## 7. 频域三级质量门

v0.3.2 同时计算三条路径：

```text
PCHIP → Welch
Linear → Welch
Irregular NN → Lomb–Scargle
```

### 必须通过的互证

```text
Welch / Lomb 谱形相关        ≥70%
PCHIP / Linear 谱形相关      ≥95%
```

### LIMITED 最大异常范围

```text
修复 NN ≤8%
未解决异常 ≤5%
连续未解决异常 ≤2
采样 p95 ≤4 ms
```

任何硬门失败均为 INVALID。

严格条件全部通过时为 VALID；
互证可靠、但存在少量孤立异常时为 LIMITED。

## 8. SPWVD

`frequency.valid=True` 的 VALID / LIMITED 窗口都可生成 SPWVD。

SPWVD 继续只用于观察时频结构：

```text
频带绝对功率以 Welch 为准
```

## 9. 实测反事实验证

在本次 RR 完全不变的情况下，只把采样时基视为恢复到 125 Hz：

```text
时域       LIMITED
RMSSD      ≈112.97 ms

频域       LIMITED
Welch/Lomb ≈82.0%
插值一致性 ≈99.95%
```

说明现阶段首要工作是消除采集任务阻塞。

采样恢复后，即使仍存在当前量级的少数孤立 RR 异常，
时频模块也已经具备可审计的 LIMITED 计算路径。
