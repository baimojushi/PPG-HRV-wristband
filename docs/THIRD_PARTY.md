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


## v0.4.1 间期核心的公开设计参考

桌面 interval core 的两条检测路径是项目内独立实现，运行时不依赖 NeuroKit2、
pyPPG 或 PPG-beats 源代码。

设计参考包括：

- Charlton et al. 的 PPG-beats detector benchmark；
- MSPTD / MSPTDfast 的多尺度局部极值持续性思想；
- Elgendi-style moving-window systolic peak detection；
- pyPPG Aboy++ 关于“坏窗口不应反向污染下一窗口 HR 先验”的设计原则。

这里只借鉴论文/公开算法描述与架构思想；没有复制第三方实现。
