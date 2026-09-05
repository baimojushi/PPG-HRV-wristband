# 第三方依赖

## PPG 心搏检测

v0.3.0 的 `zeezPPG` 是项目自有实现，源码完整位于：

```text
firmware/lib/zeezPPG/
```

运行时不依赖 CheezPPG。

旧版 CheezPPG 源码审查文档仍保留在仓库，用于说明项目演化过程。

## Python

桌面端依赖见：

```text
desktop/requirements.txt
```

主要用于 UI、串口、数值分析与 SciPy HRV 频域计算。
