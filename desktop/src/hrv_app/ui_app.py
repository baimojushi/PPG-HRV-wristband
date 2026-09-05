from __future__ import annotations

from pathlib import Path
import threading
import traceback

import numpy as np
import pyqtgraph as pg
from serial.tools import list_ports

from PySide6.QtCore import Qt, QTimer, QRectF
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
        self._worker_status = "未连接设备"
        self._csv_loading = False
        self._spwvd_loading = False
        self._spwvd_result: SPWVDResult | None = None

        self.setWindowTitle("此刻 · HRV 身体节律")
        self.resize(1180, 820)
        self.setStyleSheet(APP_STYLE)

        self._build_ui()
        self._refresh_ports()

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
        plot.getAxis("bottom").setTextPen("#746C66")
        plot.getAxis("left").setTextPen("#746C66")

    def _build_state_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)

        # ------------------------------------------------------------------
        # 实时 PPG + 心跳识别 Debug 叠加层
        # ------------------------------------------------------------------
        self.signal_plot = pg.PlotWidget()
        self._style_plot(self.signal_plot)
        self.signal_plot.setLabel("left", "滤波 PPG")
        self.signal_plot.setLabel("bottom", "最近时间", units="s")
        self.signal_curve = self.signal_plot.plot(
            pen=pg.mkPen("#7F718D", width=2)
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

        # 紫线：连续动态形态分数 0~1。
        # 它是可解释算法评分，不是“心搏概率”。
        self.detector_score_curve = pg.PlotCurveItem(
            pen=pg.mkPen("#B06C9B", width=2)
        )

        # 黄线：局部极值 Candidate 脉冲。
        self.candidate_curve = pg.PlotCurveItem(
            pen=pg.mkPen("#C79A3B", width=2)
        )

        # 绿线：周期内竞争 / Rescue 后的最终 Accepted Beat。
        self.accepted_beat_curve = pg.PlotCurveItem(
            pen=pg.mkPen("#4F8A6B", width=3)
        )

        self.signal_debug_view.addItem(
            self.detector_score_curve
        )
        self.signal_debug_view.addItem(
            self.candidate_curve
        )
        self.signal_debug_view.addItem(
            self.accepted_beat_curve
        )

        self.signal_plot.getViewBox().sigResized.connect(
            self._sync_signal_debug_view
        )
        self._sync_signal_debug_view()

        self.signal_debug_label = QLabel(
            "调试：紫=动态形态分数0~1 · 黄=Candidate（含峰/谷） · 绿=同极性 Accepted Beat"
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

        layout.addWidget(QLabel("实时 PPG + zeezPPG 动态检测"))
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

    def _build_analysis_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)

        summary = QHBoxLayout()
        self.freq_status = QLabel("频域：等待 5 分钟 NN 窗口")
        self.freq_status.setWordWrap(True)

        self.freq_stats_label = QLabel("频带统计：尚无通过质量门的窗口")
        self.freq_stats_label.setWordWrap(True)
        self.freq_stats_label.setObjectName("heroSub")

        self.spwvd_button = QPushButton("更新 SPWVD 时频图")
        self.spwvd_button.clicked.connect(self._start_spwvd)

        summary.addWidget(self.freq_status, 1)
        summary.addWidget(self.spwvd_button)
        layout.addLayout(summary)
        layout.addWidget(self.freq_stats_label)

        self.psd_plot = pg.PlotWidget()
        self._style_plot(self.psd_plot)
        self.psd_plot.setLabel("left", "功率谱密度", units="ms²/Hz")
        self.psd_plot.setLabel("bottom", "频率", units="Hz")
        self.psd_curve = self.psd_plot.plot(
            pen=pg.mkPen("#70869B", width=2)
        )
        self.psd_plot.setXRange(0.0, 0.42)

        self.tf_plot = pg.PlotWidget()
        self._style_plot(self.tf_plot)
        self.tf_plot.setLabel("left", "频率", units="Hz")
        self.tf_plot.setLabel("bottom", "窗口时间", units="s")
        self.tf_image = pg.ImageItem()
        self.tf_plot.addItem(self.tf_image)
        self.tf_plot.setYRange(0.0, 0.42)

        layout.addWidget(QLabel("Welch 功率谱"))
        layout.addWidget(self.psd_plot, 1)
        layout.addWidget(QLabel("平滑伪 Wigner-Ville 分布（SPWVD，仅观察时频结构）"))
        layout.addWidget(self.tf_plot, 1)
        return page

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
            self._close_recorder()
            self.connect_button.setText("连接设备")
            return

        port = self.port_combo.currentText().strip()
        if not port:
            QMessageBox.information(self, "没有串口", "请先连接设备并刷新串口列表。")
            return

        try:
            self.engine.reset()

            desktop_root = Path(__file__).resolve().parents[2]
            self.recorder = SessionRecorder(desktop_root / "sessions")

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
            self._close_recorder()
            self.connect_button.setText("连接设备")

        if self._csv_loading:
            return

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

    def _export_results(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择导出目录",
        )
        if not folder:
            return

        try:
            out = Path(folder) / "hrv_export"
            export_engine_results(self.engine, out)
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
            if (
                snapshot.time.rmssd_ci_low_ms > 0
                and snapshot.time.rmssd_ci_high_ms > 0
            ):
                reasons.insert(
                    0,
                    "RMSSD 近似95%区间 "
                    f"{snapshot.time.rmssd_ci_low_ms:.1f}–"
                    f"{snapshot.time.rmssd_ci_high_ms:.1f} ms"
                )
        elif snapshot.time.validity_reason:
            reasons.insert(
                0,
                "时域已暂停："
                + snapshot.time.validity_reason
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
            accepted_beat,
            debug_stats,
        ) = self.engine.recent_signal_debug(
            12.0
        )

        self.signal_curve.setData(
            x,
            y,
        )
        self.detector_score_curve.setData(
            x,
            detector_score,
        )
        self.candidate_curve.setData(
            x,
            candidate,
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
        rescue_count = debug_stats[
            "rescue_count"
        ]
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

        expected_text = (
            f"{expected_rr:.0f} ms"
            if expected_rr > 0
            else "建立中"
        )

        self.signal_debug_label.setText(
            "调试：紫=形态分数 · 黄=Candidate（含峰/谷） · 绿=同极性Accepted  |  "
            f"窗口 {duration:.1f}s · "
            f"Candidate {candidate_count}（≈{candidate_bpm:.0f} bpm） · "
            f"Accepted {accepted_count}（≈{accepted_bpm:.0f} bpm） · "
            f"Rescue {rescue_count} · "
            f"未选 {difference} · "
            f"预测RR {expected_text} · "
            f"接受HR {accepted_hr:.0f} bpm · "
            f"平均Winner分 {score_mean:.2f}"
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
                item.get("time_status") == "VALID"
                and np.isfinite(
                    item.get("rmssd_ms", np.nan)
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

        if freq.valid:
            self.freq_status.setText(
                "频域有效  |  "
                f"Total {freq.total_power_ms2:.1f} ms²  ·  "
                f"VLF {freq.vlf_ms2:.1f} ms²  ·  "
                f"LF {freq.lf_ms2:.1f} ms²  ·  "
                f"HF {freq.hf_ms2:.1f} ms²  ·  "
                f"LFnu {freq.lf_nu:.1f}%  ·  "
                f"HFnu {freq.hf_nu:.1f}%  ·  "
                f"LF/HF {freq.lf_hf:.2f}"
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

        # 会话级 VLF/LF/HF 统计。
        statistics = (
            self.engine.frequency_statistics()
        )
        valid_count = statistics.get(
            "valid_window_count",
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

            self.freq_stats_label.setText(
                f"有效频域窗口 {valid_count}/{total_count}  |  "
                f"VLF均值 {stat_mean('vlf_ms2'):.1f} ms²  ·  "
                f"LF均值 {stat_mean('lf_ms2'):.1f} ms²  ·  "
                f"HF均值 {stat_mean('hf_ms2'):.1f} ms²  ·  "
                f"LF/HF中位数 "
                f"{metrics['lf_hf']['median']:.2f}"
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
                display = np.log1p(
                    result.power.T
                )

                # 使用稳健百分位避免少数极端能量把整幅图压成黑白条纹。
                finite = display[
                    np.isfinite(display)
                ]
                if finite.size:
                    low, high = np.percentile(
                        finite,
                        [2.0, 98.0],
                    )
                    if high <= low:
                        high = low + 1.0
                    self.tf_image.setImage(
                        display,
                        autoLevels=False,
                        levels=(low, high),
                    )
                else:
                    self.tf_image.setImage(
                        display,
                        autoLevels=True,
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
