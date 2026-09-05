from __future__ import annotations

import re
from typing import Union

from .models import (
    BeatFrame,
    DiagnosticFrame,
    FirmwareMetricFrame,
    ProtocolHealth,
    SampleFrame,
)

ProtocolMessage = Union[
    SampleFrame,
    BeatFrame,
    FirmwareMetricFrame,
    DiagnosticFrame,
]


class ProtocolError(ValueError):
    """协议字段、CRC 或帧结构错误。"""


def crc16_ccitt(
    data: bytes,
    initial: int = 0xFFFF,
) -> int:
    """CRC-16/CCITT-FALSE：poly=0x1021, init=0xFFFF。"""
    crc = initial

    for byte in data:
        crc ^= byte << 8

        for _ in range(8):
            if crc & 0x8000:
                crc = (
                    (crc << 1) ^ 0x1021
                ) & 0xFFFF
            else:
                crc = (
                    crc << 1
                ) & 0xFFFF

    return crc


def build_framed_body(
    body: str,
) -> bytes:
    body_bytes = body.encode(
        "ascii"
    )
    crc = crc16_ccitt(
        body_bytes
    )

    return (
        b"@"
        + body_bytes
        + f"*{crc:04X}\r\n".encode(
            "ascii"
        )
    )


# 兼容既有测试/外部脚本名称。
def build_v3_frame(
    body: str,
) -> bytes:
    return build_framed_body(
        body
    )


class ProtocolParser:
    """
    解析单帧。

    v2/v3:
      S = 9 fields
      B = 6 fields

    v4:
      S = 11 fields
      B = 7 fields

    M / D 字段保持不变。
    """

    def parse(
        self,
        line: str,
    ) -> ProtocolMessage | None:
        line = line.strip()

        if (
            not line
            or line.startswith("#")
        ):
            return None

        if line.startswith("@"):
            star = line.rfind("*")

            if (
                star <= 1
                or len(line) - star != 5
            ):
                raise ProtocolError(
                    "带 CRC 帧缺少 4 位 CRC"
                )

            body = line[1:star]
            crc_text = (
                line[star + 1:]
            )

            try:
                received_crc = int(
                    crc_text,
                    16,
                )
            except ValueError as exc:
                raise ProtocolError(
                    "CRC 不是十六进制"
                ) from exc

            expected_crc = crc16_ccitt(
                body.encode("ascii")
            )

            if (
                received_crc
                != expected_crc
            ):
                raise ProtocolError(
                    "CRC 不匹配："
                    f"{received_crc:04X}"
                    f"!={expected_crc:04X}"
                )

            line = body

        parts = line.split(",")
        kind = parts[0]

        try:
            if kind == "S":
                if len(parts) == 9:
                    # v2/v3
                    return SampleFrame(
                        seq=int(parts[1]),
                        t_us=int(parts[2]),
                        raw=float(parts[3]),
                        avg=float(parts[4]),
                        filtered=float(
                            parts[5]
                        ),
                        peak=int(parts[6]),
                        hr_bpm=float(
                            parts[7]
                        ),
                        detector_score=0.0,
                        expected_rr_ms=0.0,
                        flags=int(parts[8]),
                    )

                if len(parts) == 11:
                    # v4
                    return SampleFrame(
                        seq=int(parts[1]),
                        t_us=int(parts[2]),
                        raw=float(parts[3]),
                        avg=float(parts[4]),
                        filtered=float(
                            parts[5]
                        ),
                        peak=int(parts[6]),
                        detector_score=float(
                            parts[7]
                        ),
                        expected_rr_ms=float(
                            parts[8]
                        ),
                        hr_bpm=float(
                            parts[9]
                        ),
                        flags=int(parts[10]),
                    )

                raise ProtocolError(
                    "S 帧字段数错误："
                    f"{len(parts)}，期望 9 或 11"
                )

            if kind == "B":
                if len(parts) == 6:
                    return BeatFrame(
                        seq=int(parts[1]),
                        t_us=int(parts[2]),
                        rr_ms=float(
                            parts[3]
                        ),
                        hr_bpm=float(
                            parts[4]
                        ),
                        score=0.0,
                        flags=int(parts[5]),
                    )

                if len(parts) == 7:
                    return BeatFrame(
                        seq=int(parts[1]),
                        t_us=int(parts[2]),
                        rr_ms=float(
                            parts[3]
                        ),
                        hr_bpm=float(
                            parts[4]
                        ),
                        score=float(
                            parts[5]
                        ),
                        flags=int(parts[6]),
                    )

                raise ProtocolError(
                    "B 帧字段数错误："
                    f"{len(parts)}，期望 6 或 7"
                )

            if kind == "M":
                if len(parts) != 6:
                    raise ProtocolError(
                        "M 帧字段数错误："
                        f"{len(parts)}，期望 6"
                    )

                return FirmwareMetricFrame(
                    t_us=int(parts[1]),
                    rmssd_ms=float(
                        parts[2]
                    ),
                    valid_rr_count=int(
                        parts[3]
                    ),
                    artifact_ratio=float(
                        parts[4]
                    ),
                    valid=bool(
                        int(parts[5])
                    ),
                )

            if kind == "D":
                if len(parts) != 7:
                    raise ProtocolError(
                        "D 帧字段数错误："
                        f"{len(parts)}，期望 7"
                    )

                return DiagnosticFrame(
                    t_us=int(parts[1]),
                    sample_drop_count=int(
                        parts[2]
                    ),
                    beat_drop_count=int(
                        parts[3]
                    ),
                    metric_drop_count=int(
                        parts[4]
                    ),
                    sample_queue_depth=int(
                        parts[5]
                    ),
                    sample_queue_high_water=int(
                        parts[6]
                    ),
                )

        except ProtocolError:
            raise
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ProtocolError(
                "协议数值解析失败："
                + line
            ) from exc

        raise ProtocolError(
            f"未知协议类型：{kind}"
        )


class ProtocolStreamDecoder:
    """
    字节流解码器。

    `@ + CRC16` 在 v3/v4 保持一致。
    v4 只是字段扩展，所以重同步逻辑无需改变。
    """

    LEGACY_START = re.compile(
        r"(?=(?:S|B|M|D),)"
    )

    def __init__(self):
        self._parser = (
            ProtocolParser()
        )
        self._buffer = bytearray()
        self._health = (
            ProtocolHealth()
        )
        self._last_sample_seq: (
            int | None
        ) = None

        self._framed_seen = False

    def reset(self) -> None:
        self._buffer.clear()
        self._health = (
            ProtocolHealth()
        )
        self._last_sample_seq = None
        self._framed_seen = False

    def health(self) -> ProtocolHealth:
        return ProtocolHealth(
            mode=self._health.mode,
            ok_frames=(
                self._health.ok_frames
            ),
            crc_errors=(
                self._health.crc_errors
            ),
            format_errors=(
                self._health.format_errors
            ),
            resync_count=(
                self._health.resync_count
            ),
            sample_seq_gaps=(
                self._health.sample_seq_gaps
            ),
            legacy_frames=(
                self._health.legacy_frames
            ),
        )

    def feed(
        self,
        data: bytes,
    ) -> list[ProtocolMessage]:
        if data:
            self._buffer.extend(
                data
            )

        messages: list[
            ProtocolMessage
        ] = []

        while self._buffer:
            if self._buffer.startswith(
                b"#"
            ):
                newline = (
                    self._buffer.find(
                        b"\n"
                    )
                )

                if newline < 0:
                    break

                raw = bytes(
                    self._buffer[
                        :newline + 1
                    ]
                )
                del self._buffer[
                    :newline + 1
                ]

                text = raw.decode(
                    "ascii",
                    errors="replace",
                ).strip()

                if text.startswith(
                    "#PPGHRV,4"
                ):
                    self._framed_seen = True
                    self._health.mode = "v4"

                elif text.startswith(
                    "#PPGHRV,3"
                ):
                    self._framed_seen = True
                    self._health.mode = "v3"

                elif text.startswith(
                    "#PPGHRV,2"
                ):
                    if (
                        not self._framed_seen
                    ):
                        self._health.mode = "v2"

                continue

            at = self._buffer.find(
                b"@"
            )

            if at == 0:
                newline = (
                    self._buffer.find(
                        b"\n"
                    )
                )
                next_at = (
                    self._buffer.find(
                        b"@",
                        1,
                    )
                )

                if (
                    next_at > 0
                    and (
                        newline < 0
                        or next_at < newline
                    )
                ):
                    del self._buffer[
                        :next_at
                    ]
                    self._health.format_errors += 1
                    self._health.resync_count += 1
                    continue

                if newline < 0:
                    break

                raw = bytes(
                    self._buffer[
                        :newline + 1
                    ]
                )
                del self._buffer[
                    :newline + 1
                ]

                message = (
                    self._parse_framed(
                        raw
                    )
                )

                if message is not None:
                    messages.append(
                        message
                    )

                continue

            if (
                at > 0
                and self._framed_seen
            ):
                del self._buffer[:at]
                self._health.format_errors += 1
                self._health.resync_count += 1
                continue

            newline = self._buffer.find(
                b"\n"
            )

            if newline < 0:
                if at > 0:
                    prefix = bytes(
                        self._buffer[:at]
                    )
                    del self._buffer[:at]

                    self._recover_legacy_text(
                        prefix.decode(
                            "ascii",
                            errors="replace",
                        ),
                        messages,
                    )

                    self._health.resync_count += 1
                    continue

                break

            raw = bytes(
                self._buffer[
                    :newline + 1
                ]
            )
            del self._buffer[
                :newline + 1
            ]

            self._recover_legacy_text(
                raw.decode(
                    "ascii",
                    errors="replace",
                ).strip(),
                messages,
            )

        return messages

    def _parse_framed(
        self,
        raw: bytes,
    ) -> ProtocolMessage | None:
        text = raw.decode(
            "ascii",
            errors="replace",
        ).strip()

        try:
            message = (
                self._parser.parse(
                    text
                )
            )
        except ProtocolError as exc:
            if "CRC" in str(exc):
                self._health.crc_errors += 1
            else:
                self._health.format_errors += 1

            self._health.resync_count += 1
            return None

        if message is not None:
            if self._health.mode == "unknown":
                # 没收到 hello 也能按 framed protocol 工作。
                self._health.mode = "framed"

            self._framed_seen = True
            self._accept_message(
                message
            )

        return message

    def _recover_legacy_text(
        self,
        text: str,
        messages: list[
            ProtocolMessage
        ],
    ) -> None:
        text = text.strip()

        if not text:
            return

        if text.startswith("#"):
            if text.startswith(
                "#PPGHRV,2"
            ):
                self._health.mode = "v2"
            return

        try:
            message = (
                self._parser.parse(
                    text
                )
            )
        except ProtocolError:
            message = None

        if message is not None:
            self._health.legacy_frames += 1

            if (
                self._health.mode
                == "unknown"
            ):
                self._health.mode = "v2"

            self._accept_message(
                message
            )
            messages.append(
                message
            )
            return

        starts = [
            match.start()
            for match
            in self.LEGACY_START.finditer(
                text
            )
        ]

        for pos, start in enumerate(
            starts
        ):
            end = (
                starts[pos + 1]
                if pos + 1 < len(starts)
                else len(text)
            )

            candidate = text[
                start:end
            ].strip(
                " ,\r\n"
            )

            try:
                message = (
                    self._parser.parse(
                        candidate
                    )
                )
            except ProtocolError:
                continue

            if message is not None:
                self._health.legacy_frames += 1
                self._accept_message(
                    message
                )
                messages.append(
                    message
                )

        self._health.format_errors += 1
        self._health.resync_count += 1

    def _accept_message(
        self,
        message: ProtocolMessage,
    ) -> None:
        self._health.ok_frames += 1

        if isinstance(
            message,
            SampleFrame,
        ):
            if (
                self._last_sample_seq
                is not None
            ):
                expected = (
                    self._last_sample_seq
                    + 1
                )

                if (
                    message.seq
                    > expected
                ):
                    self._health.sample_seq_gaps += (
                        message.seq
                        - expected
                    )

            self._last_sample_seq = (
                message.seq
            )
