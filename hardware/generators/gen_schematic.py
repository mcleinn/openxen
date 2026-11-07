#!/usr/bin/env python3
"""Generate the openxen-m56 schematic (KiCad 9) from ``layout/module.json`` and HE60.

Proven-design policy: nothing on the controller side is drawn from scratch.
* Controller block (MCU, USB-C, ESD, polyfuse, both LDOs, crystal, BOOT/RESET buttons,
  TC2030, JST): copied verbatim from HE60's schematic (region below the key matrix), then
  patched: MUX_OUT_8/9 become no-connects, PB6/PB7/PC0 get the LED driver labels.
* Sensor cell (sensor + 100 nF + 4.7 nF + power + label): HE60's HE1 cell cloned 56×.
* Mux cell (74LV4051 + decoupling + 8 input labels + output + selects): HE60's AM1 cell
  cloned 7×, inputs relabelled from the mux matrix in module.json.
* LED sheet: generated from the driver datasheet's typical application circuit
  (see hardware/parts.json for values and part numbers).

Output: hardware/kicad/openxen-m56/openxen-m56.kicad_sch (+ .kicad_pro written by
gen_project.py). Every symbol carries an "LCSC Part #" property for Fabrication Toolkit.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sexp  # noqa: E402
from sexp import Quoted as Q, kid, kids, prop  # noqa: E402
import kicad_sch as ks  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "layout" / "module.json").read_text(encoding="utf-8"))
PARTS = json.loads((ROOT / "hardware" / "parts.json").read_text(encoding="utf-8"))
HE60_SCH = ROOT / "reference" / "repos" / "HE60" / "HE60" / "HE60.kicad_sch"
KICAD_SYM = Path(r"C:\Program Files\KiCad\9.0\share\kicad\symbols")
OUT = ROOT / "hardware" / "kicad" / "openxen-m56" / "openxen-m56.kicad_sch"
PROJECT = "openxen-m56"

# Layout of our sheet (mm). HE60 cells are copied with their internal geometry intact.
SENSOR_ORIGIN = (34.29, 35.56)      # first sensor cell anchor (HE1 position maps here); multiples of 1.27 keep pins on grid
SENSOR_PITCH = (35.56, 33.02)       # cell pitch (multiples of 2.54); 8 columns x 7 rows = 56
SENSOR_COLS = 8
MUX_ORIGIN = (45.72, 76.2)
MUX_PITCH = 50.8
CTRL_SHIFT = (0.0, -231.14)         # HE60 controller region (y 262..360) moves to y 31..129 of its own A3 sheet (multiple of 2.54)
LED_ORIGIN = (20.32, 25.4)


def he60_cell_items(doc: list, ref: str, radius: tuple[float, float, float, float]) -> tuple[list, list]:
    """Return (anchor symbol, items) of the HE60 cell around symbol `ref`.

    radius = (left, up, right, down) extents in mm around the anchor's position.
    """
    anchor = [s for s in kids(doc, "symbol") if prop(s, "Reference") == ref][0]
    ax, ay, _ = sexp.at(anchor)
    l, u, r, d = radius
    items = []
    for item in doc:
        if not isinstance(item, list) or not item or item[0] not in ks.ITEM_TAGS:
            continue
        pts = ks._item_points(item)
        if pts and all(ax - l <= x <= ax + r and ay - u <= y <= ay + d for x, y in pts):
            if item[0] == "symbol" and sexp.q(item, "lib_id").startswith("Mechanical:"):
                continue
            items.append(item)
    return anchor, items


def stamp(sheet: ks.Sheet, items: list, dx: float, dy: float, ref_map: dict[str, str], label_map: dict[str, str]) -> None:
    """Clone a list of HE60 items shifted by (dx, dy), renaming references and labels."""
    for item in items:
        new = ks._deepcopy(item)
        if new[0] in ("wire", "bus", "polyline"):
            for p in kids(kid(new, "pts"), "xy"):
                p[1], p[2] = round(float(p[1]) + dx, 4), round(float(p[2]) + dy, 4)
        else:
            a = kid(new, "at")
            a[1], a[2] = round(float(a[1]) + dx, 4), round(float(a[2]) + dy, 4)
        for p in kids(new, "property"):
            pa = kid(p, "at")
            if pa:
                pa[1], pa[2] = round(float(pa[1]) + dx, 4), round(float(pa[2]) + dy, 4)
        u = kid(new, "uuid")
        if u:
            u[1] = ks.new_uuid()
        for p in kids(new, "pin"):
            pu = kid(p, "uuid")
            if pu:
                pu[1] = ks.new_uuid()
        if new[0] == "global_label":
            new[1] = Q(label_map.get(new[1].s, new[1].s))
        if new[0] == "symbol":
            lid = kid(new, "lib_id")
            if lid[1].s.startswith("HE60:"):
                lid[1] = Q(lid[1].s.replace("HE60:", "openxen:"))
            old_ref = prop(new, "Reference")
            ref = ref_map.get(old_ref)
            if ref is None:
                if old_ref.startswith("#PWR"):
                    n = sheet.ref_counter.get("#PWR", 0) + 1
                    sheet.ref_counter["#PWR"] = n
                    ref = f"#PWR{n:03d}"
                else:
                    raise KeyError(f"no new reference for {old_ref}")
            for p in kids(new, "property"):
                if p[1].s == "Reference":
                    p[2] = Q(ref)
            add_lcsc(new)
            inst_node = kid(new, "instances")
            new[new.index(inst_node)] = ["instances", ["project", Q(PROJECT), ["path", Q(sheet.path), ["reference", Q(ref)], ["unit", 1]]]]
        sheet.add_raw(new)


def add_lcsc(sym: list) -> None:
    """Attach the LCSC part number (and our chosen footprint) from parts.json by value."""
    lib_id, value = sexp.q(sym, "lib_id"), prop(sym, "Value")
    if lib_id.startswith("power:") or value in ("PWR_FLAG",):
        return
    bv = PARTS["by_value"]
    if (value in bv and bv[value] is None) or (lib_id in bv and bv[lib_id] is None):
        return  # explicitly no part (mechanical / pads only)
    key = bv.get(value) or bv.get(lib_id)
    if not key:
        print(f"  warning: no part mapping for {lib_id} value={value}")
        return
    part = PARTS["parts"][key]
    for p in kids(sym, "property"):
        if p[1].s == "Footprint" and part.get("footprint"):
            p[2] = Q(part["footprint"])
        if p[1].s == "Value" and part.get("value"):
            p[2] = Q(part["value"])
    x, y, _ = sexp.at(sym)
    sym.append(["property", Q("LCSC Part #"), Q(part["lcsc"]), ["at", x, y, 0], ["effects", ["font", ["size", 1.27, 1.27]], ["hide", "yes"]]])
    if part.get("mpn"):
        sym.append(["property", Q("MPN"), Q(part["mpn"]), ["at", x, y, 0], ["effects", ["font", ["size", 1.27, 1.27]], ["hide", "yes"]]])


def main() -> int:
    he = sexp.loads(HE60_SCH.read_text(encoding="utf-8"))
    libs = ks.LibSymbols()
    libs.add_from_schematic(he)
    libs.add_from_library(KICAD_SYM / "Device.kicad_sym", "Device", ["LED_ARGB", "R", "C"])
    libs.add_from_library(KICAD_SYM / "power.kicad_sym", "power", ["+5V", "+3.3V", "GND"])
    libs.add_from_library(KICAD_SYM / "Connector.kicad_sym", "Connector", ["TestPoint"])
    drv = PARTS["parts"]["led_driver"]
    libs.add_from_library(KICAD_SYM / drv["symbol_lib"], drv["symbol_lib"].split(".")[0], [drv["symbol"]])
    # KiCad stacks duplicate power pins (PGND 12 on 5, GND 49 on 48) as hidden passive pins, which a wire
    # does not connect; make them ordinary visible pins so the bus wire picks them up.
    drv_sym = libs.defs[f"{drv['symbol_lib'].split('.')[0]}:{drv['symbol']}"]
    for unit in kids(drv_sym, "symbol"):
        for pin in kids(unit, "pin"):
            if kid(pin, "name")[1].s in ("PGND", "GND", "PVCC", "AGND") and kid(pin, "hide"):
                pin.remove(kid(pin, "hide"))
    # HE60's embedded symbols become ours (hardware/kicad/lib/openxen.kicad_sym, GPL-3.0, see provenance)
    for old in ("HE60:MT9102ET", "HE60:AT32F405RxT7"):
        d = libs.defs.pop(old)
        d[1] = Q(old.replace("HE60:", "openxen:"))
        libs.defs[old.replace("HE60:", "openxen:")] = d
    root = ks.Sheet(PROJECT, libs, title="openxen-m56 module", comment="56-key Hall-effect hex module; HE60 v2.1 / libhmk derived")
    sub = lambda title, comment: ks.Sheet(PROJECT, libs, parent_path=root.path, title=title, comment=comment)
    sh_ctrl = sub("openxen-m56 - Controller", "AT32F405, USB-C, power, debug: HE60 v2.1 block, verbatim")
    sh_sens = sub("openxen-m56 - Sensors", "56x GH39FKSW linear Hall sensors, one cell per key (HE60 cell)")
    sh_mux = sub("openxen-m56 - Multiplexers", "7x SN74LV4051A, 8 keys each, shared select lines")
    sh_led = sub("openxen-m56 - LED matrix", "IS31FL3733, 56x MHT151RGBCT common-anode RGB (anode->CS, cathodes->SW)")

    # ---- 1. sensor cells (HE60 HE1 cell: sensor, two caps, power symbols, label, wires)
    he1, cell = he60_cell_items(he, "HE1", (15.0, 3.0, 15.0, 11.0))  # x 21.59..46.99, y 74.93..86.36 (next cell starts at 96.52)
    hx, hy, _ = sexp.at(he1)
    cell_refs = sorted({prop(i, "Reference") for i in cell if i[0] == "symbol"})
    caps = [r for r in cell_refs if r.startswith("C")]
    for k in sorted(SPEC["keys"], key=lambda k: k["id"]):
        n = k["id"]
        col, row = n % SENSOR_COLS, n // SENSOR_COLS
        dx = SENSOR_ORIGIN[0] + col * SENSOR_PITCH[0] - hx
        dy = SENSOR_ORIGIN[1] + row * SENSOR_PITCH[1] - hy
        ref_map = {"HE1": f"HE{n}"}
        for i, c in enumerate(caps):
            ref_map[c] = f"C{n}" if i == 0 else f"CF{n}"
        stamp(sh_sens, cell, dx, dy, ref_map, {"HE1": f"HE{n}"})
    sh_sens.text("Sensor cells: HE60 cell (100 nF decoupling, 4.7 nF output filter) x 56. Label HEn = key n (Lumatone .ltn index).", 20.32, 22.86, 2.0)

    # ---- 2. mux cells (HE60 AM2 cell)
    am1, mcell = he60_cell_items(he, "AM2", (14.0, 31.0, 16.0, 25.0))
    mx, my, _ = sexp.at(am1)
    mrefs = sorted({prop(i, "Reference") for i in mcell if i[0] == "symbol"})
    matrix = SPEC["mux"]["libhmk_matrix"]  # [mux input][select channel] -> key id + 1 (libhmk keyboard.json order)
    he_in_by_channel = he60_mux_channel_labels(he, am1, mcell, libs)
    for m in range(7):
        label_map = {"MUX_OUT_2": f"MUX_OUT_{m + 1}"}
        for s_ in range(8):
            kid_ = matrix[m][s_]
            label_map[he_in_by_channel[s_]] = f"HE{kid_ - 1}" if kid_ else f"NC_MUX{m}_{s_}"
        ref_map = {r: (f"AM{m}" if r == "AM2" else f"CM{m}") for r in mrefs if not r.startswith("#")}
        stamp(sh_mux, mcell, MUX_ORIGIN[0] + m * MUX_PITCH - mx, MUX_ORIGIN[1] - my, ref_map, label_map)
    sh_mux.text("Mux m serves keys 8m..8m+7 (channel = key - 8m). Select lines PC1..PC3, outputs MUX_OUT_1..7 -> PA3..PA7, PC4, PC5 (HE60 pins).", 20.32, 22.86, 2.0)

    # ---- 3. controller block: everything of HE60 below y = 262 except key/mux cells, verbatim
    ctrl = ks.clone_region(he, -1000, 262.0, 5000, 5000, CTRL_SHIFT[0], CTRL_SHIFT[1], sh_ctrl,
                           skip_lib_ids=("Mechanical:", "HE60:MT9102ET", "4xxx:4051", "openxen:MT9102ET"))
    for item in ctrl:
        if item[0] == "symbol":
            if prop(item, "Reference") == "J2":  # HE60's JST alternative USB connector: not populated, not on our board
                for flag, val in (("in_bom", "no"), ("on_board", "no"), ("dnp", "yes")):
                    node = kid(item, flag)
                    if node:
                        node[1] = val
            lid = kid(item, "lib_id")
            if lid[1].s.startswith("HE60:"):
                lid[1] = Q(lid[1].s.replace("HE60:", "openxen:"))
            add_lcsc(item)
    sh_ctrl.used_libs = {("openxen:" + l.split(":", 1)[1]) if l.startswith("HE60:") else l for l in sh_ctrl.used_libs}
    patch_controller(sh_ctrl, libs)
    sh_ctrl.text("Copied from HE60 v2.1 (GPL-3.0). Changes: F1 1 A fuse, J2 not populated, PB6/PB7 = LED driver I2C, PC0 = LED_SDB, MUX_OUT_8/9 unused.", 20.32, 22.86, 2.0)
    gen_test_points(sh_ctrl, libs)

    # ---- 4. LED sheet
    gen_led_sheet(sh_led, libs)

    # ---- 5. root sheet with the four sheet symbols
    root.text("openxen-m56: 56-key Hall-effect hex keyboard module. One of five identical modules; each is a USB device.", 20.32, 20.32, 2.0)
    root.text("Sources: layout/module.json (geometry, mux matrix, LED matrix), hardware/parts.json (LCSC parts). Generated by hardware/generators/gen_schematic.py.", 20.32, 24.13, 1.5)
    pages = [(sh_ctrl, "Controller", "controller.kicad_sch"), (sh_sens, "Sensors", "sensors.kicad_sch"),
             (sh_mux, "Multiplexers", "muxes.kicad_sch"), (sh_led, "LED matrix", "leds.kicad_sch")]
    for i, (sh, name, fn) in enumerate(pages):
        root.add_subsheet(sh, name, fn, 25.4 + i * 50.8, 40.64, 38.1, 25.4, i + 2)
        for lid in sh.used_libs:
            if lid not in libs.defs:
                raise RuntimeError(f"{name}: instance without embedded lib symbol: {lid}")
        sh.write(OUT.parent / fn, paper="A3")
    root.write(OUT, paper="A4")
    print(f"wrote {OUT.relative_to(ROOT)} + 4 sub-sheets: ctrl {len(sh_ctrl.items)}, sensors {len(sh_sens.items)}, muxes {len(sh_mux.items)}, leds {len(sh_led.items)} items")
    return 0


def he60_mux_channel_labels(he: list, am1: list, mcell: list, libs: ks.LibSymbols) -> list[str]:
    """Which HE60 label sits on each 4051 input pin X0..X7 of AM1 (by wire tracing one hop)."""
    pins = libs.pin_points(am1)
    names = {num: name for num, name, *_ in libs.pins(sexp.q(am1, "lib_id"))}
    # wire endpoints -> other end
    wires = [(tuple(map(float, (kid(w, "pts")[1][1], kid(w, "pts")[1][2]))), tuple(map(float, (kid(w, "pts")[2][1], kid(w, "pts")[2][2])))) for w in mcell if w[0] == "wire"]
    labels = {(round(sexp.at(g)[0], 2), round(sexp.at(g)[1], 2)): g[1].s for g in mcell if g[0] == "global_label"}
    out = [None] * 8
    for num, (x, y) in pins.items():
        name = names[num]
        if name.startswith("X") and name[1:].isdigit():
            ch = int(name[1:])
            p = (round(x, 2), round(y, 2))
            seen = {p}
            frontier = [p]
            found = None
            while frontier and found is None:
                q_ = frontier.pop()
                if q_ in labels:
                    found = labels[q_]
                    break
                for a, b in wires:
                    a, b = (round(a[0], 2), round(a[1], 2)), (round(b[0], 2), round(b[1], 2))
                    for s, t in ((a, b), (b, a)):
                        if s == q_ and t not in seen:
                            seen.add(t)
                            frontier.append(t)
            out[ch] = found
    if any(o is None for o in out):
        raise RuntimeError(f"could not trace all mux inputs: {out}")
    return out


def patch_controller(sheet: ks.Sheet, libs: ks.LibSymbols) -> None:
    """MUX_OUT_8/9 -> no-connect; PB6/PB7/PC0 no-connects -> LED driver labels."""
    mcu = [i for i in sheet.items if i[0] == "symbol" and "AT32" in sexp.q(i, "lib_id")][0]
    pts = libs.pin_points(mcu)
    names = {num: name for num, name, *_ in libs.pins(sexp.q(mcu, "lib_id"))}
    want = {"PB6": "LED_SCL", "PB7": "LED_SDA", "PC0": "LED_SDB"}
    # remove the no_connect at those pins and add a label
    targets = {names[n]: p for n, p in pts.items() if names[n] in want}
    keep = []
    for item in sheet.items:
        if item[0] == "no_connect":
            x, y, _ = sexp.at(item)
            if any(abs(x - tx) < 0.01 and abs(y - ty) < 0.01 for tx, ty in targets.values()):
                continue
        if item[0] == "global_label" and item[1].s in ("MUX_OUT_8", "MUX_OUT_9"):
            x, y, _ = sexp.at(item)
            keep.append(["no_connect", ["at", x, y], ["uuid", ks.new_uuid()]])
            continue
        keep.append(item)
    sheet.items = keep
    pin_rot = {name: prot for _num, name, _px, _py, prot in libs.pins(sexp.q(mcu, "lib_id"))}
    inst_rot = sexp.at(mcu)[2]
    for pin, label in want.items():
        x, y = targets[pin]
        rot = (pin_rot[pin] + 180 + inst_rot) % 360   # label points away from the body (top pins: 90)
        sheet.glabel(label, x, y, rot, "bidirectional" if label != "LED_SDB" else "output")


TEST_POINTS = ["MUX_OUT_1", "MUX_OUT_2", "MUX_OUT_3", "MUX_OUT_4", "MUX_OUT_5", "MUX_OUT_6", "MUX_OUT_7",
               "MUX_SELECT_0", "MUX_SELECT_1", "MUX_SELECT_2", "+3.3VA", "+3.3V", "+5V", "GND", "LED_SDA", "LED_SCL"]


def gen_test_points(sheet: ks.Sheet, libs: ks.LibSymbols) -> None:
    """DFT: 1 mm test pads on the bottom side for the signals a bring-up needs (TP1..TP16).

    Two rows of eight; the pad symbol is rotated so its pin points left and the net label
    (or power symbol) hangs horizontally off the pin end.
    """
    x0, y0, dx, dy = 60.96, 157.48, 38.1, 12.7
    sheet.text("Test points (bottom side, 1 mm pads, 2.54 mm pitch): mux outputs, select lines, rails, I2C. SWD via J3 (TC2030).", 30.48, y0 - 10.16, 1.5)
    for i, net in enumerate(TEST_POINTS):
        x, y = x0 + (i % 8) * dx, y0 + (i // 8) * dy
        tp = sheet.symbol("Connector:TestPoint", x, y, 270, f"TP{i + 1}", net, "TestPoint:TestPoint_Pad_D1.0mm", hide_value=True)
        kid(tp, "in_bom")[1] = "no"
        px, py = libs.pin_points(tp)["1"]   # the pin's connection point is the symbol origin; the pad circle sits to the right
        ref = next(pr for pr in kids(tp, "property") if pr[1].s == "Reference")
        kid(ref, "at")[1:] = [x + 5.08, y - 1.9, 90]   # property angle is relative to the symbol: 270 + 90 = horizontal, above the pad
        if net in ("+3.3V", "+5V", "+3.3VA", "GND"):   # power symbol standing on / hanging off the wire end
            sheet.wire(px, py, px - 2.54, py)
            sheet.power(f"power:{net}", px - 2.54, py, 0)
        else:
            sheet.glabel(net, px, py, 180, "passive")


def gen_led_sheet(sheet: ks.Sheet, libs: ks.LibSymbols) -> None:
    """IS31FL3733 (12 SW sinks x 16 CS sources) + 56 common-anode RGB, per datasheet Figure 2.

    LED anode -> CSn (current source), cathodes R/G/B -> three SW lines of the LED's group.
    Support parts: 2k I2C pull-ups to 3.3 V, 100k on INTB (to 3.3 V), IICRST and SYNC 100k
    to GND, SDB from the MCU with 100k to GND, ADDR1/ADDR2 to GND, R_EXT 20k to GND,
    VIO = 3.3 V (0.47u + 0.1u), DVCC/AVCC/PVCC = +5V (0.47u + 0.1u each, 22u bulk on PVCC).
    """
    drv = PARTS["parts"]["led_driver"]
    lib_id = f"{drv['symbol_lib'].split('.')[0]}:{drv['symbol']}"
    ox, oy = LED_ORIGIN
    sheet.text("LED matrix (IS31FL3733, datasheet Fig. 2 RGB): anode -> CSx source, cathodes -> SWy sinks. 4 groups x 14 keys.", ox, oy - 7.62, 1.5)
    u = sheet.symbol(lib_id, ox + 50.8, oy + 66.04, 0, "U10", drv["value"], drv["footprint"], {"LCSC Part #": drv["lcsc"], "MPN": drv.get("mpn", "")})
    pts = libs.pin_points(u)
    names = {num: name for num, name, *_ in libs.pins(lib_id)}
    ux, uy = sexp.at(u)[0], sexp.at(u)[1]
    gnd_pins, p5_pins = [], []
    for num, (x, y) in pts.items():
        name = names[num].replace("~{", "").replace("}", "").upper()
        side = 0 if x > ux else 180
        if name.startswith("SW") and name[2:].isdigit():
            sheet.glabel(f"LED_SW{int(name[2:]) - 1}", x, y, side, "input")
        elif name.startswith("CS") and name[2:].isdigit():
            if int(name[2:]) - 1 < SPEC["led"]["cs_used"]:
                sheet.glabel(f"LED_CS{int(name[2:]) - 1}", x, y, side, "output")
            else:
                sheet.no_connect(x, y)
        elif name == "SDA":
            sheet.glabel("LED_SDA", x, y, side, "bidirectional")
        elif name == "SCL":
            sheet.glabel("LED_SCL", x, y, side, "input")
        elif name == "SDB":
            sheet.glabel("LED_SDB", x, y, side, "input")
        elif name == "INTB":
            sheet.glabel("LED_INTB", x, y, side, "output")
        elif name in ("IICRST", "SYNC"):
            sheet.glabel(f"LED_{name}", x, y, side, "input")
        elif name in ("ADDR1", "ADDR2"):
            gnd_pins.append((x, y))  # I2C address 0: both to GND (datasheet Fig. 2)
        elif name in ("RSET", "R_EXT", "REXT"):
            sheet.glabel("LED_REXT", x, y, side, "passive")
        elif name == "VIO":
            dx = 5.08 if x > ux else -5.08
            sheet.power("power:+3.3V", x + dx, y, 90 if dx < 0 else 270)
            sheet.wire(x, y, x + dx, y)
        elif name in ("GND", "AGND", "PGND", "EP"):
            gnd_pins.append((x, y))
        elif name in ("PVCC", "AVCC", "DVCC", "VCC"):
            p5_pins.append((x, y, name))
        else:  # NC and anything unexpected
            sheet.no_connect(x, y)
    # Pins on the left/right columns sit 2.54 mm apart, so power symbols go outward horizontally;
    # top/bottom pins get them vertically.
    def bus_power(pins: list[tuple[float, float]], lib: str, below: bool) -> None:
        """Join pins of one power net with a bus drawn as end-to-end segments (one per pin pair,
        junction at every shared endpoint) and a single power symbol at one end."""
        pins = sorted(set(pins))
        side = [(x, y) for x, y in pins if abs(x - ux) > abs(y - uy)]
        vert = sorted((x, y) for x, y in pins if (x, y) not in side)
        for left in (True, False):
            grp = sorted(((x, y) for x, y in side if (x < ux) == left), key=lambda p: p[1])
            if not grp:
                continue
            dx = -5.08 if left else 5.08
            xb = grp[0][0] + dx
            for x, y in grp:
                sheet.wire(x, y, xb, y)
            for (x1, y1), (x2, y2) in zip(grp, grp[1:]):
                sheet.wire(xb, y1, xb, y2)
            for x, y in grp[1:-1]:
                sheet.junction(xb, y)
            end_y = grp[-1][1] if below else grp[0][1]
            sheet.wire(xb, end_y, xb, end_y + (2.54 if below else -2.54))
            sheet.power(lib, xb, end_y + (2.54 if below else -2.54), 0)
            if len(grp) > 1:
                sheet.junction(xb, end_y)
        if not vert:
            return
        dy = 2.54 if below else -2.54
        yb = vert[0][1] + dy
        for x, y in vert:
            sheet.wire(x, y, x, yb)
        for (x1, _), (x2, _) in zip(vert, vert[1:]):
            sheet.wire(x1, yb, x2, yb)
        for x, _ in vert[1:-1]:
            sheet.junction(x, yb)
        xm = vert[0][0]
        sheet.wire(xm, yb, xm, yb + dy)
        sheet.power(lib, xm, yb + dy, 0)
        if len(vert) > 1:
            sheet.junction(xm, yb)
    bus_power(gnd_pins, "power:GND", below=True)
    bus_power([(x, y) for x, y, _ in p5_pins], "power:+5V", below=False)

    def two_terminal(ref: str, part_key: str, x: float, y: float, top: str, bottom: str, lib: str = "Device:R") -> None:
        part = PARTS["parts"][part_key]
        r = sheet.symbol(lib, x, y, 0, ref, part["value"], part["footprint"], {"LCSC Part #": part["lcsc"]})
        p = libs.pin_points(r)
        (x1, y1), (x2, y2) = p["1"], p["2"]
        top_pt, bot_pt = ((x1, y1), (x2, y2)) if y1 < y2 else ((x2, y2), (x1, y1))
        for pt, net in ((top_pt, top), (bot_pt, bottom)):
            if net == "GND":
                sheet.power("power:GND", pt[0], pt[1] + 2.54, 0)
                sheet.wire(pt[0], pt[1], pt[0], pt[1] + 2.54)
            elif net in ("+3.3V", "+5V"):
                sheet.power(f"power:{net}", pt[0], pt[1] - 2.54, 0)
                sheet.wire(pt[0], pt[1], pt[0], pt[1] - 2.54)
            else:
                sheet.glabel(net, pt[0], pt[1], 90 if pt == top_pt else 270, "passive")

    sx, sy = ox + 10.16, oy + 157.48
    col = 0
    def nxt() -> float:
        nonlocal col
        col += 1
        return sx + (col - 1) * 12.7
    two_terminal("R10", "r_20k", nxt(), sy, "LED_REXT", "GND")
    two_terminal("R11", "r_2k", nxt(), sy, "+3.3V", "LED_SDA")
    two_terminal("R12", "r_2k", nxt(), sy, "+3.3V", "LED_SCL")
    two_terminal("R13", "r_100k", nxt(), sy, "+3.3V", "LED_INTB")
    two_terminal("R14", "r_100k", nxt(), sy, "LED_IICRST", "GND")
    two_terminal("R15", "r_100k", nxt(), sy, "LED_SYNC", "GND")
    two_terminal("R16", "r_100k", nxt(), sy, "LED_SDB", "GND")
    cy = sy + 30.48
    col = 0
    two_terminal("C210", "c_470n", nxt(), cy, "+3.3V", "GND", "Device:C")   # VIO
    two_terminal("C211", "c_100n", nxt(), cy, "+3.3V", "GND", "Device:C")
    for i, key in enumerate(("c_470n", "c_100n", "c_470n", "c_100n", "c_470n", "c_100n", "c_22u")):
        two_terminal(f"C{212 + i}", key, nxt(), cy, "+5V", "GND", "Device:C")  # DVCC, AVCC, PVCC + bulk
    sheet.text("C210/C211: VIO. C212-C217: DVCC, AVCC, PVCC (0.47u + 0.1u each, at the pins). C218: PVCC bulk 22u.", sx, cy + 12.7, 1.2)

    # LEDs: 56 common-anode RGB (Device:LED_ARGB: 1=A, 2=RK, 3=GK, 4=BK)
    led = PARTS["parts"]["led_rgb"]
    L = SPEC["led"]
    cols = 7
    for k in sorted(SPEC["keys"], key=lambda k: k["id"]):
        n = k["id"]
        c_, r_ = n % cols, n // cols
        x, y = ox + 142.24 + c_ * 38.1, oy + 25.4 + r_ * 27.94
        d = sheet.symbol("Device:LED_ARGB", x, y, 0, f"D{n}", led["value"], led["footprint"], {"LCSC Part #": led["lcsc"]}, hide_value=True)
        for pr in kids(d, "property"):
            if pr[1].s == "Reference":
                kid(pr, "at")[1], kid(pr, "at")[2] = x, y - 9.65   # body top is y - 7.62
        p = libs.pin_points(d)
        grp, cs = L["key_group"][str(n)], L["key_cs"][str(n)]
        ax, ay = p["1"]
        sheet.glabel(f"LED_CS{cs}", ax, ay, 0, "input")
        for pin, colour in (("2", "R"), ("3", "G"), ("4", "B")):
            px, py = p[pin]
            sheet.glabel(f"LED_SW{L['sw_lines'][str(grp)][colour]}", px, py, 180, "output")
    # unused driver outputs: CS14, CS15 stay as single labels (ERC: flag as intentional via no-connect labels)


if __name__ == "__main__":
    sys.exit(main())
