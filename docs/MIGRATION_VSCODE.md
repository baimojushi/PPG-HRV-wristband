# VS Code / PlatformIO 迁移说明

## 当前固件依赖

PPG 算法已经完整纳入项目：

```text
firmware/lib/zeezPPG/
```

不需要 Arduino IDE 全局库，也不需要 PlatformIO 下载 CheezPPG。

## 构建

```bash
cd firmware
pio run
```

烧录：

```bash
pio run --target upload
```

串口：

```bash
pio device monitor
```

删除 `.pio/` 不会删除 zeezPPG 源码。

## 关键历史参数

```text
125 Hz
GPIO32
ADC 10 bit
WearThreshold = 1
PeakThresholdFactor = 11.0
```

其中 11.0 作为兼容灵敏度中性点保留。
