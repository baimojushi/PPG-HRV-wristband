from __future__ import annotations

import threading
from typing import Callable

import serial

from .models import ProtocolHealth
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
    ):
        self.on_message = on_message
        self.on_status = on_status or (lambda text: None)
        self.on_protocol_health = (
            on_protocol_health
            or (lambda health: None)
        )

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
                raw = self._serial.read(4096)

                if not raw:
                    continue

                messages = self._decoder.feed(raw)

                for message in messages:
                    self.on_message(message)

                health = self._decoder.health()
                self.on_protocol_health(health)

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
