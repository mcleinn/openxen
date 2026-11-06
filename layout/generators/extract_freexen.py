#!/usr/bin/env python3
"""Extract the module geometry from the last freexen xenIO board and plate DXF.

Writes ``layout/source/freexen_extract.json`` with everything expressed relative to the
module's top-left corner (x to the right, y downwards, millimetres):

* ``outline``  – Edge.Cuts polygon vertices
* ``keys``     – 56 switch centres with the original mux reference (``AMx:y``)
* ``holes``    – 8 mounting holes
* ``plate``    – cutout centres and holes parsed from ``module_top.dxf``

Only the standard library is used. Inputs are read-only.
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PCB = Path(r"C:\Dev-Free\freexen\xenIO\void_switch_keyboard.kicad_pcb")
DXF = Path(r"C:\Dev-Free\freexen\xenCase\module_top.dxf")
OUT = ROOT / "layout" / "source" / "freexen_extract.json"

ORIGIN = (211.2, 115.2)  # top-left of the Edge.Cuts bbox in KiCad coordinates


def rel(x: float, y: float) -> tuple[float, float]:
    return round(x - ORIGIN[0], 3), round(y - ORIGIN[1], 3)


def parse_pcb(text: str) -> dict:
    outline = []
    for m in re.finditer(r"\(gr_poly(.*?)\(layer \"Edge\.Cuts\"\)", text, re.S):
        outline = [rel(float(a), float(b)) for a, b in re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", m.group(1))]
    keys, holes = [], []
    for name, body in re.findall(r'\(footprint "([^"]+)"(.*?)\n\t\)\n', text, re.S):
        at = re.search(r"\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", body)
        ref = re.search(r'\(property "Reference" "([^"]+)"', body)
        if not at:
            continue
        x, y = rel(float(at.group(1)), float(at.group(2)))
        if "VoidSwitch" in name:
            keys.append({"ref": ref.group(1) if ref else "?", "x": x, "y": y})
        elif "MountingHole" in name:
            holes.append({"ref": ref.group(1) if ref else "?", "x": x, "y": y})
    keys.sort(key=lambda k: (k["y"], k["x"]))
    holes.sort(key=lambda h: (h["x"], h["y"]))
    return {"outline": outline, "keys": keys, "holes": holes}


def parse_dxf(text: str) -> dict:
    """Minimal DXF reader: LWPOLYLINE (cutouts/outline) and CIRCLE entities."""
    lines = text.splitlines()
    ents = []
    i = 0
    while i < len(lines) - 1:
        if lines[i].strip() == "0" and lines[i + 1].strip() in ("LWPOLYLINE", "CIRCLE"):
            kind = lines[i + 1].strip()
            data: dict[str, list[str]] = {}
            j = i + 2
            while j < len(lines) - 1 and lines[j].strip() != "0":
                data.setdefault(lines[j].strip(), []).append(lines[j + 1].strip())
                j += 2
            ents.append((kind, data))
            i = j
        else:
            i += 1
    circles = [(float(d["10"][0]), float(d["20"][0]), float(d["40"][0])) for k, d in ents if k == "CIRCLE"]
    polys = []
    for k, d in ents:
        if k == "LWPOLYLINE" and "10" in d:
            xs = [float(v) for v in d["10"]]
            ys = [float(v) for v in d["20"]]
            polys.append(list(zip(xs, ys)))
    # cutouts: closed 4-point polys of ~14 mm; outline: the big one
    cutouts, outline = [], None
    for p in polys:
        xs, ys = [q[0] for q in p], [q[1] for q in p]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if 13.5 <= w <= 14.5 and 13.5 <= h <= 14.5:
            cutouts.append(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, w, h))
        elif w > 100:
            outline = p
    return {"circles": circles, "cutouts": cutouts, "outline": outline, "n_polys": len(polys)}


def main() -> int:
    pcb = parse_pcb(PCB.read_text(encoding="utf-8", errors="replace"))
    dxf = parse_dxf(DXF.read_text(encoding="utf-8", errors="replace"))

    # DXF is y-up with its own origin; normalise to top-left, y-down like the PCB.
    pts = [(x, y) for x, y, *_ in dxf["cutouts"]] + [(x, y) for x, y, _ in dxf["circles"]]
    if dxf["outline"]:
        pts += dxf["outline"]
    minx, maxy = min(p[0] for p in pts), max(p[1] for p in pts)

    def dxf_rel(x: float, y: float) -> tuple[float, float]:
        return round(x - minx, 3), round(maxy - y, 3)

    plate = {
        "cutouts": sorted([{"x": dxf_rel(x, y)[0], "y": dxf_rel(x, y)[1], "w": round(w, 3), "h": round(h, 3)}
                           for x, y, w, h in dxf["cutouts"]], key=lambda c: (c["y"], c["x"])),
        "holes": sorted([{"x": dxf_rel(x, y)[0], "y": dxf_rel(x, y)[1], "r": round(r, 3)}
                         for x, y, r in dxf["circles"]], key=lambda c: (c["x"], c["y"])),
        "outline_bbox": None,
    }
    if dxf["outline"]:
        ox = [dxf_rel(x, y)[0] for x, y in dxf["outline"]]
        oy = [dxf_rel(x, y)[1] for x, y in dxf["outline"]]
        plate["outline_bbox"] = [min(ox), min(oy), max(ox), max(oy)]

    out = {
        "source_pcb": str(PCB),
        "source_dxf": str(DXF),
        "origin_kicad": ORIGIN,
        "outline": pcb["outline"],
        "keys": pcb["keys"],
        "holes": pcb["holes"],
        "plate": plate,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")

    # Report
    ox = [p[0] for p in pcb["outline"]]
    oy = [p[1] for p in pcb["outline"]]
    print(f"outline: {len(pcb['outline'])} vertices, bbox {min(ox)}..{max(ox)} x {min(oy)}..{max(oy)}")
    print(f"keys: {len(pcb['keys'])}, holes: {len(pcb['holes'])}")
    print(f"plate: {len(plate['cutouts'])} cutouts, {len(plate['holes'])} holes, bbox {plate['outline_bbox']}")
    # nearest-cutout deviation per key
    devs = []
    for k in pcb["keys"]:
        c = min(plate["cutouts"], key=lambda c: (c["x"] - k["x"]) ** 2 + (c["y"] - k["y"]) ** 2)
        devs.append(math.hypot(c["x"] - k["x"], c["y"] - k["y"]))
    print(f"key vs plate cutout deviation: max {max(devs):.3f} mm, mean {sum(devs)/len(devs):.3f} mm")
    hdev = []
    for h in pcb["holes"]:
        c = min(plate["holes"], key=lambda c: (c["x"] - h["x"]) ** 2 + (c["y"] - h["y"]) ** 2)
        hdev.append((h["ref"], round(math.hypot(c["x"] - h["x"], c["y"] - h["y"]), 3)))
    print("hole deviations:", hdev)
    return 0


if __name__ == "__main__":
    sys.exit(main())
