"""openxen analog stream: the firmware's packing/ring code (compiled for the PC with zig cc)
produces reports the reference decoder (host/oxs.py) reads correctly, and the protocol
constants agree between firmware, descriptor, documentation and decoder."""
from __future__ import annotations

import re
import struct
import subprocess
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "host"))
import oxs  # noqa: E402

FW = ROOT / "firmware" / "libhmk"


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    try:
        import ziglang  # noqa: F401
    except ImportError:
        pytest.skip("host C compiler missing (pip install ziglang)")
    exe = tmp_path_factory.mktemp("oxs") / "harness.exe"
    cmd = [sys.executable, "-m", "ziglang", "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wsign-conversion",
           "-I", str(FW / "include"), str(FW / "src" / "openxen_stream_core.c"),
           str(ROOT / "tests" / "firmware_host" / "stream_core_harness.c"), "-o", str(exe)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    def run(mode: str) -> list[str]:
        p = subprocess.run([str(exe), mode], capture_output=True, text=True)
        assert p.returncode == 0, (mode, p.returncode, p.stderr)
        return p.stdout.split()
    return run


def expected_values(scan: int) -> tuple[int, ...]:
    return tuple((scan * 100 + k) & 0x0FFF for k in range(56))


def test_basic_reports_decode(harness):
    s = oxs.Stream()
    frames = [s.feed(bytes.fromhex(h)) for h in harness("basic")]
    assert len(frames) == 14
    for i, f in enumerate(frames):
        assert f.sequence == i and f.lost_before == 0
        assert f.time_us == 1000 + 250 * i
        assert f.values == expected_values(i)
        assert f.flags == oxs.FLAG_INVERTED
    # 4 keys of calibration per report: complete table after 14 reports (3.5 ms at 4 kHz)
    assert s.rest == {k: 1000 + k for k in range(56)} and s.bottom == {k: 3000 + k for k in range(56)}
    assert frames[9].travel[50] is None                  # key 50's calibration not seen after 10 reports
    last = frames[-1]
    for k in (0, 5, 55):
        assert last.travel[k] == pytest.approx(min(1, max(0, (last.values[k] - (1000 + k)) / 2000)))


def test_overflow_is_reported_as_loss(harness):
    s = oxs.Stream()
    frames = [s.feed(bytes.fromhex(h)) for h in harness("overflow")]
    raw = [oxs.parse(bytes.fromhex(h)) for h in harness("overflow")]
    # ring holds 8: scans 0..7 delivered, 8..11 lost, then 12..14 delivered
    assert [f.sequence for f in frames] == [0, 1, 2, 3, 4, 5, 6, 7, 12, 13, 14]
    assert frames[8].lost_before == 4 and s.lost_total == 4
    assert raw[0].dropped == 4                            # firmware counter, reported with the next report
    assert sum(r.dropped for r in raw) == 4
    # device time wrapped past 2^32 and is unwrapped monotonically
    times = [f.time_us for f in frames]
    assert all(b > a for a, b in zip(times, times[1:]))
    assert times[-1] - times[0] == 14 * 250
    assert frames[8].values == expected_values(12)


def test_clock_across_counter_wrap(harness):
    us = [int(x) for x in harness("clock")]
    assert us == [250 * (i + 1) for i in range(6)]       # 7 extra cycles per step never add up to 1 us here


def test_constants_consistent():
    hdr = (FW / "include" / "openxen_stream.h").read_text(encoding="utf-8")
    apply = (FW / "apply_openxen.py").read_text(encoding="utf-8")
    doc = (ROOT / "docs" / "stream-protocol.md").read_text(encoding="utf-8")
    assert "sizeof(oxs_report_t) == 144" in hdr and oxs.REPORT_SIZE == 144
    assert "#define OXS_REPORT_SIZE 144" in apply
    assert f"#define OXS_USAGE_PAGE {oxs.USAGE_PAGE:#06X}".replace("0X", "0x") in apply
    assert re.search(r"OXS_MAGIC 0x584Fu", hdr) and oxs.MAGIC == 0x584F
    assert f"`{oxs.USAGE_PAGE:#06X}`".replace("0X", "0x") in doc
    assert oxs.HEADER.size == 16 and 16 + 2 * 56 + 16 == oxs.REPORT_SIZE


def test_firmware_contains_stream(tmp_path):
    """The built firmware links the stream (symbols present) and its HID report descriptor
    declares usage page 0xFFAC with a 144-byte input report."""
    from test_firmware_binary import ELF, Elf32
    if not ELF.exists():
        pytest.skip("firmware not built")
    elf = Elf32(ELF.read_bytes())
    desc = elf.symbol("desc_stream_report")
    assert desc[:3] == bytes([0x06, 0xAC, 0xFF])           # Usage Page (16 bit) 0xFFAC
    assert bytes([0x95, 144]) in desc                       # Report Count 144 (1-byte item)
    for sym in ("ring", "clock_us", "report"):
        elf.symbol(sym)
