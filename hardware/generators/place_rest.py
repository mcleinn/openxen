#!/usr/bin/env python3
"""Place the remaining parts that are not part of a key cell or an HE60 block:
the seven muxes with their decoupling caps (in the free band south of a key near each
group's centroid) and the LED driver block (bottom-left strip). Run with KiCad's Python.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pcbnew  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "layout" / "module.json").read_text(encoding="utf-8"))

MUX_DY = 7.0     # mux body centre below the key centre (free band between sensor and next row)
CAP_DX = 5.4     # mux decoupling cap right of the mux


def mm(x: float, y: float) -> "pcbnew.VECTOR2I":
    return pcbnew.VECTOR2I_MM(float(x), float(y))


def put(b, ref: str, x: float, y: float, rot: float, bottom: bool = True) -> None:
    fp = b.FindFootprintByReference(ref)
    if fp is None:
        print("  missing", ref)
        return
    if bottom and not fp.IsFlipped():
        fp.SetLayerAndFlip(pcbnew.B_Cu)
    fp.SetPosition(mm(x, y))
    fp.SetOrientationDegrees(rot)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    args = ap.parse_args()
    b = pcbnew.LoadBoard(args.board)
    keys = {k["id"]: k for k in SPEC["keys"]}
    # muxes: nearest key to the group centroid, but prefer a key whose south band is inside the board
    for g in SPEC["mux"]["groups"]:
        cx, cy = g["centroid"]
        host = min((keys[i] for i in g["keys"]), key=lambda k: math.hypot(k["x"] - cx, k["y"] - cy))
        put(b, f"AM{g['index']}", host["x"], host["y"] + MUX_DY, 0)       # pin rows vertical at x +-2.9
        put(b, f"CM{g['index']}", host["x"] + CAP_DX, host["y"] + MUX_DY, 90)
        print(f"mux {g['index']} under key {host['id']} at ({host['x']:.1f},{host['y'] + MUX_DY:.1f})")
    # LED driver block in the bottom-left strip (x 10.8..84.8, y 190.7..210.2)
    x0, y0 = 40.0, 200.0   # clear of mounting hole H4 at (19.2, 192)
    put(b, "U10", x0, y0, 0)
    caps = ["C212", "C213", "C214", "C215", "C216", "C217", "C210", "C211"]
    for i, c in enumerate(caps):
        put(b, c, x0 - 6.5 + (i % 4) * 2.2, y0 - 6.3 + (i // 4) * 1.6 if i < 4 else y0 + 6.0 + (i // 4 - 1) * 1.6, 90)
    put(b, "C218", x0 + 6.8, y0 - 5.0, 90)          # 22u bulk
    for i, r in enumerate(["R10", "R11", "R12", "R13", "R14", "R15", "R16"]):
        put(b, r, x0 + 9.0 + i * 2.0, y0 + 2.0, 90)
    # test points: one row below the LDO block, bottom side (TP1..TP16)
    for i in range(16):
        put(b, f"TP{i + 1}", 61.0 + i * 2.54, 19.3, 0)
    pcbnew.SaveBoard(args.board, b, True)
    print("placed muxes, LED driver block and test points")
    return 0


if __name__ == "__main__":
    sys.exit(main())
