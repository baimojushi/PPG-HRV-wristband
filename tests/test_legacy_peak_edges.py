from pathlib import Path

import pandas as pd

from hrv_app.engine import AnalysisEngine
from hrv_app.legacy_csv import load_csv_into_engine


def test_legacy_peak_plateau_is_confirmed_at_local_peak(tmp_path: Path):
    rows = 680
    peak = [0] * rows
    filtered = [10.0] * rows

    starts = [20, 120, 220, 320, 420, 520]

    for start in starts:
        peak[start:start + 3] = [1, 1, 1]

        center = start + 12
        for index in range(
            max(0, center - 12),
            min(rows, center + 13),
        ):
            filtered[index] = max(
                filtered[index],
                100.0
                - abs(index - center) * 6.0,
            )

    frame = pd.DataFrame({
        "Channel 1": [300] * rows,
        "Channel 2": [300] * rows,
        "Channel 3": filtered,
        "Channel 4": peak,
        "Channel 5": [75] * rows,
    })

    path = tmp_path / "plateau.csv"
    frame.to_csv(
        path,
        index=False,
    )

    engine = AnalysisEngine()
    load_csv_into_engine(
        path,
        engine,
    )

    beats = engine.beat_records()

    # 动态检测器约需 1.7 秒建立自相关周期，因此启动阶段允许少一搏。
    assert len(beats) >= 4
    assert all(
        790 <= beat.rr_raw_ms <= 810
        for beat in beats
    )
