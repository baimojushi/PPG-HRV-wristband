# v0.2.2 Peak Debug Patch

## 目的

实测 UI 中：

```text
可见 PPG 主周期约 60–65 bpm
库 HR ≈ 123 bpm
异常搏比例 ≈ 50%
```

该组合高度提示“一个物理 PPG 周期内产生两个 Peak 检测段”。

本 patch 不调整：

```text
125 Hz
GPIO32
Wear = 1
PeakThresholdFactor = 11.0
RR/NN 清洗门限
```

先把检测证据直接画出来，再决定峰值算法如何修改。

## 新增实时 Debug 线

状态页的 PPG 图增加右侧独立 0/1 轴：

```text
紫线：CheezPPG getPpgPeak() 原始状态
绿线：固件实际生成 BeatFrame 的事件脉冲
```

二者都严格使用 ESP32 `t_us` 时间轴。

如果一个 PPG 主波形中看到：

```text
Peak: 0→1→0→1→0
Beat:   1   1
```

即可确认同一个生理周期被计成两次心搏。

如果 Peak 只出现一次、Beat 出现两次：

```text
Peak: 0→1→0
Beat:   1 1
```

则问题位于 acquisition.cpp 的事件生成逻辑。

## 新增 Debug 统计

PPG 图下显示：

```text
窗口秒数
Peak 上升沿数量
Peak 粗略 bpm
BeatFrame 数量
Beat 粗略 bpm
CheezPPG 库 HR
```

这些粗略 bpm 只用于 Debug，不进入正式 HRV。

## 为什么先不改阈值

CheezPPG v1.0.2 的 `detectPPGPeak()` 每个采样点判断：

```text
filtered - local_mean > factor × local_std
```

如果同一主波形的抬升段中间短暂跌回阈值以下，再次越阈时就会形成第二个 0→1 检测段。

先把 0/1 与 PPG 形状对齐，可以确定应当修：

```text
阈值滞回
最小 Peak 间隔
波峰位置确认
上升沿/下降沿状态机
```

中的哪一层。
