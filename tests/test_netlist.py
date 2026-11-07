"""The schematic's connectivity implements exactly what the spec (and therefore the firmware)
assumes: sensor cells, mux channels, select lines, MCU pins, LED matrix, LED driver bus."""
from __future__ import annotations

from facts import (LED_PIN, MUX_COM_PIN, MUX_GND_PIN, MUX_INH_PIN, MUX_SELECT_PIN, MUX_VCC_PIN, MUX_VEE_PIN,
                   MUX_Y_PIN, SENSOR_PIN)


def test_sensor_cells(pin_net, netlist, keys):
    for n in keys:
        assert pin_net[(f"HE{n}", SENSOR_PIN["VDD"])] == "+3.3VA"
        assert pin_net[(f"HE{n}", SENSOR_PIN["GND"])] == "GND"
        assert pin_net[(f"HE{n}", SENSOR_PIN["OUT"])] == f"HE{n}"
        assert {pin_net[(f"C{n}", p)] for p in "12"} == {"+3.3VA", "GND"}          # 100 nF decoupling
        assert {pin_net[(f"CF{n}", p)] for p in "12"} == {f"HE{n}", "GND"}         # 4.7 nF output filter


def test_mux_channels(netlist, spec):
    """HEn reaches exactly its mux's Y<channel> pin (datasheet pin numbers)."""
    for g in spec["mux"]["groups"]:
        for ch, kid in enumerate(g["keys"]):
            nodes = {(r, p) for r, p, _ in netlist[f"HE{kid}"]}
            assert nodes == {(f"HE{kid}", "2"), (f"CF{kid}", "1"), (f"AM{g['index']}", MUX_Y_PIN[ch])}, (kid, ch)


def test_mux_outputs_selects_and_supply(pin_net, pin_by_function, spec):
    for g in spec["mux"]["groups"]:
        m = g["index"]
        out = pin_net[(f"AM{m}", MUX_COM_PIN)]
        assert out == f"MUX_OUT_{m + 1}"
        assert pin_by_function[("U4", "P" + spec["mux"]["input_pins"][m])] == out        # libhmk input pin
        for bit, pin in MUX_SELECT_PIN.items():
            sel = pin_net[(f"AM{m}", pin)]
            assert sel == f"MUX_SELECT_{bit}"
            assert pin_by_function[("U4", "P" + spec["mux"]["select_pins"][bit])] == sel
        assert pin_net[(f"AM{m}", MUX_VCC_PIN)] == "+3.3VA"
        for p in (MUX_INH_PIN, MUX_VEE_PIN, MUX_GND_PIN):                            # INH low = enabled
            assert pin_net[(f"AM{m}", p)] == "GND", (m, p)
        assert {pin_net[(f"CM{m}", p)] for p in "12"} == {"+3.3VA", "GND"}


def test_mux_outputs_have_test_points(netlist):
    for m in range(7):
        assert any(r.startswith("TP") for r, _, _ in netlist[f"MUX_OUT_{m + 1}"])


def test_led_matrix(pin_net, pin_by_function, spec, keys):
    L = spec["led"]
    for n in keys:
        g, cs = L["key_group"][str(n)], L["key_cs"][str(n)]
        assert pin_net[(f"D{n}", LED_PIN["A"])] == f"LED_CS{cs}"
        for col in "RGB":
            assert pin_net[(f"D{n}", LED_PIN[col])] == f"LED_SW{L['sw_lines'][str(g)][col]}", (n, col)
    for c in range(14):
        assert pin_by_function[("U10", f"CS{c + 1}")] == f"LED_CS{c}"
    for s in range(12):
        assert pin_by_function[("U10", f"SW{s + 1}")] == f"LED_SW{s}"
    for c in (15, 16):                                                              # unused sources
        assert pin_by_function[("U10", f"CS{c}")].startswith("unconnected")


def test_led_driver_bus(pin_by_function):
    """I2C on PB6/PB7 (LED_SCL/LED_SDA), shutdown on PC0; ADDR1/ADDR2 to GND -> address 0x50."""
    assert pin_by_function[("U4", "PB6")] == "LED_SCL" == pin_by_function[("U10", "SCL")]
    assert pin_by_function[("U4", "PB7")] == "LED_SDA" == pin_by_function[("U10", "SDA")]
    assert pin_by_function[("U4", "PC0")] == "LED_SDB" == pin_by_function[("U10", "~{SDB}")]
    assert pin_by_function[("U10", "ADDR1")] == "GND" and pin_by_function[("U10", "ADDR2")] == "GND"


def test_erc_clean(erc):
    v = [x for s in erc["sheets"] for x in s["violations"]]
    errors = [x for x in v if x["severity"] == "error"]
    assert not errors, errors[:5]
    assert {x["type"] for x in v} <= {"lib_symbol_mismatch"}, {x["type"] for x in v}
