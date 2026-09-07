# v0.3.8 自动频域解读与可视化增强验证

## 目标

在重做后的 v0.3.7 基线上新增：

1. 面向非专业用户的自动化频域解释；
2. VLF / LF / HF / 中位频率趋势图；
3. SPWVD 三色自主神经频带渲染；
4. Welch 功率谱 X 轴神经意义色带；
5. 提高专业分析页图表轴线可读性与高度；
6. 导出频域解释 JSON 与趋势 CSV。

## 核心改动

- `frequency_insights.py`
  - 计算 `median_frequency_hz`；
  - 输出非专业用户说明文本；
  - 生成频域趋势导出行；
  - 统一 Welch / SPWVD 自主神经色带定义。
- `ui_app.py`
  - 新增自动解析说明区；
  - 新增 VLF / LF / HF / 中位频率趋势图；
  - SPWVD 采用三色频带渲染；
  - Welch 图增加色带背景与说明；
  - 增强坐标轴线条与图表高度。
- `engine.py` / `models.py` / `hrv_frequency.py`
  - 正式写入 `median_frequency_hz`，并进入历史与 summary。
- `storage.py`
  - 新增 `frequency_interpretation.json`；
  - 新增 `frequency_trends.csv`；
  - `summary.json` 增加 `frequency_interpretation` 字段。

## 回归验证

```text
PYTHONPATH=desktop/src python -m pytest -q
75 passed in 4.86s
```

## 说明

- SPWVD 仍只用于时频结构观察，绝对频带功率仍以 Welch 为准。
- 色带的“交感偏主 / 共调 / 副交感偏主”仅用于可视解释，不是医疗诊断。
