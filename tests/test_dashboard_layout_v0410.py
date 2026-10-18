"""v0.4.10 single-screen 3x3 dashboard regression tests.

Pure-Python tests run without PySide6. An optional offscreen Qt smoke test checks
actual widget geometry when runtime dependencies are installed (e.g. on Windows).
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "desktop" / "src" / "hrv_app" / "ui_app.py"
MANIFEST = ROOT / "MANIFEST.json"


def ui_source_and_class():
    src = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
    return src, cls


def extracted_method(name):
    _, cls = ui_source_and_class()
    method = next(node for node in cls.body
                  if isinstance(node, ast.FunctionDef) and node.name == name)
    # Call the actual method without importing PySide6, using fake view objects.
    ns = {}
    program = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    exec(compile(program, str(SOURCE), "exec"), ns)
    return ns[name]


class FakeWidget:
    def __init__(self):
        self.parent = "original"
        self.max_height = None

    def setParent(self, parent):
        self.parent = parent

    def setMaximumHeight(self, pixels):
        self.max_height = pixels


class FakeGrid:
    def __init__(self):
        self.slots = []
        self.invalidated = 0

    def count(self):
        return len(self.slots)

    def takeAt(self, index):
        widget, *_ = self.slots.pop(index)
        return SimpleNamespace(widget=lambda: widget)

    def addWidget(self, widget, row, col, row_span, col_span):
        self.slots.append((widget, row, col, row_span, col_span))

    def setColumnMinimumWidth(self, col, value):
        pass

    def setColumnStretch(self, col, stretch):
        pass

    def setRowMinimumHeight(self, row, value):
        pass

    def setRowStretch(self, row, stretch):
        pass

    def verticalSpacing(self):
        return 9

    def invalidate(self):
        self.invalidated += 1


class FakeDashboard:
    def __init__(self):
        self.tile_signal = FakeWidget()
        self.tile_trend = FakeWidget()
        self.tile_frequency = FakeWidget()
        self.tile_hour = FakeWidget()
        self.tile_prototype = FakeWidget()
        self.tile_keywords = FakeWidget()
        self.tile_research = FakeWidget()
        self.tile_psd = FakeWidget()
        self.tile_tf = FakeWidget()
        self.dashboard_tiles = [
            self.tile_signal, self.tile_trend, self.tile_frequency,
            self.tile_hour, self.tile_prototype, self.tile_keywords,
            self.tile_research, self.tile_psd, self.tile_tf,
        ]
        self.dashboard_layout = FakeGrid()
        self._focused_tile = None
        self._focus_placeholder = None
        self.focus_overlay = SimpleNamespace(raise_=lambda: None)


def test_version_and_scope():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["version"] == "0.4.10"
    assert manifest["base_version"] == "0.4.9"
    record = manifest["dashboard_layout_v0_4_10"]
    assert record["firmware_changed"] is False
    assert record["data_protocol_changed"] is False
    assert record["hrv_algorithms_changed"] is False


def test_3x3_positions_are_stable_across_all_width_modes():
    fn = extracted_method("_arrange_dashboard_tiles")
    view = FakeDashboard()
    target = {(row, col) for row in range(3) for col in range(3)}
    for mode in ("wide", "medium", "narrow"):
        fn(view, mode)
        assert len(view.dashboard_layout.slots) == 9
        assert {slot[1:3] for slot in view.dashboard_layout.slots} == target
        assert set(view._responsive_dashboard_specs) == set(view.dashboard_tiles)
        assert len({slot[0] for slot in view.dashboard_layout.slots}) == 9
        assert all(slot[3:] == (1, 1) for slot in view.dashboard_layout.slots)
    assert view._responsive_dashboard_specs[view.tile_signal] == (0, 0, 1, 1)
    assert view._responsive_dashboard_specs[view.tile_tf] == (2, 2, 1, 1)


def test_focusing_keeps_one_placeholder_and_eight_other_tiles():
    fn = extracted_method("_arrange_dashboard_tiles")
    view = FakeDashboard()
    fn(view, "wide")
    view._focused_tile = view.tile_signal
    view._focus_placeholder = FakeWidget()
    fn(view, "narrow")
    assert len(view.dashboard_layout.slots) == 9
    assert view.tile_signal not in [slot[0] for slot in view.dashboard_layout.slots]
    assert view._focus_placeholder in [slot[0] for slot in view.dashboard_layout.slots]
    assert all(slot[1] < 3 for slot in view.dashboard_layout.slots)


def test_height_budget_allocates_three_equal_rows_inside_viewport():
    fn = extracted_method("_fit_dashboard_to_viewport")
    view = FakeDashboard()
    view._ui_ready = True
    view._dashboard_fit_pending = True
    view._dashboard_row_budget = 300
    view.root_layout = SimpleNamespace(
        contentsMargins=lambda: SimpleNamespace(top=lambda: 10, bottom=lambda: 10),
        spacing=lambda: 7,
    )
    heights = [40, 36, 55, 54, 27]  # toolbar, annotation, hero, banner, disclaimer
    sections = [SimpleNamespace(
        sizeHint=lambda height=h: SimpleNamespace(height=lambda: height),
        maximumHeight=lambda height=h: height,
    ) for h in heights]
    (view.toolbar_widget, view.annotation_widget, view.hero,
     view.linkage_banner, view.disclaimer) = sections
    central = SimpleNamespace(height=lambda: 900)
    view.centralWidget = lambda: central
    fn(view)
    expected = (900 - sum(heights) - 20 - 7 * 5 - 9 * 2) // 3
    assert expected == 205
    assert view._dashboard_row_budget == expected
    assert all(tile.max_height == expected for tile in view.dashboard_tiles)
    assert view.dashboard_layout.invalidated == 1
    view._focused_tile = view.tile_signal
    view.tile_signal.max_height = 16777215
    fn(view)
    assert view.tile_signal.max_height == 16777215
    assert all(tile.max_height == expected for tile in view.dashboard_tiles[1:])


def test_old_tabs_and_unbounded_medium_layout_are_gone():
    src, cls = ui_source_and_class()
    assert "self.tabs" not in src
    assert "QScrollArea" not in src
    assert "specs_by_mode" not in src
    assert "_schedule_dashboard_fit()" in src
    assert "_set_hero_compact(True)" in src
    assert "self.tile_signal" in src
    assert "self.signal_curve.setData" in src
    assert "self.accepted_beat_curve.setData" in src
    assert "_refresh_brush_linkage()" in src
    names = [n.name for n in cls.body if isinstance(n, ast.FunctionDef)]
    assert names.count("_arrange_dashboard_tiles") == 1
    assert names.count("_set_dashboard_tile_detail_mode") == 1
    assert names.count("_focus_dashboard_tile") == 1
    assert names.count("_restore_dashboard_tile_focus") == 1


def test_gui_layout_if_qt_dependencies_available():
    packages = ("PySide6", "pyqtgraph", "serial")
    if not all(importlib.util.find_spec(p) for p in packages):
        pytest.skip("PySide6 / pyqtgraph / pyserial are not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication

    src = ROOT / "desktop" / "src"
    sys.path.insert(0, str(src))
    from hrv_app.ui_app import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        for width, height in ((1500, 900), (1280, 760), (990, 740)):
            window.resize(width, height)
            window.show()
            for _ in range(5):
                app.processEvents()
            assert window.dashboard_layout.count() == 9
            assert all(tile.isVisible() for tile in window.dashboard_tiles)
            rects = [tile.geometry() for tile in window.dashboard_tiles]
            assert all(rect.width() > 50 and rect.height() > 20 for rect in rects)
            assert all(
                rect.top() >= 0 and rect.bottom() <= window.dashboard_widget.height() + 4
                for rect in rects
            )
            assert len({tile.geometry().top() for tile in window.dashboard_tiles}) == 3
        window._focus_dashboard_tile(window.tile_signal)
        for _ in range(3):
            app.processEvents()
        assert window._focused_tile is window.tile_signal
        window._restore_dashboard_tile_focus()
        for _ in range(3):
            app.processEvents()
        assert window.dashboard_layout.count() == 9
        assert window._focused_tile is None
    finally:
        window.timer.stop()
        window.close()
        app.processEvents()
