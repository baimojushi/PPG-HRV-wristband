# PPG / HRV 实时分析系统 v0.3.1

v0.3.1 根据最新实测数据修复 **峰/谷双极性误计数**。

实测 v0.3.0：

```text
Candidate 49 / 12 s
Accepted 33 / 12 s
预测 RR 464 ms
接受 HR 172 bpm
```

导出 RR 中位数为 364 ms。隔一个 Accepted 取一个后，
两条子序列 RR 中位数约 725 / 720 ms，
对应约 82.7 / 83.3 bpm。

## v0.3.1 核心

```text
双极性 Candidate
      ↓
首个稳定 Winner
      ↓
锁定极性 +1 / -1
      ↓
同极性 Candidate 竞争
      ↓
同极性 Rescue
      ↓
Accepted Beat
```

两个稳定同极性 RR 后，RR 中位数成为主节律锚点。
明显不一致的自相关周期不再覆盖稳定 RR。

## 导出增强

“导出分析结果”新增：

```text
samples_debug.csv
beats_raw.csv
```

以后只需提供新的 `hrv_export`，即可逐采样离线重跑检测器。

## UI

```text
紫：动态形态分数
黄：Candidate（含峰/谷）
绿：同极性 Accepted Beat
```

## 协议

协议保持 v4，不改 Sample / Beat 帧格式。

## 构建

```bash
cd firmware
pio run
pio run --target upload
pio device monitor
```

## 测试

```bash
python -m pytest -q tests
```

## 文档

```text
docs/ALGORITHM_v0.3.1.md
docs/PATCH_v0.3.1_POLARITY_LOCK.md
docs/VALIDATION_v0.3.1_REAL_MEASUREMENT.md
docs/PROTOCOL.md
docs/ARCHITECTURE.md
```
