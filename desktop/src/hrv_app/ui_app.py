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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .engine import AnalysisEngine
from .frequency_insights import AUTONOMIC_ZONES, describe_frequency_balance, frequency_zone_brushes
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

        self.setWindowTitle("此刻 · HRV 身体节律")
        self.resize(1180, 820)
        self.setStyleSheet(APP_STYLE)

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
        root.setSpacing(16)
        self.setCentralWidget(container)

        # ------------------------------------------------------------------
        # 顶部连接工具栏
        # ------------------------------------------------------------------
        toolbar = QHBoxLayout()
        self.port_combo = QComboBox()

        self.refresh_port_button = QPushButton("刷新串口")
        self.refresh_port_button.clicked.connect(self._refresh_ports)

        self.connect_button = QPushButton("连接设备")
        self.connect_button.setObjectName("primary")
        self.connect_button.clicked.connect(self._toggle_connection)

        self.open_csv_button = QPushButton("打开历史 CSV")
        self.open_csv_button.clicked.connect(self._open_csv)

        self.export_button = QPushButton("导出分析结果")
        self.export_button.clicked.connect(self._export_results)

        toolbar.addWidget(self.port_combo, 1)
        toolbar.addWidget(self.refresh_port_button)
        toolbar.addWidget(self.connect_button)
        toolbar.addWidget(self.open_csv_button)
        toolbar.addWidget(self.export_button)
        root.addLayout(toolbar)

        # ------------------------------------------------------------------
        # v0.3.6 软件人工标注。
        # ------------------------------------------------------------------
        # 点击/F8 只冻结“当前屏幕数据的设备时间”，不修改任何检测状态。
        annotation_bar = QHBoxLayout()

        annotation_bar.addWidget(
            QLabel("人工标注")
        )

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
            "可先保持“未分类”；时间戳会在按键瞬间立即保存。"
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

        annotation_bar.addWidget(
            self.annotation_type_combo
        )
        annotation_bar.addWidget(
            self.mark_annotation_button
        )
        annotation_bar.addWidget(
            self.annotation_hint,
            1,
        )
        root.addLayout(
            annotation_bar
        )

        # ------------------------------------------------------------------
        # C 端首页主视觉
        # ------------------------------------------------------------------
        hero = QFrame()
        hero.setObjectName("hero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(24, 20, 24, 20)
        hero_layout.setSpacing(12)

        self.hero_title = QLabel("此刻 · 身体节律")
        self.hero_title.setObjectName("heroTitle")

        self.status_label = QLabel("等待设备或历史记录")
        self.status_label.setObjectName("heroSub")
        self.status_label.setWordWrap(True)

        hero_layout.addWidget(self.hero_title)
        hero_layout.addWidget(self.status_label)

        card_row = QGridLayout()
        card_row.setHorizontalSpacing(12)

        self.hr_card = MetricCard("心率", "bpm")
        self.rmssd_card = MetricCard("HRV · RMSSD", "ms")
        self.conf_card = MetricCard("数据质量 · SQI", "%")

        card_row.addWidget(self.hr_card, 0, 0)
        card_row.addWidget(self.rmssd_card, 0, 1)
        card_row.addWidget(self.conf_card, 0, 2)

        hero_layout.addLayout(card_row)

        self.conf_progress = QProgressBar()
        self.conf_progress.setRange(0, 100)
        self.conf_progress.setTextVisible(False)

        self.quality_reason = QLabel("正在积累信号质量信息")
        self.quality_reason.setObjectName("heroSub")
        self.quality_reason.setWordWrap(True)

        hero_layout.addWidget(self.conf_progress)
        hero_layout.addWidget(self.quality_reason)
        root.addWidget(hero)

        # ------------------------------------------------------------------
        # 两层信息架构：状态页 + 专业分析页
        # ------------------------------------------------------------------
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_state_tab(), "状态与趋势")
        self.tabs.addTab(self._build_analysis_tab(), "专业分析")
        root.addWidget(self.tabs, 1)

        disclaimer = QLabel(
            "数据用于自我觉察、艺术疗愈交互与研究记录，不用于医疗诊断。"
        )
        disclaimer.setObjectName("heroSub")
        root.addWidget(disclaimer)

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

        self.signal_plot.setLabel("left", "滤波 PPG")
        self.signal_plot.setLabel("bottom", "最近时间", units="s")
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
        self.signal_plot.getAxis("right").setLabel("心跳识别", units="0/1")

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
            "显示：紫=滤波PPG · 绿=8秒整窗纠错心搏 · 红色阴影=人工标注窗口"
        )
        self.signal_debug_label.setObjectName("heroSub")
        self.signal_debug_label.setWordWrap(True)

        self.trend_plot = pg.PlotWidget()
        self._style_plot(self.trend_plot)
        self.trend_plot.setLabel("left", "RMSSD", units="ms")
        self.trend_plot.setLabel("bottom", "分析窗口", units="min")
        self.trend_curve = self.trend_plot.plot(
            pen=pg.mkPen("#7C967D", width=2),
            symbol="o",
            symbolSize=5,
        )

        layout.addWidget(QLabel("实时 PPG + 8秒整窗波形复核"))
        layout.addWidget(self.signal_plot, 1)
        layout.addWidget(self.signal_debug_label)
        layout.addWidget(QLabel("HRV 趋势"))
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
        self.freq_status = QLabel("频域：等待 5 分钟 NN 窗口")
        self.freq_status.setWordWrap(True)

        self.freq_stats_label = QLabel("频带统计：尚无通过质量门的窗口")
        self.freq_stats_label.setWordWrap(True)
        self.freq_stats_label.setObjectName("heroSub")

        self.freq_auto_label = QLabel("自动解析：等待频域窗口。")
        self.freq_auto_label.setWordWrap(True)
        self.freq_auto_label.setObjectName("heroSub")

        self.freq_guide_label = QLabel(
            "说明：VLF=极慢变化背景；LF=低频调节；HF=呼吸相关快波动；中位频率=频谱能量重心。"
        )
        self.freq_guide_label.setWordWrap(True)
        self.freq_guide_label.setObjectName("heroSub")

        self.spwvd_button = QPushButton("更新 SPWVD 时频图")
        self.spwvd_button.clicked.connect(self._start_spwvd)

        summary.addWidget(self.freq_status, 1)
        summary.addWidget(self.spwvd_button)
        layout.addLayout(summary)
        layout.addWidget(self.freq_stats_label)
        layout.addWidget(self.freq_auto_label)
        layout.addWidget(self.freq_guide_label)

        self.frequency_trend_plot = pg.PlotWidget()
        self._style_plot(self.frequency_trend_plot)
        self.frequency_trend_plot.setMinimumHeight(240)
        self.frequency_trend_plot.setLabel("left", "频带功率", units="ms²")
        self.frequency_trend_plot.setLabel("bottom", "窗口时间", units="min")
        self.frequency_trend_plot.showAxis("right")
        self.frequency_trend_plot.getAxis("right").setLabel("中位频率", units="mHz")
        self.frequency_trend_plot.addLegend(offset=(12, 10))

        self.vlf_trend_curve = self.frequency_trend_plot.plot(
            pen=pg.mkPen("#9B7B62", width=2.2),
            name="VLF",
        )
        self.lf_trend_curve = self.frequency_trend_plot.plot(
            pen=pg.mkPen("#D67A56", width=2.2),
            name="LF",
        )
        self.hf_trend_curve = self.frequency_trend_plot.plot(
            pen=pg.mkPen("#609B7C", width=2.2),
            name="HF",
        )

        self.frequency_trend_view = pg.ViewBox()
        self.frequency_trend_plot.scene().addItem(self.frequency_trend_view)
        self.frequency_trend_plot.getAxis("right").linkToView(self.frequency_trend_view)
        self.frequency_trend_view.setXLink(self.frequency_trend_plot)
        self.median_freq_curve = pg.PlotCurveItem(
            pen=pg.mkPen("#7F718D", width=2.4, style=Qt.DashLine),
            name="中位频率",
        )
        self.frequency_trend_view.addItem(self.median_freq_curve)
        self.frequency_trend_plot.getViewBox().sigResized.connect(
            self._sync_frequency_trend_view
        )
        self._sync_frequency_trend_view()

        self.freq_trend_hint = QLabel(
            "趋势线：棕=VLF，橙=LF，绿=HF，紫虚线=中位频率。"
        )
        self.freq_trend_hint.setObjectName("heroSub")

        self.psd_plot = pg.PlotWidget()
        self._style_plot(self.psd_plot)
        self.psd_plot.setMinimumHeight(260)
        self.psd_plot.setLabel("left", "功率谱密度", units="ms²/Hz")
        self.psd_plot.setLabel("bottom", "频率", units="Hz")
        self.psd_curve = self.psd_plot.plot(
            pen=pg.mkPen("#70869B", width=2.4)
        )
        self.psd_plot.setXRange(0.0, 0.42)
        self._add_frequency_zone_regions(self.psd_plot, horizontal=False)

        self.psd_band_hint = QLabel(
            "Welch 色带：灰=VLF慢变背景，橙=交感偏主，金=交感-副交感共调，绿=副交感偏主。"
        )
        self.psd_band_hint.setObjectName("heroSub")

        self.tf_plot = pg.PlotWidget()
        self._style_plot(self.tf_plot)
        self.tf_plot.setMinimumHeight(280)
        self.tf_plot.setLabel("left", "频率", units="Hz")
        self.tf_plot.setLabel("bottom", "窗口时间", units="s")
        self.tf_image = pg.ImageItem()
        self.tf_plot.addItem(self.tf_image)
        self.tf_plot.setYRange(0.0, 0.42)
        self._add_frequency_zone_regions(self.tf_plot, horizontal=True)

        self.spwvd_hint = QLabel(
            "SPWVD 色带：橙=交感偏主带，金=两神经共调带，绿=副交感偏主带；亮度表示该频率在该时段更活跃。"
        )
        self.spwvd_hint.setObjectName("heroSub")
        self.spwvd_hint.setWordWrap(True)

        layout.addWidget(QLabel("VLF / LF / HF / 中位频率趋势"))
        layout.addWidget(self.frequency_trend_plot)
        layout.addWidget(self.freq_trend_hint)
        layout.addWidget(QLabel("Welch 功率谱"))
        layout.addWidget(self.psd_plot)
        layout.addWidget(self.psd_band_hint)
        layout.addWidget(QLabel("平滑伪 Wigner-Ville 分布（SPWVD，仅观察时频结构）"))
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

    def _set_worker_status(self, text: str) -> None:
        # 后台线程只更新普通 Python 字符串；
        # Qt 主线程在 500 ms 定时刷新时读取。
        self._worker_status = text

    def _open_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开历史 PPG CSV",
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
                "人工标注未记录：需要连接实时设备并先收到 PPG。"
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
        # 顶部状态：协议错误不再只显示“某一行解析失败”，改为累计可审计计数。
        # --------------------------------------------------------------
        protocol_text = (
            f"协议 {protocol.mode} · "
            f"CRC {protocol.crc_errors} · "
            f"格式 {protocol.format_errors} · "
            f"序号缺口 {protocol.sample_seq_gaps}"
        )
        self.status_label.setText(
            f"{self._worker_status}  |  {protocol_text}"
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

        reasons = list(
            snapshot.quality.reasons
        )

        if snapshot.time.valid:
            prefix = (
                "RMSSD 有效"
                if snapshot.time.status == "VALID"
                else "RMSSD 受限可用"
            )

            if (
                snapshot.time.rmssd_ci_low_ms > 0
                and snapshot.time.rmssd_ci_high_ms > 0
            ):
                reasons.insert(
                    0,
                    f"{prefix} · 近似95%区间 "
                    f"{snapshot.time.rmssd_ci_low_ms:.1f}–"
                    f"{snapshot.time.rmssd_ci_high_ms:.1f} ms"
                )
            else:
                reasons.insert(
                    0,
                    prefix
                )
        elif snapshot.time.validity_reason:
            reasons.insert(
                0,
                "时域已暂停："
                + snapshot.time.validity_reason
            )

        if (
            snapshot.timeline_quality.raw_rr_count > 0
            and snapshot.timeline_quality.fiducial_quality_mean < 0.999
        ):
            reasons.insert(
                1 if reasons else 0,
                "心搏标志点质量 "
                f"{snapshot.timeline_quality.fiducial_quality_mean * 100:.0f}% · "
                "不确定度p95 "
                f"{snapshot.timeline_quality.fiducial_uncertainty_p95_ms:.0f} ms"
            )

        self.quality_reason.setText(
            " · ".join(reasons[:4])
            if reasons
            else "正在积累数据质量信息"
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
                "最近人工标注 "
                f"{last_annotation_age_s:.1f}s 前 · "
                "红色区域=标注前3秒"
            )
        else:
            self.annotation_hint.setText(
                "屏幕显示约7.25秒成熟波形；看到问题后3秒内按F8。"
            )

        self.signal_debug_label.setText(
            "显示：紫=PPG · 绿=8秒整窗纠错心搏 · 红色阴影=人工标注窗口  |  "
            f"屏幕滞后 {display_lag_s:.2f}s · "
            f"窗口 {duration:.1f}s · "
            f"正式Beat {accepted_count}（≈{accepted_bpm:.0f} bpm） · "
            f"固件Beat {firmware_count} · "
            f"波形补搏 {correction_inserted} · "
            f"匹配固件 {correction_matched} · "
            f"波形RR {correction_rr:.0f} ms · "
            f"自相关 {correction_autocorr:.2f} · "
            f"Firmware Candidate {candidate_count} · "
            f"固件Rescue {rescue_count} · "
            f"人工标注 {annotation_count} · "
            f"近窗 {recent_annotation_count} · "
            f"HR {accepted_hr:.0f} bpm · "
            f"波顶质量 {fiducial_quality * 100:.0f}% · "
            f"不确定度p95 {fiducial_uncertainty:.0f} ms · "
            f"固件↔波顶偏移p95 {fiducial_shift:.0f} ms · "
            f"采样 {effective_hz:.1f} Hz · "
            f"p95抖动 {timing_p95:.1f} ms · "
            f"超时 {timing_overrun * 100:.1f}%"
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
            frequency_label = (
                "频域有效"
                if freq.status == "VALID"
                else "频域受限可用"
            )

            self.freq_status.setText(
                f"{frequency_label}  |  "
                f"Total {freq.total_power_ms2:.1f} ms²  ·  "
                f"VLF {freq.vlf_ms2:.1f} ms²  ·  "
                f"LF {freq.lf_ms2:.1f} ms²  ·  "
                f"HF {freq.hf_ms2:.1f} ms²  ·  "
                f"中位频率 {freq.median_frequency_hz * 1000.0:.1f} mHz  ·  "
                f"LFnu {freq.lf_nu:.1f}%  ·  "
                f"HFnu {freq.hf_nu:.1f}%  ·  "
                f"LF/HF {freq.lf_hf:.2f}  ·  "
                f"稳健Welch/Lomb {freq.spectral_agreement * 100:.0f}%  ·  "
                f"原始逐点 {freq.spectral_agreement_raw * 100:.0f}%  ·  "
                f"频带一致 {freq.band_power_agreement * 100:.0f}%  ·  "
                f"插值一致 {freq.interpolation_agreement * 100:.0f}%"
            )
            self.psd_curve.setData(
                freq.freqs_hz,
                freq.psd_ms2_hz,
            )
        else:
            reason = (
                freq.validity_reason
                or "频域质量门未通过"
            )
            self.freq_status.setText(
                "频域暂不输出  |  "
                + reason
            )
            self.psd_curve.setData([], [])

        valid_frequency_history = [
            item
            for item in history
            if (
                item.get("frequency_status")
                in {"VALID", "LIMITED"}
                and np.isfinite(item.get("vlf_ms2", np.nan))
                and np.isfinite(item.get("lf_ms2", np.nan))
                and np.isfinite(item.get("hf_ms2", np.nan))
                and np.isfinite(item.get("median_frequency_hz", np.nan))
            )
        ]

        if valid_frequency_history:
            t0 = valid_frequency_history[0]["t_us"]
            tx = np.asarray(
                [
                    (item["t_us"] - t0) / 60e6
                    for item in valid_frequency_history
                ],
                dtype=float,
            )
            self.vlf_trend_curve.setData(
                tx,
                np.asarray([item["vlf_ms2"] for item in valid_frequency_history], dtype=float),
            )
            self.lf_trend_curve.setData(
                tx,
                np.asarray([item["lf_ms2"] for item in valid_frequency_history], dtype=float),
            )
            self.hf_trend_curve.setData(
                tx,
                np.asarray([item["hf_ms2"] for item in valid_frequency_history], dtype=float),
            )
            self.median_freq_curve.setData(
                tx,
                np.asarray(
                    [item["median_frequency_hz"] * 1000.0 for item in valid_frequency_history],
                    dtype=float,
                ),
            )
            max_power = max(
                float(np.nanmax([item["vlf_ms2"] for item in valid_frequency_history])),
                float(np.nanmax([item["lf_ms2"] for item in valid_frequency_history])),
                float(np.nanmax([item["hf_ms2"] for item in valid_frequency_history])),
                1.0,
            )
            self.frequency_trend_plot.setYRange(0.0, max_power * 1.12)
            max_mhz = max(
                float(np.nanmax([item["median_frequency_hz"] * 1000.0 for item in valid_frequency_history])),
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
            metrics = statistics["metrics"]

            def stat_mean(name: str) -> float:
                value = metrics[name]["mean"]
                return (
                    float(value)
                    if value is not None
                    else 0.0
                )

            median_freq = metrics['median_frequency_hz']['median']
            median_freq_text = (
                f"{median_freq * 1000.0:.1f} mHz"
                if median_freq is not None
                else "--"
            )

            self.freq_stats_label.setText(
                f"可计算频域窗口 {valid_count}/{total_count} "
                f"（VALID {strict_count} · LIMITED {limited_count}）  |  "
                f"VLF均值 {stat_mean('vlf_ms2'):.1f} ms²  ·  "
                f"LF均值 {stat_mean('lf_ms2'):.1f} ms²  ·  "
                f"HF均值 {stat_mean('hf_ms2'):.1f} ms²  ·  "
                f"中位频率中位数 {median_freq_text}  ·  "
                f"LF/HF中位数 {metrics['lf_hf']['median']:.2f}"
            )
        else:
            self.freq_stats_label.setText(
                f"频带统计：0/{total_count} 个窗口通过质量门"
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
            else "更新 SPWVD 时频图"
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

                self._worker_status = (
                    result.message
                    or "SPWVD 已更新"
                )
            else:
                self.tf_image.clear()
                self._worker_status = (
                    result.message
                    or "SPWVD 数据不足"
                )

    def _close_recorder(self) -> None:
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
