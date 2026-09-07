from pathlib import Path


def _ui_source() -> str:
    root = Path(__file__).resolve().parents[1]
    return (
        root
        / "desktop"
        / "src"
        / "hrv_app"
        / "ui_app.py"
    ).read_text(encoding="utf-8")


def test_professional_analysis_uses_native_vertical_scroll_area():
    source = _ui_source()

    assert "QScrollArea" in source
    assert "self.analysis_scroll" in source
    assert "ScrollBarAlwaysOn" in source
    assert "ScrollBarAlwaysOff" in source


def test_professional_tab_compacts_hero_automatically():
    source = _ui_source()

    assert "def _set_hero_compact" in source
    assert "index == 1" in source
    assert "self.hero.setMaximumHeight(72)" in source
    assert "self.hero_compact_summary" in source


def test_window_resize_has_three_responsive_layout_modes():
    source = _ui_source()

    assert 'mode = "wide"' in source
    assert 'mode = "medium"' in source
    assert 'mode = "narrow"' in source
    assert "def resizeEvent" in source
    assert "self._apply_responsive_layout" in source


def test_toolbar_and_annotation_controls_reflow_instead_of_overlapping():
    source = _ui_source()

    assert "self.toolbar_layout = QGridLayout" in source
    assert "self.annotation_layout = QGridLayout" in source
    assert "self._clear_grid_layout" in source
    assert "self.toolbar_layout.addWidget" in source
    assert "self.annotation_layout.addWidget" in source


def test_analysis_charts_use_minimum_height_plus_page_scrolling():
    source = _ui_source()

    assert "self.frequency_trend_plot.setMinimumHeight" in source
    assert "self.psd_plot.setMinimumHeight" in source
    assert "self.tf_plot.setMinimumHeight" in source
    assert "self.signal_plot.setMinimumHeight" in source
    assert "self.trend_plot.setMinimumHeight" in source
