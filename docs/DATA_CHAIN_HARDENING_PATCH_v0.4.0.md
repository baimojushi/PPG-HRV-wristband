# v0.4.0 数据链加固与诊断 Patch

本补丁针对 2026-09-09 实测中两类同步出现的退化：

- 约会话 12.6 分钟后，5 分钟节律趋势由平滑变为明显折线/断续；
- 约会话 12.9 分钟后，研究相似度轨迹出现不符合语义的整组 0 值。

实测证据显示，串口错误率、设备时间轴和桌面队列都没有在故障点退化；第一处明确断点位于原始 PPG 工作点/振幅和 wear 状态。软件随后把这一输入变化放大成心搏相位歧义、频率窗口拒绝，以及 UI 上的跨空档连线和“不可评价=0%相似”的错误表达。

本补丁把“可观测性”和“最小修复”一起落地，不扩大研究原型，也不改产品面向用户的叙事体系。

## 1. 实时诊断链真正接通

原代码虽然已经有 `ProvenanceRecorder`，但 UI 创建 `SessionRecorder` 后没有把 recorder 注入 `AnalysisEngine`，因此大量溯源 CSV 实际不会产生；部分 builder 也读取了旧字段或错误字段。

现在：

- 建立实时会话时执行 `engine.attach_provenance_recorder(recorder.provenance)`；
- 关闭会话前先从 Engine detach，再关闭文件，避免关文件后继续写；
- `transport_io.csv` 记录每次主机串口 read 的 monotonic 时间、耗时、字节数、解码消息数、Sample 序号范围、设备时间范围、`in_waiting` 与协议累计错误；
- `signal_input_trace.csv` 每约 5 秒记录原始 ADC 分位数、削底比例、wear 比例与最长 no-wear、滤波振幅、设备采样时基、SQI、协议/队列状态，以及 fixed-lag 自相关与候选统计；
- `beat_detector_state.csv` 改为读取 `FixedLagWaveformCorrector.last_diagnostics`，不再长期写 0；
- `beat_provenance.csv` 区分 `inserted_by_smoother`、`timing_recovered`、`low_prominence_rescue`，并修复匹配 firmware beat 时构造不完整 `BeatFrame` 导致整行日志被异常吞掉的问题；
- `hrv_window_provenance.csv` 只统计当前窗口内 firmware beats，正确计算重建比例、绝对偏移与 signed 相邻偏移变化；
- `spectrum_5min_trace.csv` 增加频带一致性、插值一致性、两种主峰、重建负担和明确拒绝原因；
- `baseline_trace.csv`、`prototype_score_trace.csv` 改用当前 v0.4.0 的真实 baseline `features/rows` 结构；
- `causality_trace.csv` 显式标出历史评分是否使用了当前时刻之后的数据，便于后续单独处理“重绘历史”的因果性问题。

下一次实测时，通信/I/O、传感器输入、心搏重建、频率质量门和研究评分将能通过设备 `t_us` 对齐到同一条证据链。

## 2. 短时 wear 掉线不再直接摧毁整个节律先验

旧行为：只要 `wear=false`，`ZeezAdaptiveDetector::update()` 立即 `reset()`，RR ring、expected RR、自相关状态、相位和当前候选全部冷启动。

新行为分两级：

- 短时 no-wear：立即停止输出，清当前波形/候选/相位，当前 HR 置 0，但保留 RR ring、expected RR 和自相关周期先验；
- 恢复后的第一颗正式心搏只重新建立相位锚点，`rr_ms=0`，不会跨 no-wear 区间计算 RR；
- 连续 no-wear 达到 2 秒：执行完整冷启动，丢弃旧节律先验。

这样 0.25–1 秒的接触抖动不会把前面已经稳定学习的周期尺度全部清掉，同时真正摘下腕带仍会在 2 秒后彻底重置。

## 3. fixed-lag 不允许同一 firmware beat 跨调用重复消费

旧实现的 `used_firmware` 只在一次 `propose()` 内有效。发生相位歧义时，同一个 firmware Accepted Beat 可以在下一次 fixed-lag 调用中再次被另一个波形主峰匹配。

现在维护跨调用的 `consumed_firmware_t_us`；已经匹配过的 firmware beat 在仍处于上下文窗口期间不会再次被使用，离开历史窗口后自动清理集合。

## 4. “重建负担”正式进入 5 分钟频率质量门

过去的频率质量门可以看到常规 artifact、SQI、采样时基、Welch/Lomb/插值一致性，却不知道桌面端为了得到心搏时间轴到底做了多少重建。

新增三个工程指标：

- `waveform_inserted_ratio`：没有 firmware 对应事件、由波形层补出的心搏比例；
- `timing_recovered_ratio`：进入时间恢复路径的心搏比例；
- `timing_shift_delta_p95_ms`：匹配 firmware 的连续心搏之间，signed 时间修正变化量的 p95。

最后一项是主要保护门。原因是：如果每一搏都统一整体平移 250 ms，RR 基本不变；如果相邻心搏在 `+150 ms / -150 ms` 之间切换，RR 会被直接扭曲约 300 ms。

当前门限：

| 指标 | 严格输出上限 | 可接受输出硬上限 |
|---|---:|---:|
| 波形独立补搏比例 | 8% | 15% |
| 时间恢复比例 | 12% | 25% |
| 相邻时间修正跳变 p95 | 80 ms | 180 ms |

超过严格门只降为 `LIMITED`；超过硬上限则拒绝该 5 分钟频率窗口。此次实测在稳定段的相邻修正变化 p95 约 7 ms，而退化后跃升到约 285–310 ms，因此这个门针对的是非常明显的相位不稳定，不是追逐普通毫秒级抖动。

## 5. 频率图保留无效窗口为真正的“空档”

旧 UI 先删除所有 `INVALID` 行，再把剩余点直接连线。因此中间缺失 40–80 秒时会被画成一条很长的直线，形成错误的尖角和折线感。

现在 `build_frequency_trend_rows()` 保留完整历史时间轴：

- 可用点写真实值；
- 积累中/INVALID 点写 `NaN`；
- pyqtgraph 使用 `connect="finite"`，无效区间真正断开；
- 横轴从会话历史第一条记录计时，不再从第一个成功的 5 分钟频率窗口重新归零。

因此图上的 7.5 分钟不会再实际代表会话约 12.6 分钟。

## 6. “无法评价”不再画成“相似度 0%”

研究时间轴以前在质量系数为 0 时，六个原型全部得到数值 `0.0`。这会让 UI 画出垂直坠零/弹回的尖峰，而真实语义只是“这一个时间点没有足够可靠的数据做比较”。

现在：

- `quality_multiplier <= 0` 时，各 `score_*` 写 `NaN`；
- `primary_code` 仍为 `DATA_UNSTABLE`；
- UI 用 `connect="finite"` 把该段画成缺口；
- 不改变有效窗口的原型评分逻辑。

## 7. 本补丁没有做的事情

为了保持故障定位边界清晰，本补丁没有：

- 扩大研究原型库；
- 重新定义研究原型评分公式；
- 修复历史轨迹使用最终 baseline 重算过去的因果性问题，只新增 `causality_trace` 把它记录出来；
- 猜测原始 ADC 工作点变化一定来自佩戴松动。当前证据只能确认输入工作区发生变化，下一次需结合 `signal_input_trace.csv` 判断削底/wear/振幅变化，再结合硬件端增益、LED/环境光信息继续定位。

## 8. 下一次实测建议看这几个同步断点

按同一个 `t_us` 对齐：

1. `transport_io.csv`：read 是否突然变慢、批量是否堆大、`in_waiting` 是否积压；
2. `signal_input_trace.csv`：`raw_p05`、`clip_low_ratio`、`wear_ratio`、`max_no_wear_run_ms` 是否先变化；
3. `beat_detector_state.csv`：自相关置信度、reference RR、候选/最终峰数量是否跟着改变；
4. `beat_provenance.csv`：`timing_recovered`、补搏和 firmware↔waveform shift 是否开始分叉；
5. `hrv_window_provenance.csv`：相邻 shift 变化 p95 是否突然放大；
6. `spectrum_5min_trace.csv`：是重建负担门先触发，还是 Welch/Lomb/SQI 先触发；
7. `prototype_score_trace.csv`：无匹配到底是质量不可用、门限封顶还是得分本身低。

## 验证

- Python `compileall` 通过；
- 全测试套件：`99 passed`；
- C++ host 测试新增短 no-wear 保留 RR 先验、恢复首搏不跨 gap 计算 RR、长 no-wear 冷启动；
- 新增频率相位跳变硬门、无效频率绘图缺口、研究相似度 NaN、firmware beat 跨调用不可重复消费、实时 provenance/transport 落盘测试。
