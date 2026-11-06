#!/usr/bin/env python3
"""Build ``layout/module.json`` — the single source of truth for the openxen module.

Inputs
* nominal hex grid (19.2 mm pitch, 9.6 mm stagger) with the Lumatone key order used by
  xentool (`LTN_BOARD0_TUPLES` in C:\\Dev-Free\\xentool\\src\\geometry.rs)
* ``layout/source/freexen_extract.json`` (run ``extract_freexen.py`` first) for the proven
  outline polygon, the mounting holes and a cross-check of every key centre

Conventions: millimetres, origin at the module's top-left corner, x right, y down
(KiCad board convention). Key ``id`` is the Lumatone/.ltn index 0..55.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXTRACT = ROOT / "layout" / "source" / "freexen_extract.json"
OUT = ROOT / "layout" / "module.json"

PITCH = 19.2          # key pitch within a row and between rows
STAGGER = PITCH / 2   # half-key offset of alternate rows
KEY_TOL = 0.3         # max allowed deviation nominal vs freexen board (mm)

# Lumatone board 0 in xentool's doubled-y hex coordinates: (id, row, doubled_col).
LTN_BOARD0 = [
    (0, 0, 0), (1, 0, 2),
    (2, 1, 1), (3, 1, 3), (4, 1, 5), (5, 1, 7), (6, 1, 9),
    (7, 2, 0), (8, 2, 2), (9, 2, 4), (10, 2, 6), (11, 2, 8), (12, 2, 10),
    (13, 3, 1), (14, 3, 3), (15, 3, 5), (16, 3, 7), (17, 3, 9), (18, 3, 11),
    (19, 4, 0), (20, 4, 2), (21, 4, 4), (22, 4, 6), (23, 4, 8), (24, 4, 10),
    (25, 5, 1), (26, 5, 3), (27, 5, 5), (28, 5, 7), (29, 5, 9), (30, 5, 11),
    (31, 6, 0), (32, 6, 2), (33, 6, 4), (34, 6, 6), (35, 6, 8), (36, 6, 10),
    (37, 7, 1), (38, 7, 3), (39, 7, 5), (40, 7, 7), (41, 7, 9), (42, 7, 11),
    (43, 8, 0), (44, 8, 2), (45, 8, 4), (46, 8, 6), (47, 8, 8), (48, 8, 10),
    (49, 9, 3), (50, 9, 5), (51, 9, 7), (52, 9, 9), (53, 9, 11),
    (54, 10, 8), (55, 10, 10),
]

# Per-key unit cell (relative to the switch centre, x right, y down => -y is "north").
UNIT_CELL = {
    "switch": {"footprint": "openxen:SW_Lekker_1u", "plate_cutout_mm": 14.0,
               "guide_holes": [{"x": -5.08, "y": 0.0, "d": 1.75}, {"x": 5.08, "y": 0.0, "d": 1.75}],
               "notes": "Lekker Tikken: no centre post, no metal pins; verified on photos docs/input/lekker-2.jpg"},
    "sensor": {"part": "MT9102ET", "package": "SOT-23", "layer": "B.Cu", "x": 0.0, "y": 0.0, "rot": -90,
               "notes": "centred under the stem magnet, as HE60 and Wooting 60HE; rotation as HE60 (sensing face up through the PCB)"},
    "led": {"part": "SK6812MINI-E (variant A) / reverse-mount RGB (variant B)", "layer": "B.Cu",
            "x": 0.0, "y": -4.9, "cutout_w": 3.7, "cutout_h": 3.0,
            "notes": "reverse-mount in a PCB cutout under the Tikken's north lens (MX LED position 5.08 mm north; Wooting photo ~4.7 mm). Cutout per SK6812MINI-E datasheet 'Recommended dimensions for PCB' — confirm before layout"},
    "passives": [
        {"ref": "C_dec", "value": "100n", "package": "0402", "net": "+3V3A", "notes": "sensor decoupling, within 2 mm of the sensor VDD pin"},
        {"ref": "C_out", "value": "4n7", "package": "0402", "net": "sensor OUT -> GND", "notes": "as HE60; keep at the sensor"},
    ],
}

# Controller zone: housing-free strip at the top right (and its mirror at the bottom left).
CONTROLLER_ZONES = [
    {"name": "top-right", "x0": 40.0, "y0": 1.0, "x1": 114.0, "y1": 20.5, "preferred": True,
     "keepouts": [{"x": 105.6, "y": 19.2, "r": 3.6, "why": "M3 mounting hole H"}],
     "notes": "where freexen's IDC header and power terminal sat; USB-C exits the top edge into the case bay"},
    {"name": "bottom-left", "x0": 10.8, "y0": 190.7, "x1": 84.8, "y1": 210.2, "preferred": False,
     "keepouts": [{"x": 19.2, "y": 192.0, "r": 3.6, "why": "M3 mounting hole"}],
     "notes": "mirror strip; spare"},
]

# libhmk analog mux configuration (HE60 pins kept; 7 of the 9 inputs used).
MUX = {
    "select_pins": ["C1", "C2", "C3"],
    "input_pins": ["A3", "A4", "A5", "A6", "A7", "C4", "C5"],
    "mux_part": "SN74LV4051A",
}


def nominal_xy(row: int, dcol: int) -> tuple[float, float]:
    return STAGGER + dcol * STAGGER, STAGGER + row * PITCH


def assign_muxes(keys: list[dict]) -> None:
    """Group keys into 7 spatially compact octets, 8 keys each (row-major chunks)."""
    order = sorted(keys, key=lambda k: (k["y"], k["x"]))
    for i, k in enumerate(order):
        k["mux"] = i // 8
        k["mux_channel"] = i % 8


def main() -> int:
    ext = json.loads(EXTRACT.read_text(encoding="utf-8"))
    keys = []
    worst = 0.0
    for kid, row, dcol in LTN_BOARD0:
        x, y = nominal_xy(row, dcol)
        near = min(ext["keys"], key=lambda k: (k["x"] - x) ** 2 + (k["y"] - y) ** 2)
        dev = math.hypot(near["x"] - x, near["y"] - y)
        worst = max(worst, dev)
        if dev > KEY_TOL:
            print(f"ERROR key {kid} nominal ({x:.2f},{y:.2f}) is {dev:.3f} mm from the nearest freexen key {near['ref']}")
            return 1
        keys.append({"id": kid, "hex": [row, dcol], "x": round(x, 3), "y": round(y, 3),
                     "freexen_ref": near["ref"], "freexen_dev_mm": round(dev, 3)})
    assign_muxes(keys)

    # Mux centroids (for placing each 74LV4051 near its keys).
    muxes = []
    for m in range(7):
        ks = [k for k in keys if k["mux"] == m]
        muxes.append({"index": m, "input_pin": MUX["input_pins"][m],
                      "centroid": [round(sum(k["x"] for k in ks) / 8, 2), round(sum(k["y"] for k in ks) / 8, 2)],
                      "keys": [k["id"] for k in sorted(ks, key=lambda k: k["mux_channel"])]})

    # libhmk matrix: rows = select value 0..7, cols = mux input 0..6, values = key id + 1 (0 = unused).
    matrix = [[0] * 7 for _ in range(8)]
    for k in keys:
        matrix[k["mux_channel"]][k["mux"]] = k["id"] + 1

    holes = [{"x": h["x"], "y": h["y"], "d": 3.2, "ref": h["ref"]} for h in ext["holes"]]
    spec = {
        "name": "openxen-m56",
        "version": "0.1.0",
        "units": "mm",
        "origin": "top-left corner of the outline bbox, x right, y down",
        "pitch": PITCH, "stagger": STAGGER,
        "outline": {"vertices": ext["outline"], "bbox": [0.0, 0.0, 124.842, 211.2],
                    "notes": "identical to the last freexen xenIO board (proven to fit the case); sharp corners; case DXF has R1.5 fillets"},
        "holes": holes,
        "hole_notes": "M3; freexen plate DXF has its hole near (20.24,192) 1.04 mm off-grid — PCB keeps the grid (19.2) as all previous boards did",
        "keys": keys,
        "unit_cell": UNIT_CELL,
        "controller_zones": CONTROLLER_ZONES,
        "mux": {**MUX, "groups": muxes, "libhmk_matrix": matrix},
        "plate": {"thickness": 1.5, "standoff": 3.5, "cutout": 14.0, "source": "existing CNC plates from freexen module_top.dxf"},
        "provenance": {"extract": str(EXTRACT.relative_to(ROOT)), "key_order": "xentool LTN_BOARD0_TUPLES (Lumatone .ltn index)"},
    }
    OUT.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(keys)} keys, worst key deviation {worst:.3f} mm, {len(holes)} holes, {len(ext['outline'])} outline vertices")
    for m in muxes:
        print(f"  mux {m['index']} ({m['input_pin']}) centroid {m['centroid']} keys {m['keys']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
