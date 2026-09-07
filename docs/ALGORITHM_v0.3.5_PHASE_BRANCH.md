# zeezPPG v0.3.5：同极性相位分支稳定

## 目标

解决同一 PPG 周期内多个同极性局部最大值导致的 Winner 分支切换。

## 固件

```text
Raw Candidate
   ↓
Peak Complex
   ↓
等待到约 1.40 × predicted phase
   ↓
形态主导 Winner
   ↓
小增益独立相位跟踪
```

Candidate Pool：

```text
score = 0.86*morphology + 0.14*timing
```

Winner：

```text
score = 0.90*morphology + 0.10*timing
```

时间上下文仍有作用，但不能让较弱次级峰仅凭“更接近预测时刻”击败主峰。

## 桌面 fiducial

```text
高分 Winner 建模板
     ↓
普通 ±120 ms 模板搜索
     ↓ 失配
独立周期预测附近恢复
     ↓
<0.5×RR 的 source-wide 恢复
     ↓
高相关 + 节律一致性门
     ↓
统一 HRV fiducial
```

周期预测只定义搜索区域；最终时间仍必须来自真实 PPG 模板相关峰。

## 安全条件

大偏移恢复要求：

- 模板相关度 ≥0.88；
- timing quality ≥0.74；
- 源时间偏移 < min(420 ms, 0.48×RR)；
- 恢复峰落在独立预测时间约 0.22×RR 范围内；
- 相关度明显优于普通搜索。

这些条件用于防止两个错误固件事件同时吸附到同一个真实主峰。
