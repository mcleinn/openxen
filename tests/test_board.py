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


FANOUT_R = 9.5     # route_led_driver.py: U10's scripted fan-out stays within this radius


def near_driver(pos: dict, footprints) -> bool:
    x, y, _ = at(footprints["U10"])
    return ((pos["x"] - x) ** 2 + (pos["y"] - y) ** 2) ** 0.5 < FANOUT_R


def test_drc_warnings_known(drc, footprints):
    """Only known warning kinds: the 1 mm LED anode stubs awaiting their lines, the sink lines'
    open end toward the driver, the sensor escape vias awaiting the fan-in, the LED driver's
    fan-out vias awaiting their lines, and HE60's USB-C silk touching the board edge."""
    for v in drc["violations"]:
        if v["severity"] != "warning":
            continue
        if v["type"] == "track_dangling":
            d = v["items"][0]["description"]
            # LED anode stubs (B.Cu, 1 mm) and the sink lines' open end toward the driver (F.Cu)
            assert re.search(r"\[LED_CS\d+\] on B\.Cu, length 1[,.]0000 mm", d) or re.search(r"\[LED_SW\d+\] on F\.Cu", d), d
        elif v["type"] == "via_dangling":
            # sensor-output escape vias (route_cell.py) wait for the fan-in on F.Cu
            # and U10's fan-out vias (route_led_driver.py) wait for their lines
            it = v["items"][0]
            assert re.search(r"Via \[HE\d+\]", it["description"]) or near_driver(it["pos"], footprints), it["description"]
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


def test_fully_routed_when_routes_stored(drc):
    """Once autorouted tracks are stored (hardware/routes), the board must be complete."""
    from pathlib import Path
    routes = Path(__file__).resolve().parents[1] / "hardware" / "routes" / "openxen-m56.routes.json"
    import os
    if not routes.exists() or os.environ.get("OPENXEN_NO_ROUTES"):
        pytest.skip("no stored routes, or an unrouted build (build_board.py --no-routes)")
    assert drc["unconnected_items"] == [], [[i["description"] for i in u["items"]] for u in drc["unconnected_items"][:5]]


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


def test_track_and_via_sizes(board, board_nets, footprints):
    ux, uy, _ = at(footprints["U10"])

    def at_driver(seg) -> bool:
        """Pad escapes of U10 (0.4 mm pitch QFN): 0.2 mm is the widest track that fits."""
        return all(((p[1] - ux) ** 2 + (p[2] - uy) ** 2) ** 0.5 < FANOUT_R for p in (sexp.kid(seg, "start"), sexp.kid(seg, "end")))

    def name(item):
        v = sexp.kid(item, "net")[1]
        return board_nets.get(v, getattr(v, "s", v))
    for s in sexp.kids(board, "segment"):
        w, n = sexp.kid(s, "width")[1], name(s)
        assert w >= MIN_TRACK - 1e-9, (n, w)
        if n == "VBUS":
            # the whole module (~1 A): scripted at 0.8 mm (route_vbus.py); short neck-downs into
            # the USB-C pads only
            assert w >= 0.5 or length(s) < 2.5, (n, w, length(s))
        if n == "+5V":
            # IPC-2221, 1 oz outer layer, 10 K rise: 0.2 mm carries ~0.74 A. The long thin +5V
            # runs are the LED driver branch, capped at 600 mA by the firmware
            # (OXL_BUDGET_MAX_MA, test_led.py); widen_power.py widens wherever there is room
            assert w >= 0.2 - 1e-9, (n, w, length(s))
        if n.startswith("LED_SW") and sexp.q(s, "layer") == "F.Cu" and length(s) > 10.0 and sexp.kid(s, "locked"):
            # the scripted sink lines (route_led_sw.py, locked): 14 LEDs x 42 mA peak
            assert w >= 0.4, (n, w)
        # the router's links from a sink line to U10's fan-out (unlocked) are >= MIN_TRACK:
        # 588 mA peak at 1/12 duty is below the ~0.74 A of 0.2 mm (IPC-2221, 1 oz outer, 10 K)
    for v in sexp.kids(board, "via"):
        assert sexp.kid(v, "size")[1] >= MIN_VIA_D and sexp.kid(v, "drill")[1] >= MIN_VIA_DRILL


def test_led_sink_lines_reach_every_led(drc, keys, footprints):
    """Each LED_SW net is one copper island plus the driver pin (or its fan-out): every LED
    cathode is on its line."""
    per = collections.Counter()
    for u in drc["unconnected_items"]:
        descs = [i["description"] for i in u["items"]]
        m = re.search(r"\[(LED_SW\d+)\]", descs[0])
        if m:
            per[m.group(1)] += 1
            assert any("U10" in d for d in descs) or any(near_driver(i["pos"], footprints) for i in u["items"]), descs  # the only gap is at the driver
    assert all(per[f"LED_SW{s}"] <= 1 for s in range(12)), per


def _num(pad) -> str:
    return str(getattr(pad[1], "s", pad[1]))


def _pad_net(pad, board_nets):
    n = sexp.kid(pad, "net")
    if n is None:
        return None
    v = n[2] if len(n) > 2 else board_nets.get(n[1], n[1])
    return getattr(v, "s", v)


def test_led_pads_follow_datasheet_pinout(footprints, board_nets, spec, keys):
    """MHT151RGBCT: the anode pad's close neighbour must carry the blue line, the pad across
    the hole the red line, the diagonal one green (datasheet pad pattern, facts.py). Catches
    a footprint whose pad numbers do not match the part's pins."""
    from facts import MHT151_NEIGHBOUR_OF_ANODE
    L = spec["led"]
    for n in keys:
        fp = footprints[f"D{n}"]
        pads = {_num(p): p for p in sexp.kids(fp, "pad") if _num(p) in ("1", "2", "3", "4")}
        pos = {k: sexp.kid(p, "at")[1:3] for k, p in pads.items()}
        assert _pad_net(pads["1"], board_nets) == f"LED_CS{L['key_cs'][str(n)]}", n
        ax, ay = pos["1"]
        for k in ("2", "3", "4"):
            dx, dy = abs(pos[k][0] - ax), abs(pos[k][1] - ay)
            rel = "near" if dx < 0.5 else "across" if dy < 0.5 else "diagonal"
            col = MHT151_NEIGHBOUR_OF_ANODE[rel]
            want = f"LED_SW{L['sw_lines'][str(L['key_group'][str(n)])][col]}"
            assert _pad_net(pads[k], board_nets) == want, (n, k, rel, col)


def test_sensor_pin_one_geometry(footprints):
    """SOT-23: pads 1 (VDD) and 2 (OUT) on one side, pad 3 (GND) alone on the other."""
    for ref, fp in footprints.items():
        if not re.fullmatch(r"HE\d+", ref):
            continue
        pos = {_num(p): sexp.kid(p, "at")[1:3] for p in sexp.kids(fp, "pad")}
        assert pos["1"][0] == pytest.approx(pos["2"][0]) and abs(pos["3"][0] - pos["1"][0]) > 1.5, ref
