# v0.3.0 架构

## 固件

```text
Core 1 / Acquisition
│
├─ ADC 125 Hz
│
└─ zeezPPG
   ├─ EMA 去毛刺
   ├─ 慢基线 EMA
   ├─ 脉搏 EMA
   ├─ Signal Ring 320
   ├─ Slope Ring 320
   ├─ RR Ring 9
   ├─ Candidate Pool 16
   │
   ├─ 动态形态特征
   │   ├─ amplitude_z
   │   ├─ prominence_z
   │   ├─ slope_z
   │   └─ curvature_z
   │
   ├─ Autocorrelation Rhythm Anchor
   ├─ Cycle-level Candidate Competition
   └─ Rescue Search
          ↓
       Accepted Beat
          ↓
 Sample Queue / Beat Queue
          ↓
Core 0 / Transport
          ↓
 Protocol v4 + CRC16
```

采集任务不进行字符串格式化、USB 或蓝牙输出。

## 桌面端

```text
ProtocolStreamDecoder
        ↓
Raw Session Recorder
        ↓
AnalysisEngine
        ↓
BeatTimelineCleaner
        ├─ false peak merge
        ├─ missed beat repair
        └─ unresolved skip
        ↓
Clean NN Timeline
   ├───────────────┐
   ↓               ↓
Time Gate      Frequency Gate
   ↓               ↓
RMSSD/SDNN     Welch/Lomb
pNN50          VLF/LF/HF
                   ↓
                 SPWVD
```

## 两级质量控制

第一层：

```text
zeezPPG 动态心搏检测
```

目标是从源头减少误检和漏检。

第二层：

```text
RR/NN 清洗 + SQI + 结果有效性门
```

目标是防止残余异常进入正式 HRV。

两层职责分离。HRV 质量门不会反向删除心搏事件。

## 固定内存

检测器核心没有 STL 动态容器：

```text
SignalPoint[320]
float signal_stats[320]
float slope_stats[320]
RR[9]
Candidate[16]
```

纯 C++ 核心可以脱离 Arduino 在 PC 上直接编译和测试。
