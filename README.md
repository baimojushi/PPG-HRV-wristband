# PPG / HRV 实时分析系统 v0.4.4

## v0.4.4 · 研究案例库与包容式匹配

v0.4.4 保留 v0.4.2 的 Interval Artifact Core 和 v0.4.3 的长时间状态模型，
本轮只解决“正常采集到 15 分钟仍然没有用户结论”的产品层缺口。

核心变化：

- 文献注册表从 8 条扩展到 16 条，加入慢呼吸、自我关怀、认知任务、压力后恢复、情绪调节及荟萃分析等来源；
- 新增“平稳而均匀 / 起伏整体变强 / 起伏整体收窄 / 安抚下来 / 进入专注状态 / 从紧绷中回弹 / 混合过渡中”等日常节律形态；
- 把 `case_similarity`、`match_confidence`、`state_strength` 三个概念拆开；数据质量只降低可信程度，不再改变生理相似度；
- 缺失特征不再当作“正好处在个人常态”；
- 个人参照分为 `PROVISIONAL` 和 `MATURE` 两级；正常连续采集约 15 分钟后必须给出第一版稳定节律结论；
- 短时信号异常时保留最近可靠结论，不再把长期观察结果瞬间清零；
- 主界面采用 Top-K 最近研究案例，研究文献只作形态参照，不推断用户的心理诊断或冥想身份。

完整设计与验证见：

- `docs/RESEARCH_CASE_LIBRARY_AND_MATCHING_v0.4.4.md`
- `docs/VALIDATION_v0.4.4_RESEARCH_CASE_LIBRARY.md`


v0.4.2 从 **v0.4.1 interval core** 建立。本版不再继续调 HRV gate 数字，
而是补齐 `Beat consensus → RR sequence → corrected NN` 的结构性异常层。

ESP32 固件和串口协议保持不变；Firmware Accepted Beat 继续只作诊断。
两个 PPG detector 的一致也只作为波形证据，正式 NN 还必须经过序列级审核。

## 1. v0.4.2 序列异常层

```text
双 detector 波形候选
        ↓
fixed-lag sequence resolver
        ↓
raw formal Beat / RR
        ↓
IntervalArtifactClassifier
        ├─ extra-peak split / merge
        ├─ missed-beat multiple
        ├─ long-short compensating pair
        ├─ isolated unresolved outlier
        └─ coherent real rate transition
        ↓
corrected NN timeline
        ↓
时域 / 频率 HRV
```

核心原则：

- 双 detector 同意不再自动等于“这一搏一定正确”；
- single-detector 候选不会在第一轮拒绝后丢失，长间期可由 sequence resolver 重新审查真实波形候选；
- raw Beat 时间戳永久保留，修复只发生在独立的 corrected NN 层；
- 已解决的结构异常与 unresolved evidence 分开计数；
- 时域 HRV 只使用原始连续可信 NN pair，不用修复值制造 RMSSD；
- 频率分析可使用 corrected NN，因此修复负担仍会降低 SpectralReliability。

v0.4.2 同时修复成熟 5 分钟窗口边界、研究 baseline 提前建立、LIMITED
相似度数学死区、历史研究轨迹使用未来数据，以及分析时间戳倒退。

## 2. v0.4.1 间期核心

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

## 3. v0.4.0 研究层（保留）

研究原型、一小时体验和来源可追溯 UI 继续位于正式 HRV 结果之后。

## 4. 研究原型状态机

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

## 5. 文献事实注册表

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

## 6. 一小时级体验

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

## 7. 长期身份层

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

## 8. 数据质量

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

## 9. 导出

```text
research_prototype_snapshot.json
hour_experience.json
research_prototype_table.json
literature_sources.json
research_state_timeline.csv
```

`summary.json` 同步包含研究原型与一小时体验。

## 10. 自动验收

```text
Python compileall    PASS
pytest               119 passed
v0.4.1 → v0.4.2 两份长实测 interval A/B replay  PASS
```

`20260910_135448`：旧 cleaner 的最大连续异常为 6，v0.4.2 最大连续
**未解决**异常降为 1；20 秒级时域回放从 `86 VALID / 7 LIMITED / 17 INVALID`
变为 `95 VALID / 0 LIMITED / 15 INVALID`，剩余末段 INVALID 主要来自正式心搏峰附近真实 clipping。

`20260910_152745`：v0.4.2 在同一条 formal PPG Beat 时间线上识别并修复
`336.004 + 407.998 = 744.002 ms` 的 extra-peak split，以及 `1296.004 ms`
的 missed-beat multiple；unresolved ratio 从约 0.240% 降至约 0.040%。

这些实测没有同步 ECG，因此以上结论验证的是结构逻辑和 gate 行为，不能替代 ECG ground truth。

## 11. 固件

v0.4.2 的 `firmware/` 与 v0.4.1 保持不变。

协议：

```text
v4
```

**无需重新烧录 ESP32。**

## 12. 文档

```text
docs/RESEARCH_PROTOTYPE_STATE_MACHINE_v0.4.0.md
docs/HOUR_EXPERIENCE_v0.4.0.md
docs/COPY_AND_SOURCE_REFINEMENT_v0.4.0.md
docs/PATCH_v0.4.0_RESEARCH_HOUR.md
docs/VALIDATION_v0.4.0_RESEARCH_STATE.md
docs/INTERVAL_CORE_REWRITE_v0.4.1.md
docs/VALIDATION_v0.4.1_INTERVAL_CORE.md
docs/VALIDATION_v0.4.1_INTERVAL_CORE.json
docs/INTERVAL_ARTIFACT_REWRITE_v0.4.2.md
docs/VALIDATION_v0.4.2_INTERVAL_ARTIFACT.md
docs/VALIDATION_v0.4.2_INTERVAL_ARTIFACT.json
```

## 13. ECG / 公开数据基准验证

v0.4.1 现在包含独立于 UI / 研究原型 / Firmware Beat 的 interval benchmark：

```text
同步 PPG + ECG / 参考 R-peak
        ↓
双 ECG QRS detector 共识（若已有参考标注则直接使用）
        ↓
ECG→PPG 脉搏传导延迟 / 慢漂移对齐
        ↓
生产版 v0.4.1 IntervalCore
        ↓
Sensitivity / PPV / F1
RR MAE / p95 / correlation
RMSSD / SDNN error
执行时间 / real-time ratio
```

默认采用 ±150 ms beat correctness tolerance，并允许每 300 s 重新估计 ECG→PPG
lag。没有把任何单次实测阈值硬编码成科学验收标准；CI 阈值必须显式指定。

内置：

```bash
cd desktop
python -m hrv_app.benchmark synthetic
python -m hrv_app.benchmark bidmc --records 01-05
```

`bidmc` 会直接缓存 PhysioNet 开放的 BIDMC CSV（53 条、每条 8 min、125 Hz、
同步 PPG + ECG）。另外支持 `csv-pair` 用于腕带与外部 ECG 同步实测，以及 `npz`
用于已有参考 R-peak 的离线回放。详见：

```text
docs/ECG_PUBLIC_BENCHMARK_v0.4.1.md
```
