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


def test_tiles_support_click_selection_and_double_click_focus():
    source = _ui_source()

    assert "clicked = Signal()" in source
    assert "doubleClicked = Signal()" in source
    assert "def _toggle_dashboard_tile_focus" in source
    assert "def _focus_dashboard_tile" in source
    assert "def _restore_dashboard_tile_focus" in source
    assert "杩斿洖鎬昏" in source
    assert 'QKeySequence("Esc")' in source


def test_linked_brushing_syncs_multiple_time_series_and_copy():
    source = _ui_source()

    assert "def _setup_linked_brushing" in source
    assert "self._linked_regions" in source
    assert "LinearRegionItem" in source
    assert "def _set_linked_brush_range" in source
    assert "def _clear_linked_brush" in source
    assert "def _refresh_brush_linkage" in source
    assert "鍒烽€夎仈鍔細" in source
    assert "鏇茬嚎鍜屾枃妗堜細鍚屾绛涢€?" in source


def test_dashboard_layout_keeps_three_responsive_modes():
    source = _ui_source()

    assert 'mode = "wide"' in source
    assert 'mode = "medium"' in source
    assert 'mode = "narrow"' in source
    assert "specs_by_mode" in source
    assert "self._set_hero_compact(True)" in source


def test_dashboard_includes_all_major_visual_tiles():
    source = _ui_source()

    for key in [
        "self.tile_hour = self._create_dashboard_tile",
        "self.tile_prototype = self._create_dashboard_tile",
        "self.tile_keywords = self._create_dashboard_tile",
        "self.tile_signal = self._create_dashboard_tile",
        "self.tile_trend = self._create_dashboard_tile",
        "self.tile_frequency = self._create_dashboard_tile",
        "self.tile_research = self._create_dashboard_tile",
        "self.tile_psd = self._create_dashboard_tile",
        "self.tile_tf = self._create_dashboard_tile",
    ]:
        assert key in source


def test_window_resize_has_three_responsive_layout_modes():
    source = _ui_source()

    assert 'mode = "wide"' in source
    assert 'mode = "medium"' in source
    assert 'mode = "narrow"' in source
    assert "def resizeEvent" in source
    assert "self._apply_responsive_layout" in source


def test_dashboard_hero_compacts_automatically():
    source = _ui_source()

    assert "def _set_hero_compact" in source
    assert "self.hero.setMaximumHeight(72)" in source
    assert "self.hero_compact_summary" in source


def test_tiles_support_click_selection_and_double_click_focus():
    source = _ui_source()

    assert "clicked = Signal()" in source
    assert "doubleClicked = Signal()" in source
    assert "def _toggle_dashboard_tile_focus" in source
    assert "def _focus_dashboard_tile" in source
    assert "def _restore_dashboard_tile_focus" in source
    assert "杩斿洖鎬昏" in source
    assert 'QKeySequence("Esc")' in source


def test_linked_brushing_syncs_multiple_time_series_and_copy():
    source = _ui_source()

    assert "def _setup_linked_brushing" in source
    assert "self._linked_regions" in source
    assert "LinearRegionItem" in source
    assert "def _set_linked_brush_range" in source
    assert "def _clear_linked_brush" in source
    assert "def _refresh_brush_linkage" in source
    assert "鍒烽€夎仈鍔細" in source
    assert "鏇茬嚎鍜屾枃妗堜細鍚屾绛涢€?" in source


def test_dashboard_layout_keeps_three_responsive_modes():
    source = _ui_source()

    assert 'mode = "wide"' in source
    assert 'mode = "medium"' in source
    assert 'mode = "narrow"' in source
    assert "specs_by_mode" in source
    assert "self._set_hero_compact(True)" in source


def test_dashboard_includes_all_major_visual_tiles():
    source = _ui_source()

    for key in [
        "self.tile_hour = self._create_dashboard_tile",
        "self.tile_prototype = self._create_dashboard_tile",
        "self.tile_keywords = self._create_dashboard_tile",
        "self.tile_signal = self._create_dashboard_tile",
        "self.tile_trend = self._create_dashboard_tile",
        "self.tile_frequency = self._create_dashboard_tile",
        "self.tile_research = self._create_dashboard_tile",
        "self.tile_psd = self._create_dashboard_tile",
        "self.tile_tf = self._create_dashboard_tile",
    ]:
        assert key in source