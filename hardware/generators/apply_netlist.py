#!/usr/bin/env python3
"""Bring a board in sync with the schematic netlist (headless "Update PCB from schematic").

Run with KiCad's Python:

    "C:\\Program Files\\KiCad\\9.0\\bin\\python.exe" hardware/generators/apply_netlist.py \
        --board hardware/kicad/openxen-m56/openxen-m56.kicad_pcb --netlist build/openxen-m56.net [--create]

* Every component of the netlist gets a footprint on the board (existing ones are kept,
  missing ones are loaded from the KiCad libraries or ours and parked in the controller
  zone / near their mux group).
* Every pad gets its net; nets are created as needed; footprint Value is synced.
* With --create the key field is placed first via place_module.place().

Afterwards `kicad-cli pcb drc --schematic-parity` must report no parity issues.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pcbnew  # type: ignore

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "layout" / "generators"))
import sexp  # noqa: E402
from sexp import kids, kid, q  # noqa: E402
import place_module  # noqa: E402

KICAD_FP = Path(os.environ.get("KICAD9_FOOTPRINT_DIR", r"C:\Program Files\KiCad\9.0\share\kicad\footprints"))
SPEC = json.loads((ROOT / "layout" / "module.json").read_text(encoding="utf-8"))


def lib_path(nick: str) -> Path:
    if nick == "openxen":
        return ROOT / "hardware" / "kicad" / "lib" / "openxen.pretty"
    return KICAD_FP / f"{nick}.pretty"


def park_position(ref: str, index: int) -> tuple[float, float, bool]:
    """Where to drop a footprint that place_module did not place: muxes near their group,
    everything else in a grid inside the preferred controller zone (bottom side)."""
    if ref.startswith("AM") or ref.startswith("CM"):
        m = int(ref[2:])
        cx, cy = SPEC["mux"]["groups"][m]["centroid"]
        return (cx + (3.0 if ref.startswith("CM") else 0.0), cy + 9.6, True)
    z = [z for z in SPEC["controller_zones"] if z["preferred"]][0]
    cols = 14
    x = z["x0"] + 3 + (index % cols) * 5.0
    y = z["y0"] + 3 + (index // cols) * 4.5
    return (x, y, True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    ap.add_argument("--netlist", required=True)
    ap.add_argument("--create", action="store_true")
    args = ap.parse_args()

    bp = Path(args.board)
    if args.create:
        board = pcbnew.CreateEmptyBoard()
        board.GetDesignSettings().SetCopperLayerCount(4)
        bp.parent.mkdir(parents=True, exist_ok=True)
        place_module.place(SPEC, board, place_module.DEFAULT_LIBS, redraw_edges=True)
    else:
        board = pcbnew.LoadBoard(str(bp))

    net = sexp.loads(Path(args.netlist).read_text(encoding="utf-8"))
    comps = kids(kid(net, "components"), "comp")
    by_ref = {fp.GetReference(): fp for fp in board.GetFootprints()}

    created = 0
    parked = 0
    for c in comps:
        ref, value, fpname = q(c, "ref"), q(c, "value"), q(c, "footprint")
        if not fpname or ":" not in fpname:
            print(f"  skip {ref}: no footprint ({fpname!r})")
            continue
        fp = by_ref.get(ref)
        if fp is None:
            nick, name = fpname.split(":", 1)
            fp = pcbnew.FootprintLoad(str(lib_path(nick)), name)
            if fp is None:
                print(f"  ERROR footprint {fpname} for {ref} not found")
                continue
            fp.SetFPIDAsString(fpname)
            fp.SetReference(ref)
            board.Add(fp)
            x, y, bottom = park_position(ref, parked)
            fp.SetPosition(pcbnew.VECTOR2I_MM(x, y))
            if bottom and not fp.IsFlipped():
                fp.SetLayerAndFlip(pcbnew.B_Cu)
            by_ref[ref] = fp
            created += 1
            parked += 1
        fp.SetValue(value)
        # carry the LCSC field for the Fabrication Toolkit
        for f in kids(c, "fields") or []:
            pass
        fields = kid(c, "fields")
        if fields:
            for fld in kids(fields, "field"):
                if q(fld, "name") == "LCSC Part #" and len(fld) > 2 and isinstance(fld[2], sexp.Quoted):
                    fp.SetField("LCSC Part #", fld[2].s)

    # nets
    netinfo = board.GetNetInfo()
    existing = {netinfo.GetNetItem(i).GetNetname(): netinfo.GetNetItem(i) for i in range(1, netinfo.GetNetCount())} if netinfo.GetNetCount() > 1 else {}
    assigned = 0
    missing_pads = []
    for n in kids(kid(net, "nets"), "net"):
        name = q(n, "name")
        ni = existing.get(name)
        if ni is None:
            ni = pcbnew.NETINFO_ITEM(board, name)
            board.Add(ni)
            existing[name] = ni
        for node in kids(n, "node"):
            ref, pin = q(node, "ref"), q(node, "pin")
            fp = by_ref.get(ref)
            if fp is None:
                continue
            pads = [p for p in fp.Pads() if p.GetNumber() == pin]
            if not pads:
                missing_pads.append((ref, pin))
                continue
            for p in pads:
                p.SetNet(ni)
                assigned += 1
    pcbnew.SaveBoard(str(bp), board, True)   # True: never rewrite the .kicad_pro (net classes, rules)
    print(f"{bp.name}: {len(comps)} components, {created} footprints created, {assigned} pads netted, {len(existing)} nets")
    if missing_pads:
        print("  pads not found:", missing_pads[:20])
    return 0


if __name__ == "__main__":
    sys.exit(main())
