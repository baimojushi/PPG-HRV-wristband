# v0.3.5 完整架构

```text
Core 1 · Acquisition @125 Hz
│
└─ zeezPPG
   ├─ dynamic morphology
   ├─ raw Candidate
   ├─ same-polarity Peak Complex
   ├─ incremental autocorrelation
   ├─ independent rhythm phase
   ├─ delayed decision @ ~1.40×RR
   ├─ morphology-dominant Winner
   └─ Rescue
          ↓
   Firmware Accepted Beat
          ↓
Protocol v4
          ↓
Desktop
│
├─ TemplateFiducialRefiner
│  ├─ high-score bootstrap
│  ├─ normal ±120 ms search
│  ├─ rhythm-centered recovery
│  ├─ <0.5×RR source-wide recovery
│  └─ high-correlation + rhythm-consistency gate
│       ↓
│   Unified HRV fiducial
│
├─ Beat Timing Quality
├─ BeatTimelineCleaner
├─ Time Domain
└─ Frequency Domain
```

## 三种时间语义

### 节律相位
描述下一搏大致应该出现的周期位置。

### 固件 Winner
描述固件认为本周期最强的实际候选。

### HRV fiducial
描述经过完整 PPG 模板统一后的时间标志点。

三者分开维护，避免一个局部峰选错后把下一周期和 HRV 时间轴同时拖偏。
