# v0.4.1 Interval Core Validation

## 自动测试

```text
python -m pytest -q
105 passed
```

`compileall` 另行执行并要求通过。

## 最新静止实测回放

回放源：本轮问题定位使用的 `hrv_export/raw_session`。

规模：

```text
PPG samples        155146
session duration   1241.224 s
Firmware beats     1527
```

同一份输入在上传基线与 v0.4.1 间期核心上离线重放。

### 上传基线

```text
formal beats                1586
最终时域                    INVALID
最终频率                    INVALID
最终失败原因                SQI 56% < 75%

完整 5 min 窗口：
VALID                       0
LIMITED                     23
INVALID                     23
```

### v0.4.1

```text
formal beats                1585
RR median                   784.0 ms
RR min / max                552.002 / 1136.0 ms
adjacent RR delta p95       64.0 ms

Timeline raw RR             1584
accepted NN                 1583
unresolved ratio            0.063%
dual-detector ratio         100%
single-detector ratio       0%
detector spread p95         0 ms
sequence rescue ratio       0%
local fiducial clip ratio   0%
firmware-unmatched ratio    12.25%

TransportQuality            VALID
transport score             0.9989

SensorContactQuality        INVALID
contact score               0.5165
legacy SQI                  0.6649
raw clip-low ratio          14.88%

最终时域                    VALID
最终频率                    LIMITED
频率受限原因                Welch/Lomb 89%；频带一致性 83%
```

完整 5 min 窗口：

```text
VALID                       22
LIMITED                     24
INVALID                     0
```

这次回放验证了关键架构目标：

1. 原始波谷削底仍会如实降低 SensorContactQuality；
2. 但正式心搏附近没有局部削底，两个独立 PPG detector 对逐搏位置高度一致；
3. 因此 RR/时域不再被 clip-heavy SQI 误杀；
4. Firmware 漏搏/相位差只作为诊断，不再反向否决正式波形 RR；
5. 频率方法意见不一致时保留结果并标记 LIMITED，而不是把 BeatTimeline 判错。

## 结论边界

这不是 ECG ground-truth 验证。当前结果只证明：

> 对这份静止 PPG，新的正式间期链能够在传感器接触质量下降时保持双检测器一致，
> 并消除旧 gate 的系统性误杀。

下一阶段必须增加同步 ECG / validated PPG datasets，用 sensitivity、PPV、F1、
RR MAE 和 HRV error 校准 detector consensus 与 sequence-rescue 阈值。
