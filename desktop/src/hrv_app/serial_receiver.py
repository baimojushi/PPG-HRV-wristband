from __future__ import annotations

import threading
import time
from typing import Callable

import serial

from .models import ProtocolHealth, SampleFrame
from .protocol import ProtocolStreamDecoder


class SerialReceiver:
    """
    后台读取 USB / 蓝牙 SPP 串口。

    V0.2.1 不再依赖“一次 readline 就对应一帧”的假设，
    所有粘帧、拆帧、CRC 和重同步都交给 ProtocolStreamDecoder。
    """

    def __init__(
        self,
        on_message: Callable[[object], None],
        on_status: Callable[[str], None] | None = None,
        on_protocol_health: Callable[[ProtocolHealth], None] | None = None,
        on_io_trace: Callable[[dict], None] | None = None,
    ):
        self.on_message = on_message
        self.on_status = on_status or (lambda text: None)
        self.on_protocol_health = (
            on_protocol_health
            or (lambda health: None)
        )
        self.on_io_trace = on_io_trace or (lambda row: None)

        self._decoder = ProtocolStreamDecoder()
        self._serial: serial.Serial | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._last_reported_error_total = 0

    @property
    def running(self) -> bool:
        return bool(
            self._thread
            and self._thread.is_alive()
        )

    def start(
        self,
        port: str,
        baudrate: int = 115200,
    ) -> None:
        self.stop()
        self._decoder.reset()
        self._last_reported_error_total = 0

        self._serial = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=0.20,
        )
        self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._run,
            name="SerialReceiver",
            daemon=True,
        )
        self._thread.start()
        self.on_status(f"已连接 {port}")

    def stop(self) -> None:
        self._stop_event.set()

        if (
            self._thread
            and self._thread.is_alive()
        ):
            self._thread.join(timeout=1.5)

        self._thread = None

        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass

        self._serial = None

    def _run(self) -> None:
        assert self._serial is not None

        while not self._stop_event.is_set():
            try:
                # read() 允许一次拿到多帧，也允许帧跨多次读取。
                # 记录 host monotonic 时钟与批量大小，下一次实测可以直接
                # 区分“设备 t_us 正常但 PC 端成批晚到”的 I/O 堵塞。
                read_start_ns = time.monotonic_ns()
                raw = self._serial.read(4096)
                read_end_ns = time.monotonic_ns()

                if not raw:
                    continue

                messages = self._decoder.feed(raw)

                for message in messages:
                    self.on_message(message)

                health = self._decoder.health()
                self.on_protocol_health(health)

                sample_messages = [
                    message
                    for message in messages
                    if isinstance(message, SampleFrame)
                ]
                self.on_io_trace({
                    "host_read_start_ns": int(read_start_ns),
                    "host_read_end_ns": int(read_end_ns),
                    "read_duration_ms": (read_end_ns - read_start_ns) / 1e6,
                    "bytes_read": int(len(raw)),
                    "decoded_message_count": int(len(messages)),
                    "sample_count": int(len(sample_messages)),
                    "first_sample_seq": int(sample_messages[0].seq) if sample_messages else -1,
                    "last_sample_seq": int(sample_messages[-1].seq) if sample_messages else -1,
                    "first_sample_t_us": int(sample_messages[0].t_us) if sample_messages else 0,
                    "last_sample_t_us": int(sample_messages[-1].t_us) if sample_messages else 0,
                    "serial_in_waiting": int(getattr(self._serial, "in_waiting", 0) or 0),
                    "protocol_ok_frames": int(health.ok_frames),
                    "crc_errors": int(health.crc_errors),
                    "format_errors": int(health.format_errors),
                    "resync_count": int(health.resync_count),
                    "sample_seq_gaps": int(health.sample_seq_gaps),
                })

                # 避免每个坏帧都刷 UI，只在累计错误跨越 10 的整数段时提示。
                error_total = (
                    health.crc_errors
                    + health.format_errors
                )
                if (
                    error_total >= self._last_reported_error_total + 10
                ):
                    self._last_reported_error_total = error_total
                    self.on_status(
                        "协议已自动重同步："
                        f"CRC {health.crc_errors}，"
                        f"格式 {health.format_errors}，"
                        f"序号缺口 {health.sample_seq_gaps}"
                    )

            except Exception as exc:
                if not self._stop_event.is_set():
                    self.on_status(
                        f"串口读取异常：{exc}"
                    )
                break

        self.on_status("串口已停止")
