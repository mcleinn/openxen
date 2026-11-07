"""openxen LEDs: the firmware's LED core (compiled for the PC) driven with host commands from
the reference encoder (host/oxl.py); its register writes are replayed into a model of the
IS31FL3733 (page-lock protocol per datasheet) and the resulting PWM/GCC are checked against
the netlist wiring, gamma, power budget, highlight and timeout rules."""
from __future__ import annotations

import subprocess
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "host"))
import oxl  # noqa: E402

FW = ROOT / "firmware"
GAMMA = [0] + [max(1, round(255 * ((i / 255) ** 2.2))) for i in range(1, 256)]


class Chip:
    """IS31FL3733 register model: FD (page) is writable only right after FE = C5."""

    def __init__(self):
        self.pages = [[0] * 256 for _ in range(4)]
        self.page = None
        self.unlocked = False

    def write(self, reg: int, data: bytes):
        if reg == 0xFE:
            self.unlocked = data == b"\xc5"
            return
        if reg == 0xFD:
            assert self.unlocked, "page register written without unlock"
            assert len(data) == 1 and data[0] in (0, 1, 2, 3)
            self.page, self.unlocked = data[0], False
            return
        assert self.page is not None, "register write before any page select"
        for i, b in enumerate(data):
            self.pages[self.page][reg + i] = b

    @property
    def gcc(self) -> int:
        return self.pages[3][1]

    def pwm(self, sw: int, cs: int) -> int:
        return self.pages[1][sw * 16 + cs]

    def current_ma(self) -> float:
        return 3.5 * self.gcc / 255 * sum(self.pages[1][:192]) / 256


@pytest.fixture(scope="module")
def harness_exe(tmp_path_factory):
    try:
        import ziglang  # noqa: F401
    except ImportError:
        pytest.skip("host C compiler missing (pip install ziglang)")
    exe = tmp_path_factory.mktemp("oxl") / "led_harness.exe"
    cmd = [sys.executable, "-m", "ziglang", "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wsign-conversion",
           "-I", str(FW / "libhmk" / "include"), "-I", str(FW / "keyboards" / "openxen-m56"),
           str(FW / "libhmk" / "src" / "openxen_led_core.c"),
           str(ROOT / "tests" / "firmware_host" / "led_core_harness.c"), "-o", str(exe)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return exe


class Session:
    """Builds a harness script, runs it, replays writes into a Chip after every step."""

    def __init__(self, exe):
        self.exe, self.lines = exe, []

    def cmd(self, ms: int, report: bytes):
        self.lines.append(f"cmd {ms} {report.hex()}")
        return self

    def press(self, keys: set[int]):
        bits = bytearray(7)
        for k in keys:
            bits[k // 8] |= 1 << (k % 8)
        self.lines.append(f"press {bits.hex()}")
        return self

    def step(self, ms: int):
        self.lines.append(f"step {ms}")
        return self

    def write1(self, ms: int):
        self.lines.append(f"write1 {ms}")
        return self

    def fail(self):
        self.lines.append("fail")
        return self

    def status(self, ms: int):
        self.lines.append(f"status {ms}")
        return self

    def run(self):
        p = subprocess.run([str(self.exe)], input="\n".join(self.lines) + "\n", capture_output=True, text=True)
        assert p.returncode == 0, p.stderr
        out = p.stdout.split("\n")
        chip, steps, acks, statuses, writes = Chip(), [], [], [], []
        cur = []
        for line in out:
            if line.startswith("W "):
                _, reg, data = (line.split() + [""])[:3]
                w = (int(reg, 16), bytes.fromhex(data))
                chip.write(*w)
                cur.append(w)
                writes.append((w, chip.current_ma()))
            elif line.startswith("ACK"):
                acks.append(int(line.split()[1]))
            elif line.startswith("STATUS"):
                statuses.append(int(line.split()[1]))
            elif line == "END":
                steps.append((cur, [row[:] for row in chip.pages]))
                cur = []
        return chip, steps, acks, statuses, writes


def wiring(pin_by_function, netlist, keys):
    """key -> (cs, (sw_r, sw_g, sw_b)), 0-based, derived from the netlist only."""
    pin_net = {(r, p): n for n, nodes in netlist.items() for r, p, _ in nodes}
    cs_of = {pin_by_function[("U10", f"CS{c}")]: c - 1 for c in range(1, 15)}
    sw_of = {pin_by_function[("U10", f"SW{s}")]: s - 1 for s in range(1, 13)}
    return {n: (cs_of[pin_net[(f"D{n}", "1")]], tuple(sw_of[pin_net[(f"D{n}", p)]] for p in "234")) for n in keys}


def colours_pattern():
    return [((k * 37) % 256, (k * 91 + 20) % 256, (255 - k * 4) % 256) for k in range(56)]


def full_session(exe, budget=600, brightness=255, colours=None):
    s = Session(exe).step(0)
    s.cmd(1, oxl.config(brightness, None, 2000, budget))
    for r in oxl.frame(colours or colours_pattern()):
        s.cmd(2, r)
    return s.step(3)


def test_init_sequence_brings_chip_up(harness_exe):
    chip, steps, *_ = Session(harness_exe).step(0).run()
    assert chip.pages[3][0x00] == 0x01                       # normal operation
    assert chip.gcc == 0                                     # dark until the host speaks
    assert chip.pages[3][0x0F] == 0x07 and chip.pages[3][0x10] == 0x07
    # 14 CS x 12 SW used: CS1..8 all on, CS9..14 on (0x3F), CS15/16 off, for every SW
    assert chip.pages[0][:24] == [0xFF, 0x3F] * 12
    assert sum(chip.pages[1][:192]) == 0


def test_frame_lands_on_the_wired_channels(harness_exe, pin_by_function, netlist, keys):
    chip, *_ = full_session(harness_exe).run()
    wire = wiring(pin_by_function, netlist, keys)
    cols = colours_pattern()
    for k, (cs, sws) in wire.items():
        for c in range(3):
            assert chip.pwm(sws[c], cs) == GAMMA[cols[k][c]], (k, "RGB"[c])
    # every register not wired to an LED stays 0
    used = {sw * 16 + cs for cs, sws in wire.values() for sw in sws}
    assert all(chip.pages[1][i] == 0 for i in range(192) if i not in used)


def test_generated_map_matches_netlist(pin_by_function, netlist, keys):
    import re
    text = (FW / "keyboards" / "openxen-m56" / "openxen_led_map.h").read_text(encoding="utf-8")
    rows = re.findall(r"\{\s*(\d+), \{\s*(\d+),\s*(\d+),\s*(\d+)\}\}, /\* key (\d+) \*/", text)
    assert len(rows) == 56
    wire = wiring(pin_by_function, netlist, keys)
    for cs, r, g, b, k in rows:
        assert wire[int(k)] == (int(cs), (int(r), int(g), int(b))), k


@pytest.mark.parametrize("budget", [50, 100, 300, 600])
def test_power_budget_respected_at_every_write(harness_exe, budget):
    white = [(255, 255, 255)] * 56
    chip, steps, acks, _, writes = full_session(harness_exe, budget=budget, colours=white).run()
    assert all(a == 0 for a in acks)
    assert max(ma for _, ma in writes) <= budget + 0.5
    full_white_ma = 3.5 * 192 * 255 / 256 * 168 / 192            # all 168 channels at PWM 255, GCC 255
    one_gcc_step = full_white_ma / 255
    assert chip.current_ma() >= budget - one_gcc_step or chip.gcc == 255   # uses the budget it is given
    if budget >= 600:
        assert chip.current_ma() <= 600


def test_dimming_lowers_current_before_raising_pwm(harness_exe):
    dark = [(10, 10, 10)] * 56
    bright = [(255, 255, 255)] * 56
    s = full_session(harness_exe, budget=300, colours=dark)
    for r in oxl.frame(bright):
        s.cmd(10, r)
    s.step(11)
    _, _, _, _, writes = s.run()
    assert max(ma for _, ma in writes) <= 300.5


def test_partial_update_writes_only_the_change(harness_exe):
    cols = colours_pattern()
    s = full_session(harness_exe, colours=cols)
    s.cmd(10, oxl.pixels(30, [(1, 2, 3)], show=True)).step(11)
    _, steps, *_ = s.run()
    last = steps[-1][0]
    data_bytes = sum(len(d) for r, d in last if r not in (0xFE, 0xFD) and r != 0x01)
    assert 1 <= data_bytes <= 16 + 3, last                    # one run of PWM bytes (+ possibly GCC)


def test_staged_pixels_need_show(harness_exe):
    s = full_session(harness_exe)
    s.cmd(10, oxl.pixels(0, [(255, 0, 0)] * 20, show=False)).step(11)
    _, steps, *_ = s.run()
    assert steps[-1][0] == [] or all(r == 0x01 for r, _ in steps[-1][0] if r not in (0xFE, 0xFD))


def test_highlight_replaces_pressed_key(harness_exe, pin_by_function, netlist, keys):
    s = Session(harness_exe).step(0)
    s.cmd(1, oxl.config(255, (255, 0, 0), 2000, 600))
    for r in oxl.frame([(0, 0, 255)] * 56):
        s.cmd(2, r)
    s.press({5}).step(3)
    chip, *_ = s.run()
    cs, (r, g, b) = wiring(pin_by_function, netlist, keys)[5]
    assert (chip.pwm(r, cs), chip.pwm(g, cs), chip.pwm(b, cs)) == (255, 0, 0)
    cs6, (r6, g6, b6) = wiring(pin_by_function, netlist, keys)[6]
    assert (chip.pwm(r6, cs6), chip.pwm(g6, cs6), chip.pwm(b6, cs6)) == (0, 0, 255)


def test_host_timeout_turns_leds_off_and_keepalive_restores(harness_exe):
    s = full_session(harness_exe)
    s.step(1000).status(1000)
    s.step(2004).status(2004)                                 # last command at 2 ms, timeout 2000
    s.cmd(3000, oxl.keepalive()).step(3001).status(3001)
    _, steps, _, statuses, _ = s.run()
    lit, off, back = steps[-3][1], steps[-2][1], steps[-1][1]
    assert sum(lit[1][:192]) > 0 and lit[3][1] > 0
    assert sum(off[1][:192]) == 0 and off[3][1] == 0
    assert back[1][:192] == lit[1][:192] and back[3][1] == lit[3][1]
    assert statuses == [oxl.STATUS_HOST, oxl.STATUS_TIMEOUT, oxl.STATUS_HOST]


def test_timeout_zero_means_never(harness_exe):
    s = Session(harness_exe).step(0).cmd(1, oxl.config(255, None, 0, 300))
    for r in oxl.frame(colours_pattern()):
        s.cmd(2, r)
    s.step(3).step(10_000_000)
    _, steps, *_ = s.run()
    assert steps[-1][1][1][:192] == steps[-2][1][1][:192] and sum(steps[-1][1][1][:192]) > 0


@pytest.mark.parametrize("report", [
    bytes([0x10, 1, 0, 21]) + bytes(60),          # count > 20
    bytes([0x10, 1, 50, 10]) + bytes(60),         # beyond key 55
    bytes([0x10, 1, 56, 1]) + bytes(60),          # first key out of range
    bytes([0x10, 1, 0, 19]),                      # report shorter than its pixels
    bytes([0x11, 255, 2]) + bytes(61),            # highlight mode 2
    bytes([0x11, 255, 0]),                        # config too short
    bytes([0x7F]) + bytes(63),                    # unknown command
    b"",                                          # empty
])
def test_malformed_commands_are_rejected(harness_exe, report):
    s = full_session(harness_exe)
    s.lines.append(f"cmd 10 {report.hex()}" if report else "cmd 10 00")
    s.step(11)
    chip_before = full_session(harness_exe).run()[0]
    chip, steps, acks, *_ = s.run()
    if report:
        assert acks[-1] == -1
    assert chip.pages == chip_before.pages


def test_i2c_failure_reinitialises_to_the_same_state(harness_exe):
    s = full_session(harness_exe).fail().step(20)
    chip, steps, *_ = s.run()
    reinit = steps[-1][0]
    assert reinit[0] == (0xFE, b"\xc5") and reinit[1] == (0xFD, b"\x03")    # starts from the page protocol
    ref = full_session(harness_exe).run()[0]
    assert chip.pages == ref.pages


def test_encoder_layout():
    c = oxl.config(200, (1, 2, 3), 2000, 450)
    assert c[:10] == bytes([0x11, 200, 1, 1, 2, 3, 0xD0, 0x07, 0xC2, 0x01]) and len(c) == 64
    f = oxl.frame([(k, k, k) for k in range(56)])
    assert [r[:4] for r in f] == [bytes([0x10, 0, 0, 20]), bytes([0x10, 0, 20, 20]), bytes([0x10, 1, 40, 16])]
    assert oxl.keepalive() == bytes([0x12]) + bytes(63)
