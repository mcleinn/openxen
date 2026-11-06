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
SENSOR_ORIGIN = (34.29, 30.48)      # first sensor cell anchor (HE1 position maps here); multiples of 1.27 keep pins on grid
SENSOR_PITCH = (35.56, 33.02)       # cell pitch (multiples of 2.54); 8 columns x 7 rows = 56
SENSOR_COLS = 8
MUX_ORIGIN = (45.72, 279.4)
MUX_PITCH = 50.8
CTRL_SHIFT = (0.0, 60.96)           # HE60 controller region (y 262..360) moves to y 323..421, below the mux row (multiple of 2.54)
LED_ORIGIN = (419.1, 30.48)


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
            new[new.index(inst_node)] = ["instances", ["project", Q(PROJECT), ["path", Q("/" + sheet.root_uuid.s), ["reference", Q(ref)], ["unit", 1]]]]
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
    drv = PARTS["parts"]["led_driver"]
    libs.add_from_library(KICAD_SYM / drv["symbol_lib"], drv["symbol_lib"].split(".")[0], [drv["symbol"]])
    # HE60's embedded symbols become ours (hardware/kicad/lib/openxen.kicad_sym, GPL-3.0, see provenance)
    for old in ("HE60:MT9102ET", "HE60:AT32F405RxT7"):
        d = libs.defs.pop(old)
        d[1] = Q(old.replace("HE60:", "openxen:"))
        libs.defs[old.replace("HE60:", "openxen:")] = d
    sheet = ks.Sheet(PROJECT, libs)

    # ---- 1. sensor cells (HE60 HE1 cell: sensor, two caps, power symbols, label, wires)
    he1, cell = he60_cell_items(he, "HE1", (15.0, 3.0, 15.0, 11.0))  # x 21.59..46.99, y 74.93..86.36 (next cell starts at 96.52)
    hx, hy, _ = sexp.at(he1)
    cell_refs = sorted({prop(i, "Reference") for i in cell if i[0] == "symbol"})
    print("HE1 cell symbols:", cell_refs, "items:", len(cell))
    caps = [r for r in cell_refs if r.startswith("C")]
    for k in sorted(SPEC["keys"], key=lambda k: k["id"]):
        n = k["id"]
        col, row = n % SENSOR_COLS, n // SENSOR_COLS
        dx = SENSOR_ORIGIN[0] + col * SENSOR_PITCH[0] - hx
        dy = SENSOR_ORIGIN[1] + row * SENSOR_PITCH[1] - hy
        ref_map = {"HE1": f"HE{n}"}
        for i, c in enumerate(caps):
            ref_map[c] = f"C{n}" if i == 0 else f"CF{n}"
        stamp(sheet, cell, dx, dy, ref_map, {"HE1": f"HE{n}"})

    # ---- 2. mux cells (HE60 AM1 cell)
    am1, mcell = he60_cell_items(he, "AM2", (14.0, 31.0, 16.0, 25.0))  # AM2: all 8 inputs labelled; x -12.7..12.7 plus VCC cap at -10.16, y -30.48..24.13
    mx, my, _ = sexp.at(am1)
    mrefs = sorted({prop(i, "Reference") for i in mcell if i[0] == "symbol"})
    mlabels = sorted({i[1].s for i in mcell if i[0] == "global_label"})
    print("AM2 cell symbols:", mrefs, "labels:", mlabels)
    he_in = [l for l in mlabels if l.startswith("HE")]
    matrix = SPEC["mux"]["libhmk_matrix"]  # [select][input] -> key id + 1
    for m in range(7):
        label_map = {"MUX_OUT_2": f"MUX_OUT_{m + 1}"}
        # HE60's AM1 inputs HEa..HEh correspond to mux channels 0..7 in label order;
        # we map channel s -> key id from our matrix column m.
        he_in_by_channel = he60_mux_channel_labels(he, am1, mcell, libs)
        for s in range(8):
            kid_ = matrix[s][m]
            label_map[he_in_by_channel[s]] = f"HE{kid_ - 1}" if kid_ else f"NC_MUX{m}_{s}"
        ref_map = {r: (f"AM{m}" if r == "AM2" else f"CM{m}") for r in mrefs if not r.startswith("#")}
        stamp(sheet, mcell, MUX_ORIGIN[0] + m * MUX_PITCH - mx, MUX_ORIGIN[1] - my, ref_map, label_map)

    # ---- 3. controller block: everything of HE60 below y = 240 except key/mux cells
    ctrl = ks.clone_region(he, -1000, 262.0, 5000, 5000, CTRL_SHIFT[0], CTRL_SHIFT[1], sheet,
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
    sheet.used_libs = {("openxen:" + l.split(":", 1)[1]) if l.startswith("HE60:") else l for l in sheet.used_libs}
    patch_controller(sheet, libs)
    missing = [l for l in sheet.used_libs if l not in libs.defs]
    if missing:
        raise RuntimeError(f"instances without embedded lib symbol: {missing}")
    print("controller items copied:", len(ctrl))

    # ---- 4. LED sheet
    gen_led_sheet(sheet, libs)

    sheet.write(OUT, paper="A1")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(sheet.items)} items")
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
    for pin, label in want.items():
        x, y = targets[pin]
        rot = 0 if x > sexp.at(mcu)[0] else 180
        sheet.glabel(label, x, y, rot, "bidirectional" if label != "LED_SDB" else "output")


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
    u = sheet.symbol(lib_id, ox + 50.8, oy + 81.28, 0, "U10", drv["value"], drv["footprint"], {"LCSC Part #": drv["lcsc"], "MPN": drv.get("mpn", "")})
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
            dx = 2.54 if x > ux else -2.54
            sheet.power("power:+3.3V", x + dx, y, 270 if dx > 0 else 90)
            sheet.wire(x, y, x + dx, y)
        elif name in ("GND", "AGND", "PGND", "EP"):
            gnd_pins.append((x, y))
        elif name in ("PVCC", "AVCC", "DVCC", "VCC"):
            p5_pins.append((x, y, name))
        else:  # NC and anything unexpected
            sheet.no_connect(x, y)
    # Pins on the left/right columns sit 2.54 mm apart, so power symbols go outward horizontally;
    # top/bottom pins get them vertically.
    for x, y in gnd_pins:
        if abs(x - ux) > abs(y - uy):      # side pin
            dx = 2.54 if x > ux else -2.54
            sheet.power("power:GND", x + dx, y, 0)
            sheet.wire(x, y, x + dx, y)
        else:
            dy = 2.54 if y >= uy else -2.54
            sheet.power("power:GND", x, y + dy, 0 if dy > 0 else 180)
            sheet.wire(x, y, x, y + dy)
    for x, y, name in p5_pins:
        if abs(x - ux) > abs(y - uy):
            dx = 2.54 if x > ux else -2.54
            sheet.power("power:+5V", x + dx, y, 0)
            sheet.wire(x, y, x + dx, y)
        else:
            sheet.power("power:+5V", x, y - 2.54, 0)
            sheet.wire(x, y, x, y - 2.54)

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

    sx, sy = ox + 111.76, oy + 15.24
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
    cols = 8
    for k in sorted(SPEC["keys"], key=lambda k: k["id"]):
        n = k["id"]
        c_, r_ = n % cols, n // cols
        x, y = ox + c_ * 30.48, oy + 152.4 + r_ * 27.94
        d = sheet.symbol("Device:LED_ARGB", x, y, 0, f"D{n}", led["value"], led["footprint"], {"LCSC Part #": led["lcsc"]})
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
