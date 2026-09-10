# PPG / HRV 实时分析系统 v0.4.1

v0.4.1 从 **v0.4.0** 建立。本次冻结研究原型与普通用户 UI，集中重写
`PPG → Beat → RR → quality` 的正式间期核心。

ESP32 固件和串口协议保持不变；桌面端正式心搏时间线不再把 Firmware
Accepted Beat 当作参考真值。

## 1. v0.4.1 间期核心

```text
PPG filtered waveform
        ↓
0.5–8 Hz 稳健预处理
        ↓
┌──────────────────┬──────────────────┐
│ 多尺度峰持续性检测 │ 自适应窗口峰检测   │
│ MSPTD-style       │ Elgendi-style    │
└──────────────────┴──────────────────┘
        ↓
异构检测器共识
        ↓
7.25 s fixed-lag sequence resolver
（只在真实波形候选中消歧，不凭预计 RR 创造心搏）
        ↓
正式 Beat / RR 时间线
        ↓
RR 异常分类与清洗
        ↓
HR / RMSSD / Welch / Lomb / SPWVD
```

Firmware Beat 继续保留用于实时 HR、诊断和相位对照，但
`firmware_unmatched`、Firmware↔waveform 相位差不再进入 HRV hard gate。

质量模型拆为：

```text
TransportQuality       数据有没有丢、设备时间轴是否可靠
SensorContactQuality   佩戴、原始 ADC 削底/饱和
BeatTimelineQuality    两个独立波形检测器是否逐搏一致
SpectralReliability    5 分钟内不同频率估计方法是否一致
```

低端削底若没有发生在正式心搏标志点附近，只降低接触质量，不自动否决 RR。
Welch/Lomb 等方法不一致表示“频率解释受限”，不再反向证明 RR 时间线错误。

本版设计参考了 PPG-beats / MSPTDfast、Elgendi-style detector 与 pyPPG
Aboy++ 的公开设计原则；实现为项目内独立代码，没有复制第三方实现。

## 2. v0.4.0 研究层（保留）

研究原型、一小时体验和来源可追溯 UI 继续位于正式 HRV 结果之后。

## 3. 研究原型状态机

当前急性原型：

```text
INWARD_QUIET
RESONANCE_0P1
PHASED_VIPASSANA
TRAINED_VIPASSANA_SHIFT
AROUSAL_MEDITATION
SLOW_RECOVERY_VLF
```

状态机：

```text
Q0_BUFFERING
Q1_DATA_UNSTABLE
Q2_BASELINE_BUILDING
Q3_ANALYZABLE
Q4_STATE_CANDIDATE
Q5_STATE_ACTIVE
Q6_STATE_EXITING
```

个人基线使用当前会话的稳健 median / MAD，不使用固定人群常模。

## 4. 文献事实注册表

每个原型包含：

```text
测试状态描述
工程匹配证据
受试者身份
样本数量
实验/冥想行为
主要统计现象
作者
文献名
URL
```

UI 采用：

```text
[1] [2] ...
```

方括号数字本身为可点击超链接。

作者和文献名直接显示在编号后。

## 5. 一小时级体验

过去一小时分成：

```text
H0  0–5 min      建立时域
H1  5–10 min     建立频域与个人基线
H2  10–20 min    第一批可重复研究原型
H3  20–40 min    状态持续 / 退出 / 转场
H4  40–60 min    一小时状态分布与恢复轨迹
H5  >60 min      扩展会话
```

状态页新增：

```text
过去一小时 · 节律脉络
```

显示：

```text
已观察时间
有效覆盖率
当前研究原型
状态转场数
最长持续时间
过去一小时状态分布
研究来源
```

专业页新增 6 条研究原型匹配轨迹。

## 6. 长期身份层

v0.4.0 固定：

```text
T0_TRAIT_UNKNOWN
```

单次一小时不会自动判断：

```text
冥想经验水平
长期修行身份
运动员身份
高阶修行水平
```

后续需要跨天本地历史后再启用长期层。

## 7. 数据质量

当正式数据质量门失败：

```text
Q1_DATA_UNSTABLE
```

研究原型解释暂停。

UI 提示：

```text
保持手腕稳定
保持腕带贴合
继续积累稳定窗口
```

## 8. 导出

```text
research_prototype_snapshot.json
hour_experience.json
research_prototype_table.json
literature_sources.json
research_state_timeline.csv
```

`summary.json` 同步包含研究原型与一小时体验。

## 9. 自动验收

```text
Python compileall    PASS
pytest               105 passed
最新静止实测回放  PASS
```

同一份约 20.7 分钟静止实测，在 v0.4.0 gate 逻辑下完整 5 分钟窗口为
`0 VALID / 23 LIMITED / 23 INVALID`；v0.4.1 回放为
`22 VALID / 24 LIMITED / 0 INVALID`。最终 RR 中位数 784 ms，
相邻 RR 变化 p95 64 ms；末段原始接触质量虽受低端削底影响，
TransportQuality 仍为 VALID，BeatTimeline 双检测器一致率为 100%。

## 10. 固件

v0.4.1 的 `firmware/` 与 v0.4.0 保持不变。

协议：

```text
v4
```

**无需重新烧录 ESP32。**

## 11. 文档

```text
docs/RESEARCH_PROTOTYPE_STATE_MACHINE_v0.4.0.md
docs/HOUR_EXPERIENCE_v0.4.0.md
docs/COPY_AND_SOURCE_REFINEMENT_v0.4.0.md
docs/PATCH_v0.4.0_RESEARCH_HOUR.md
docs/VALIDATION_v0.4.0_RESEARCH_STATE.md
docs/INTERVAL_CORE_REWRITE_v0.4.1.md
docs/VALIDATION_v0.4.1_INTERVAL_CORE.md
docs/VALIDATION_v0.4.1_INTERVAL_CORE.json
```
