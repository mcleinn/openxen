#!/usr/bin/env python3
"""Autoroute one unit cell with Freerouting for comparison with route_cell.py.

Run with KiCad's Python. Steps: copy the real board, keep only the footprints of key N
(switch, sensor, caps, LED), drop all tracks, export Specctra DSN headless, run Freerouting
(portable Java 25 + jar under reference/tools), import the SES, save build/cell-freerouted.kicad_pcb.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pcbnew  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "reference" / "tools"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    ap.add_argument("--key", type=int, default=0)
    ap.add_argument("--passes", type=int, default=20)
    args = ap.parse_args()
    n = args.key
    keep = {f"K{n}", f"HE{n}", f"C{n}", f"CF{n}", f"D{n}"}

    # Build a fresh board holding only this key's parts (removing footprints from the full
    # board confuses the SWIG wrappers), then net the pads from the exported netlist.
    sys.path.insert(0, str(ROOT / "layout" / "generators"))
    sys.path.insert(0, str(ROOT / "hardware" / "generators"))
    import json
    import place_module, sexp
    from sexp import kids, kid, q
    spec = json.loads((ROOT / "layout" / "module.json").read_text(encoding="utf-8"))
    spec1 = dict(spec)
    spec1["keys"] = [k for k in spec["keys"] if k["id"] == n]
    spec1["holes"] = []
    board = pcbnew.CreateEmptyBoard()
    board.GetDesignSettings().SetCopperLayerCount(4)
    place_module.place(spec1, board, place_module.DEFAULT_LIBS, redraw_edges=False)
    # a small board outline around the cell so the autorouter has a boundary
    k = spec1["keys"][0]
    pl = place_module.Placer(board, place_module.DEFAULT_LIBS)
    cx, cy, h = k["x"], k["y"], 9.6
    for a, b in [((cx-h, cy-h), (cx+h, cy-h)), ((cx+h, cy-h), (cx+h, cy+h)), ((cx+h, cy+h), (cx-h, cy+h)), ((cx-h, cy+h), (cx-h, cy-h))]:
        pl.segment(a, b)
    net = sexp.loads((ROOT / "build" / "openxen-m56.net").read_text(encoding="utf-8"))
    by_ref = {fp.GetReference(): fp for fp in board.GetFootprints()}
    nets = {}
    for nn in kids(kid(net, "nets"), "net"):
        name = q(nn, "name")
        for node in kids(nn, "node"):
            ref, pin = q(node, "ref"), q(node, "pin")
            fp = by_ref.get(ref)
            if fp is None:
                continue
            ni = nets.get(name)
            if ni is None:
                ni = pcbnew.NETINFO_ITEM(board, name)
                board.Add(ni)
                nets[name] = ni
            for pad in fp.Pads():
                if pad.GetNumber() == pin:
                    pad.SetNet(ni)
    out_dir = ROOT / "build" / "freerouting"
    out_dir.mkdir(parents=True, exist_ok=True)
    cell_pcb = out_dir / f"cell{n}.kicad_pcb"
    pcbnew.SaveBoard(str(cell_pcb), board, True)
    print("cell board:", len(by_ref), "footprints,", len(nets), "nets")

    dsn = out_dir / f"cell{n}.dsn"
    ses = out_dir / f"cell{n}.ses"
    board = pcbnew.LoadBoard(str(cell_pcb))
    ok = pcbnew.ExportSpecctraDSN(board, str(dsn))
    print("DSN export:", ok, dsn.stat().st_size if dsn.exists() else "missing")

    java = next(TOOLS.glob("jre25/*/bin/java.exe"))
    jar = TOOLS / "freerouting-2.5.0.jar"
    cmd = [str(java), "-jar", str(jar), "-de", str(dsn), "-do", str(ses), "-mp", str(args.passes), "-l", "en"]
    print("running:", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    tail = (r.stdout + r.stderr).strip().splitlines()[-12:]
    print("\n".join(tail))
    if not ses.exists():
        print("no SES produced")
        return 1
    ok = pcbnew.ImportSpecctraSES(board, str(ses))
    print("SES import:", ok, "tracks now:", len(list(board.GetTracks())))
    out = out_dir / f"cell{n}-freerouted.kicad_pcb"
    pcbnew.SaveBoard(str(out), board, True)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
