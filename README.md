# PPG / HRV 实时分析系统 v0.3.7

v0.3.7 已根据 v0.3.6 人工标注数据重新设计。

上一版实验性的 `HOLD / trusted-state` 固件冻结方案已经完整撤销。项目内 ESP32 固件与用户当前 v0.3.6 固件保持字节一致。协议继续使用 v4。

## 核心结构

```text
ESP32 zeezPPG（v0.3.6 行为）
        ↓ 实时
Sample + Firmware Beat
        ↓
PC 保存原始证据
        ↓
7.25 s 固定滞后窗口
        ↓
整窗 PPG 主波解析
├─ 全窗自相关估计主周期
├─ 主波 / 次级峰竞争
├─ 长间隙低门限补峰
├─ 未来波形确认
└─ 局部抛物线波顶细化
        ↓
正式 PPG 心搏时间线
        ↓
未来感知 RR 清洗
        ↓
HR / RMSSD / 频域 HRV
```

正式 HRV 心搏不再要求 Firmware Beat 先存在。固件漏检时，PC 可以直接从完整 PPG 波形补回主波；固件多检或落到次级峰时，该事件仍保留在原始证据中，但不会自动进入正式 HRV 时间线。

## 8 秒纠错余裕

用户允许正式结果最多滞后 8 秒。

当前实时目标：

```text
固定滞后目标       7.25 s
纠错运行周期       0.20 s
工程上限           8.00 s
```

一个待提交波顶可以看到约 7.25 秒未来 PPG，相当于常见心率下后续多个完整心动周期。

周期模型只决定搜索尺度。正式时间戳仍必须落在真实 PPG 局部波顶，不会把 RR 强制写成规则等间隔。

停止采集或离线导出时，会使用已经采到的完整尾部波形完成最终离线纠错，只保留约 0.25 秒右边界保护。

## 波形图

状态页只保留两条连续视觉序列：

```text
紫线    滤波 PPG
绿线    7.25 s 固定滞后纠错后的正式心搏
```

形态分、Firmware Candidate、Firmware Winner 不再绘制，仍完整保留在 Debug 与导出数据中。

人工 F8 标注继续保留红色半透明 3 秒问题区间，不再画额外红色竖线。PPG 图网格也关闭，进一步降低人工视觉标注负荷。

PPG 画面本身也使用相同的成熟时间窗，因此紫线与绿线始终处在同一时间语义。F8 保存当前屏幕右缘对应的真实设备 `t_us`。

## 已标注历史数据回放

来源：v0.3.6 的 92,051 个 Sample、22 次 F8 标注。

```text
                              v0.3.6       v0.3.7
Timeline artifact               7.31%         0.00%
Unresolved                      4.87%         0.00%
人工问题窗含 RR artifact      18/22          0/22
频域状态                      INVALID     VALID
RMSSD                         36.16 ms     25.04 ms
```

正式整窗心搏：

```text
Firmware Beat                  904
v0.3.7 正式 Beat               918
匹配到 Firmware                864
PPG 独立补回                   54
Firmware 未进入正式时间线      40
RR 中位数                      798.1 ms
```

额外使用固定参数的整段 PPG `find_peaks` 作为离线视觉形态工程参考：

```text
视觉参考主波数                 919
v0.3.7 正式主波数              918
波顶位置差中位数               1.935 ms
波顶位置差 p95                 4.000 ms
```

这个参考只验证“PPG 中明显主波的数量和波顶位置”，没有同步心电，不能视为生理真值。新的 RMSSD 也只能说明 PPG 观测时间线内部更一致。

## 神经网络接口

当前 `FixedLagWaveformCorrector` 是确定性的数学基线。

未来可以将其中的整窗主波选择器替换为小参数视觉 Transformer / 一维时序模型：

```text
长窗 PPG
→ 主波数量
→ 波顶热力图
→ 原始 PPG 局部极值细化
→ 正式时间线
```

Engine、HRV、导出和 8 秒固定滞后接口无需重写。

## 固件

重做版 v0.3.7 没有修改 v0.3.6 固件。

如果 ESP32 仍运行 v0.3.6，无需重新烧录。

如果此前已经烧入失败版 v0.3.7 的 `HOLD/trusted-state` 固件，请用本工程 `firmware/` 重新烧录一次，把固件恢复到 v0.3.6 行为。

## 运行

```bash
cd desktop
python run_ui.py
```

固件恢复时：

```bash
cd firmware
pio run
pio run --target upload
```

## 关键文档

```text
docs/ALGORITHM_v0.3.7_FIXED_LAG_WAVEFORM.md
docs/VALIDATION_v0.3.7_FIXED_LAG.md
docs/PATCH_v0.3.7_FIXED_LAG_WAVEFORM.md
```
