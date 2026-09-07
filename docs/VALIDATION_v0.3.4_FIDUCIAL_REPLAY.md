# v0.3.4 心搏相位 / 时间标志点验证

## 实测问题

最新实机截图显示两类剩余误差：

1. 同一生理 PPG 主峰中，固件 Accepted 时间有时靠近峰顶，有时落在峰侧；
2. 某些周期 Candidate 很多，真实主峰仍可能因为上一搏时间误差带动下一周期窗口漂移而漏检。

这类问题对平均心率影响较小，对 RR 差分和 RMSSD 影响明显。

## v0.3.4 数据链

```text
固件
Candidate 原始局部极值
    ↓
同极性 Peak Complex 合并
    ↓
独立节律相位跟踪
    ↓
Firmware Winner
    ↓
协议 v4（不变）
    ↓
桌面端等待约 400 ms PPG 上下文
    ↓
整段波形模板互相关
    ↓
统一 HRV fiducial
    ↓
Beat Timing Quality
    ↓
RR / NN / HRV
```

## 独立相位跟踪

上一搏 Accepted 不再直接成为下一周期时间窗原点。

```text
predicted_beat_t += expected_RR
```

当前 Winner 只做小增益相位校正：

```text
phase_error = accepted_t - predicted_t
bounded_error = clip(phase_error, -40, +40 ms)
phase_correction = 0.22 × bounded_error
```

单搏晚 80 ms 的测试中，下一目标额外移动不超过约 10 ms。

## Peak Complex 合并

同极性 Candidate 在动态窗口内合并：

```text
cluster_window = clamp(0.28 × expected_RR, 80, 180 ms)
```

宽峰内部优先保留真正的幅值极值，形态分只做幅值接近时的第二裁判。

自动测试中，同一宽峰的 3 个同极性局部极值只保留 1 个 Peak Complex 代表点。

## 桌面端模板时间标志点

模板窗口：

```text
-280 ms ... +280 ms
```

在固件 Winner 附近：

```text
±120 ms
```

搜索整段 PPG 波形与高质量模板的最佳相关平移，再用三点抛物线细化相关峰。

它不使用 RR 预测去拉齐时间戳，避免人为降低真实 HRV。

### 低质量保护

以下任一情况出现时，不应用模板平移：

```text
单搏 timing quality < 0.62
相关峰 uncertainty > 80 ms
|shift| > 96 ms
```

固件原时间保留，低质量证据继续进入 HRV 质量门。

## 旧实测导出回放

只使用 `samples_debug.csv` 实际覆盖范围内的固件 Beat：

```text
固件 Beat                  455
HRV Beat                   455
成功模板细化               438
低质量回退                 17

原 RMSSD                    20.736 ms
细化后 RMSSD                19.642 ms
HR                          89.16 bpm
时域状态                    VALID

Fiducial 平均质量           93.7%
不确定度 p95                12.0 ms
实际应用平移 p95            8.6 ms
低质量时间标志点比例        3.7%

时间线未解决异常            0.66%
最大连续异常                1
频域状态                    VALID
稳健 Welch/Lomb             95.0%
```

该导出本身已经属于较稳定数据，所以模板细化只把 RMSSD 从约 20.74 ms 调整到约 19.64 ms，没有大幅改变心率和频谱。

## 人工时间漂移测试

固件时间人为加入：

```text
-64, +48, +72, -40, 0 ms
```

循环抖动后，模板对齐时间误差 p95 保持在 8 ms 内。

## 质量语义

PPG SQI=100% 只表示采样/传输质量很好。

v0.3.4 新增独立 Beat Timing Quality：

```text
模板相关质量
相关峰宽度 / 时间不确定度
低质量 fiducial 比例
```

时间标志点不稳定时，HRV 会下降为 LIMITED / INVALID，即使 PPG SQI 仍为 100%。
