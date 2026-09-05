from __future__ import annotations

from collections.abc import Sequence
import numpy as np


FREQUENCY_FIELDS = (
    "total_power_ms2",
    "vlf_ms2",
    "lf_ms2",
    "hf_ms2",
    "lf_nu",
    "hf_nu",
    "lf_hf",
    "hf_lf",
)


def compute_frequency_statistics(history: Sequence[dict]) -> dict:
    """
    对所有通过质量门的 20 秒频域窗口做会话级统计。

    输出 mean / median / std / p25 / p75 / min / max，
    并记录有效窗口数和有效覆盖率。
    """
    rows = [
        row
        for row in history
        if row.get("frequency_status") == "VALID"
    ]

    result: dict = {
        "valid_window_count": len(rows),
        "total_window_count": len(history),
        "valid_window_ratio": (
            len(rows) / len(history)
            if history
            else 0.0
        ),
        "metrics": {},
    }

    for field in FREQUENCY_FIELDS:
        values = np.asarray(
            [
                row.get(field, np.nan)
                for row in rows
            ],
            dtype=float,
        )
        values = values[np.isfinite(values)]

        if values.size == 0:
            result["metrics"][field] = {
                "count": 0,
                "mean": None,
                "median": None,
                "std": None,
                "p25": None,
                "p75": None,
                "min": None,
                "max": None,
            }
            continue

        result["metrics"][field] = {
            "count": int(values.size),
            "mean": float(np.mean(values)),
            "median": float(np.median(values)),
            "std": (
                float(np.std(values, ddof=1))
                if values.size >= 2
                else 0.0
            ),
            "p25": float(np.percentile(values, 25)),
            "p75": float(np.percentile(values, 75)),
            "min": float(np.min(values)),
            "max": float(np.max(values)),
        }

    return result
