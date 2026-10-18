"""v0.4.9 Dashboard regression checks.

Pure checks do not need Qt. Qt integration smoke runs only if dependencies exist.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "desktop" / "src" / "hrv_app" / "ui_app.py"
BRUSH = ROOT / "desktop" / "src" / "hrv_app" / "dashboard_brush.py"


def load_brush_module():
    spec = importlib.util.spec_from_file_location("_dashboard_brush_v049", BRUSH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_049_valid_json():
    manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    # This v0.4.9 regression is also retained by the v0.4.10 UI-only update.
    assert manifest["version"] in {"0.4.9", "0.4.10"}
    expected_base = "0.4.8" if manifest["version"] == "0.4.9" else "0.4.9"
    assert manifest["base_version"] == expected_base
    assert manifest["dashboard_stabilization_v0_4_9"]["firmware_changed"] is False


def test_dashboard_no_tab_reference_and_layout_is_called():
    source = UI.read_text(encoding="utf-8")
    tree = ast.parse(source)
    main = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == "MainWindow")
    methods = [x for x in main.body if isinstance(x, ast.FunctionDef)]
    names = [m.name for m in methods]
    assert "self.tabs" not in source
    assert "QTabWidget" not in source
    assert names.count("_setup_focus_overlay") == 1
    assert names.count("_set_active_dashboard_tile") == 1
    assert names.count("_arrange_dashboard_tiles") == 1
    responsive = next(m for m in methods if m.name == "_apply_responsive_layout")
    assert any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "_arrange_dashboard_tiles"
        for n in ast.walk(responsive)
    )
    focus = next(m for m in methods if m.name == "_setup_focus_overlay")
    created_overlay_layouts = [
        n for n in ast.walk(focus)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "QVBoxLayout"
        and n.args
        and isinstance(n.args[0], ast.Attribute)
        and n.args[0].attr == "focus_overlay"
    ]
    assert len(created_overlay_layouts) == 1


def test_selection_filters_minutes_not_seconds():
    m = load_brush_module()
    x, y = m.selected_xy(([0, 1, 2, 3, 5], [10, 11, np.nan, 13, 15]), (1, 3))
    assert x.tolist() == [1, 2, 3]
    assert np.isnan(y[1])
    assert m.selected_mean(([0, 1, 2, 3, 5], [10, 11, np.nan, 13, 15]), (1, 3)) == (12.0, 2)
    assert m.selected_xy((None, None), (0, 1))[0].size == 0
    assert m.selected_xy(([1, 2], [10]), (0, 5))[0].size == 0
    assert m.selected_xy(([0, 5], [10, 20]), None)[0].size == 0


def test_selection_narrative_handles_gaps_and_missing_data():
    m = load_brush_module()
    content = m.format_brush_summary(
        (3, 1),
        ([0, 1, 2, 3], [10, 20, 40, np.nan]),
        {"CASE": ([0, 1, 2, 3], [0.1, 0.4, 0.6, 0.7])},
        {"VLF": ([1, 2, 3], [10, 12, 14])},
        {"CASE": "研究样本A"},
    )
    assert "1.0–3.0 分钟" in content
    assert "RMSSD均值 30.0 ms / 2窗" in content
    assert "研究样本A 0.57" in content
    assert "VLF" in content
    missing = m.format_brush_summary((10, 11), ([], []), {}, {})
    assert "暂无有效窗口" in missing
    assert "暂无有效数据" in missing
    assert "拖动" in m.format_brush_summary(None, ([], []), {}, {})


def test_dashboard_smoke_only_if_qt_dependencies_present(monkeypatch):
    if not all(
        importlib.util.find_spec(x)
        for x in ("PySide6", "pyqtgraph", "serial")
    ):
        pytest.skip("Qt runtime not installed in this environment")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from hrv_app.ui_app import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert window._ui_ready
        assert len(window.dashboard_tiles) == 9
        assert window.dashboard_layout.count() == 9
        assert len(window._linked_regions) == 3
        assert len({id(x) for x in window._linked_regions}) == 3
        assert all(
            region.scene() is plot.scene()
            for region, plot in zip(
                window._linked_regions,
                (window.trend_plot, window.prototype_score_plot, window.frequency_trend_plot),
            )
        )

        region = window._linked_regions[1]
        region.setRegion((2.0, 4.0))
        window._set_linked_brush_range(region)
        assert window._brush_selection == (2.0, 4.0)
        assert all(tuple(r.getRegion()) == (2.0, 4.0) for r in window._linked_regions)

        tile = window.tile_signal
        window._focus_dashboard_tile(tile)
        assert window._focused_tile is tile
        assert window.focus_overlay.isVisible() is False or window._focused_tile is tile
        window._arrange_dashboard_tiles("medium")
        assert window._focused_tile is tile
        assert window.dashboard_layout.count() == 9
        window._restore_dashboard_tile_focus()
        assert window._focused_tile is None
        assert window.dashboard_layout.count() == 9

        window._clear_linked_brush()
        assert window._brush_selection is None
    finally:
        window.timer.stop()
        window.close()
        app.processEvents()
