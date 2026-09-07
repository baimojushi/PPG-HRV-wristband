# v0.4.0 用户叙事与研究来源细化

## 1. 目标

本轮继续沿用 v0.4.0 的研究原型状态机，不修改 PPG、RR 清洗、HRV 数值或原型评分门。

重点完成三层分离：

```text
C端叙事层
研究事实溯源层
专业工程证据层
```

C端只描述当前节律形态与一小时变化；研究事实说明“研究看的是谁、观察到什么”；内部代码、匹配度、协议计数、标志点质量继续留在专业分析页与导出文件。

## 2. 研究来源文案规范

每条来源保持一行事实，不展开成论文摘要：

```text
受试者身份 / 人数 / 关键经验背景；
与当前原型直接相关的一项观察结果。
[n] 《文献名称》 — 作者
```

Qt RichText 只把 `[n]` 做成超链接，文献名称和作者保持普通文本，方便阅读和复制。

示例：

```text
10名有Zen禅修经验者与10名无禅修经验对照，比较内向注意冥想与正常休息；
经验组冥想时LF/HF和LF标准化功率下降、HF标准化功率上升，并观察到较规则的心率振荡。
[1] 《Inward-attention meditation increases parasympathetic activity: a study based on heart rate variability》 — Shr-Da Wu, Pei-Chen Lo
```

## 3. 原型文案接口

`PROTOTYPE_DEFINITIONS` 现在同时保留：

```text
test_state
user_narrative
```

`test_state` 给测试、专业分析与导出使用；`user_narrative` 给主tab使用。两层不再共用同一句文案。

`evaluate_research_state()` 输出：

```text
primary_state.user_narrative
primary_source_ids
primary_source_facts_html
```

主tab只展示当前主模式的研究来源；专业分析页仍展示所有 ACTIVE / CANDIDATE 来源。

## 4. 一小时体验补齐

原有一小时层已经有阶段、状态分布、持续时间和转场计数，用户仍需要自行把这些数字拼成“这一小时发生了什么”。

本轮增加：

```text
state_distribution: code + name + minutes
hour_summary: 一句小时级轨迹摘要
```

`hour_summary` 优先回答：

```text
哪一种研究相似模式累计最久
最近是否发生明显转场
当前是否更多处于稳定中性
数据不足时是否暂停连续解读
```

主tab不再显示 `Q*`、`H*`、`ACTIVE`、`CANDIDATE` 或匹配度小数。

## 5. UI 信息架构

状态与趋势：

```text
Hero
过去一小时 · 节律脉络
HRV 趋势
```

专业分析：

```text
设备与信号诊断
PPG + 8秒整窗波形复核
研究原型状态机与工程匹配证据
过去一小时原型匹配轨迹
VLF / LF / HF / 中位频率
Welch PSD
SPWVD
```

新增 `narrativeText` 与 `sourceText` 两档样式，并把免责声明改为独立横条；一小时卡内部再重复一次“研究形态参照”边界。

## 6. 边界

研究原型输出始终表示 HRV / 时频形态相似性。

不从腕带数据判断：

```text
用户正在冥想
用户属于某种修行身份
冥想深度
疾病状态
医疗诊断
```

长期练习者、运动训练等身份层继续保持 `T0_TRAIT_UNKNOWN`，等待跨天历史后再启用。
