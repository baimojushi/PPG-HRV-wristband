# PPG / HRV 实时分析系统 v0.4.7


# PPG / HRV 实时分析系统 v0.4.8


## v0.4.8 · 焦点仪表板与联动刷选

v0.4.8 在 v0.4.7 的证据链与重采样审计基础上，重构桌面端 UI 为**单屏点选聚焦式仪表板**：

- 单屏仪表板：所有核心图块同屏可见（3×3 宽屏 / 4×2 中屏 / 9×1 窄屏），单击图块高亮、双击进入居中放大聚焦视图，Esc/返回键恢复总览；
- **链表刷选**：`trend_plot`、`prototype_score_plot`、`frequency_trend_plot` 三条时间曲线共享统一 `LinearRegionItem` 刷选区间；拖动任一曲线上的半透明区间，其他两条同步高亮，并同步更新右侧 6 个文案标签（匹配摘要、时段、心态、转场、研究匹配、频段状态）；
- **单块聚焦**：双击任意图块进入居中放大层，Esc/点击空白/右下“返回总览”恢复概览；聚焦态下仍保留刷选联动；
- 响应式三档布局：`wide` (3×3) / `medium` (4×2→3 列) / `narrow` (9×1)；窗口大小变化自动重排；
- Hero 区自动压缩，预留图块空间；`ESC` / 右下“返回总览”按钮双重保险退出聚焦；
- `linked_brushing` / `tile_focus` 状态通过 `linkage_banner` 顶部横幅同步提示，右侧提供“清除刷选”按钮；
- UI 增加 `DashboardTile` 组件（单击/双击信号、激活态样式、自适应布局）、`linkage_banner` 联动横幅、`focus_overlay` 聚焦遮罩层；
- **关键词云**与 `research_prototypes` 的关键词权重计算复用 v0.4.5 逻辑；`hour_experience`、`prototype_score`、`trend_plot`、`frequency_trend_plot`、`research_state_frame`、`psd_plot`、`tf_plot` 复用原有绘图逻辑。

设计说明：`docs/FOCUS_DASHBOARD_v0.4.8.md`；验证记录：`docs/VALIDATION_v0.4.8_FOCUS_DASHBOARD.md`。


## v0.4.7 · Beat 证据链与重采样审计加固

v0.4.7 不改变固件、协议帧格式或 v0.4.6 的 125 Hz / 31.25 Hz 采样契约；本轮只把桌面端 Beat 时间可信度、固件相位差和重采样误差拆成可审计的独立证据，避免“波形形态分高 = 时间一定准”的过度自信。

- `timing_quality` 不再直接复制 `waveform_score`，而是由波形质量、检测器时间不确定度和 Beat 来源（双检测器 / 单检测器 / 序列救援 / 低显著度救援 / 局部削底）共同形成；
- 固件 Beat 仍然只作诊断参照：大相位偏移或未匹配会进入 `firmware_alignment_*`，**不会**单独把 v0.4.1+ 的正式波形 Beat 时间线判坏；
- `beats_refined.csv` / `beats_cleaned.csv` / Beat provenance 额外导出时间质量分量和原因字符串，便于追到具体哪一拍为什么降级；
- v0.4.6 的蓝牙带限重采样增加输入步长、实际重采样比以及“回投影到原始 31.25 Hz 样本时”的 RMS / 最大误差，能区分重采样失真与接触/基线/检测器状态变化；
- 20 秒 `hrv_window_provenance.csv` 现在比较当前窗口与紧邻的前一个非重叠窗口，输出固件匹配率、相位偏移 p95、Timing Quality 的前后变化，并附正式时域/频域状态与拒绝原因；
- 新增 6 个边界测试，覆盖干净双检测器、单检测器+序列救援、约 330 ms 固件相位偏移、固件缺失、31.25→125 Hz 重采样审计和窗口突变证据；完整测试集合为 153 项。

设计说明：`docs/EVIDENCE_HARDENING_v0.4.7.md`；验证记录：`docs/VALIDATION_v0.4.7_EVIDENCE_HARDENING.md`。


## v0.4.6 · 日常佩戴采样契约与间期覆盖

v0.4.6 优先修复办公室日常佩戴中“几乎所有窗口都不过”的根因，不改固件协议格式，也不回退 v0.4.5 的研究案例库与动态状态关键词云。

- 正式区分 **125 Hz 设备原始采样时钟** 与蓝牙约 **31.25 Hz 接收波形流**；稳定 `seq +4 / t_us +32 ms` 不再被误判成 75% 丢包和 24 ms 时基抖动；
- `ProtocolStreamDecoder` 按已识别发送步长计算真实缺帧，蓝牙 `+8` 只表示少 1 个应转发帧；
- 规则降采样波形先在实际采样率完成 0.5–8 Hz 预处理，再通过带限重采样回到约 125 Hz 的 Beat 分析网格；同时保留原始 31.25 Hz 带来的约 16 ms 标志点分辨率下限；
- interval core 的候选 `seq` 与局部削底检查改为按时间映射回真实收到样本，避免重采样后错用数组下标；
- 日常佩戴频域门改为“5% 以内可严格、5–15% 修复负担最多 LIMITED、超过 15% INVALID”，未解决异常和连续异常硬门不放宽；
- 新增 `direct_interval_ratio` / `usable_interval_ratio`，把“有多少原始间期直接可信”和“含可靠修复后有多少覆盖”分开审计；
- 固件目录未修改，现有 ESP32 **不用重新烧录**。

设计说明：`docs/DAILY_WEAR_SAMPLING_CONTRACT_v0.4.6.md`；验证记录：`docs/VALIDATION_v0.4.6_DAILY_WEAR.md`。


## v0.4.5 · 动态状态关键词云

v0.4.5 在 v0.4.4 的包容式研究匹配上新增一层面向普通用户的语义可视化，不改动 Beat / RR / HRV 核心计算与固件。

- “更多细节”页把研究轨迹明确标成“节律心态匹配度 · 过去一小时”，并在其下加入动态关键词云；
- 每个研究形态维护一组经过通俗化转译的中文状态短句，不直接把欧美冥想术语或论文术语丢给用户；
- 关键词权重主要由当前 `case_similarity` 决定，相同语义被多个高相似研究形态共同支持时会累积变大；
- `state_strength` 只做轻微稳定化，数据质量不会反向改写“像不像”的语义权重；
- 关键词云最多展示 12 个语义，字号和透明度平滑过渡，状态刷新时不会突然整块跳变；
- UI 明确提示：词云描述的是研究中出现过的相似节律语义，不是对用户心情的诊断。

设计说明见 `docs/SEMANTIC_KEYWORD_CLOUD_v0.4.5.md`，验证记录见 `docs/VALIDATION_v0.4.5_SEMANTIC_KEYWORD_CLOUD.md`。

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

## v0.4.9 Dashboard 修复

本版本修复 v0.4.8 Dashboard 启动与九宫格、双击聚焦、三曲线刷选和联动文案的实现缺陷。详情参见 `v0.4.9-RELEASE-NOTES.md`。
