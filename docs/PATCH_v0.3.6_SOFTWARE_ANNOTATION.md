# v0.3.6 Patch：软件人工异常标注

## 定位

v0.3.6 是 **desktop observability release**。

基线：

```text
v0.3.5
```

本版没有改变：

- ESP32 固件；
- zeezPPG；
- Winner / Rescue；
- fiducial refiner；
- RR cleaner；
- 时域 HRV；
- 频域 HRV；
- 协议 v4。

## UI

新增：

```text
[异常类型 ▼] [标记异常 · F8]
```

按键时使用：

```text
最近一次真正绘制到屏幕的设备 t_us
```

同时保存：

```text
host monotonic time
latest received sample t_us
UI data lag
```

## 标注可视化

```text
红色半透明区 = 人工问题窗口 -3~0 s
红虚线       = 软件标注设备时间
```

## 导出

新增：

```text
annotations.csv
annotation_context_1s.csv
annotation_summary.json
raw_session/
```

## 安全约束

人工标注入口严格单向：

```text
User mark
    ↓
logging / export
```

不存在：

```text
User mark
    ↓
detector state / RR / HRV
```

## 固件

和 v0.3.5 字节一致。

不需要重新烧录。
