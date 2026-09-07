# v0.2.1 Patch 说明

## 1. 心搏事件级清洗

V0.2 的 `RRCleaner.clean(rr)` 每次只看一个 RR，已经被实测证明无法识别：

```text
951
639
311
824
```

其中：

```text
639 + 311 = 950
```

v0.2.1 使用 `BeatTimelineCleaner` 批量重建时间轴：

### 伪峰

```text
A ──639ms── B(false peak) ──311ms── C
              ↓ 删除

A ───────────950ms────────────── C
```

### 漏搏

```text
A ─────────1600ms───────── C
              ↓
A ──800ms── synthetic B ──800ms── C
```

### 无法可靠修复

直接：

```text
status = hard_outlier / local_outlier
metric_eligible = false
```

不再用局部中位数替换后继续计算。

## 2. 时域质量门

最近 60 个原始 RR 事件必须同时满足：

```text
accepted NN >= 40
detected_artifact_ratio <= 5%
unresolved_suspect_ratio <= 2%
max_consecutive_artifacts <= 1
SQI >= 70%
```

任何一项失败：

```text
time_status = INVALID
rmssd_ms = null / UI --
```

保留：

```text
candidate_rmssd_ms
```

只用于开发排查。

RMSSD 的正式有效窗口新增短块 bootstrap 近似 95% 区间。

## 3. SQI

V0.2 的“confidence”存在：

```text
1e-6 几何平均
+
weakest + 0.15
```

导致实测中大量结果聚集在约 18%。

v0.2.1 删除该概率式命名。

SQI 采用透明加权分量：

| 分量 | 权重 |
|---|---:|
| PPG 削底/饱和 | 45% |
| 佩戴 | 20% |
| 采样时基 | 15% |
| Sample 序号连续性 | 10% |
| 协议完整性 | 10% |

输出：

```text
sqi
VALID / LIMITED / INVALID
reasons[]
```

SQI 是工程数据质量分，不是概率。

## 4. 协议 v3

固件：

```text
#PPGHRV,3
@S,...*CRC16
@B,...*CRC16
@M,...*CRC16
@D,...*CRC16
```

CRC：

```text
CRC-16/CCITT-FALSE
poly 0x1021
init 0xFFFF
```

桌面端改为字节流解析：

```text
read(4096)
→ 找 @
→ 找完整帧
→ CRC
→ 字段校验
→ seq 连续性
→ 坏帧重同步到下一个 @
```

仍兼容 v2，并能从部分 `S,...S,...` 粘帧中回收后续完整帧。

## 5. 频域

频域输入改为：

```text
修复后的 NN Event Timeline
→ PCHIP 4 Hz
→ detrend
→ Welch
→ Lomb–Scargle 形状交叉验证
```

频域质量门：

```text
5分钟窗口完整
5分钟 PPG SQI >= 75%
修复事件比例 <= 5%
未解决异常 <= 1%
协议错误 <= 1%
```

新增指标：

```text
Total Power
VLF
LF
HF
LFnu
HFnu
LF/HF
HF/LF
```

会话统计：

```text
mean
median
std
P25
P75
min
max
valid_window_ratio
```

## 6. SPWVD

SPWVD 只在频域质量门通过后运行。

SPWVD 继续用于时频结构显示，
VLF/LF/HF 绝对功率统一使用 Welch，不再对截断后的 Wigner-Ville 图做绝对功率统计。

## 7. 导出一致性

`export_bundle()` 在同一锁内冻结：

```text
snapshot
beats
NN timeline
hrv history
frequency stats
protocol health
```

避免 V0.2 中：

```text
hrv_windows.csv != summary.json
```

导出新增：

```text
nn_intervals.csv
frequency_statistics.json
frequency_statistics.csv
protocol_health.json
export_snapshot.json
```

## 8. 本次用户数据回放

见：

```text
docs/VALIDATION_v0.2.1_USER_EXPORT.md
```
