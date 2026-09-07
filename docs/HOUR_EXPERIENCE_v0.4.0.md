# v0.4.0 一小时级产品体验

## 1. 原缺口

v0.3.9 已经能很好回答：

```text
此刻 HR / RMSSD
最近 5 min 频域
VLF / LF / HF 趋势
Welch / SPWVD
```

一小时使用中仍缺少：

```text
我已经戴了多久？
前 10 分钟与后 40 分钟分别在做什么？
某个状态是刚出现还是持续了很久？
过去一小时发生过多少次状态转场？
哪个状态最稳定？
数据不稳占了多长时间？
什么时候才能开始形成更深的解释？
```

v0.4.0 增加一个独立的 Hour Experience Layer。

## 2. 会话阶段

| 阶段 | 时间 | 产品能力 |
|---|---:|---|
| `H0_ACQUIRING` | 0–5 min | 建立时域和数据质量 |
| `H1_BASELINE` | 5–10 min | 第一组频域结果 + 个人近期基线 |
| `H2_FIRST_PATTERN` | 10–20 min | 开始形成研究原型候选 |
| `H3_TRAJECTORY` | 20–40 min | 观察持续、退出与转场 |
| `H4_HOUR_SCALE` | 40–60 min | 形成一小时状态分布和恢复轨迹 |
| `H5_EXTENDED` | >60 min | 一小时模型完整运行，继续扩展会话 |

UI 同时显示：

```text
已观察分钟
有效数据覆盖率
距下一阶段时间
```

## 3. 过去一小时状态时间轴

每个约 20 s 的指标窗口保存：

```text
quality_multiplier
primary_code
primary_score
score_INWARD_QUIET
score_RESONANCE_0P1
score_PHASED_VIPASSANA
score_TRAINED_VIPASSANA_SHIFT
score_AROUSAL_MEDITATION
score_SLOW_RECOVERY_VLF
```

专业页绘制 6 条研究原型匹配轨迹。

## 4. 一小时摘要

自动计算：

```text
每个状态累计分钟
研究状态转场次数
最长连续研究状态
数据不稳累计分钟
有效覆盖率
当前研究状态
```

状态页新增：

```text
过去一小时 · 节律脉络
```

用户即使不进入专业分析页，也能知道当前会话已经积累到什么深度。

## 5. 为什么现在不做跨天身份判断

一小时能观察“状态”。

不能仅凭一小时自动判断：

```text
长期练习水平
冥想身份
运动训练身份
高阶修行水平
```

因此 v0.4.0 长期层固定：

```text
T0_TRAIT_UNKNOWN
```

后续 0.4.x 如果增加本地跨会话档案，再启用：

```text
ENTRY_LATENCY
STATE_STABILITY
STATE_DURATION
REPRODUCIBILITY
FLEXIBILITY
```
