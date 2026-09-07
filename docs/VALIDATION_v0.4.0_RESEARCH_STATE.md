# v0.4.0 研究原型与一小时体验验证

## 自动回归

当前源码树：

```text
Python compileall    PASS
pytest               90 passed
```

新增专项：

```text
文献注册表包含受试者身份 / 作者 / 文献名 / URL
[数字] 在 Qt RichText 中为超链接，文献名与作者保持普通文本
每个研究原型均包含独立 user_narrative，和工程 test_state 分层
主界面仅展示当前主原型的精简研究来源，专业分析保留完整匹配来源
0.1 Hz 窄峰结构提取
INWARD_QUIET 个人基线 + 两窗口持续门
RESONANCE_0P1 在个人基线完成前可先进入候选
40–60 min 会话阶段识别
一小时 research timeline / state_distribution / hour_summary
T0_TRAIT_UNKNOWN 长期身份门
UI 研究原型层结构
导出文件结构
```

## 隔离性

研究层只读取：

```text
AnalysisSnapshot
metric_history
Welch PSD
```

没有回写：

```text
PPG detector
fixed-lag waveform corrector
RR cleaner
HRV time metrics
HRV frequency metrics
```

因此研究原型匹配失败不会改变正式 HR / RMSSD / VLF / LF / HF。

## 工程约束

- 原型匹配度是工程相似度，不是概率；
- ACTIVE 需要连续至少 2 个更新窗口达到 0.70；
- EXITING 需要连续 2 个窗口低于 0.45；
- 数据质量失败时原型层暂停；
- 长期身份层 v0.4.0 固定关闭。
