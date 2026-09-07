# v0.2.3 Peak Event Gate 修复

## 1. 根因

v0.2.2 的实机调试图已经确认：

```text
Peak 上升沿数量 == BeatFrame 数量
```

而可见 PPG 主周期约为其一半。

旧固件核心：

```cpp
const bool rising_peak =
    sample.peak
    && !g_previous_peak_state;

if (rising_peak) {
    enqueueBeat(...);
}
```

因此 CheezPPG 阈值状态只要在同一主波形中出现：

```text
1 → 0 → 1
```

就会产生第二次 Beat。

## 2. 新事件定义

新增：

```text
firmware/include/peak_event_gate.h
firmware/src/peak_event_gate.cpp
desktop/src/hrv_app/peak_event_gate.py
```

数据链：

```text
raw threshold rising
        ↓
Start Candidate
        ↓
raw threshold 可以暂时回 0
        ↓
持续跟踪 filtered PPG
        ↓
best = local maximum
        ↓
峰顶后连续下降 5 个采样
+
下降幅度达到动态门限
        ↓
Accepted Beat(best_t_us)
```

Accepted Beat 的时间戳使用**局部最大值真实采样时刻**，
不会再使用抬升前段 threshold crossing 时刻。

## 3. 峰顶确认条件

在 125 Hz 下：

```text
最短追踪时间        80 ms
峰后下降确认        5 samples ≈ 40 ms
动态下降比例        12%
最小下降量          2 filter units
安全追踪超时        450 ms
峰顶后尾部不应期    120 ms
```

450 ms 是安全超时：

```text
超时 → 跳过候选
```

不会在超时时强行生成 Beat。

120 ms 只抑制峰顶后的极短尾部触发。
双计数的主要合并机制是“候选持续追踪到峰顶”，不依赖长固定不应期。

## 4. 高心率保护

本 patch 明确增加：

```text
333 ms RR ≈ 180 bpm
273 ms RR ≈ 220 bpm
```

回归测试。

尤其 220 bpm 用例每个周期只有一个 threshold candidate，
用来防止不应期过长导致：

```text
接受一搏
跳过一搏
接受一搏
```

的二分频问题。

## 5. 心率来源

### SampleFrame.hr_bpm

仍保留：

```text
CheezPPG getPpgHr()
```

只用于 Debug。

### BeatFrame.hr_bpm

现在使用：

```text
最近 5 个 Accepted RR 中位数
→ 60000 / median_RR
```

UI 主心率只读取 BeatFrame HR。

这样库内部双计数即使仍存在，也不会继续污染 C 端主心率卡。

## 6. UI

右侧 0/1 轴显示：

```text
紫 = raw threshold state
黄 = Candidate Rising
绿 = Accepted Beat
```

Debug 行显示：

```text
Candidate count / rough bpm
Accepted count / rough bpm
Candidate - Accepted
CheezPPG library HR
Accepted HR
```

## 7. HRV

固件轻量 RMSSD 和桌面端 RR/NN 链都只接收 Accepted Beat。

v0.2.1 的：

```text
异常搏清洗
SQI
VALID / LIMITED / INVALID
频域质量门
```

全部继续保留，作为第二层防护。

## 8. 历史 CSV

历史 CSV 加载器也使用 Python 镜像 PeakEventGate，
不再用 false→true 上升沿直接重建 RR。

回放结果见：

```text
docs/VALIDATION_v0.2.3_HISTORY_REPLAY.md
```

## 9. 协议

协议仍是 v3，无需改帧结构。

字段语义：

```text
S.hr_bpm = CheezPPG library HR（Debug）
B.hr_bpm = Accepted RR median HR（主结果）
```
