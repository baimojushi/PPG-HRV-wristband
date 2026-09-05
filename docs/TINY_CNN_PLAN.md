# Tiny CNN 预留方案

> v0.3.3 决策：暂不进入实时固件。当前实测瓶颈位于频域互证尺度；
> 详细评估见 `CNN_ENGINEERING_ROI_v0.3.3.md`。

## 当前状态

v0.3.0 没有启用神经网络。

原因：

- 目前没有足够的人眼标注真峰 / 假峰 / 漏峰；
- 未训练模型无法证明比动态算法更可靠；
- 直接把随机或弱监督 CNN 放进 ESP32 会增加不可解释误差。

## 已经准备的数据

实时会话保存：

```text
samples.csv
    seq
    t_us
    raw
    avg
    filtered
    candidate
    detector_score
    expected_rr_ms
    hr_bpm
    flags

beats.csv
    seq
    t_us
    rr_ms
    hr_bpm
    score
    flags
```

这些数据可以和人工点击的真实心搏时间戳组成训练集。

## 推荐模型

输入窗口：

```text
128 samples ≈ 1.024 s
Channel 0: robust-normalized PPG
Channel 1: first derivative
```

建议第一版：

```text
Conv1D 2→8, kernel 5
ReLU
Pool
Conv1D 8→12, kernel 5
ReLU
Global Average Pool
Dense 12→8
Dense 8→1
```

部署形式：

```text
INT8
```

CNN 只输出 Candidate morphology score。

最终决策仍使用：

```text
CNN morphology
+ expected RR
+ candidate competition
+ rescue
```

## 训练难负例

重点收集：

- 同一脉搏的肩峰；
- 抬升前段局部极值；
- 重搏切迹；
- 运动尖峰；
- 基线漂移；
- 削底边缘；
- 宽峰中的次级峰。

随机无信号窗口价值较低，不应成为主要负例。