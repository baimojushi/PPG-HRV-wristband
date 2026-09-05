# 串口 / 蓝牙协议 v4

## 帧结构

```text
@BODY*CRC16\r\n
```

CRC：

```text
CRC-16/CCITT-FALSE
poly = 0x1021
init = 0xFFFF
```

握手：

```text
#PPGHRV,4
```

## Sample

```text
@S,seq,t_us,raw,avg,filtered,candidate,detector_score,expected_rr_ms,hr_bpm,flags*CRC
```

字段：

| 字段 | 含义 |
|---|---|
| `candidate` | 当前采样是否产生动态局部极值 Candidate |
| `detector_score` | 连续形态活跃度 0–1，工程评分 |
| `expected_rr_ms` | 当前动态周期预测 |
| `hr_bpm` | Accepted RR 中位数心率 |

`candidate=1` 不代表最终心搏。

## Beat

```text
@B,seq,t_us,rr_ms,hr_bpm,score,flags*CRC
```

`BeatFrame` 只发送最终 Accepted Beat。

flags：

```text
bit0  WEAR
bit1  FIRST
bit2  RR_HARD_INVALID
bit3  ADAPTIVE_ACCEPTED
bit4  RESCUED
```

`score` 是周期 Winner 综合评分。

## Metric

```text
@M,t_us,rmssd_ms,valid_rr_count,artifact_ratio,valid*CRC
```

ESP32 RMSSD 仅用于诊断。

## Diagnostic

```text
@D,t_us,sample_drop,beat_drop,metric_drop,sample_queue_depth,sample_queue_high_water*CRC
```

## 兼容

桌面端仍接受：

```text
v2/v3 Sample: 9 fields
v2/v3 Beat:   6 fields
```

v4：

```text
Sample: 11 fields
Beat:    7 fields
```

CRC 错误、格式错误、重同步次数与 Sample 序号缺口继续进入协议健康统计。
