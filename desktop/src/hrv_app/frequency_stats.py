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
    对所有允许正式输出的 20 秒频域窗口做会话级统计。

    VALID 与 LIMITED 都属于“可计算窗口”，
    但单独记录严格 VALID / LIMITED 数量，避免把两种质量等级混为一谈。
    """
    rows = [
        row
        for row in history
        if row.get("frequency_status")
        in {"VALID", "LIMITED"}
        and np.isfinite(
            row.get(
                "total_power_ms2",
                np.nan,
            )
        )
    ]

    strict_valid_count = sum(
        row.get("frequency_status")
        == "VALID"
        for row in rows
    )

    limited_count = sum(
        row.get("frequency_status")
        == "LIMITED"
        for row in rows
    )

    result: dict = {
        # 兼容旧 UI 字段：valid_window_count 现在表示“可计算窗口”。
        "valid_window_count": len(rows),
        "usable_window_count": len(rows),
        "strict_valid_window_count": strict_valid_count,
        "limited_window_count": limited_count,
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
