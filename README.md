# PPG / HRV 实时分析系统 v0.3.6

v0.3.6 重做为 **软件人工异常标注版**。

这版从 v0.3.5 重新建立，取消 GPIO 按钮方案。

## 重要

```text
ESP32 固件        与 v0.3.5 完全相同
zeezPPG           与 v0.3.5 完全相同
协议              v4，不变
检测参数          不变
HRV 参数          不变
```

**不需要重新烧录 ESP32。**

只更新桌面端。

## 为什么用软件标注

异常是通过桌面 UI 观察到的。

因此 F8 记录的是：

```text
当前屏幕真正显示到的设备 Sample t_us
```

而不是：

```text
Windows 墙钟
最新后台串口 Sample
```

这能让人工标签直接对齐你肉眼看到的 PPG / Winner / fiducial。

## 使用

实时连接设备后：

```text
F8
```

或点击：

```text
标记异常 · F8
```

可提前选择：

```text
未分类
峰位漂移
漏检
多检
周期跳变
其他
```

来不及分类就保持“未分类”。

## 人工标签

看到问题后 3 秒内按一次。

```text
device_t_us
    当前屏幕 PPG 右缘设备时间

label window
    device_t_us - 3 s
    ~ device_t_us
```

同时记录：

```text
latest_sample_t_us
host_monotonic_ns
ui_data_lag_ms
```

用于审计 UI / 串口延迟。

## UI

PPG 图：

```text
红色阴影 = 最近一次人工标注前 3 秒
红虚线   = 标注时刻
```

Debug 行：

```text
人工标注 N
近窗 N
```

## 低频前兆分析

每个标注自动分析：

```text
前 120 秒
到
后 5 秒
```

输出 1 秒粒度：

```text
PPG baseline / amplitude
detector score
Candidate rate
expected RR
Winner score
Timing Quality
fiducial shift
Rescue / phase recovery
RR artifact
```

并计算：

```text
30 秒滚动水平
60 秒趋势斜率
```

## 导出新增

```text
annotations.csv
annotation_context_1s.csv
annotation_summary.json
raw_session/
```

`annotation_summary.json` 自动比较：

```text
远期 -120~-30 s
vs
临近 -30~0 s
```

多个问题事件还会统计趋势是否反复同向。

## 完整会话

导出会包含整个实时 SessionRecorder：

```text
hrv_export/raw_session/
```

所以连续采集 20–30 分钟也可以追溯早期标注前的完整 PPG。

先断开设备再导出也支持。

## 推荐实验

```text
单次连续 15–30 分钟
收集 10–20 个独立异常标注
保留大量正常无标注区间
测试期间不改算法参数
```

完成后把整个 `hrv_export` 压缩用于下一轮分析。

## 桌面运行

```bash
cd desktop
python run_ui.py
```

## 关键文档

```text
docs/ANNOTATION_WORKFLOW_v0.3.6.md
docs/PATCH_v0.3.6_SOFTWARE_ANNOTATION.md
docs/QUALITY_CONFIDENCE.md
docs/ARCHITECTURE.md
```
