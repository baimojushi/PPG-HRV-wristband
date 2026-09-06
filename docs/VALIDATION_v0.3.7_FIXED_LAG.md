# v0.3.7 重做版：固定滞后整窗波形纠错验证

来源：v0.3.6 已完成人工标注的 `hrv_export.zip`。

## 1. 回放规模

```text
Sample                  92051
人工标注                22
Firmware Beat           904
正式整窗 Beat           918
回放耗时                31.12 s
```

## 2. 正式时间线不再要求 Firmware Beat 先存在

```text
匹配到 Firmware Beat    864
由 PPG 独立补回         54
Firmware 未进入正式线   40
```

因此固件漏检可以补回，固件多检 / 次级峰也可以留在原始证据中而不进入 HRV。

## 3. RR 时间线

```text
RR 中位数               798.1 ms
RR p01                  630.7 ms
RR p99                  953.1 ms
```

所有正式时间戳来自实际 PPG 局部波顶。reference RR 只控制搜索尺度，没有把时间轴写成等间隔。

## 4. v0.3.6 与重做 v0.3.7

```text
                         v0.3.6      v0.3.7

Timeline artifact          7.31%       0.00%
Unresolved                 4.87%       0.00%
Frequency                 INVALID     VALID
RMSSD                     36.16 ms    25.04 ms
```

RMSSD 的变化说明旧检测错误对逐搏差分有明显影响。
这份回放只能验证 PPG 观测时间线一致性，不能把新 RMSSD 当作 ECG 真值。

## 5. 人工标注窗口

22 个 F8 标注的前 3 秒窗口：

```text
v0.3.6 存在 RR artifact 的窗口    18/22
v0.3.7 存在 RR artifact 的窗口    0/22
```

## 6. 独立视觉形态工程参考

额外对整段 PPG 使用简单固定参数宽距 `find_peaks`，
仅用于验证“肉眼明显主波数量 / 波顶位置”，不参与在线算法：

```text
参考主波数              919
v0.3.7 正式主波数       918
时间差中位数            1.94 ms
时间差 p95              4.00 ms
```

该工程参考同样没有 ECG，不是生理真值。

## 7. 结论

本轮结果支持新的分层：

```text
Firmware zeezPPG
    = 实时证据 / 备用粗检测

7.25 s fixed-lag waveform observer
    = 正式 PPG 主波解析

HRV
    = 正式 PPG 主波时间线
```

失败版 v0.3.7 的 `HOLD 100%` 自锁路径已经从固件中完全撤销。

## 8. 难负例

v0.3.7 增加两类防“过度纠错”测试。

### 真实 RR 变化不能被拉平

构造一段具有明确波顶、RR 在约 720–910 ms 间变化的 PPG。

固定滞后观察器必须：

```text
跟随真实 PPG 波顶
保留逐搏 RR 变化
```

验收：

```text
波顶位置误差 p95 < 30 ms
正式 RR 标准差 > 45 ms
正式 RR p95-p05 > 120 ms
```

### 平滑生理 HRV 不能被 RR cleaner 正则化

构造：

```text
RR = 800 ms + 70 ms × sin(...)
```

未来感知清洗必须保留绝大多数原始 NN，
并保留明显的 RR 标准差与动态范围。

这两个测试用于约束 8 秒未来窗口：

```text
未来信息可以帮助找正确波顶
不能把生理时间线改写成 reference RR
```

## 9. 自动回归

```text
Python compileall          PASS
pytest                    72 passed
固定滞后专项测试          13 passed
```

固件目录在制包阶段做整目录字节哈希比较，
必须与用户当前 v0.3.6 完全一致。
