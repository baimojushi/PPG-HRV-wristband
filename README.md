# PPG / HRV 实时分析系统 v0.3.0

v0.3.0 重写了 PPG 心搏检测核心。项目不再依赖 Arduino IDE 全局库、
PlatformIO 下载目录或官方 CheezPPG。完整算法源码随工程保存。

## 当前数据链

```text
GPIO32 / ADC 10 bit / 125 Hz
        ↓
zeezPPG 本地库
        ├─ 去基线滤波
        ├─ 信号环形缓冲区
        ├─ 斜率环形缓冲区
        ├─ RR 环形缓冲区
        ├─ 动态均值 / 标准差
        ├─ 幅值 / 突出度 / 斜率 / 曲率
        ├─ 自相关周期预测
        ├─ 多 Candidate 周期内竞争
        └─ 周期超时 Rescue Search
        ↓
Accepted Beat
        ↓
Peak-to-Peak RR
        ↓
BeatTimelineCleaner
        ↓
NN
        ├─ RMSSD / SDNN / pNN50
        ├─ Welch / Lomb–Scargle
        └─ SPWVD
```

## 环形缓冲区

ESP32 检测器使用固定内存，不在 125 Hz 主循环中申请动态内存：

```text
信号 / 斜率环形缓冲区     320 samples ≈ 2.56 s
Accepted RR 环形缓冲区      9 RR
Candidate Pool              16 candidates
```

信号和斜率缓冲区在 `push()` 时维护 `sum / sumsq`，
动态均值和标准差为 O(1) 更新。

## 心搏判断

算法不再使用“越过一个阈值就记一次心跳”。

每个局部极值先形成 Candidate，并计算：

```text
amplitude_z
prominence_z
slope_z
curvature_z
morphology_score
timing_score
combined_score
```

同时从最近约 2 秒 PPG 做自相关，预测当前 RR。

一个预测周期允许出现多个 Candidate，最终只选一个 Winner。
预测周期明显超时后会降低 Candidate 门限，并执行波形 Rescue Search。

## 周期谐波保护

腕部 PPG 的肩峰、重搏成分容易让自相关在 `2× / 3×` 周期出现高峰。

v0.3.0 会在接近全局最强的自相关局部峰中选择最早的强峰，
并让高置信度自相关成为节律锚点，防止错误 Accepted RR 自我强化。

自动测试覆盖：

```text
900 ms / 约 67 bpm
820 ms + 幅值调制 + 基线漂移
333 ms / 约 180 bpm
极弱脉搏（正常幅值约 8%）
肩峰造成的多个 Candidate
```

## 历史参数兼容

保持：

```text
采样率                    125 Hz
PPG 输入                   GPIO32
ADC                        10 bit
WearThreshold              1
PeakThresholdFactor        11.0
```

`PeakThresholdFactor=11.0` 在 v0.3.0 中作为兼容灵敏度中性点。
它只对综合 Candidate 分数门做小范围缩放，不再直接决定“是否是心搏”。

## 协议 v4

帧头和 CRC 机制保持：

```text
@BODY*CRC16\r\n
CRC-16/CCITT-FALSE
```

Sample：

```text
S,seq,t_us,raw,avg,filtered,candidate,detector_score,expected_rr_ms,hr_bpm,flags
```

Beat：

```text
B,seq,t_us,rr_ms,hr_bpm,score,flags
```

桌面端仍兼容 v2 / v3 历史协议。

## UI 调试层

实时 PPG 图右侧：

```text
紫：动态形态分数 0~1
黄：Candidate
绿：Accepted Beat
```

图下显示：

```text
Candidate 数量
Accepted 数量
Rescue 数量
预测 RR
Accepted HR
平均 Winner 分数
```

只有 Accepted Beat 可以进入 RR / HRV。

## HRV 质量门

v0.2.1 建立的第二层保护继续保留：

```text
有效 NN 数
异常搏比例
未解决异常比例
连续异常长度
SQI
协议错误比例
```

质量门未通过时 UI 显示 `--`，不会把 Candidate HRV 当成正式结果。

## Tiny CNN

v0.3.0 不默认启用 CNN。

当前已经为后续训练保留：

```text
samples.csv:
    detector_score
    expected_rr_ms
    candidate

beats.csv:
    score
    rescued
```

等积累人工标注的真实峰 / 假峰 / 漏峰数据后，可将一个 INT8 Tiny 1D CNN
作为 Candidate 形态评分器加入，不需要再次修改 RR / HRV 架构。

## VS Code / PlatformIO

首次构建不需要下载 CheezPPG：

```bash
cd firmware
pio run
pio run --target upload
pio device monitor
```

`zeezPPG` 位于：

```text
firmware/lib/zeezPPG/src/
```

## Python UI

```bash
cd desktop
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run_ui.py
```

macOS / Linux 将虚拟环境激活命令换成：

```bash
source .venv/bin/activate
```

## 关键文档

```text
docs/ALGORITHM_v0.3.0.md
docs/PROTOCOL.md
docs/ARCHITECTURE.md
docs/VALIDATION_v0.3.0_HISTORY_REPLAY.md
docs/TINY_CNN_PLAN.md
```

旧 `PATCH_v0.2.x` 与 `CHEEZPPG_SOURCE_REVIEW.md` 只作为演化记录保留，
不代表当前运行算法。
