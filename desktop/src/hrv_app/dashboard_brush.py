"""Pure-data helpers for the v0.4.9 linked-brush dashboard.

A brush covers session-relative MINUTES on every time-series plot.
No Qt dependency: this module can be tested independently.
"""
from __future__ import annotations

from collections.abc import Mapping
import numpy as np


def paired_xy(series):
    """Normalize pyqtgraph getData() output to equal-length float arrays."""
    if not isinstance(series, (tuple, list)) or len(series) != 2:
        return np.empty(0, dtype=float), np.empty(0, dtype=float)
    x, y = series
    if x is None or y is None:
        return np.empty(0, dtype=float), np.empty(0, dtype=float)
    try:
        xx = np.asarray(x, dtype=float).reshape(-1)
        yy = np.asarray(y, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        return np.empty(0, dtype=float), np.empty(0, dtype=float)
    if xx.size != yy.size:
        return np.empty(0, dtype=float), np.empty(0, dtype=float)
    return xx, yy


def selected_xy(series, bounds):
    """Return only samples in the selected session-relative minute interval."""
    xx, yy = paired_xy(series)
    if bounds is None:
        return np.empty(0, dtype=float), np.empty(0, dtype=float)
    low, high = sorted((float(bounds[0]), float(bounds[1])))
    selected = np.isfinite(xx) & (xx >= low) & (xx <= high)
    return xx[selected], yy[selected]


def selected_mean(series, bounds):
    """Return (mean, count) over finite y values in a selected minute range."""
    _, yy = selected_xy(series, bounds)
    valid = yy[np.isfinite(yy)]
    if not valid.size:
        return None, 0
    return float(np.mean(valid)), int(valid.size)


def format_brush_summary(bounds, trend, prototypes, frequency, prototype_names=None):
    """Honest, data-derived narrative; no inference about mood/health states."""
    if bounds is None:
        return (
            "拖动任意时间曲线中的半透明区间即可刷选；"
            "三张图同步移动并高亮选中数据，文案随之更新。"
        )
    low, high = sorted((float(bounds[0]), float(bounds[1])))
    chunks = [
        f"刷选 {low:.1f}–{high:.1f} 分钟（{high - low:.1f} 分钟）"
    ]
    rmssd, rmssd_count = selected_mean(trend, bounds)
    if rmssd is not None:
        chunks.append(f"RMSSD均值 {rmssd:.1f} ms / {rmssd_count}窗")
    else:
        chunks.append("RMSSD暂无有效窗口")
    candidates = []
    for code, series in prototypes.items():
        mean, count = selected_mean(series, bounds)
        if mean is not None and count:
            candidates.append((mean, code))
    if candidates:
        mean, code = max(candidates)
        name = (prototype_names or {}).get(code, code)
        chunks.append(f"研究相似曲线均值最高：{name} {mean:.2f}")
    else:
        chunks.append("研究匹配暂无有效数据")
    band_means = []
    for band in ("VLF", "LF", "HF"):
        mean, count = selected_mean(frequency.get(band), bounds)
        if mean is not None:
            band_means.append(f"{band} {mean:.0f}")
    if band_means:
        chunks.append("频段均值 " + "/".join(band_means) + " ms²")
    return "｜".join(chunks) + "。曲线高亮为选中区间，未选部分仍作背景参照。"
