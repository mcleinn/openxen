#!/usr/bin/env python3
"""Reference encoder for openxen LED commands (docs/led-protocol.md).

Every command is one 64-byte HID output report on the openxen interface (usage page 0xFFAC),
no report ID, zero padded.
"""
from __future__ import annotations

import struct

REPORT_SIZE = 64
CMD_PIXELS = 0x10
CMD_CONFIG = 0x11
CMD_KEEPALIVE = 0x12
PIXELS_SHOW = 0x01
PIXELS_PER_REPORT = 20
KEYS = 56
HL_OFF, HL_REPLACE = 0, 1
BUDGET_MAX_MA = 600

STATUS_HOST = 0x01
STATUS_TIMEOUT = 0x02
STATUS_I2C_ERROR = 0x04


def _pad(b: bytes) -> bytes:
    assert len(b) <= REPORT_SIZE
    return b + bytes(REPORT_SIZE - len(b))


def pixels(first: int, colours: list[tuple[int, int, int]], show: bool) -> bytes:
    if not 1 <= len(colours) <= PIXELS_PER_REPORT or not 0 <= first or first + len(colours) > KEYS:
        raise ValueError("bad pixel range")
    body = bytes([CMD_PIXELS, PIXELS_SHOW if show else 0, first, len(colours)])
    for r, g, b in colours:
        body += bytes([r, g, b])
    return _pad(body)


def frame(colours: list[tuple[int, int, int]]) -> list[bytes]:
    """A whole module frame (56 colours) as 3 reports; the last one shows it."""
    if len(colours) != KEYS:
        raise ValueError("a frame has 56 colours")
    out = []
    for first in range(0, KEYS, PIXELS_PER_REPORT):
        chunk = colours[first:first + PIXELS_PER_REPORT]
        out.append(pixels(first, chunk, show=first + len(chunk) == KEYS))
    return out


def config(brightness: int, highlight: tuple[int, int, int] | None, timeout_ms: int, budget_ma: int) -> bytes:
    hl_mode = HL_OFF if highlight is None else HL_REPLACE
    r, g, b = highlight or (0, 0, 0)
    return _pad(struct.pack("<BBB3BHH", CMD_CONFIG, brightness, hl_mode, r, g, b, timeout_ms, budget_ma))


def keepalive() -> bytes:
    return _pad(bytes([CMD_KEEPALIVE]))
