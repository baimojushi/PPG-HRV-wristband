# v0.3.9 窗口分辨率自适应验证

## 目标

解决 Python / Qt 桌面窗口在不同分辨率下出现的三类问题：

1. 专业分析页内容超出窗口后无可用翻页滚动条；
2. 缩小窗口后工具栏、人工标注控件和指标卡互相挤压；
3. 双轴图在 resize 后出现绘图区几何不同步。

## 实现

### 原生页内滚动

`状态与趋势` 与 `专业分析` 都使用 `QScrollArea`。

专业分析页：

```text
Vertical ScrollBar = AlwaysOn
Horizontal ScrollBar = AlwaysOff
WidgetResizable = True
```

这样低分辨率显示器、窗口化运行和系统缩放下都能访问完整趋势图、Welch 与 SPWVD。

### 三档响应式布局

```text
wide    >= 1000 px
medium  700–999 px
narrow  < 700 px
```

串口工具栏和人工标注栏使用 `QGridLayout` 动态重排，避免水平控件直接超出窗口。

### 专业分析极简 Hero

切换到专业分析页时，`此刻 · 身体节律` 容器自动：

- 隐藏三张大指标卡；
- 隐藏质量进度条与长质量文本；
- 保留标题；
- 显示一行 `HR / RMSSD / SQI / 频域状态`；
- 最大高度 72 px。

低于 700 px 宽或 650 px 高时，状态页也允许进入同一极简模式。

### 图表 resize 稳定性

图表不再依赖固定窗口高度。根据当前窗口高度设置最小高度，再交给页内滚动区管理总高度。

每次 resize 后通过 `QTimer.singleShot(0, ...)` 延迟同步：

- PPG 心搏识别右轴 ViewBox；
- VLF/LF/HF 趋势图中位频率右轴 ViewBox。

## 自动验证

```text
Python compileall    PASS
pytest               80 passed
responsive UI tests  5 passed
```

当前制包环境没有 PySide6，因此无法在该环境创建真实 Qt 窗口做像素级截图验证。代码通过 Python 字节码编译、全量算法回归和响应式 UI 静态结构测试。
