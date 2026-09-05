# v0.3.2 完整架构

```text
Core 1 · 125 Hz Acquisition
│
├─ ADC GPIO32
│
└─ zeezPPG
   ├─ EMA 去毛刺 / 去基线
   ├─ Signal Ring 320
   ├─ Slope Ring 320
   ├─ RR Ring 9
   ├─ Candidate Pool 16
   │
   ├─ amplitude / prominence / slope / curvature
   ├─ polarity lock
   ├─ cycle-level winner
   ├─ rescue
   │
   └─ incremental autocorrelation
       ├─ ≤4 lag / sample
       └─ ≤96 pair / lag
          ↓
       Accepted Beat
          ↓
 Sample Queue / Beat Queue
          ↓
Core 0 · Transport
          ↓
 Protocol v4 + CRC16
          ↓
Desktop Analysis
│
├─ Sample Timebase Audit
│  ├─ effective Hz
│  ├─ p95 jitter
│  └─ overrun ratio
│
├─ BeatTimelineCleaner
│  ├─ false peak merge
│  ├─ missed beat split
│  └─ unresolved skip
│
├─ Time Domain
│  └─ VALID / LIMITED / INVALID
│
└─ Frequency Domain
   ├─ PCHIP → Welch
   ├─ Linear → Welch
   ├─ Irregular NN → Lomb
   ├─ spectral cross-validation
   └─ VALID / LIMITED / INVALID
          ↓
        SPWVD
```

## 核心原则

1. 125 Hz 采样任务内不能出现突发大计算；
2. 心搏识别与 HRV 质量门职责分离；
3. LIMITED 有明确硬门和独立互证，不等于“放宽阈值”；
4. 采样时基严重失真时，所有正式时频指标停止；
5. 所有结果均保留原始 Sample / Beat 证据用于回放。
