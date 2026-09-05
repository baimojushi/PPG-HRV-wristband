# PPG / HRV 实时分析系统 v0.3.4

v0.3.4 基于 v0.3.3，针对最新实机波形中 **Accepted Beat 在宽峰内漂移** 与 **周期窗口相位漂移导致漏检** 两个问题升级。

本版同时修改 ESP32 固件和桌面端，需要重新编译并烧录固件。

## 当前链路

```text
125 Hz PPG
   ↓
动态 Candidate
   ↓
同极性 Peak Complex 合并
   ↓
独立节律相位跟踪
   ↓
Firmware Winner
   ↓
协议 v4
   ↓
桌面端 PPG 模板互相关
   ↓
HRV 统一 fiducial
   ↓
Beat Timing Quality
   ↓
RR / NN / HRV
```

## 1. Peak Complex

宽峰、平顶峰上的多个同极性局部极值不会直接分别参加 Winner 竞争。

```text
cluster_window = clamp(0.28 × expected_RR, 80, 180 ms)
```

Candidate 原始脉冲仍全部保留在 UI 黄线，便于 Debug；候选池只保留每个 Peak Complex 的代表点。

## 2. 独立节律相位

上一搏 Accepted 时间不再直接作为下一周期窗口原点。

```text
predicted_next += expected_RR
```

单搏相位误差只做小增益校正：

```text
0.22 × clip(error, ±40 ms)
```

这样某一搏落在峰侧，不会把下一搏窗口整体拖走。

## 3. HRV 模板时间标志点

固件负责“该周期存在心搏”。

桌面端等待约 400 ms PPG 上下文后，在固件 Winner 附近 ±120 ms 做整段模板互相关，统一 HRV 时间相位。

模板细化不使用 RR 预测强制拉齐，因此不会人为压低真实 HRV。

低质量对齐：

```text
quality < 0.62
uncertainty > 80 ms
|shift| > 96 ms
```

会回退到固件时间，并把低质量证据交给 HRV 质量门。

## 4. Beat Timing Quality

PPG SQI 继续描述采样/传输质量。

v0.3.4 额外评价：

```text
fiducial_quality_mean
fiducial_uncertainty_p95_ms
fiducial_shift_p95_ms
fiducial_unstable_ratio
```

所以即使 SQI=100%，宽峰时间位置不稳定时，HRV 仍会下降为 LIMITED / INVALID。

## 5. UI

```text
紫       动态形态分数
黄       原始 Candidate
灰虚线   固件 Winner 原始时间
绿       HRV 统一 fiducial
```

Debug 行同时显示 fiducial 平均质量、不确定度 p95、平移 p95。

## 6. 导出

```text
samples_debug.csv
beats_raw.csv       固件 Accepted 原始证据
beats_refined.csv   HRV 模板时间标志点
beats_cleaned.csv   RR/NN 清洗结果
```

## 7. 协议

协议保持 v4，串口/蓝牙帧格式没有变化。

## 8. CNN

当前继续不加入实时 CNN。

本次错误属于 **周期相位耦合 + fiducial 不统一**。确定性相位跟踪和模板对齐可以直接解决，并且可逐搏审计。

后续 CNN 仍保留为 Candidate 形态评分器候选方案；若要用 CNN 回归 fiducial，需要同步 ECG 或等价的高精度独立时间标签。

## 构建

```bash
cd firmware
pio run
pio run --target upload
pio device monitor
```

桌面端：

```bash
cd desktop
python -m pytest -q ../tests
python run_ui.py
```

## 关键文档

```text
docs/ALGORITHM_v0.3.4_FIDUCIAL_PHASE.md
docs/VALIDATION_v0.3.4_FIDUCIAL_REPLAY.md
docs/PATCH_v0.3.4_FIDUCIAL_PHASE.md
docs/QUALITY_CONFIDENCE.md
docs/CNN_ENGINEERING_ROI_v0.3.3.md
```
