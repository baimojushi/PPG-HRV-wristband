# PPG / HRV 实时分析系统 v0.4.0

v0.4.0 从 **v0.3.9 响应式桌面版**建立。

本版不改 ESP32 固件、不改协议、不改正式 PPG / RR / HRV 算法。

新增的是：

```text
研究原型匹配层
+
过去一小时会话体验层
+
研究来源可追溯 UI
```

## 1. 主分析链保持 v0.3.9

```text
ESP32 zeezPPG
        ↓
实时 Sample + Firmware Beat
        ↓
PC 保存原始证据
        ↓
7.25 s 固定滞后整窗 PPG 复核
        ↓
正式心搏时间线
        ↓
未来感知 RR 清洗
        ↓
HR / RMSSD / Welch / Lomb / SPWVD
```

研究层位于这些正式结果之后。

## 2. 研究原型状态机

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

## 3. 文献事实注册表

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

## 4. 一小时级体验

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

## 5. 长期身份层

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

## 6. 数据质量

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

## 7. 新增导出

```text
research_prototype_snapshot.json
hour_experience.json
research_prototype_table.json
literature_sources.json
research_state_timeline.csv
```

`summary.json` 同步包含研究原型与一小时体验。

## 8. 自动验收

```text
Python compileall    PASS
pytest               90 passed
```

## 9. 固件

v0.4.0 的 `firmware/` 与 v0.3.9 保持不变。

协议：

```text
v4
```

**无需重新烧录 ESP32。**

## 10. 文档

```text
docs/RESEARCH_PROTOTYPE_STATE_MACHINE_v0.4.0.md
docs/HOUR_EXPERIENCE_v0.4.0.md
docs/COPY_AND_SOURCE_REFINEMENT_v0.4.0.md
docs/PATCH_v0.4.0_RESEARCH_HOUR.md
docs/VALIDATION_v0.4.0_RESEARCH_STATE.md
```
