# v0.4.2 Interval Artifact Rewrite

## 目标

v0.4.2 不再继续放宽/收紧 HRV gate，而是补上 v0.4.1 interval core 缺失的最后一层：

> 两个 PPG detector 同意某个光学峰，只能说明它是强波形证据；它仍需要经过 RR 序列层判断，才能进入正式 NN 时间线。

这次改动由 2026-09-10 两次静止实测直接驱动。实测中出现了两个典型反例：

- `336.004 ms + 407.998 ms = 744.002 ms`：两个 detector 都支持中间峰，但前后 RR 显示一个正常周期被额外光学峰拆成两段；
- `1296.004 ms`：附近稳定参考约 `620 ms`，更符合漏掉一搏后形成约两个周期的长间期。

v0.4.1 的 detector consensus 无法单独处理这两类情况，因此 v0.4.2 把“找波形峰”和“判断 NN 序列”彻底分开。

## 新正式链路

```text
PPG waveform
    ↓
多尺度 detector + Elgendi-like detector
    ↓
Beat consensus candidate
    ↓
Fixed-lag sequence resolver
    │  - 保留真实 single-detector candidate
    │  - 可在长间期中重新取回被第一轮拒绝的真实候选
    │  - 不凭预计 RR 创造不存在的波形峰
    ↓
Raw formal Beat / RR timeline
    ↓
IntervalArtifactClassifier
    │  - extra-peak split pair
    │  - missed-beat multiple
    │  - long-short / short-long compensating pair
    │  - hard short / hard long
    │  - isolated local outlier
    │  - coherent real rate transition
    ↓
Corrected NN timeline
    ↓
Time-domain HRV / Frequency-domain HRV
```

Firmware Accepted Beat 仍然只作为实时 HR、诊断和对照证据，不重新进入正式 HRV hard gate。

## IntervalArtifactClassifier 的约束

分类器使用前后稳健 RR 邻域建立局部节律参考，但不把历史中位数当成不可改变的真值。

### 额外峰 / 分裂周期

若相邻两个短 RR 各自明显短于局部参考，而它们的和与局部正常 RR 一致，则判断为一个周期被额外峰拆开：

```text
336 ms + 408 ms ≈ 744 ms
```

原始 Beat 不删除、不移动；审计层保存两个原始 RR。NN 时间线只产生一个合并后的 corrected NN。

### 漏搏

若一个长 RR 接近局部参考的 2 倍或 3 倍，并且拆分后的每段重新落回前后稳健节律，则在 corrected NN 中等分为 2/3 个区间。

这只是 NN 重建，不会在 raw Beat timeline 中伪造一颗“真实检测到的波形峰”。如果 sequence resolver 在原始 PPG 中保存过可信的 single-detector candidate，应优先恢复真实波形候选。

### 长短补偿对

对于一长一短、但总时间接近两个正常周期的 RR 对，分类器将其视为潜在的 fiducial phase slip / compensating pair，并保持总时长不变地重建两个 NN。

### 连续真实心率变化

旧 cleaner 的主要问题之一是：第一个局部 RR 被拒后，参考不再正常更新，后续一串真实的心率变化可能持续被标为 `local_outlier`。

v0.4.2 只有在异常 RR 被前后两个相对稳定、彼此相容的节律锚点夹住时，才把它当成孤立异常。若后续形成一串内部连续的新 RR 水平，则视为可能的真实速率转场，不制造自维持 reject cascade。

## Raw Beat 与 corrected NN 分离

正式导出现在明确保留三层：

```text
raw / refined Beat          原始正式波形心搏时间
artifact classification     这一搏/这一 RR 为什么被接受、修复或拒绝
corrected NN                用于 HRV 的 NN 时间轴
```

`beats_cleaned.csv` 新增/保留：

```text
artifact_class
artifact_confidence
artifact_reference_rr_ms
artifact_evidence

detector_support_count
detector_names
detector_consensus
detector_time_spread_ms
single_detector
sequence_rescued
firmware_unmatched
local_clipped
```

## 两份新的诊断证据链

### interval_candidate_trace.csv

记录每个成熟波形候选在 sequence resolver 中的命运：

```text
候选时间
两个 detector 各自的时间
support count
波形分数
局部 sequence fit
combined score
左右 RR gap
selected / rejected / rescued
原因
```

因此下一次若出现约 `2 × RR` 的长间期，可以直接检查：中间是否曾有一个 single-detector candidate，以及它为什么被第一轮拒绝。

### interval_artifact_trace.csv

逐 RR 记录：

```text
raw RR
局部 reference RR
robust scale
artifact class / status
是否已解决
corrected RR
拆分数量
配对 RR 的时间
confidence
原 detector evidence
local clip
原因和结构证据
revision
```

因为固定滞后窗口会随着未来几搏到来而补足证据，同一 RR 的分类可能从“暂定”升级到最终结构分类；日志用 `revision` 保留这种变化，不静默覆盖。

## 质量门语义修正

### Time-domain

已被结构层明确修复的 interval 不再因为“artifact ratio 高”本身把 RMSSD/SDNN 全部判死。

原因是 v0.4.2 的时域 RMSSD 仍然只使用**原始、连续、未修复的 metric-eligible NN pair**。corrected NN 不被拿去制造漂亮的时域数值。时域可靠性主要看：

- 是否仍有足够多原始可信 NN；
- 连续原始 NN pair 是否够；
- 是否仍存在连续未解决异常；
- 正式心搏附近是否削底/饱和；
- Transport / Beat timeline 证据是否足够。

### Frequency-domain

频率分析为了保持完整 5 分钟 tachogram，会使用 corrected NN，因此 correction load 仍然可以限制频率解释。这是有意保留的区别：

```text
Time HRV：不把 repaired NN 当测量值
Frequency HRV：可使用 repaired NN，但修复负担会降低 SpectralReliability
```

## 5 分钟窗口边界

旧逻辑从 `latest - 300 s` 之后的第一条 NN 开始取样。心搏不可能恰好落在精确 300.000 秒边界，因此成熟会话偶尔只得到 298–299 秒，被 UI 错误地退回“窗口积累中”。

v0.4.2 会保留 cutoff 之前紧邻的一条 NN 作为边界锚点，成熟滑动窗口不再因为心搏量化误差重新 BUFFERING。

## 研究层同步修复

这轮没有扩研究原型，但修掉三处会污染解释的状态逻辑：

1. **频率 baseline 只使用真正完成 5 分钟窗口的 row。** `frequency_ready=false` 的 buffering row 不再增加 baseline reference count；
2. **相似度与证据质量分开。** LIMITED 的 `0.65/0.68` 不再乘进 similarity，因此不会出现 `最高 0.65 < 门槛 0.70` 的数学死区；质量仍作为独立 evidence 字段显示；
3. **历史评分严格因果。** 每个历史时点只能使用 `t <= 当前历史时点` 的 row 和当时可建立的 baseline，不再用会话末尾 baseline 回头重算过去；
4. `A → 暂无突出 → A` 会合并成同一研究片段，不再生成“从 A 转场到 A”的摘要。

## 时间单调性

强制刷新可能先以最新 Sample 时间生成 snapshot，而下一个自动 callback 仍带着较旧的 fixed-lag Beat 时间。v0.4.2 规定 AnalysisEngine 的正式 snapshot/history/provenance 时间不允许倒退：

```text
now_us = max(callback_t_us, last_snapshot_t_us)
```

避免结束/刷新阶段出现 4–5 秒日志倒序。

## 本版没有做什么

- 没有重新把 Firmware Beat 变成 HRV 真值；
- 没有把 SensorContactQuality 再并回 BeatTimelineQuality；
- 没有靠放宽 `6 > 2` 一类阈值掩盖问题；
- 没有把 dual-detector consensus 宣称成 ECG ground truth；
- 没有修改 ESP32 固件或串口协议。

真正的绝对准确度仍需要同步 ECG / 公共 ECG-reference 数据验证。v0.4.2 解决的是已经能从实际 PPG RR 序列中确定的结构性逻辑缺陷。
