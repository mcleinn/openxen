"""Sending OSC messages (strings, floats, integers) over UDP: enough to drive the
SuperCollider instruments that sit next to the main one, e.g. the mridangam patch
(`host/synth/mridangam.scd`: `/mridangam/stroke <name> <loudness 0..1>` on port 57141)."""

from __future__ import annotations

import socket
import struct


def encode(address: str, *args) -> bytes:
    def padded(raw: bytes) -> bytes:
        return raw + b"\0" * (4 - len(raw) % 4)

    tags, body = ",", b""
    for arg in args:
        if isinstance(arg, str):
            tags += "s"
            body += padded(arg.encode("utf-8"))
        elif isinstance(arg, bool) or isinstance(arg, int):
            tags += "i"
            body += struct.pack(">i", int(arg))
        else:
            tags += "f"
            body += struct.pack(">f", float(arg))
    return padded(address.encode("ascii")) + padded(tags.encode("ascii")) + body


class Sender:
    """Fire-and-forget: UDP gives no answer, so a patch that is not running is silence, not an error."""

    def __init__(self, host: str = "127.0.0.1", port: int = 57141):
        self.target = (host, int(port))
        self.sent: list[tuple] = []         # kept for tests and the call log
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, address: str, *args) -> None:
        self.sent.append((address, *args))
        del self.sent[:-500]
        try:
            self._socket.sendto(encode(address, *args), self.target)
        except OSError:
            pass
