# v0.4.6 日常佩戴采样契约与间期覆盖

## 1. 这版解决什么

办公室日常佩戴实测暴露出一个比“动作伪迹”更靠前的系统问题：设备内部采样时钟是 **125 Hz**，但固件蓝牙路径为了避免发送队列阻塞，会按 `BT_SAMPLE_DECIMATION = 4` 只转发每 4 个 PPG 样本中的 1 个。于是桌面端实际收到的波形流约为 **31.25 Hz**，其 `seq` 仍然属于 125 Hz 原始采样时钟：

```text
source seq:   0, 1, 2, 3, 4, 5, 6, 7, 8 ...
Bluetooth S:  0,          4,          8 ...
t_us:         0 ms,       32 ms,      64 ms ...
```

v0.4.5 以前的质量层把收到的每个 `S` 帧都假定为 `seq + 1 / 8 ms`，因此会把完全规则的 `+4 / 32 ms` 错判为约 75% 丢样，并把 `32 - 8 = 24 ms` 当成采样时基抖动。这个误判会让 TransportQuality 整窗 INVALID，继而把时间域、频域和研究解释层一起截断。

v0.4.6 把“设备原始采样时钟”和“传输后收到的波形流”正式拆开。

## 2. 新采样契约

新增 `hrv_app.sampling_contract`，同时使用 `seq` 与 `t_us` 推断：

- `source_sample_rate_hz`：设备原始采样时钟；
- `received_sample_rate_hz`：桌面端实际收到的波形流速率；
- `sample_stride`：相邻收到帧对应的原始样本步长；
- `sample_stride_confidence`：该步长在当前窗口内的稳定程度；
- `intentional_decimation`：是否满足稳定规则抽样条件；
- `sequence_drop_ratio`：相对已识别发送步长的真实缺帧比例；
- `timing_jitter_p95_ms`：相对 **`Δseq × 8 ms`** 的时基残差，而不是相对固定 8 ms；
- `timing_overrun_ratio`：真正的设备时间轴异常比例。

因此：

```text
seq +4, t +32 ms  -> 正常规则抽样，残差 0 ms
seq +8, t +64 ms  -> 少收到 1 个蓝牙转发帧，但设备时钟仍正常
seq +1, t +66 ms  -> 真实采样停顿，残差约 58 ms
```

只有稳定重复、且 `seq/t_us` 反推的源采样率仍接近 125 Hz 时，`stride > 1` 才被接受为规则抽样。随机 USB 缺口不会因为单次跳号就自动被解释成降采样。

## 3. 协议健康不再把规则抽样算成丢包

`ProtocolStreamDecoder` 现在累计相邻 `seq` 步长分布。稳定 `stride=4` 后：

- `+4` 记为完整收到一个应转发帧；
- `+8` 记为少 1 个应转发帧；
- `sample_seq_gaps` 不再把 `+4` 解释为少 3 帧。

新增可审计字段：

```text
sample_seq_stride
sample_stride_confidence
intentional_sample_decimation
```

协议版本仍是 v4，帧格式没有改变；已有固件无需重新烧录。

## 4. 31.25 Hz 波形如何继续做 Beat / RR

仅修 TransportQuality 还不够。31.25 Hz 的原始时间网格每点约 32 ms，如果双检测器直接在这个网格上提交波顶，逐搏时间会受到明显量化，RMSSD 尤其容易被放大。

v0.4.6 在 `preprocess_ppg()` 中加入受约束的带限重采样：

1. 仍先在**真实接收采样率**上完成 0.5–8 Hz 预处理；
2. 只有采样契约明确识别为规则降采样，且接收率至少 25 Hz 时才进入重采样；
3. 使用 `scipy.signal.resample_poly` 将已限带波形重建到约 125 Hz 的分析网格；
4. 两个独立波形检测器继续在同一分析网格上工作；
5. 最终候选时间映射回最近的真实收到样本来取得 `seq` 与削底证据；
6. 标志点不确定度保留原始采样分辨率下限：31.25 Hz 时至少约 `0.5 × 32 = 16 ms`，不会因为插值就假装拥有 125 Hz 原生测量精度。

这一步不是把 31.25 Hz 变成新的生理信息。它只在原波形已经限带、Nyquist 仍覆盖 0.5–8 Hz 检测带宽的前提下，恢复更细的连续时间峰位估计，避免把规则传输抽样的 32 ms 网格直接写进 RR 差分。

## 5. 日常佩戴不再把“可修复”直接等于“不可用”

频域质量继续保留严格模式：

```text
corrected_ratio <= 5%       -> 有机会 VALID
5% < corrected_ratio <=15%  -> 最多 LIMITED
corrected_ratio > 15%       -> INVALID
```

未解决异常的硬门没有放松：

```text
unresolved_suspect_ratio <= 5%
max_consecutive_unresolved <= 2
```

并新增两个审计量：

- `direct_interval_ratio`：频域 NN 中未经修复的直接间期比例；
- `usable_interval_ratio`：计入可解释修复后，相对当前未解决异常的可用覆盖。

这样办公室里偶发抬手、打字、拿杯子造成的孤立伪迹，可以明确降级为 LIMITED，而不是只因为修复比例从 8% 越到 9% 就把整个 5 分钟窗口抹掉。真正连续、未解决的异常仍会拒绝输出。

## 6. 层级顺序

v0.4.6 的判定顺序明确为：

```text
设备原始采样时钟 / 接收流契约
            ↓
真实传输完整性与时间轴
            ↓
带限波形分析网格
            ↓
Beat / RR 独立质量
            ↓
日常佩戴可用间期覆盖
            ↓
时间域 / 频域 HRV
            ↓
研究案例匹配与状态关键词
```

研究层和 v0.4.5 关键词云本身没有改变；它们只是终于不会被一个错误的 125/31.25 Hz transport gate 提前截断。

## 7. 兼容性

- 固件：**未修改**；
- 协议帧格式：**未修改**；
- v2/v3/v4 解析：保持兼容；
- USB 125 Hz 全速流：继续 `stride=1`；
- 蓝牙约 31.25 Hz 规则流：识别为 `stride=4`；
- 真实设备时钟停顿：仍保持 INVALID；
- 研究案例库与动态状态关键词云：保留 v0.4.5 行为。
