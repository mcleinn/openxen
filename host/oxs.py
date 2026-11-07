#!/usr/bin/env python3
"""Reference decoder for the openxen analog stream (docs/stream-protocol.md).

    from oxs import Stream
    s = Stream()
    for raw in reports:            # 144-byte HID input reports in arrival order
        frame = s.feed(raw)        # Frame with unwrapped sequence/time, travel per key

Also runnable as a live reader when the `hid` (hidapi) package is installed:
    python host/oxs.py [--serial SERIAL]
"""
from __future__ import annotations

import struct
import sys
from dataclasses import dataclass, field

MAGIC = 0x584F
VERSION = 1
USAGE_PAGE = 0xFFAC
REPORT_SIZE = 144
HEADER = struct.Struct("<HBBHHIBBBB")          # 16 bytes
CAL_PER_REPORT = 4
FLAG_INVERTED = 0x01
FLAG_CALIBRATING = 0x02


@dataclass
class Report:
    flags: int
    sequence: int
    dropped: int
    timestamp_us: int
    num_keys: int
    cal_first_key: int
    adc_bits: int
    values: tuple[int, ...]
    cal: tuple[tuple[int, int], ...]          # (rest, bottom_out) for cal_first_key + i


def parse(raw: bytes) -> Report:
    if len(raw) != REPORT_SIZE:
        raise ValueError(f"report must be {REPORT_SIZE} bytes, got {len(raw)}")
    magic, version, flags, seq, dropped, ts, nkeys, cal_first, bits, _ = HEADER.unpack_from(raw, 0)
    if magic != MAGIC or version != VERSION:
        raise ValueError(f"not an openxen stream report (magic {magic:#06x}, version {version})")
    if not 0 < nkeys <= 56:
        raise ValueError(f"bad num_keys {nkeys}")
    values = struct.unpack_from("<56H", raw, 16)[:nkeys]
    cal = tuple(struct.unpack_from("<2H", raw, 128 + 4 * i) for i in range(CAL_PER_REPORT))
    return Report(flags, seq, dropped, ts, nkeys, cal_first, bits, values, cal)


@dataclass
class Frame:
    sequence: int                 # unwrapped
    time_us: int                  # unwrapped device time
    lost_before: int              # scans lost between the previous frame and this one
    values: tuple[int, ...]
    travel: tuple[float | None, ...]   # 0..1 per key, None until the key's calibration is known
    flags: int


@dataclass
class Stream:
    """Unwraps sequence and time, tracks losses and keeps the rotating calibration table."""
    rest: dict[int, int] = field(default_factory=dict)
    bottom: dict[int, int] = field(default_factory=dict)
    _seq: int | None = None
    _time: int | None = None
    lost_total: int = 0

    def feed(self, raw: bytes) -> Frame:
        r = parse(raw)
        for i, (rest, bottom) in enumerate(r.cal):
            k = (r.cal_first_key + i) % r.num_keys
            self.rest[k], self.bottom[k] = rest, bottom
        if self._seq is None:
            seq, lost = r.sequence, 0
            t = r.timestamp_us
        else:
            step = (r.sequence - self._seq) & 0xFFFF
            if step == 0:
                raise ValueError("repeated sequence number")
            seq, lost = self._seq + step, step - 1
            t = self._time + ((r.timestamp_us - self._time) & 0xFFFFFFFF)
        self._seq, self._time = seq, t
        self.lost_total += lost
        travel = []
        for k, v in enumerate(r.values):
            if k in self.rest and self.bottom[k] > self.rest[k]:
                travel.append(min(1.0, max(0.0, (v - self.rest[k]) / (self.bottom[k] - self.rest[k]))))
            else:
                travel.append(None)
        return Frame(seq, t, lost, r.values, tuple(travel), r.flags)


def main() -> int:                                     # pragma: no cover - needs hardware
    import argparse
    try:
        import hid  # type: ignore
    except ImportError:
        print("pip install hid (hidapi) for the live reader")
        return 1
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial")
    args = ap.parse_args()
    devs = [d for d in hid.enumerate() if d["usage_page"] == USAGE_PAGE and (not args.serial or d["serial_number"] == args.serial)]
    if not devs:
        print("no openxen stream interface found")
        return 1
    dev = hid.Device(path=devs[0]["path"])
    s = Stream()
    n = 0
    while True:
        f = s.feed(bytes(dev.read(REPORT_SIZE)))
        n += 1
        if n % 1000 == 0:
            pressed = [k for k, t in enumerate(f.travel) if t and t > 0.05]
            print(f"seq {f.sequence} t {f.time_us / 1e6:.3f} s lost {s.lost_total} pressed {pressed}")


if __name__ == "__main__":
    sys.exit(main())
