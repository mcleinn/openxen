#!/usr/bin/env python3
"""Write the KiCad project scaffolding for openxen-m56:

* hardware/kicad/lib/openxen.kicad_sym — our symbol library: MT9102ET and AT32F405RxT7 copied
  from HE60's schematic (GPL-3.0, see docs/provenance.md)
* hardware/kicad/openxen-m56/sym-lib-table and fp-lib-table — project library tables
* hardware/kicad/openxen-m56/openxen-m56.kicad_pro — minimal project file (KiCad fills the rest)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sexp  # noqa: E402
from sexp import Quoted as Q, kid, kids  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
HE60_SCH = ROOT / "reference" / "repos" / "HE60" / "HE60" / "HE60.kicad_sch"
LIB_DIR = ROOT / "hardware" / "kicad" / "lib"
PRJ_DIR = ROOT / "hardware" / "kicad" / "openxen-m56"
SYMBOLS = ["MT9102ET", "AT32F405RxT7"]


def write_symbol_lib() -> None:
    he = sexp.loads(HE60_SCH.read_text(encoding="utf-8"))
    ls = kid(he, "lib_symbols")
    out = ["kicad_symbol_lib", ["version", 20241209], ["generator", Q("openxen")], ["generator_version", Q("0.1")]]
    for s in kids(ls, "symbol"):
        if s[1].s in [f"HE60:{n}" for n in SYMBOLS]:
            d = [x for x in s]
            d[1] = Q(s[1].s.split(":", 1)[1])
            out.append(d)
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    (LIB_DIR / "openxen.kicad_sym").write_text(sexp.dumps(out) + "\n", encoding="utf-8")
    print("wrote", LIB_DIR / "openxen.kicad_sym")


def write_tables() -> None:
    PRJ_DIR.mkdir(parents=True, exist_ok=True)
    (PRJ_DIR / "sym-lib-table").write_text(
        '(sym_lib_table\n  (version 7)\n  (lib (name "openxen")(type "KiCad")(uri "${KIPRJMOD}/../lib/openxen.kicad_sym")(options "")(descr "openxen symbols (HE60-derived, GPL-3.0)"))\n)\n', encoding="utf-8")
    (PRJ_DIR / "fp-lib-table").write_text(
        '(fp_lib_table\n  (version 7)\n  (lib (name "openxen")(type "KiCad")(uri "${KIPRJMOD}/../lib/openxen.pretty")(options "")(descr "openxen footprints"))\n)\n', encoding="utf-8")
    pro = PRJ_DIR / "openxen-m56.kicad_pro"
    data = json.loads(pro.read_text(encoding="utf-8")) if pro.exists() else {
        "board": {"design_settings": {"defaults": {}, "rules": {}}, "layer_presets": [], "viewports": []},
        "boards": [], "cvpcb": {"equivalence_files": []}, "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": "openxen-m56.kicad_pro", "version": 3},
        "pcbnew": {"last_paths": {}, "page_layout_descr_file": ""},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [], "text_variables": {}}
    def cls(name, w, clr=0.2, via=0.6, drill=0.3, dpw=None, dpg=None):
        # KiCad 9 (net_settings version 4) ignores a class without "priority" / "diff_pair_via_gap":
        # Default has the lowest priority (INT_MAX), the others take their list position.
        return {"name": name, "priority": 2147483647 if name == "Default" else len(classes), "clearance": clr, "track_width": w,
                "via_diameter": via, "via_drill": drill,
                "diff_pair_width": dpw or w, "diff_pair_gap": dpg or 0.2, "diff_pair_via_gap": 0.25, "microvia_diameter": 0.3, "microvia_drill": 0.1,
                "bus_width": 12, "wire_width": 6, "line_style": 0, "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)"}
    # Widths from the current budget (hardware/README.md "Net classes"):
    classes: list = []
    # 0.2 mm where tracks must reach the IS31FL3733's 0.4 mm-pitch QFN pads (0.2 wide):
    # 0.4 - 0.2/2 - 0.2/2 = 0.2 mm clearance; anything wider cannot enter those pads.
    classes.append(cls("Default", 0.2))                       # digital: I2C, selects, SWD, mux outputs
    classes.append(cls("Analog", 0.25))                       # HEn sensor outputs: keep short, over the GND plane
    classes.append(cls("Power5V", 0.8, via=0.8, drill=0.4))   # VBUS/+5V: up to ~0.9 A (sensors via LDO + LED matrix)
    classes.append(cls("Power3V3", 0.5, via=0.6, drill=0.3))  # +3.3V and +3.3VA feeders (pours carry the bulk)
    classes.append(cls("LED_SW", 0.2, via=0.6, drill=0.3))    # sink fan-in to the QFN (the scripted lines are 0.4, route_led_sw.py)
    classes.append(cls("LED_CS", 0.2))                        # IS31FL3733 sources: one LED, <= 42 mA peak
    classes.append(cls("USB", 0.25, dpw=0.25, dpg=0.2))       # HE60 geometry copied; short run
    classes.append(cls("Plane", 0.5, via=0.6, drill=0.3))     # GND / +3.3VA: inner planes, pads reach them by via (add_plane_vias.py); autorouter ignores them
    patterns = [{"pattern": "HE*", "netclass": "Analog"}, {"pattern": "/HE*", "netclass": "Analog"},
                {"pattern": "+5V", "netclass": "Power5V"}, {"pattern": "VBUS", "netclass": "Power5V"},
                {"pattern": "+3.3V", "netclass": "Power3V3"}, {"pattern": "+3.3VA", "netclass": "Plane"}, {"pattern": "GND", "netclass": "Plane"},
                {"pattern": "LED_SW*", "netclass": "LED_SW"}, {"pattern": "LED_CS*", "netclass": "LED_CS"},
                {"pattern": "USB_*", "netclass": "USB"}]
    data["net_settings"] = {"classes": classes, "meta": {"version": 4}, "net_colors": None, "netclass_assignments": None, "netclass_patterns": patterns}
    ds = data.setdefault("board", {}).setdefault("design_settings", {})
    ds["rules"] = {"min_clearance": 0.15, "min_track_width": 0.15, "min_via_diameter": 0.5, "min_via_annular_width": 0.1,
                   "min_through_hole_diameter": 0.3, "min_hole_clearance": 0.2, "min_copper_edge_clearance": 0.25,
                   "min_hole_to_hole": 0.5, "solder_mask_clearance": 0.0, "solder_mask_min_width": 0.0}
    pro.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("wrote tables and project in", PRJ_DIR)


if __name__ == "__main__":
    write_symbol_lib()
    write_tables()
