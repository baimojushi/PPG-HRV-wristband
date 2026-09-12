from __future__ import annotations

from pathlib import Path
import threading
import time
import traceback

import numpy as np
import pyqtgraph as pg
from serial.tools import list_ports

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .engine import AnalysisEngine
from .frequency_insights import (
    AUTONOMIC_ZONES,
    build_frequency_trend_rows,
    describe_frequency_balance,
    frequency_zone_brushes,
)
from .legacy_csv import load_csv_into_engine
from .models import (
    BeatFrame,
    DiagnosticFrame,
    FirmwareMetricFrame,
    SampleFrame,
    SPWVDResult,
)
from .serial_receiver import SerialReceiver
from .storage import SessionRecorder, export_engine_results


APP_STYLE = """
QWidget {
    background: #F7F3EE;
    color: #3F3A37;
    font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
    font-size: 14px;
}
QMainWindow {
    background: #F7F3EE;
}
QFrame#hero {
    background: #EEE8F2;
    border: 1px solid #E2D9E7;
    border-radius: 22px;
}
QFrame[class="metricCard"] {
    background: #FCFAF7;
    border: 1px solid #E8E0D8;
    border-radius: 18px;
}
QLabel#heroTitle {
    font-size: 24px;
    font-weight: 650;
}
QLabel#heroSub {
    color: #756E69;
    font-size: 13px;
}
QLabel#narrativeText {
    color: #4E4945;
    font-size: 15px;
    font-weight: 520;
}
QLabel#sourceText {
    color: #756E69;
    font-size: 12px;
}
QLabel#disclaimerBanner {
    color: #665E58;
    font-size: 12px;
    background: #EFE7E0;
    border: 1px solid #E2D7CE;
    border-radius: 10px;
    padding: 8px 10px;
}
QLabel[class="metricValue"] {
    font-size: 28px;
    font-weight: 650;
}
QLabel[class="metricName"] {
    color: #7C746E;
    font-size: 13px;
}
QPushButton {
    min-height: 38px;
    padding: 0 16px;
    border: 1px solid #D9D0C8;
    border-radius: 12px;
    background: #FCFAF7;
}
QPushButton:hover {
    background: #F1ECE6;
}
QPushButton#primary {
    background: #82758F;
    color: white;
    border: none;
}
QPushButton#mark {
    background: #B86F68;
    color: white;
    border: none;
    font-weight: 600;
}
QPushButton#mark:hover {
    background: #A9605A;
}
QComboBox {
    min-height: 38px;
    padding: 0 12px;
    border: 1px solid #D9D0C8;
    border-radius: 12px;
    background: #FCFAF7;
}
QProgressBar {
    min-height: 12px;
    max-height: 12px;
    border: none;
    border-radius: 6px;
    background: #E7E0DA;
    text-align: center;
}
QProgressBar::chunk {
    border-radius: 6px;
    background: #91A591;
}
QTabWidget::pane {
    border: 0;
}
QTabBar::tab {
    padding: 10px 18px;
    margin-right: 6px;
    border-radius: 10px;
    background: #EEE8E2;
}
QTabBar::tab:selected {
    background: #DCD1E2;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QScrollBar:vertical {
    width: 12px;
    margin: 2px 0 2px 0;
    background: #EEE8E2;
    border-radius: 6px;
}
QScrollBar::handle:vertical {
    min-height: 36px;
    background: #B8ACA2;
    border-radius: 6px;
}
QScrollBar::handle:vertical:hover {
    background: #9D9086;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}
"""


class MetricCard(QFrame):
    """首页三个核心指标卡，减少传统医疗监护仪式的信息密度。"""

    def __init__(self, name: str, unit: str = ""):
        super().__init__()
        self.setProperty("class", "metricCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)

        self.name_label = QLabel(name)
        self.name_label.setProperty("class", "metricName")

        self.value_label = QLabel("--")
        self.value_label.setProperty("class", "metricValue")

        self.unit_label = QLabel(unit)
        self.unit_label.setProperty("class", "metricName")

        layout.addWidget(self.name_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.unit_label)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.engine = AnalysisEngine()
        self.receiver = SerialReceiver(
            on_message=self._on_protocol_message,
            on_status=self._set_worker_status,
            on_protocol_health=self.engine.ingest_protocol_health,
            on_io_trace=self._on_transport_io_trace,
        )

        self.recorder: SessionRecorder | None = None

        # 先断开设备再导出时，仍保留刚结束的完整实时会话目录。
        self._last_session_dir: Path | None = None

        # 该时间戳来自最近一次真正绘制到屏幕上的 PPG 右缘。
        # 软件人工标注使用它，不使用“点击瞬间后台线程收到的更晚 Sample”。
        self._displayed_end_t_us = 0

        self._worker_status = "未连接设备"
        self._csv_loading = False
        self._spwvd_loading = False
        self._spwvd_result: SPWVDResult | None = None

        self.setWindowTitle("此刻 · 身体节律")
        self.resize(1180, 820)
        self.setMinimumSize(520, 480)
        self.setStyleSheet(APP_STYLE)

        self._hero_compact = False
        self._responsive_mode = ""

        self._build_ui()
        self._refresh_ports()

        # F8 是不会和串口、图表拖动、文本输入冲突的全局人工标注快捷键。
        self.mark_annotation_shortcut = QShortcut(
            QKeySequence("F8"),
            self,
        )
        self.mark_annotation_shortcut.setContext(
            Qt.ShortcutContext.ApplicationShortcut
        )
        self.mark_annotation_shortcut.activated.connect(
            self._mark_annotation
        )

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh_ui)
        self.timer.start(500)

    def _build_ui(self) -> None:
        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(14)
        self.root_layout = root
        self.setCentralWidget(container)

        # ------------------------------------------------------------------
        # 顶部连接工具栏：使用 GridLayout，窗口变窄时可以安全换行。
        # ------------------------------------------------------------------
        self.toolbar_widget = QWidget()
        self.toolbar_layout = QGridLayout(
            self.toolbar_widget
        )
        self.toolbar_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        self.toolbar_layout.setHorizontalSpacing(8)
        self.toolbar_layout.setVerticalSpacing(8)

        self.port_combo = QComboBox()
        self.port_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        self.refresh_port_button = QPushButton("刷新串口")
        self.refresh_port_button.clicked.connect(self._refresh_ports)

        self.connect_button = QPushButton("连接设备")
        self.connect_button.setObjectName("primary")
        self.connect_button.clicked.connect(self._toggle_connection)

        self.open_csv_button = QPushButton("打开历史 CSV")
        self.open_csv_button.clicked.connect(self._open_csv)

        self.export_button = QPushButton("导出分析结果")
        self.export_button.clicked.connect(self._export_results)

        self._toolbar_widgets = [
            self.port_combo,
            self.refresh_port_button,
            self.connect_button,
            self.open_csv_button,
            self.export_button,
        ]

        for widget in self._toolbar_widgets[1:]:
            widget.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )

        root.addWidget(self.toolbar_widget)

        # ------------------------------------------------------------------
        # 软件人工标注：窄窗口时说明文字自动换到下一行。
        # ------------------------------------------------------------------
        self.annotation_widget = QWidget()
        self.annotation_layout = QGridLayout(
            self.annotation_widget
        )
        self.annotation_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        self.annotation_layout.setHorizontalSpacing(8)
        self.annotation_layout.setVerticalSpacing(6)

        self.annotation_title_label = QLabel("人工标注")

        self.annotation_type_combo = QComboBox()
        self.annotation_type_combo.addItems([
            "未分类",
            "峰位漂移",
            "漏检",
            "多检",
            "周期跳变",
            "其他",
        ])
        self.annotation_type_combo.setToolTip(
            "可先保持‘未分类’；时间戳会在按键瞬间立即保存。"
        )

        self.mark_annotation_button = QPushButton(
            "标记异常 · F8"
        )
        self.mark_annotation_button.setObjectName(
            "mark"
        )
        self.mark_annotation_button.setEnabled(
            False
        )
        self.mark_annotation_button.clicked.connect(
            self._mark_annotation
        )

        self.annotation_hint = QLabel(
            "屏幕显示约7.25秒成熟波形；看到问题后3秒内按F8。"
        )
        self.annotation_hint.setObjectName(
            "heroSub"
        )
        self.annotation_hint.setWordWrap(True)

        self._annotation_widgets = [
            self.annotation_title_label,
            self.annotation_type_combo,
            self.mark_annotation_button,
            self.annotation_hint,
        ]
        root.addWidget(self.annotation_widget)

        # ------------------------------------------------------------------
        # C 端首页主视觉。
        # 专业分析页会自动折叠成极简条，避免占用图表纵向空间。
        # ------------------------------------------------------------------
        self.hero = QFrame()
        self.hero.setObjectName("hero")
        self.hero_layout = QVBoxLayout(self.hero)
        self.hero_layout.setContentsMargins(24, 20, 24, 20)
        self.hero_layout.setSpacing(12)

        self.hero_title = QLabel("此刻 · 身体节律")
        self.hero_title.setObjectName("heroTitle")

        self.hero_compact_summary = QLabel(
            "心率 -- 次/分 · 心跳起伏 -- 毫秒 · 当前信号 --%"
        )
        self.hero_compact_summary.setObjectName("heroSub")
        self.hero_compact_summary.setWordWrap(False)
        self.hero_compact_summary.setVisible(False)

        self.status_label = QLabel("等待设备或历史记录")
        self.status_label.setObjectName("heroSub")
        self.status_label.setWordWrap(True)

        self.hero_layout.addWidget(self.hero_title)
        self.hero_layout.addWidget(self.hero_compact_summary)
        self.hero_layout.addWidget(self.status_label)

        self.metric_cards_widget = QWidget()
        self.card_row = QGridLayout(
            self.metric_cards_widget
        )
        self.card_row.setContentsMargins(0, 0, 0, 0)
        self.card_row.setHorizontalSpacing(12)
        self.card_row.setVerticalSpacing(10)

        self.hr_card = MetricCard("心率", "次/分")
        self.rmssd_card = MetricCard("心跳起伏", "毫秒")
        self.conf_card = MetricCard("当前信号", "%")

        self._metric_cards = [
            self.hr_card,
            self.rmssd_card,
            self.conf_card,
        ]
        self.hero_layout.addWidget(
            self.metric_cards_widget
        )

        self.hero_quality_widget = QWidget()
        self.hero_quality_layout = QVBoxLayout(
            self.hero_quality_widget
        )
        self.hero_quality_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        self.hero_quality_layout.setSpacing(8)

        self.conf_progress = QProgressBar()
        self.conf_progress.setRange(0, 100)
        self.conf_progress.setTextVisible(False)

        self.quality_reason = QLabel("正在积累信号质量信息")
        self.quality_reason.setObjectName("heroSub")
        self.quality_reason.setWordWrap(True)

        self.hero_quality_layout.addWidget(
            self.conf_progress
        )
        self.hero_quality_layout.addWidget(
            self.quality_reason
        )
        self.hero_layout.addWidget(
            self.hero_quality_widget
        )
        root.addWidget(self.hero)

        # ------------------------------------------------------------------
        # 两层信息架构。
        # 每页内部使用原生 QScrollArea，任何分辨率下都不会截断底部图表。
        # ------------------------------------------------------------------
        self.tabs = QTabWidget()
        self.state_scroll = self._make_scrollable_page(
            self._build_state_tab(),
            always_vertical=False,
        )
        self.analysis_scroll = self._make_scrollable_page(
            self._build_analysis_tab(),
            always_vertical=True,
        )

        self.tabs.addTab(
            self.state_scroll,
            "此刻与趋势",
        )
        self.tabs.addTab(
            self.analysis_scroll,
            "更多细节",
        )
        self.tabs.currentChanged.connect(
            self._on_tab_changed
        )
        root.addWidget(self.tabs, 1)

        self.disclaimer = QLabel(
            "用于自我觉察和情绪疗愈互动，不用于医疗诊断。研究来源只说明曾出现过相似节律。"
        )
        self.disclaimer.setObjectName("disclaimerBanner")
        self.disclaimer.setWordWrap(True)
        root.addWidget(self.disclaimer)

        self._apply_responsive_layout(
            self.width()
        )
        self._on_tab_changed(
            self.tabs.currentIndex()
        )

    def _make_scrollable_page(
        self,
        content: QWidget,
        *,
        always_vertical: bool,
    ) -> QScrollArea:
        content.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.MinimumExpanding,
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
            if always_vertical
            else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        scroll.setWidget(content)
        return scroll

    def _clear_grid_layout(
        self,
        layout: QGridLayout,
        widgets: list[QWidget],
    ) -> None:
        for widget in widgets:
            layout.removeWidget(widget)

    def _set_hero_compact(
        self,
        compact: bool,
    ) -> None:
        if self._hero_compact == compact:
            return

        self._hero_compact = compact

        self.status_label.setVisible(
            not compact
        )
        self.metric_cards_widget.setVisible(
            not compact
        )
        self.hero_quality_widget.setVisible(
            not compact
        )
        self.hero_compact_summary.setVisible(
            compact
        )

        if compact:
            self.hero_layout.setContentsMargins(
                18,
                7,
                18,
                7,
            )
            self.hero_layout.setSpacing(2)
            self.hero_title.setStyleSheet(
                "font-size: 17px; font-weight: 650;"
            )
            self.hero.setMaximumHeight(72)
        else:
            self.hero_layout.setContentsMargins(
                24,
                20,
                24,
                20,
            )
            self.hero_layout.setSpacing(12)
            self.hero_title.setStyleSheet("")
            self.hero.setMaximumHeight(16777215)

    def _on_tab_changed(
        self,
        index: int,
    ) -> None:
        # 专业分析页固定采用极简 Hero。
        # 极小分辨率下状态页也自动折叠，优先保证图表和滚动区域可用。
        compact = (
            index == 1
            or self.height() < 650
            or self.width() < 700
        )
        self._set_hero_compact(
            compact
        )
        self._apply_responsive_layout(
            self.width()
        )

    def _apply_responsive_layout(
        self,
        width: int,
    ) -> None:
        width = max(
            int(width),
            1,
        )

        if width >= 1000:
            mode = "wide"
            margins = (24, 22, 24, 22)
        elif width >= 700:
            mode = "medium"
            margins = (14, 12, 14, 12)
        else:
            mode = "narrow"
            margins = (8, 8, 8, 8)

        self.root_layout.setContentsMargins(
            *margins
        )
        self.root_layout.setSpacing(
            12 if mode == "wide" else 8
        )

        # 顶部连接栏换行。
        self._clear_grid_layout(
            self.toolbar_layout,
            self._toolbar_widgets,
        )
        for column in range(8):
            self.toolbar_layout.setColumnStretch(
                column,
                0,
            )

        if mode == "wide":
            self.toolbar_layout.addWidget(
                self.port_combo,
                0,
                0,
                1,
                4,
            )
            for column, widget in enumerate(
                self._toolbar_widgets[1:],
                start=4,
            ):
                self.toolbar_layout.addWidget(
                    widget,
                    0,
                    column,
                )
            self.toolbar_layout.setColumnStretch(
                0,
                1,
            )
        elif mode == "medium":
            self.toolbar_layout.addWidget(
                self.port_combo,
                0,
                0,
                1,
                4,
            )
            for column, widget in enumerate(
                self._toolbar_widgets[1:]
            ):
                self.toolbar_layout.addWidget(
                    widget,
                    1,
                    column,
                )
                self.toolbar_layout.setColumnStretch(
                    column,
                    1,
                )
        else:
            self.toolbar_layout.addWidget(
                self.port_combo,
                0,
                0,
                1,
                2,
            )
            self.toolbar_layout.addWidget(
                self.refresh_port_button,
                1,
                0,
            )
            self.toolbar_layout.addWidget(
                self.connect_button,
                1,
                1,
            )
            self.toolbar_layout.addWidget(
                self.open_csv_button,
                2,
                0,
            )
            self.toolbar_layout.addWidget(
                self.export_button,
                2,
                1,
            )
            self.toolbar_layout.setColumnStretch(
                0,
                1,
            )
            self.toolbar_layout.setColumnStretch(
                1,
                1,
            )

        # 人工标注栏换行。
        self._clear_grid_layout(
            self.annotation_layout,
            self._annotation_widgets,
        )
        for column in range(4):
            self.annotation_layout.setColumnStretch(
                column,
                0,
            )

        if mode == "wide":
            self.annotation_layout.addWidget(
                self.annotation_title_label,
                0,
                0,
            )
            self.annotation_layout.addWidget(
                self.annotation_type_combo,
                0,
                1,
            )
            self.annotation_layout.addWidget(
                self.mark_annotation_button,
                0,
                2,
            )
            self.annotation_layout.addWidget(
                self.annotation_hint,
                0,
                3,
            )
            self.annotation_layout.setColumnStretch(
                3,
                1,
            )
        elif mode == "medium":
            self.annotation_layout.addWidget(
                self.annotation_title_label,
                0,
                0,
            )
            self.annotation_layout.addWidget(
                self.annotation_type_combo,
                0,
                1,
            )
            self.annotation_layout.addWidget(
                self.mark_annotation_button,
                0,
                2,
            )
            self.annotation_layout.addWidget(
                self.annotation_hint,
                1,
                0,
                1,
                3,
            )
            self.annotation_layout.setColumnStretch(
                1,
                1,
            )
        else:
            self.annotation_layout.addWidget(
                self.annotation_title_label,
                0,
                0,
            )
            self.annotation_layout.addWidget(
                self.annotation_type_combo,
                0,
                1,
            )
            self.annotation_layout.addWidget(
                self.mark_annotation_button,
                1,
                0,
                1,
                2,
            )
            self.annotation_layout.addWidget(
                self.annotation_hint,
                2,
                0,
                1,
                2,
            )
            self.annotation_layout.setColumnStretch(
                1,
                1,
            )

        # 首页三张指标卡：只有完整 Hero 才参与布局。
        self._clear_grid_layout(
            self.card_row,
            self._metric_cards,
        )
        for column in range(3):
            self.card_row.setColumnStretch(
                column,
                0,
            )
        if width >= 700:
            for column, card in enumerate(
                self._metric_cards
            ):
                self.card_row.addWidget(
                    card,
                    0,
                    column,
                )
                self.card_row.setColumnStretch(
                    column,
                    1,
                )
        else:
            for row, card in enumerate(
                self._metric_cards
            ):
                self.card_row.addWidget(
                    card,
                    row,
                    0,
                )
            self.card_row.setColumnStretch(
                0,
                1,
            )

        # 图表采用“最小高度 + 页内滚动”，不再依赖固定窗口分辨率。
        if self.height() >= 900:
            analysis_heights = (260, 280, 300)
            state_heights = (280, 190)
        elif self.height() >= 700:
            analysis_heights = (230, 250, 270)
            state_heights = (250, 175)
        else:
            analysis_heights = (200, 220, 240)
            state_heights = (220, 160)

        self.prototype_score_plot.setMinimumHeight(
            analysis_heights[0]
        )
        self.frequency_trend_plot.setMinimumHeight(
            analysis_heights[0]
        )
        self.psd_plot.setMinimumHeight(
            analysis_heights[1]
        )
        self.tf_plot.setMinimumHeight(
            analysis_heights[2]
        )
        self.signal_plot.setMinimumHeight(
            state_heights[0]
        )
        self.trend_plot.setMinimumHeight(
            state_heights[1]
        )

        should_compact = (
            self.tabs.currentIndex() == 1
            or self.height() < 650
            or width < 700
        )
        self._set_hero_compact(
            should_compact
        )
        self._responsive_mode = mode

        QTimer.singleShot(
            0,
            self._sync_signal_debug_view,
        )
        QTimer.singleShot(
            0,
            self._sync_frequency_trend_view,
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(
            self,
            "root_layout",
        ):
            self._apply_responsive_layout(
                event.size().width()
            )

    def _style_plot(self, plot: pg.PlotWidget) -> None:
        # 图表背景保持透明 / 暖白，避免传统监护仪的强对比黑底。
        plot.setBackground("#FCFAF7")
        plot.showGrid(x=True, y=True, alpha=0.12)

        for axis_name in ("bottom", "left", "right", "top"):
            axis = plot.getAxis(axis_name)
            axis.setTextPen("#746C66")
            axis.setPen(pg.mkPen("#BFAF9E", width=1.35))
            axis.setTickPen(pg.mkPen("#BFAF9E", width=1.15))

        plot.getPlotItem().layout.setContentsMargins(10, 8, 18, 8)

    def _build_state_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)

        # ------------------------------------------------------------------
        # 实时 PPG + 心跳识别 Debug 叠加层
        # ------------------------------------------------------------------
        self.signal_plot = pg.PlotWidget()
        self._style_plot(self.signal_plot)

        # 人工视觉复核页去掉网格，只保留波形本身和正式心搏序列。
        self.signal_plot.showGrid(
            x=False,
            y=False,
        )

        self.signal_plot.setLabel("left", "腕带光学波形")
        self.signal_plot.setLabel("bottom", "最近几秒")
        self.signal_curve = self.signal_plot.plot(
            pen=pg.mkPen("#7F718D", width=2)
        )

        # 人工问题区间。
        # 只保留半透明区域，不再增加第三根竖线。
        self.annotation_region = pg.LinearRegionItem(
            values=(-3.0, 0.0),
            movable=False,
            brush=pg.mkBrush(
                184,
                111,
                104,
                36,
            ),
            pen=pg.mkPen(
                "#B86F68",
                width=1,
            ),
        )
        self.annotation_region.setZValue(
            -5
        )
        self.annotation_region.setVisible(
            False
        )
        self.signal_plot.addItem(
            self.annotation_region
        )

        # 右侧独立 0/1 轴。
        # PPG 仍使用左侧物理幅值轴，心跳识别状态不会因为波形幅度变化而被压扁。
        self.signal_plot.showAxis("right")
        self.signal_plot.getAxis("right").setLabel("找到的心跳")

        self.signal_debug_view = pg.ViewBox()
        self.signal_plot.scene().addItem(
            self.signal_debug_view
        )
        self.signal_plot.getAxis("right").linkToView(
            self.signal_debug_view
        )
        self.signal_debug_view.setXLink(
            self.signal_plot.getViewBox()
        )
        self.signal_debug_view.setYRange(
            -0.05,
            1.05,
            padding=0.0,
        )

        # v0.3.7：
        # 波形图严格只保留两条连续视觉序列：
        # 1) 左轴紫色滤波 PPG；
        # 2) 右轴绿色 8 秒整窗纠错后的正式 Beat 0/1。
        #
        # detector score / Candidate / Firmware Winner 仍保留在数据层、
        # Debug 数字和导出 CSV 中。
        self.accepted_beat_curve = pg.PlotCurveItem(
            pen=pg.mkPen(
                "#4F8A6B",
                width=3,
            )
        )

        self.signal_debug_view.addItem(
            self.accepted_beat_curve
        )

        self.signal_plot.getViewBox().sigResized.connect(
            self._sync_signal_debug_view
        )
        self._sync_signal_debug_view()

        self.signal_debug_label = QLabel(
            "紫线是腕带波形，绿线表示软件找到的心跳；这张图只在排查读数异常时需要看。"
        )
        self.signal_debug_label.setObjectName("heroSub")
        self.signal_debug_label.setWordWrap(True)

        self.trend_plot = pg.PlotWidget()
        self._style_plot(self.trend_plot)
        self.trend_plot.setLabel("left", "心跳起伏", units="毫秒")
        self.trend_plot.setLabel("bottom", "记录时间", units="分钟")
        self.trend_curve = self.trend_plot.plot(
            pen=pg.mkPen("#7C967D", width=2),
            symbol="o",
            symbolSize=5,
        )

        self.hour_experience_frame = QFrame()
        self.hour_experience_frame.setProperty(
            "class",
            "metricCard",
        )
        hour_layout = QVBoxLayout(
            self.hour_experience_frame
        )
        hour_layout.setContentsMargins(
            16,
            14,
            16,
            14,
        )
        hour_layout.setSpacing(6)

        self.hour_title_label = QLabel(
            "过去一小时 · 身体节律"
        )
        self.hour_title_label.setObjectName(
            "heroTitle"
        )
        self.hour_title_label.setStyleSheet(
            "font-size: 17px; font-weight: 650;"
        )

        self.hour_stage_label = QLabel(
            "正在建立这次记录的基础观察"
        )
        self.hour_stage_label.setWordWrap(
            True
        )
        self.hour_stage_label.setObjectName(
            "heroSub"
        )

        self.hour_state_label = QLabel(
            "正在等待足够清晰、连续的心跳记录"
        )
        self.hour_state_label.setWordWrap(
            True
        )
        self.hour_state_label.setObjectName(
            "narrativeText"
        )

        self.hour_transition_label = QLabel(
            "这段变化还在逐渐形成"
        )
        self.hour_transition_label.setObjectName(
            "narrativeText"
        )
        self.hour_transition_label.setWordWrap(
            True
        )

        self.hour_sources_label = QLabel(
            "研究依据：等待出现可比较的节律"
        )
        self.hour_sources_label.setObjectName(
            "sourceText"
        )
        self.hour_sources_label.setWordWrap(
            True
        )
        self.hour_sources_label.setTextFormat(
            Qt.TextFormat.RichText
        )
        self.hour_sources_label.setOpenExternalLinks(
            True
        )
        self.hour_sources_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )

        self.hour_disclaimer_label = QLabel(
            "研究来源只说明曾有人出现过相似的心跳节律，不代表你的情绪、身份或健康结论。"
        )
        self.hour_disclaimer_label.setObjectName(
            "sourceText"
        )
        self.hour_disclaimer_label.setWordWrap(
            True
        )

        hour_layout.addWidget(
            self.hour_title_label
        )
        hour_layout.addWidget(
            self.hour_stage_label
        )
        hour_layout.addWidget(
            self.hour_state_label
        )
        hour_layout.addWidget(
            self.hour_transition_label
        )
        hour_layout.addWidget(
            self.hour_sources_label
        )
        hour_layout.addWidget(
            self.hour_disclaimer_label
        )

        # 主tab先回答“这一段发生了什么”，再给出轻量趋势。
        # PPG人工复核与协议诊断移到专业分析页。
        layout.addWidget(
            self.hour_experience_frame
        )
        layout.addWidget(QLabel("心跳起伏趋势"))
        layout.addWidget(self.trend_plot, 1)
        return page

    def _sync_signal_debug_view(self) -> None:
        """让右侧 0/1 调试轴始终与主 PPG 图的 X 轴和绘图区完全重合。"""
        if not hasattr(self, "signal_debug_view"):
            return

        main_view = self.signal_plot.getViewBox()
        self.signal_debug_view.setGeometry(
            main_view.sceneBoundingRect()
        )
        self.signal_debug_view.linkedViewChanged(
            main_view,
            pg.ViewBox.XAxis,
        )

    def _sync_frequency_trend_view(self) -> None:
        if not hasattr(self, "frequency_trend_view"):
            return

        main_view = self.frequency_trend_plot.getViewBox()
        self.frequency_trend_view.setGeometry(
            main_view.sceneBoundingRect()
        )
        self.frequency_trend_view.linkedViewChanged(
            main_view,
            pg.ViewBox.XAxis,
        )

    def _build_analysis_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(10)

        summary = QHBoxLayout()
        self.freq_status = QLabel("最近5分钟：正在积累连续心跳")
        self.freq_status.setWordWrap(True)

        self.freq_stats_label = QLabel("这次记录：还没有足够清晰的5分钟片段")
        self.freq_stats_label.setWordWrap(True)
        self.freq_stats_label.setObjectName("heroSub")

        self.freq_auto_label = QLabel("身体节律：等待更多连续记录。")
        self.freq_auto_label.setWordWrap(True)
        self.freq_auto_label.setObjectName("heroSub")

        self.freq_guide_label = QLabel(
            "读图方法：越靠左越慢，越靠右越快；线越高，说明那种节律越明显。"
        )
        self.freq_guide_label.setWordWrap(True)
        self.freq_guide_label.setObjectName("heroSub")

        self.spwvd_button = QPushButton("更新5分钟节律变化图")
        self.spwvd_button.clicked.connect(self._start_spwvd)

        summary.addWidget(self.freq_status, 1)
        summary.addWidget(self.spwvd_button)
        layout.addLayout(summary)
        layout.addWidget(self.freq_stats_label)
        layout.addWidget(self.freq_auto_label)
        layout.addWidget(self.freq_guide_label)

        self.protocol_debug_label = QLabel(
            "设备连接：等待数据"
        )
        self.protocol_debug_label.setWordWrap(True)
        self.protocol_debug_label.setObjectName("heroSub")

        self.quality_debug_label = QLabel(
            "信号观察：正在积累"
        )
        self.quality_debug_label.setWordWrap(True)
        self.quality_debug_label.setObjectName("heroSub")

        layout.addWidget(QLabel("设备与信号"))
        layout.addWidget(self.protocol_debug_label)
        layout.addWidget(self.quality_debug_label)
        layout.addWidget(QLabel("心跳波形（排查读数异常时查看）"))
        layout.addWidget(self.signal_plot)
        layout.addWidget(self.signal_debug_label)

        self.research_state_frame = QFrame()
        self.research_state_frame.setProperty(
            "class",
            "metricCard",
        )
        research_layout = QVBoxLayout(
            self.research_state_frame
        )
        research_layout.setContentsMargins(
            16,
            14,
            16,
            14,
        )
        research_layout.setSpacing(6)

        self.research_machine_label = QLabel(
            "解读进度：正在积累可比较的记录"
        )
        self.research_machine_label.setWordWrap(
            True
        )

        self.research_match_label = QLabel(
            "研究中的相似记录：等待更多连续数据"
        )
        self.research_match_label.setWordWrap(
            True
        )
        self.research_match_label.setObjectName(
            "heroSub"
        )

        self.research_trait_label = QLabel(
            "长期变化：需要多天记录后再观察"
        )
        self.research_trait_label.setWordWrap(
            True
        )
        self.research_trait_label.setObjectName(
            "heroSub"
        )

        self.research_sources_label = QLabel(
            "研究依据：等待出现可比较的节律"
        )
        self.research_sources_label.setWordWrap(
            True
        )
        self.research_sources_label.setTextFormat(
            Qt.TextFormat.RichText
        )
        self.research_sources_label.setOpenExternalLinks(
            True
        )
        self.research_sources_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self.research_sources_label.setObjectName(
            "heroSub"
        )

        research_layout.addWidget(
            self.research_machine_label
        )
        research_layout.addWidget(
            self.research_match_label
        )
        research_layout.addWidget(
            self.research_trait_label
        )
        research_layout.addWidget(
            self.research_sources_label
        )
        layout.addWidget(
            self.research_state_frame
        )

        self.prototype_score_plot = pg.PlotWidget()
        self._style_plot(
            self.prototype_score_plot
        )
        self.prototype_score_plot.setMinimumHeight(
            220
        )
        self.prototype_score_plot.setLabel(
            "left",
            "相似程度",
        )
        self.prototype_score_plot.setLabel(
            "bottom",
            "过去一小时",
            units="min",
        )
        self.prototype_score_plot.setYRange(
            0.0,
            1.02,
        )
        self.prototype_score_plot.addLegend(
            offset=(
                12,
                10,
            )
        )

        prototype_specs = [
            ("STEADY_EVEN", "平稳而均匀", "#7F8A82"),
            ("RESONANCE_0P1", "缓慢而规律", "#70869B"),
            ("WHOLE_VARIABILITY_RISE", "起伏整体变强", "#609B7C"),
            ("WHOLE_VARIABILITY_NARROW", "起伏整体收窄", "#D67A56"),
            ("SOOTHING_DOWNSHIFT", "安抚下来", "#8B7FA3"),
            ("FOCUSED_ENGAGEMENT", "进入专注状态", "#A18B5B"),
            ("REBOUND_RECOVERY", "从紧绷中回弹", "#9B7B62"),
        ]

        self.prototype_score_curves = {}

        for (
            code,
            name,
            color,
        ) in prototype_specs:
            self.prototype_score_curves[
                code
            ] = self.prototype_score_plot.plot(
                pen=pg.mkPen(
                    color,
                    width=2.0,
                ),
                name=name,
            )

        self.frequency_trend_plot = pg.PlotWidget()
        self._style_plot(self.frequency_trend_plot)
        self.frequency_trend_plot.setMinimumHeight(240)
        self.frequency_trend_plot.setLabel("left", "心跳起伏强度")
        self.frequency_trend_plot.setLabel("bottom", "记录时间", units="分钟")
        self.frequency_trend_plot.showAxis("right")
        self.frequency_trend_plot.getAxis("right").setLabel("整体快慢位置（越高越快）")
        self.frequency_trend_plot.addLegend(offset=(12, 10))

        self.vlf_trend_curve = self.frequency_trend_plot.plot(
            pen=pg.mkPen("#9B7B62", width=2.2),
            name="很慢的背景变化",
        )
        self.lf_trend_curve = self.frequency_trend_plot.plot(
            pen=pg.mkPen("#D67A56", width=2.2),
            name="较慢的起伏",
        )
        self.hf_trend_curve = self.frequency_trend_plot.plot(
            pen=pg.mkPen("#609B7C", width=2.2),
            name="呼吸相关快起伏",
        )

        self.frequency_trend_view = pg.ViewBox()
        self.frequency_trend_plot.scene().addItem(self.frequency_trend_view)
        self.frequency_trend_plot.getAxis("right").linkToView(self.frequency_trend_view)
        self.frequency_trend_view.setXLink(self.frequency_trend_plot)
        self.median_freq_curve = pg.PlotCurveItem(
            pen=pg.mkPen("#7F718D", width=2.4, style=Qt.DashLine),
            name="整体快慢位置",
        )
        self.frequency_trend_view.addItem(self.median_freq_curve)
        self.frequency_trend_plot.getViewBox().sigResized.connect(
            self._sync_frequency_trend_view
        )
        self._sync_frequency_trend_view()

        self.freq_trend_hint = QLabel(
            "趋势线：棕色看很慢的背景变化，橙色看较慢起伏，绿色看呼吸相关快起伏，紫色虚线看整体偏慢还是偏快。"
        )
        self.freq_trend_hint.setObjectName("heroSub")

        self.psd_plot = pg.PlotWidget()
        self._style_plot(self.psd_plot)
        self.psd_plot.setMinimumHeight(260)
        self.psd_plot.setLabel("left", "这种节律有多明显")
        self.psd_plot.setLabel("bottom", "节律快慢（左慢右快）")
        self.psd_curve = self.psd_plot.plot(
            pen=pg.mkPen("#70869B", width=2.4)
        )
        self.psd_plot.setXRange(0.0, 0.42)
        self._add_frequency_zone_regions(self.psd_plot, horizontal=False)

        self.psd_band_hint = QLabel(
            "灰色表示很慢的背景变化，橙色到绿色从较慢起伏过渡到较快、常跟呼吸一起变化的起伏。"
        )
        self.psd_band_hint.setObjectName("heroSub")

        self.tf_plot = pg.PlotWidget()
        self._style_plot(self.tf_plot)
        self.tf_plot.setMinimumHeight(280)
        self.tf_plot.setLabel("left", "节律快慢（下慢上快）")
        self.tf_plot.setLabel("bottom", "过去5分钟", units="秒")
        self.tf_image = pg.ImageItem()
        self.tf_plot.addItem(self.tf_image)
        self.tf_plot.setYRange(0.0, 0.42)
        self._add_frequency_zone_regions(self.tf_plot, horizontal=True)

        self.spwvd_hint = QLabel(
            "越亮的地方表示那种快慢节奏在那个时刻更明显；颜色只帮助区分快慢范围，不代表某种情绪或神经状态。"
        )
        self.spwvd_hint.setObjectName("heroSub")
        self.spwvd_hint.setWordWrap(True)

        layout.addWidget(
            QLabel(
                "过去一小时 · 稳定节律形态的变化"
            )
        )
        layout.addWidget(
            self.prototype_score_plot
        )
        self.prototype_score_hint = QLabel(
            "曲线先汇总数分钟的身体变化，再判断这种形态是否持续；"
            "短暂波动不会立即变成新的稳定结论。"
        )
        self.prototype_score_hint.setWordWrap(True)
        self.prototype_score_hint.setObjectName("heroSub")
        layout.addWidget(self.prototype_score_hint)
        layout.addWidget(QLabel("不同快慢的心跳起伏趋势"))
        layout.addWidget(self.frequency_trend_plot)
        layout.addWidget(self.freq_trend_hint)
        layout.addWidget(QLabel("最近5分钟 · 哪些快慢节律更明显"))
        layout.addWidget(self.psd_plot)
        layout.addWidget(self.psd_band_hint)
        layout.addWidget(QLabel("最近5分钟 · 这些节律什么时候出现"))
        layout.addWidget(self.tf_plot)
        layout.addWidget(self.spwvd_hint)
        return page

    def _add_frequency_zone_regions(
        self,
        plot: pg.PlotWidget,
        *,
        horizontal: bool,
    ) -> None:
        for band in frequency_zone_brushes():
            item = pg.LinearRegionItem(
                values=(band["low_hz"], band["high_hz"]),
                orientation=(
                    pg.LinearRegionItem.Horizontal
                    if horizontal
                    else pg.LinearRegionItem.Vertical
                ),
                movable=False,
                brush=pg.mkBrush(*band["rgb"], 30),
                pen=pg.mkPen(*band["rgb"], 90),
            )
            item.setZValue(-20)
            plot.addItem(item)

    def _colorize_spwvd(
        self,
        power: np.ndarray,
        freqs_hz: np.ndarray,
    ) -> np.ndarray:
        display = np.log1p(power.T)
        finite = display[np.isfinite(display)]

        if finite.size:
            low, high = np.percentile(finite, [2.0, 98.0])
            if high <= low:
                high = low + 1.0
            normalized = np.clip((display - low) / (high - low), 0.0, 1.0)
        else:
            normalized = np.zeros_like(display, dtype=float)

        rgb = np.zeros((display.shape[0], display.shape[1], 3), dtype=np.ubyte)
        freqs = np.asarray(freqs_hz, dtype=float)

        palette = [
            {"low_hz": 0.0, "high_hz": 0.04, "rgb": (184, 176, 168)},
            *AUTONOMIC_ZONES,
        ]

        for band in palette:
            mask = (freqs >= band["low_hz"]) & (freqs < band["high_hz"])
            if not np.any(mask):
                continue

            base = np.asarray(band["rgb"], dtype=float) / 255.0
            rows = normalized[:, mask]
            color = np.clip(rows[..., None] * base[None, None, :], 0.0, 1.0)
            rgb[:, mask, :] = np.maximum(
                rgb[:, mask, :],
                np.asarray(np.round(color * 255.0), dtype=np.ubyte),
            )

        return rgb

    def _refresh_ports(self) -> None:
        current = self.port_combo.currentText()
        ports = [p.device for p in list_ports.comports()]

        self.port_combo.clear()
        self.port_combo.addItems(ports)

        if current in ports:
            self.port_combo.setCurrentText(current)

    def _toggle_connection(self) -> None:
        if self.receiver.running:
            self.receiver.stop()

            # 设备停止后，不再需要遵守实时 7.25 s 固定滞后。
            # 使用已经采到的完整尾部 PPG 做一次最终离线提交。
            self.engine.force_update()

            self._close_recorder()
            self.connect_button.setText("连接设备")
            return

        port = self.port_combo.currentText().strip()
        if not port:
            QMessageBox.information(self, "没有串口", "请先连接设备并刷新串口列表。")
            return

        try:
            self.engine.reset()
            self._displayed_end_t_us = 0

            desktop_root = Path(__file__).resolve().parents[2]
            self.recorder = SessionRecorder(
                desktop_root / "sessions"
            )
            self._last_session_dir = (
                self.recorder.session_dir
            )
            self.engine.attach_provenance_recorder(
                self.recorder.provenance
            )

            self.receiver.start(port, 115200)
            self.connect_button.setText("断开设备")

        except Exception as exc:
            self._close_recorder()
            QMessageBox.critical(self, "连接失败", str(exc))

    def _on_protocol_message(self, message: object) -> None:
        # 该回调运行于串口后台线程。
        # AnalysisEngine 与 SessionRecorder 都有自己的线程同步，不直接操作 Qt 控件。
        if self.recorder:
            self.recorder.record(message)

        if isinstance(message, SampleFrame):
            self.engine.ingest_sample(message)
        elif isinstance(message, BeatFrame):
            self.engine.ingest_beat(message)
        elif isinstance(message, FirmwareMetricFrame):
            self.engine.ingest_firmware_metric(message)
        elif isinstance(message, DiagnosticFrame):
            self.engine.ingest_diagnostic(message)

    def _on_transport_io_trace(self, row: dict) -> None:
        if self.recorder:
            self.recorder.record_transport_io(row)

    def _set_worker_status(self, text: str) -> None:
        # 后台线程只更新普通 Python 字符串；
        # Qt 主线程在 500 ms 定时刷新时读取。
        self._worker_status = text

    def _open_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开历史记录",
            "",
            "CSV (*.csv)",
        )
        if not path:
            return

        if self.receiver.running:
            self.receiver.stop()
            self.engine.force_update()
            self._close_recorder()
            self.connect_button.setText("连接设备")

        if self._csv_loading:
            return

        self._last_session_dir = None
        self._displayed_end_t_us = 0

        self._csv_loading = True
        self._worker_status = f"正在分析：{Path(path).name}"

        def worker() -> None:
            try:
                load_csv_into_engine(path, self.engine)
                self._worker_status = f"历史记录已完成：{Path(path).name}"
            except Exception as exc:
                self._worker_status = f"CSV 分析失败：{exc}"
            finally:
                self._csv_loading = False

        threading.Thread(
            target=worker,
            name="CSVLoader",
            daemon=True,
        ).start()

    def _mark_annotation(self) -> None:
        """
        软件人工标注入口。

        关键语义：
        - 使用最近一次绘图时冻结的 `_displayed_end_t_us`；
        - 同时保存 host monotonic clock；
        - 不弹对话框，保证时间标注动作尽可能快；
        - 当前下拉框的类型只是标签，不影响算法。
        """
        if (
            not self.receiver.running
            or self._displayed_end_t_us <= 0
        ):
            self._worker_status = (
                "异常标记未记录：请先连接腕带并等待出现实时波形。"
            )
            return

        annotation = (
            self.engine.add_user_annotation(
                device_t_us=(
                    self._displayed_end_t_us
                ),
                host_monotonic_ns=(
                    time.monotonic_ns()
                ),
                label_type=(
                    self.annotation_type_combo.currentText()
                ),
            )
        )

        if annotation is None:
            self._worker_status = (
                "人工标注未记录：当前屏幕数据已经不在可用设备时间范围内。"
            )
            return

        if self.recorder:
            try:
                self.recorder.record_annotation(
                    annotation
                )
            except Exception as exc:
                self._worker_status = (
                    "人工标注已进入分析引擎，但实时标注落盘失败："
                    + str(exc)
                )
                return

        self._worker_status = (
            f"已标记异常 #{annotation.annotation_id} · "
            f"{annotation.label_type} · "
            f"纠错显示滞后 {annotation.ui_data_lag_ms:.0f} ms"
        )

        # 非阻塞视觉确认；800 ms 后恢复按钮文案。
        self.mark_annotation_button.setText(
            f"已标记 #{annotation.annotation_id}"
        )
        QTimer.singleShot(
            800,
            lambda: self.mark_annotation_button.setText(
                "标记异常 · F8"
            ),
        )

    def _export_results(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择导出目录",
        )
        if not folder:
            return

        try:
            out = Path(folder) / "hrv_export"

            # 非实时状态下把会话尾部也用全部已知波形完成离线纠错。
            # 实时连接时保持 7.25 s 固定滞后，不提前偷看未成熟区域。
            if not self.receiver.running:
                self.engine.force_update()

            raw_session_dir = (
                self._last_session_dir
            )

            if self.recorder:
                self.recorder.flush()
                raw_session_dir = (
                    self.recorder.session_dir
                )

            export_engine_results(
                self.engine,
                out,
                raw_session_dir=raw_session_dir,
            )
            QMessageBox.information(
                self,
                "导出完成",
                f"已导出到：\n{out}",
            )
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))

    def _start_spwvd(self) -> None:
        if self._spwvd_loading:
            return

        self._spwvd_loading = True
        self.spwvd_button.setEnabled(False)
        self.spwvd_button.setText("正在计算…")

        def worker() -> None:
            try:
                self._spwvd_result = self.engine.compute_spwvd()
            except Exception:
                self._spwvd_result = SPWVDResult(
                    valid=False,
                    message=traceback.format_exc(limit=1),
                )
            finally:
                self._spwvd_loading = False

        threading.Thread(
            target=worker,
            name="SPWVDWorker",
            daemon=True,
        ).start()

    def _refresh_ui(self) -> None:
        snapshot = self.engine.snapshot()
        protocol = snapshot.protocol_health

        # --------------------------------------------------------------
        # C端只给连接结果；协议计数完整保留在专业分析页。
        # --------------------------------------------------------------
        protocol_issue_count = int(
            protocol.crc_errors
            + protocol.format_errors
            + protocol.sample_seq_gaps
        )
        if self.receiver.running:
            connection_text = (
                "数据传输正常"
                if protocol_issue_count == 0
                else "正在接收，偶尔有短暂传输波动"
            )
        elif self._csv_loading:
            connection_text = "正在读取历史记录"
        elif self._worker_status.startswith("历史记录已完成"):
            connection_text = "历史记录已载入"
        else:
            connection_text = "当前未连接腕带"
        self.protocol_debug_label.setText(
            "设备连接：" + connection_text
        )

        if self.receiver.running:
            self.status_label.setText(
                "腕带已连接，正在连续观察"
            )
        elif self._csv_loading:
            self.status_label.setText(
                "正在读取历史记录"
            )
        elif self._worker_status.startswith(
            "历史记录已完成"
        ):
            self.status_label.setText(
                "历史记录已载入"
            )
        else:
            self.status_label.setText(
                "等待连接腕带或打开历史记录"
            )

        self.hr_card.value_label.setText(
            f"{snapshot.hr_bpm:.0f}"
            if snapshot.hr_bpm > 0
            else "--"
        )

        # 时域质量门失败时坚决显示 --。
        # candidate_rmssd 只存在于导出 JSON 的调试字段，不进入 C 端首页。
        self.rmssd_card.value_label.setText(
            f"{snapshot.time.rmssd_ms:.1f}"
            if snapshot.time.valid
            else "--"
        )

        sqi_percent = int(
            round(
                snapshot.signal_quality.sqi
                * 100
            )
        )
        self.conf_card.value_label.setText(
            str(sqi_percent)
        )
        self.conf_progress.setValue(
            sqi_percent
        )

        hr_compact = (
            f"{snapshot.hr_bpm:.0f}"
            if snapshot.hr_bpm > 0
            else "--"
        )
        rmssd_compact = (
            f"{snapshot.time.rmssd_ms:.1f}"
            if snapshot.time.valid
            else "--"
        )
        five_minute_text = (
            "5分钟观察清晰"
            if snapshot.frequency.status == "VALID"
            else (
                "5分钟观察可参考"
                if snapshot.frequency.status == "LIMITED"
                else "5分钟观察积累中"
            )
        )
        self.hero_compact_summary.setText(
            f"心率 {hr_compact} 次/分 · "
            f"心跳起伏 {rmssd_compact} 毫秒 · "
            f"当前信号 {sqi_percent}% · "
            f"{five_minute_text}"
        )

        if (
            snapshot.time.valid
            and snapshot.signal_quality.sqi >= 0.85
        ):
            quality_detail = "最近一段信号清晰，适合连续观察心跳变化"
        elif snapshot.signal_quality.sqi >= 0.65:
            quality_detail = "最近一段信号基本可用，手腕放松时会更稳定"
        elif snapshot.signal_quality.sqi > 0:
            quality_detail = "最近一段容易受到动作或佩戴位置影响，稍微调整腕带会更好"
        else:
            quality_detail = "正在等待足够清晰的腕带信号"
        self.quality_debug_label.setText(
            "信号观察：" + quality_detail
        )

        if (
            snapshot.time.valid
            and snapshot.signal_quality.sqi >= 0.85
        ):
            self.quality_reason.setText(
                "心跳节律读数清晰稳定"
            )
        elif snapshot.signal_quality.sqi >= 0.65:
            self.quality_reason.setText(
                "当前读数基本稳定，保持手腕放松会更容易连续观察"
            )
        elif snapshot.signal_quality.sqi > 0:
            self.quality_reason.setText(
                "当前信号还不够稳定，调整腕带贴合并保持手腕静止会更容易获得连续读数"
            )
        else:
            self.quality_reason.setText(
                "正在积累稳定的心跳节律信息"
            )

        # --------------------------------------------------------------
        # 实时 PPG + Peak / Beat 0/1 Debug
        # --------------------------------------------------------------
        (
            x,
            y,
            detector_score,
            candidate,
            firmware_accepted,
            accepted_beat,
            debug_stats,
        ) = self.engine.recent_signal_debug(
            12.0
        )

        self.signal_curve.setData(
            x,
            y,
        )
        self.accepted_beat_curve.setData(
            x,
            accepted_beat,
        )

        duration = debug_stats["duration_s"]
        candidate_count = debug_stats[
            "candidate_count"
        ]
        accepted_count = debug_stats[
            "accepted_beat_count"
        ]
        firmware_count = debug_stats[
            "firmware_beat_count"
        ]
        rescue_count = debug_stats[
            "rescue_count"
        ]
        fiducial_recovery_count = debug_stats.get(
            "fiducial_recovery_count",
            0,
        )
        candidate_bpm = debug_stats[
            "candidate_bpm_estimate"
        ]
        accepted_bpm = debug_stats[
            "accepted_bpm_estimate"
        ]
        difference = debug_stats[
            "candidate_minus_accepted"
        ]
        expected_rr = debug_stats[
            "expected_rr_ms"
        ]
        accepted_hr = debug_stats[
            "accepted_hr_bpm"
        ]
        score_mean = debug_stats[
            "accepted_score_mean"
        ]
        fiducial_quality = debug_stats[
            "fiducial_quality_mean"
        ]
        fiducial_uncertainty = debug_stats[
            "fiducial_uncertainty_p95_ms"
        ]
        fiducial_shift = debug_stats[
            "fiducial_shift_p95_ms"
        ]
        effective_hz = debug_stats[
            "effective_sample_rate_hz"
        ]
        timing_p95 = debug_stats[
            "timing_jitter_p95_ms"
        ]
        timing_overrun = debug_stats[
            "timing_overrun_ratio"
        ]

        display_lag_s = float(
            debug_stats.get(
                "display_lag_s",
                0.0,
            )
        )
        correction_rr = float(
            debug_stats.get(
                "correction_reference_rr_ms",
                0.0,
            )
        )
        correction_autocorr = float(
            debug_stats.get(
                "correction_autocorr_confidence",
                0.0,
            )
        )
        correction_inserted = int(
            debug_stats.get(
                "correction_inserted_count",
                0,
            )
        )
        correction_matched = int(
            debug_stats.get(
                "correction_firmware_matched_count",
                0,
            )
        )

        self._displayed_end_t_us = int(
            debug_stats.get(
                "end_t_us",
                0,
            )
        )

        annotation_count = int(
            debug_stats.get(
                "annotation_count",
                0,
            )
        )
        recent_annotation_count = int(
            debug_stats.get(
                "recent_annotation_count",
                0,
            )
        )
        last_annotation_age_s = float(
            debug_stats.get(
                "last_annotation_age_s",
                -1.0,
            )
        )

        self.mark_annotation_button.setEnabled(
            bool(
                self.receiver.running
                and self._displayed_end_t_us > 0
            )
        )

        # 当前 12 秒图只显示最近一条人工标注，减少多次阴影覆盖。
        recent_annotations = (
            self.engine.recent_annotations(
                seconds=12.0,
                end_t_us=(
                    self._displayed_end_t_us
                ),
            )
            if self._displayed_end_t_us > 0
            else []
        )

        if recent_annotations:
            latest_annotation = (
                recent_annotations[-1]
            )

            region_start = (
                latest_annotation.label_start_us
                - self._displayed_end_t_us
            ) / 1e6
            region_end = (
                latest_annotation.label_end_us
                - self._displayed_end_t_us
            ) / 1e6
            self.annotation_region.setRegion(
                (
                    float(
                        region_start
                    ),
                    float(
                        region_end
                    ),
                )
            )
            self.annotation_region.setVisible(
                True
            )
        else:
            self.annotation_region.setVisible(
                False
            )

        expected_text = (
            f"{expected_rr:.0f} ms"
            if expected_rr > 0
            else "建立中"
        )

        if last_annotation_age_s >= 0:
            self.annotation_hint.setText(
                "最近一次异常标记在 "
                f"{last_annotation_age_s:.1f} 秒前；"
                "红色区域是标记前的几秒。"
            )
        else:
            self.annotation_hint.setText(
                "如果你看到波形明显不对，可以在3秒内按F8留下标记。"
            )

        self.signal_debug_label.setText(
            f"近 {duration:.1f} 秒找到 {accepted_count} 次心跳，"
            f"约 {accepted_bpm:.0f} 次/分。"
            f"设备原始识别 {firmware_count} 次，软件根据波形补充 {correction_inserted} 次。"
            "这一区域只用于排查漏算或多算，日常使用无需关注。"
        )

        # --------------------------------------------------------------
        # HRV 趋势只绘制通过质量门的窗口。
        # 被判 INVALID 的 candidate RMSSD 不进入趋势图。
        # --------------------------------------------------------------
        history = self.engine.metric_history()
        valid_history = [
            item
            for item in history
            if (
                item.get("time_status")
                in {"VALID", "LIMITED"}
                and np.isfinite(
                    item.get(
                        "rmssd_ms",
                        np.nan,
                    )
                )
            )
        ]

        if valid_history:
            t0 = valid_history[0]["t_us"]
            tx = np.asarray(
                [
                    (item["t_us"] - t0)
                    / 60e6
                    for item in valid_history
                ],
                dtype=float,
            )
            ty = np.asarray(
                [
                    item["rmssd_ms"]
                    for item in valid_history
                ],
                dtype=float,
            )
            self.trend_curve.setData(tx, ty)
        else:
            self.trend_curve.setData([], [])

        # --------------------------------------------------------------
        # v0.4.0：研究原型匹配 + 一小时体验。
        # --------------------------------------------------------------
        hour_experience = (
            self.engine.hour_experience()
        )
        research_state = hour_experience.get(
            "current_research_state",
            {},
        )

        elapsed_minutes = float(
            hour_experience.get(
                "elapsed_minutes",
                0.0,
            )
        )
        valid_coverage = float(
            hour_experience.get(
                "valid_coverage",
                0.0,
            )
        )
        stage_code = str(
            hour_experience.get(
                "stage_code",
                "H0_ACQUIRING",
            )
        )
        stage_name = str(
            hour_experience.get(
                "stage_name",
                "建立基础观察",
            )
        )
        next_minutes = hour_experience.get(
            "next_milestone_minutes"
        )

        coverage_text = (
            f"其中约 {valid_coverage * 100:.0f}% 的时间可以连续观察"
        )
        if next_minutes is None:
            self.hour_stage_label.setText(
                f"{stage_name}。已经记录 {elapsed_minutes:.1f} 分钟，{coverage_text}。"
            )
        else:
            self.hour_stage_label.setText(
                f"正在{stage_name}。已经记录 {elapsed_minutes:.1f} 分钟，{coverage_text}；"
                f"再积累约 {float(next_minutes):.1f} 分钟，会得到更完整的观察。"
            )

        primary = (
            research_state.get("primary_conclusion")
            or research_state.get("primary_state")
        )
        quality_state = str(research_state.get("quality_state", ""))
        conclusion_status = str(research_state.get("conclusion_status", "BUILDING"))

        if conclusion_status == "HELD" and isinstance(primary, dict):
            self.hour_state_label.setText(
                "当前信号暂时不适合刷新判断。最近一次可靠结论仍是："
                f"{primary.get('name', '稳定节律')}。"
                f"{primary.get('user_narrative', '')}"
            )
        elif conclusion_status == "LIVE" and isinstance(primary, dict):
            self.hour_state_label.setText(
                f"当前更接近 {primary.get('name', '稳定节律')}："
                f"{primary.get('user_narrative', '')}"
            )
        elif quality_state == "Q1_DATA_UNSTABLE":
            self.hour_state_label.setText(
                "当前这一小段信号不够稳定，暂时不刷新节律判断；前面的可靠记录仍会保留。"
            )
        elif quality_state == "Q0_BUFFERING":
            self.hour_state_label.setText(
                "正在积累第一段连续记录，很快会先给出基础的节律描述。"
            )
        elif quality_state == "Q2_BASELINE_BUILDING":
            self.hour_state_label.setText(
                "已经能看见连续变化，正在形成第一版近期参照；正常连续采集约15分钟后会给出稳定节律结论。"
            )
        elif conclusion_status == "UNAVAILABLE":
            self.hour_state_label.setText(
                "已经记录了一段时间，但最近可靠数据覆盖不足，当前不强行更新结论。"
            )
        else:
            self.hour_state_label.setText(
                "正在把最近几分钟的变化和这次记录里的近期参照放在一起比较。"
            )

        hour_summary = str(
            hour_experience.get(
                "hour_summary",
                "这段记录里的变化还在逐渐形成。",
            )
        )
        self.hour_transition_label.setText(
            hour_summary
        )

        hour_sources_html = str(
            research_state.get(
                "primary_source_facts_html",
                "",
            )
        )
        self.hour_sources_label.setText(
            (
                "研究依据："
                + hour_sources_html
            )
            if hour_sources_html
            else "研究依据：当前结论以身体节律本身的描述为主；只有与具体研究条件足够接近时才附上文献。"
        )

        baseline_count = int(
            research_state.get(
                "baseline_reference_window_count",
                0,
            )
        )
        baseline_maturity = str(research_state.get("baseline_maturity", "NONE"))
        if baseline_maturity == "MATURE":
            self.research_machine_label.setText(
                f"解读进度：已经形成较稳定的近期参照，参考了 {baseline_count} 段较稳定记录。"
            )
        elif baseline_maturity == "PROVISIONAL":
            self.research_machine_label.setText(
                f"解读进度：已经形成第一版近期参照，参考了 {baseline_count} 段记录；后续会继续校准。"
            )
        else:
            self.research_machine_label.setText(
                f"解读进度：正在形成第一版近期参照，目前参考了 {baseline_count} 段记录。"
            )

        visible_matches = list(research_state.get("top_cases", []))[:3]
        if visible_matches:
            match_lines = ["研究中出现过的相似节律："]
            for index, item in enumerate(visible_matches):
                similarity_score = float(item.get("case_similarity", 0.0))
                confidence = float(item.get("match_confidence", 0.0))
                similarity = (
                    "相似特征很清楚"
                    if similarity_score >= 0.65
                    else (
                        "有较明显相似"
                        if similarity_score >= 0.45
                        else "带有一些相似特征"
                    )
                )
                confidence_text = (
                    "依据较充分"
                    if confidence >= 0.72
                    else "目前可作参考"
                )
                prefix = "主要" if index == 0 else "同时"
                match_lines.append(
                    f"{prefix}接近 {item.get('name', '相似节律')}：{similarity}，{confidence_text}。"
                )
            self.research_match_label.setText("<br/>".join(match_lines))
        else:
            self.research_match_label.setText(
                "研究中的相似记录：当前以身体节律本身的描述为主，暂时没有足够接近的具体研究案例。"
            )

        trait = hour_experience.get(
            "trait_reference_state",
            {},
        )
        trait_reason = str(
            trait.get(
                "reason",
                "目前记录时间还不足以观察长期变化。",
            )
        )
        self.research_trait_label.setText(
            "长期变化：" + trait_reason
        )

        research_sources_html = str(
            research_state.get(
                "source_facts_html",
                "",
            )
        )
        self.research_sources_label.setText(
            (
                "研究依据："
                + research_sources_html
            )
            if research_sources_html
            else "研究依据：当前以描述性节律结论为主，暂不把它强行套入某一篇研究。"
        )

        research_timeline = hour_experience.get(
            "timeline",
            [],
        )

        if research_timeline:
            tx_research = np.asarray(
                [
                    float(
                        item.get(
                            "elapsed_minutes",
                            0.0,
                        )
                    )
                    for item in research_timeline
                ],
                dtype=float,
            )

            for (
                code,
                curve,
            ) in self.prototype_score_curves.items():
                values = []
                for item in research_timeline:
                    raw_value = item.get(
                        f"score_{code}",
                        np.nan,
                    )
                    try:
                        values.append(float(raw_value))
                    except (TypeError, ValueError):
                        values.append(float("nan"))

                curve.setData(
                    tx_research,
                    np.asarray(values, dtype=float),
                    connect="finite",
                )
        else:
            for curve in self.prototype_score_curves.values():
                curve.setData(
                    [],
                    [],
                )

        # --------------------------------------------------------------
        # 频域：只有质量门通过才显示功率值和功率谱。
        # --------------------------------------------------------------
        freq = snapshot.frequency
        freq_insight = describe_frequency_balance(freq)
        self.freq_auto_label.setText(
            freq_insight["headline"]
            + "  "
            + freq_insight["plain_text"]
        )
        self.spwvd_hint.setText(freq_insight["spwvd_text"])
        self.psd_band_hint.setText(freq_insight["welch_text"])
        self.freq_guide_label.setText(
            " · ".join([
                freq_insight["vlf_text"],
                freq_insight["lf_text"],
                freq_insight["hf_text"],
                freq_insight["median_text"],
            ])
        )

        if freq.valid:
            agreement = min(
                float(freq.spectral_agreement),
                float(freq.band_power_agreement),
            )
            if agreement >= 0.85:
                agreement_text = "两种计算方式看到的快慢节律很接近，结果比较稳定。"
            elif agreement >= 0.65:
                agreement_text = "两种计算方式大体一致，细节仍有一些差异。"
            else:
                agreement_text = "两种计算方式看到的细节差异较大，这5分钟只适合粗略参考。"

            window_text = (
                "这5分钟可以清楚观察快慢节律。"
                if freq.status == "VALID"
                else "这5分钟可以粗略观察快慢节律。"
            )
            self.freq_status.setText(
                window_text + " " + agreement_text
            )
            self.psd_curve.setData(
                freq.freqs_hz,
                freq.psd_ms2_hz,
            )
        else:
            self.freq_status.setText(
                "这5分钟还不适合解读快慢节律。继续保持手腕放松和腕带贴合，数据足够连续后会自动更新。"
            )
            self.psd_curve.setData([], [])

        frequency_trend_rows = build_frequency_trend_rows(
            history
        )

        if frequency_trend_rows:
            tx = np.asarray(
                [
                    item["elapsed_minutes"]
                    for item in frequency_trend_rows
                ],
                dtype=float,
            )
            vlf_values = np.asarray(
                [item["vlf_ms2"] for item in frequency_trend_rows],
                dtype=float,
            )
            lf_values = np.asarray(
                [item["lf_ms2"] for item in frequency_trend_rows],
                dtype=float,
            )
            hf_values = np.asarray(
                [item["hf_ms2"] for item in frequency_trend_rows],
                dtype=float,
            )
            median_values = np.asarray(
                [item["median_frequency_mhz"] for item in frequency_trend_rows],
                dtype=float,
            )

            self.vlf_trend_curve.setData(
                tx,
                vlf_values,
                connect="finite",
            )
            self.lf_trend_curve.setData(
                tx,
                lf_values,
                connect="finite",
            )
            self.hf_trend_curve.setData(
                tx,
                hf_values,
                connect="finite",
            )
            self.median_freq_curve.setData(
                tx,
                median_values,
                connect="finite",
            )

            finite_power = np.concatenate([
                values[np.isfinite(values)]
                for values in (vlf_values, lf_values, hf_values)
                if np.any(np.isfinite(values))
            ])
            max_power = max(
                float(np.max(finite_power)) if finite_power.size else 0.0,
                1.0,
            )
            self.frequency_trend_plot.setYRange(0.0, max_power * 1.12)

            finite_median = median_values[np.isfinite(median_values)]
            max_mhz = max(
                float(np.max(finite_median)) if finite_median.size else 0.0,
                1.0,
            )
            self.frequency_trend_view.setYRange(0.0, max_mhz * 1.12)
            self._sync_frequency_trend_view()
        else:
            self.vlf_trend_curve.setData([], [])
            self.lf_trend_curve.setData([], [])
            self.hf_trend_curve.setData([], [])
            self.median_freq_curve.setData([], [])


        # 会话级 VLF/LF/HF 统计。
        statistics = (
            self.engine.frequency_statistics()
        )
        valid_count = statistics.get(
            "usable_window_count",
            statistics.get(
                "valid_window_count",
                0,
            ),
        )
        strict_count = statistics.get(
            "strict_valid_window_count",
            0,
        )
        limited_count = statistics.get(
            "limited_window_count",
            0,
        )
        total_count = statistics.get(
            "total_window_count",
            0,
        )

        if valid_count > 0:
            self.freq_stats_label.setText(
                f"这次记录里有 {valid_count}/{total_count} 段5分钟数据可以观察；"
                f"其中 {strict_count} 段较清晰，{limited_count} 段只适合粗略参考。"
            )
        else:
            self.freq_stats_label.setText(
                f"这次记录已有 {total_count} 段5分钟数据，暂时还没有一段足够清晰。"
            )

        # --------------------------------------------------------------
        # SPWVD：后台计算；质量门失败时 compute_spwvd() 会返回明确原因。
        # --------------------------------------------------------------
        self.spwvd_button.setEnabled(
            not self._spwvd_loading
        )
        self.spwvd_button.setText(
            "正在计算…"
            if self._spwvd_loading
            else "更新5分钟节律变化图"
        )

        if self._spwvd_result is not None:
            result = self._spwvd_result
            self._spwvd_result = None

            if result.valid and result.power.size:
                colored = self._colorize_spwvd(
                    result.power,
                    result.freqs_hz,
                )
                self.tf_image.setImage(
                    colored,
                    autoLevels=False,
                )

                if (
                    result.times_s.size > 1
                    and result.freqs_hz.size > 1
                ):
                    self.tf_image.setRect(
                        QRectF(
                            float(
                                result.times_s[0]
                            ),
                            float(
                                result.freqs_hz[0]
                            ),
                            float(
                                result.times_s[-1]
                                - result.times_s[0]
                            ),
                            float(
                                result.freqs_hz[-1]
                                - result.freqs_hz[0]
                            ),
                        )
                    )

                self._worker_status = "5分钟节律变化图已更新"
            else:
                self.tf_image.clear()
                self._worker_status = "当前数据还不足以生成5分钟节律变化图"

    def _close_recorder(self) -> None:
        # 先让 Engine 停止写，再关闭文件；否则关闭后的 recorder
        # 仍可能在后续 snapshot/force_update 时被重新打开。
        self.engine.attach_provenance_recorder(None)
        if self.recorder:
            self._last_session_dir = (
                self.recorder.session_dir
            )
            self.recorder.close()
            self.recorder = None

    def closeEvent(self, event) -> None:
        self.receiver.stop()
        self._close_recorder()
        event.accept()


def run_app() -> None:
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec()
