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
        mx, my = g["pos"]                                                 # chosen by build_spec.py (host key + MUX_DY)
        put(b, f"AM{g['index']}", mx, my, 0)                              # pin rows vertical at x +-2.9
        put(b, f"CM{g['index']}", mx + CAP_DX, my, 90)
        print(f"mux {g['index']} under key {g['host_key']} at ({mx:.1f},{my:.1f})")
    # LED driver block in the bottom-left strip (x 10.8..84.8, y 190.7..210.2). All four QFN
    # edges are fanned out by route_led_driver.py (LED lines left/top/right, supply and control
    # pins at the bottom), so the support parts sit in one row below the bottom fan-out vias:
    # decoupling caps under the chip (DVCC/AVCC 37/38, VIO 39), the I2C/SDB/INTB/IICRST/SYNC/REXT
    # resistors to the right.
    x0, y0 = 40.0, 199.0   # clear of mounting hole H4 at (19.2, 192)
    put(b, "U10", x0, y0, 0)
    caps = ["C212", "C213", "C214", "C215", "C210", "C211", "C216", "C217"]   # 0603: +5V, VIO pair
    for i, c in enumerate(caps):
        put(b, c, x0 - 5.6 + i * 1.6, y0 + 8.6, 90)
    put(b, "C218", x0 - 8.2, y0 + 8.6, 90)                            # 22u bulk (0805)
    for i, r in enumerate(["R10", "R11", "R12", "R13", "R14", "R15", "R16"]):
        put(b, r, x0 + 7.5 + i * 1.5, y0 + 8.6, 90)
    # test points: one row below the LDO block, bottom side (TP1..TP16)
    for i in range(16):
        put(b, f"TP{i + 1}", 61.0 + i * 2.54, 19.3, 0)
    pcbnew.SaveBoard(args.board, b, True)
    print("placed muxes, LED driver block and test points")
    return 0


if __name__ == "__main__":
    sys.exit(main())
