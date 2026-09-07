# v0.3.6 → v0.3.7：固定滞后整窗波形纠错

## 撤销

失败实验版 v0.3.7 的以下机制不进入本版：

```text
固件 RHYTHM_HOLD
trusted-state 冻结
STATE_UPDATE_HELD
STATE_UPDATE_TRUSTED
```

固件恢复为 v0.3.6 行为。

## 桌面端新增

```text
FixedLagWaveformCorrector
7.25 s 实时固定滞后
整窗自相关主周期
独立 PPG 主波检测
同周期次级峰竞争
长间隙低门限补峰
亚采样波顶细化
Firmware ↔ 正式波顶匹配审计
未来感知 RR 清洗
```

正式 Beat 不依赖 Firmware Beat 是否存在。

## UI

连续视觉序列只保留：

```text
滤波 PPG
整窗纠错后的正式 Beat
```

人工标注使用半透明区域。

## 协议

继续 v4，字段和 flags 语义与 v0.3.6 相同。

## 固件

本版工程内固件与用户当前 v0.3.6 固件字节一致。

此前若烧过失败实验版 v0.3.7，需要重新烧录本包固件恢复。
