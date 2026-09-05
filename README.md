# PPG / HRV 实时分析系统 v0.3.5

v0.3.5 基于 v0.3.4 的最新实测，修复 **同一心搏内两个同极性局部峰之间的相位分支切换**。

本版修改固件，需要重新烧录。协议继续为 v4。

## 实测根因

```text
采样率                       125.0 Hz
采样 p95 抖动               0.003 ms

v0.3.4 主峰 ±40 ms 命中      32.1%
v0.3.4 >120 ms 错相位        67.9%

分支切换时 RR 异常           53.2%
非切换区 RR 异常             2.1%

主峰 Winner 平均分           0.850
次级分支 Winner 平均分       0.627
```

## 固件 v0.3.5

```text
同极性 Candidate
     ↓
等待更完整的周期未来上下文
     ↓
phase >= 1.40 才做正常 Winner
     ↓
90% morphology + 10% timing
     ↓
主峰优先
```

在同一份上传 PPG 上离线重放：

```text
v0.3.5 主峰 ±40 ms 命中      90.8%
v0.3.5 >120 ms 错相位        9.2%
RR 中位数                    832 ms
```

## 桌面 fiducial v0.3.5

- 模板等待高分主峰级 Winner 再启动；
- 普通搜索继续限定 ±120 ms；
- 失配时用独立稳健 RR 定义恢复搜索中心；
- 允许 `<0.5×RR` 的宽搜索跨过约 0.2–0.35 s 相位分支；
- 大偏移必须同时满足高模板相关和节律一致；
- 导出 `timing_recovered`；
- UI Debug 行显示“相位恢复”数量。

## 当前端到端回放

```text
Timing Quality 均值           91.5%
Timing 不稳定比例             6.2%
不确定度 p95                  14.0 ms
时域                         VALID
RMSSD                        40.023 ms
频域                         INVALID
```

频域仍保持严格质量门：

```text
未解决异常 6.1% > 5.0%；连续未解决异常 4 > 2
```

v0.3.5 先解决红框内的相位分支问题，不通过放宽频域门掩盖剩余计数异常。

## UI

```text
黄       Raw Candidate
灰       Firmware Winner
绿       HRV unified fiducial
相位恢复  跨分支模板恢复次数
```

## 导出

`beats_refined.csv` 与 `beats_cleaned.csv` 新增：

```text
timing_recovered
```

## VS Code / PlatformIO

```bash
cd firmware
pio run
pio run --target upload
pio device monitor
```

## 关键文档

```text
docs/VALIDATION_v0.3.5_PHASE_BRANCH.md
docs/ALGORITHM_v0.3.5_PHASE_BRANCH.md
docs/PATCH_v0.3.5_PHASE_BRANCH.md
docs/QUALITY_CONFIDENCE.md
```
