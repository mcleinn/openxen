"""The compiled firmware (build/fw/firmware.elf from firmware/build_firmware.py) contains the
mux tables the hardware needs: read straight out of the ELF, independent of every generator.

mux_input_matrix[select channel][mux input] must hold key+1 exactly where the schematic wires
key n's sensor (HEn -> AM<input> pin Y<channel>), the select pin masks must be PC1/PC2/PC3,
and the ADC channels must be the ones the MUX_OUT nets reach on the MCU.
"""
from __future__ import annotations

import struct

import pytest

from conftest import ROOT
from facts import MUX_Y_PIN

ELF = ROOT / "build" / "fw" / "firmware.elf"

# AT32F405 datasheet pin definitions: ADC1_IN0..7 = PA0..PA7, IN8..9 = PB0..PB1, IN10..15 = PC0..PC5
ADC_CHANNEL = {**{f"PA{i}": i for i in range(8)}, "PB0": 8, "PB1": 9, **{f"PC{i}": 10 + i for i in range(6)}}


class Elf32:
    """Just enough ELF32 (little endian) to read static symbols' bytes."""

    def __init__(self, data: bytes):
        self.d = data
        assert data[:4] == b"\x7fELF" and data[4] == 1 and data[5] == 1
        shoff, = struct.unpack_from("<I", data, 0x20)
        shentsize, shnum, shstrndx = struct.unpack_from("<HHH", data, 0x2E)
        self.sec = [struct.unpack_from("<IIIIIIIIII", data, shoff + i * shentsize) for i in range(shnum)]
        self.symtab = next(s for s in self.sec if s[1] == 2)            # SHT_SYMTAB
        self.strtab = self.sec[self.symtab[6]]

    def _str(self, tab, off):
        start = tab[4] + off
        return self.d[start:self.d.index(b"\0", start)].decode()

    def symbol(self, name: str) -> bytes:
        tab = self.symtab
        for i in range(tab[5] // 16):
            st_name, st_value, st_size, st_info, st_other, st_shndx = struct.unpack_from("<IIIBBH", self.d, tab[4] + i * 16)
            if self._str(self.strtab, st_name) == name and st_size:
                s = self.sec[st_shndx]                                    # sh_addr = s[3], sh_offset = s[4]
                off = s[4] + (st_value - s[3])
                return self.d[off:off + st_size]
        raise KeyError(name)


@pytest.fixture(scope="module")
def elf() -> Elf32:
    if not ELF.exists():
        pytest.skip("firmware not built (python firmware/build_firmware.py)")
    return Elf32(ELF.read_bytes())


def test_mux_input_matrix_matches_wiring(elf, netlist, keys):
    raw = elf.symbol("mux_input_matrix")
    vals = struct.unpack(f"<{len(raw) // 2}H", raw)
    assert len(vals) == 8 * 7
    table = [vals[ch * 7:(ch + 1) * 7] for ch in range(8)]              # [select channel][mux input]
    y_by_pin = {p: ch for ch, p in MUX_Y_PIN.items()}
    expected = [[0] * 7 for _ in range(8)]
    for n in keys:
        am = [(r, p) for r, p, _ in netlist[f"HE{n}"] if r.startswith("AM")]
        assert len(am) == 1, n
        m, ch = int(am[0][0][2:]), y_by_pin[am[0][1]]
        expected[ch][m] = n + 1
    assert [list(r) for r in table] == expected


def test_mux_select_pins(elf, spec, pin_by_function):
    raw = elf.symbol("mux_select_pins")
    masks = struct.unpack(f"<{len(raw) // 2}H", raw)
    pins = [int(p[1:]) for p in spec["mux"]["select_pins"]]
    assert list(masks) == [1 << p for p in pins]
    for bit, p in enumerate(spec["mux"]["select_pins"]):
        assert pin_by_function[("U4", "P" + p)] == f"MUX_SELECT_{bit}"


def test_mux_adc_channels(elf, spec, pin_by_function):
    chans = list(elf.symbol("mux_input_channels"))
    assert len(chans) == 7
    for m, chan in enumerate(chans):
        pin = "P" + spec["mux"]["input_pins"][m]
        assert ADC_CHANNEL[pin] == chan, (m, pin, chan)
        assert pin_by_function[("U4", pin)] == f"MUX_OUT_{m + 1}"
