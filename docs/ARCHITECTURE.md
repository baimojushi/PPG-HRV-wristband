# v0.3.4 完整架构

```text
Core 1 · Acquisition @125 Hz
│
├─ ADC / PPG filtering
│
└─ zeezPPG
   ├─ Signal / Slope Ring
   ├─ Dynamic morphology score
   ├─ Raw Candidate
   ├─ Same-polarity Peak Complex clustering
   ├─ Independent rhythm phase tracker
   ├─ Candidate winner
   ├─ Same-polarity Rescue
   └─ Incremental autocorrelation
          ↓
      Firmware Accepted Beat
          ↓
Core 0 · Transport
          ↓
Protocol v4 + CRC16
          ↓
Desktop
│
├─ Raw session recorder
│  ├─ samples_debug.csv
│  └─ beats_raw.csv
│
├─ TemplateFiducialRefiner
│  ├─ full-waveform cross-correlation
│  ├─ sub-sample peak interpolation
│  ├─ timing quality
│  ├─ uncertainty
│  └─ low-quality fallback
│       ↓
│   beats_refined.csv
│       ↓
├─ BeatTimelineCleaner
│       ↓
│   beats_cleaned.csv / NN
│
├─ Time domain
│  └─ VALID / LIMITED / INVALID
│
└─ Frequency domain
   ├─ Welch(PCHIP)
   ├─ Welch(linear)
   ├─ Lomb–Scargle
   ├─ robust spectral cross-validation
   └─ SPWVD
```

## 两个时间轴

### 固件时间轴

用于实时心率、心搏存在性和固件 Debug。

### HRV 时间轴

由完整 PPG 模板统一 fiducial 后产生。

两条时间轴同时保存，任何 HRV 变化都可以回溯到具体平移。

## 节律相位与 fiducial 解耦

节律预测器负责“下一搏应该大致什么时候出现”。

模板细化器负责“这一搏最终用哪个统一 PPG 相位计算 RR”。

这两个状态不互相强制，从结构上降低相位误差正反馈。
