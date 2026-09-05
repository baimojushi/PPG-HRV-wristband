# v0.3.6 软件人工异常标注工作流

## 1. 版本目的

当前偶发的 Winner / fiducial 错位已经进入低频、稀有故障阶段。

仅凭 12 秒截图继续调检测参数，会同时改变：

- 故障出现概率；
- 故障形态；
- Rescue 行为；
- Timing Quality；
- RR 清洗结果。

v0.3.6 因此暂停修改 v0.3.5 的检测算法，先建立可重复的人工作为标签。

要验证的核心假设：

```text
偶发误判
  ↑
是否存在问题前几十秒 / 几分钟的低频状态逐步积累？
```

## 2. 为什么改成软件按键

人工判断本身发生在桌面 UI。

用户真正看到的是：

```text
已经绘制到屏幕上的 PPG
+ Firmware Winner
+ HRV fiducial
```

所以标注目标应当是：

```text
“我刚才在这个屏幕时间位置看到了异常”
```

软件标注可以直接绑定 UI 当前显示数据的设备 `t_us`，不需要占用 GPIO，也不需要为了观测功能重新烧录 ESP32。

## 3. 操作入口

实时连接状态下：

```text
按钮：标记异常 · F8
快捷键：F8
```

异常类型可选：

```text
未分类
峰位漂移
漏检
多检
周期跳变
其他
```

异常类型只用于后处理分组，不参与算法。

建议优先按 F8，减少鼠标移动造成的反应延迟。

## 4. 时间戳语义

软件按键不会直接使用 Windows 系统时间定位 PPG。

UI 每次刷新曲线时，会冻结：

```text
displayed_end_t_us
```

它是当前屏幕右缘实际显示到的设备 Sample 时间。

按 F8 时保存：

```text
device_t_us
    = displayed_end_t_us

latest_sample_t_us
    = 点击时 AnalysisEngine 已收到的最新设备 Sample

host_monotonic_ns
    = PC 单调时钟，仅用于审计输入延迟

ui_data_lag_ms
    = latest_sample_t_us - device_t_us
```

这样即使串口后台线程在两个 UI 刷新之间又收到一批新数据，
标注仍指向用户真正看见的那一帧，而不会向未来漂移。

## 5. 人工问题区间

用户观察到问题后 **3 秒内按一次 F8**。

人工标签保存：

```text
label_end_us
    = device_t_us

label_start_us
    = device_t_us - 3 s
```

按钮不要求精确按在误判发生的毫秒点。

后处理会在这 3 秒内寻找：

- RR 异常；
- Timing Quality 最低点；
- Rescue；
- 相位恢复；
- Winner 分下降；
- Candidate 密度变化。

算法的 `auto_focus_t_us` 只是分析辅助，不替换人工标签本身。

## 6. 实时视觉确认

状态页 PPG 图新增：

```text
红色半透明区域 = 最近一次人工标注的前 3 秒
红色虚线       = 软件标注时刻
```

调试行显示：

```text
人工标注 N
近窗 N
```

顶部提示显示最近一次标注距当前屏幕数据多少秒。

按下 F8 后按钮短暂显示：

```text
已标记 #N
```

整个动作没有弹窗，不阻塞实时观察。

## 7. 点击时冻结的状态

`annotations.csv` 会同时记录：

```text
device_t_us
latest_sample_t_us
ui_data_lag_ms

HR
expected RR
latest Winner score

Timing Quality
Timing uncertainty
fiducial shift

最近 12 秒 Candidate count
最近 12 秒 Rescue count
最近 12 秒 phase recovery count

SQI
effective sample rate
timing jitter p95
```

这些字段用于回答：

```text
问题真正出现前，
算法内部状态是不是已经开始走坏？
```

## 8. 长时间原始数据

实时 `SessionRecorder` 持续落盘：

```text
samples.csv
beats.csv
annotations.csv
firmware_metrics.csv
diagnostics.csv
```

导出时整个实时会话复制到：

```text
hrv_export/raw_session/
```

即使 Engine 只在内存中保留最近约 5 分钟 Sample，
20–30 分钟测试的早期 PPG 仍然存在。

即使先断开设备再点击“导出分析结果”，
刚结束的实时会话目录也会继续加入导出包。

## 9. annotation_context_1s.csv

每一个人工标注自动生成：

```text
按钮前 120 秒
到
按钮后 5 秒
```

的 1 秒粒度上下文。

包括：

```text
PPG baseline median
PPG p90-p10 amplitude

detector score mean / p90
Candidate rate

expected RR
sample HR

Firmware Winner count
Winner score
Firmware RR

Timing Quality
Timing uncertainty
fiducial shift
phase recovery
Rescue

RR artifact count
unresolved count
accepted NN count
```

并计算：

```text
30 秒滚动均值
60 秒趋势斜率
```

## 10. annotation_summary.json

每个问题事件自动比较：

```text
远期基线      -120 ~ -30 s
临近问题       -30 ~   0 s
```

重点字段：

```text
PPG baseline
PPG amplitude
detector score
Candidate rate
expected RR
Winner score
Timing Quality
```

输出：

```text
far_mean
near_mean
near_minus_far
```

多次标注还会聚合：

```text
mean_delta
median_delta
positive_fraction
```

只有某个低频量在多个独立异常事件中反复同向变化，
才支持继续研究“长期积累机制”。

## 11. 推荐采集方法

单次连续采集：

```text
15–30 分钟
```

建议：

1. 看到明确问题后 3 秒内按一次 F8；
2. 同一个持续问题只按一次；
3. 类型来不及判断时保持“未分类”；
4. 标注后继续采至少 5 秒；
5. 尽量收集 10–20 个独立异常标注；
6. 保留大量没有标注的正常时段；
7. 测试中不要修改检测参数。

## 12. 下一轮交付数据

导出整个：

```text
hrv_export/
```

压缩为 ZIP。

下一轮分析优先顺序：

```text
人工标注段
vs
正常控制段
    ↓
瞬时局部特征
vs
前 30–120 秒低频趋势
    ↓
确定真正可预测的前兆
    ↓
再决定是否改：
节律状态机 / Candidate score / fiducial / RR cleaner / Tiny CNN
```
