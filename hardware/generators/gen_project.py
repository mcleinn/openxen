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
    if not pro.exists():
        pro.write_text(json.dumps({
            "board": {"design_settings": {"defaults": {}, "rules": {}}, "layer_presets": [], "viewports": []},
            "boards": [], "cvpcb": {"equivalence_files": []}, "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
            "meta": {"filename": "openxen-m56.kicad_pro", "version": 3},
            "net_settings": {"classes": [{"name": "Default", "clearance": 0.2, "track_width": 0.25, "via_diameter": 0.6, "via_drill": 0.3, "diff_pair_width": 0.2, "diff_pair_gap": 0.25, "microvia_diameter": 0.3, "microvia_drill": 0.1, "bus_width": 12, "wire_width": 6, "line_style": 0, "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)"}], "meta": {"version": 4}, "net_colors": None, "netclass_assignments": None, "netclass_patterns": []},
            "pcbnew": {"last_paths": {}, "page_layout_descr_file": ""},
            "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
            "sheets": [], "text_variables": {}
        }, indent=2), encoding="utf-8")
    print("wrote tables and project in", PRJ_DIR)


if __name__ == "__main__":
    write_symbol_lib()
    write_tables()
