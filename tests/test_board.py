"""The board: DRC, schematic parity, placement against the spec, assembly side, layer use,
track and via sizes, and the state of the scripted routing."""
from __future__ import annotations

import collections
import re

import pytest

import sexp
from facts import CAP_OFFSET, LED_OFFSET, MIN_TRACK, MIN_VIA_D, MIN_VIA_DRILL, MUX_CAP_DX

# Open connections that are expected until the remaining nets are routed. Each entry is the
# maximum per net; scripted routing must not regress (e.g. an LED cut off from its line).
OPEN_BUDGET = {
    r"LED_SW\d+": 1,        # line -> driver pin (left to the autorouter)
    r"HE\d+": 1,            # sensor cell -> mux pin (fan-in)
}


def at(fp):
    x, y, r = sexp.at(fp)
    return x, y, r


def test_drc_no_errors(drc):
    errs = [v for v in drc["violations"] if v["severity"] == "error"]
    assert not errs, [(v["type"], v["description"]) for v in errs[:8]]


def test_schematic_parity(drc):
    assert not drc.get("schematic_parity"), drc["schematic_parity"][:5]


def test_drc_warnings_known(drc):
    """Only known warning kinds: the 1 mm LED anode stubs awaiting their lines, the sink lines'
    open end toward the driver, the sensor escape vias awaiting the fan-in, and HE60's USB-C
    silk touching the board edge."""
    for v in drc["violations"]:
        if v["severity"] != "warning":
            continue
        if v["type"] == "track_dangling":
            d = v["items"][0]["description"]
            # LED anode stubs (B.Cu, 1 mm) and the sink lines' open end toward the driver (F.Cu)
            assert re.search(r"\[LED_CS\d+\] on B\.Cu, length 1[,.]0000 mm", d) or re.search(r"\[LED_SW\d+\] on F\.Cu", d), d
        elif v["type"] == "via_dangling":
            # sensor-output escape vias (route_cell.py) wait for the fan-in on F.Cu
            assert re.search(r"Via \[HE\d+\]", v["items"][0]["description"]), v["items"][0]["description"]
        elif v["type"] == "silk_edge_clearance":
            assert any("J1" in i["description"] for i in v["items"])
        else:
            pytest.fail(f"unexpected warning {v['type']}: {v['description']}")


def test_open_connections_within_budget(drc):
    per = collections.Counter()
    for u in drc["unconnected_items"]:
        for i in u["items"]:
            m = re.search(r"\[([^\]]+)\]", i["description"])
            if m:
                per[m.group(1)] += 1
                break
    for pat, limit in OPEN_BUDGET.items():
        for net, n in per.items():
            if re.fullmatch(pat, net):
                assert n <= limit, (net, n)


def test_single_sided_assembly(footprints):
    """Every footprint with SMD pads sits on the bottom (one JLCPCB assembly side)."""
    for ref, fp in footprints.items():
        if any(p[2] == "smd" for p in sexp.kids(fp, "pad")):
            assert sexp.q(fp, "layer") == "B.Cu", ref


def test_key_cells_placed_per_spec(footprints, keys):
    for n, k in keys.items():
        x, y, _ = at(footprints[f"K{n}"])
        assert (x, y) == (pytest.approx(k["x"]), pytest.approx(k["y"]))
        x, y, _ = at(footprints[f"HE{n}"])
        assert (x, y) == (pytest.approx(k["x"]), pytest.approx(k["y"]))
        x, y, _ = at(footprints[f"D{n}"])
        assert (x, y) == (pytest.approx(k["x"] + LED_OFFSET[0]), pytest.approx(k["y"] + LED_OFFSET[1]))
        for pre, (dx, dy) in CAP_OFFSET.items():
            x, y, _ = at(footprints[f"{pre}{n}"])
            assert (x, y) == (pytest.approx(k["x"] + dx), pytest.approx(k["y"] + dy)), f"{pre}{n}"


def test_muxes_placed_per_spec(footprints, spec):
    for g in spec["mux"]["groups"]:
        mx, my = g["pos"]
        x, y, r = at(footprints[f"AM{g['index']}"])
        assert (x, y) == (pytest.approx(mx), pytest.approx(my)) and r in (0, 0.0)
        x, y, _ = at(footprints[f"CM{g['index']}"])
        assert (x, y) == (pytest.approx(mx + MUX_CAP_DX), pytest.approx(my))


def test_no_tracks_on_planes(board):
    for s in sexp.kids(board, "segment"):
        assert sexp.q(s, "layer") in ("F.Cu", "B.Cu")


def test_planes_present(board, board_nets):
    zones = {(getattr(sexp.kid(z, "net_name")[1], "s", None), sexp.q(z, "layer")) for z in sexp.kids(board, "zone")}
    assert ("GND", "In1.Cu") in zones and ("+3.3VA", "In2.Cu") in zones


def length(seg) -> float:
    (x1, y1), (x2, y2) = sexp.kid(seg, "start")[1:3], sexp.kid(seg, "end")[1:3]
    return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5


def test_track_and_via_sizes(board, board_nets):
    def name(item):
        v = sexp.kid(item, "net")[1]
        return board_nets.get(v, getattr(v, "s", v))
    for s in sexp.kids(board, "segment"):
        w, n = sexp.kid(s, "width")[1], name(s)
        assert w >= MIN_TRACK - 1e-9, (n, w)
        if n in ("+5V", "VBUS"):
            assert w >= 0.5, (n, w)
        if n.startswith("LED_SW") and sexp.q(s, "layer") == "F.Cu" and length(s) > 10.0:
            assert w >= 0.4, (n, w)                                      # the long sink lines: 14 LEDs x 42 mA peak
    for v in sexp.kids(board, "via"):
        assert sexp.kid(v, "size")[1] >= MIN_VIA_D and sexp.kid(v, "drill")[1] >= MIN_VIA_DRILL


def test_led_sink_lines_reach_every_led(drc, keys):
    """Each LED_SW net is one copper island plus the driver pin: every LED cathode is on its line."""
    per = collections.Counter()
    for u in drc["unconnected_items"]:
        descs = [i["description"] for i in u["items"]]
        m = re.search(r"\[(LED_SW\d+)\]", descs[0])
        if m:
            per[m.group(1)] += 1
            assert any("U10" in d for d in descs), descs          # the only gap is at the driver
    assert all(per[f"LED_SW{s}"] <= 1 for s in range(12)), per
