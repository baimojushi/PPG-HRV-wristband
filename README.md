# PPG / HRV 实时分析系统 v0.3.2

v0.3.2 根据最新实测 `samples_debug.csv` 修复采样任务周期性阻塞，
并让时域 / 频域从“全有或全无”升级为可审计的三级结果。

## 本次实测根因

```text
目标采样率            125 Hz
实际有效采样率        85.86 Hz
p95 采样抖动          58.09 ms
长停顿比例            6.26%
长停顿间隔            ≈66 ms
长停顿周期            每 16 samples
```

固件恰好每 16 samples 执行一次完整自相关扫描。

v0.3.2 已将其改为：

```text
每 sample 最多 4 lag
每 lag 最多 96 pair
```

避免在采集核心形成 50–60 ms 的计算尖峰。

## 心搏链

```text
PPG
↓
动态形态 Candidate
↓
同极性锁
↓
周期内 Winner
↓
Rescue
↓
Accepted Beat
↓
RR / NN
```

## 采样时基监控

UI Debug 行会直接显示：

```text
采样 xx.x Hz
p95抖动 x.x ms
超时 x.x%
```

下一轮首要验收：

```text
有效采样率 ≈125 Hz
p95 抖动 <2 ms（优先目标）
超时比例接近 0
```

## 时域

```text
VALID
LIMITED
INVALID
```

LIMITED 仍然只用原始、连续、未修复 NN 对计算 RMSSD。

## 频域

输出前同时验证：

```text
PCHIP → Welch
Linear → Welch
Irregular NN → Lomb–Scargle
```

硬门：

```text
采样 p95 >4 ms → INVALID
Welch/Lomb <70% → INVALID
插值一致性 <95% → INVALID
```

少量孤立 RR 异常可以在双谱互证通过后以 LIMITED 输出。

## 协议

仍为 v4，无协议字段变化。

## 构建

```bash
cd firmware
pio run
pio run --target upload
pio device monitor
```

## Python

```bash
cd desktop
python -m pytest -q ../tests
python run_ui.py
```

## 关键文档

```text
docs/ALGORITHM_v0.3.2.md
docs/PATCH_v0.3.2_SAMPLING_AND_HRV_QUALITY.md
docs/VALIDATION_v0.3.2_REAL_MEASUREMENT.md
docs/ARCHITECTURE.md
docs/PROTOCOL.md
```


## 当前自动验收

```text
Python compileall     PASS
pytest                38 passed
C++ detector host     PASS
Arduino wrapper stub  PASS
```

PlatformIO 全固件编译需要在安装了 PlatformIO CLI 的 VS Code 开发机执行。
