#!/usr/bin/env python3
"""Silkscreen/fab text cleanup (run with KiCad's Python after any placement step).

Rules: values hidden; references 0.8 mm / 0.15 mm stroke (JLCPCB silk minimum), mirrored on
the back side as KiCad expects; per-key references in fixed spots clear of pads and the LED
hole: HE{n} below the sensor, C{n}/CF{n} above their caps, D{n} above the LED. Parts copied
from HE60 keep HE60's reference positions; parts placed by place_rest.py get a position by
rule (muxes below the package, test points alternating above/below the pad). LED footprint
silk outlines are dropped (DRC: silk over the LED stubs); HE60's controller-block 0402
passives get no reference on silk (no room; HE60 ships without them too).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pcbnew  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "layout" / "module.json").read_text(encoding="utf-8"))

REF_SIZE = 0.8
REF_THICK = 0.15
SIDE_RULES = {"U1": "left", "U3": "left", "SW2": "below_left", "U10": "above"}
CELL_REF_POS = {  # relative to key centre (mm, y down), for bottom-side parts
    "HE": (0.0, 2.9),
    "C": (-3.3, -1.75),
    "CF": (3.3, -1.75),
    "D": (0.0, -6.7),
}


def norm_text(t: "pcbnew.PCB_FIELD", flipped: bool, size: float = REF_SIZE) -> None:
    t.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(size), pcbnew.FromMM(size)))
    t.SetTextThickness(pcbnew.FromMM(REF_THICK))
    t.SetMirrored(flipped)
    t.SetTextAngleDegrees(0)
    t.SetKeepUpright(True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    args = ap.parse_args()
    b = pcbnew.LoadBoard(args.board)
    keys = {k["id"]: (k["x"], k["y"]) for k in SPEC["keys"]}
    n_cell = n_other = 0
    for fp in b.GetFootprints():
        ref = fp.GetReference()
        flipped = fp.IsFlipped()
        for f in fp.GetFields():
            if f.GetName() != "Reference":
                f.SetVisible(False)      # Value, LCSC Part #, MPN, ... never on silk
        r = fp.Reference()
        r.SetVisible(True)
        r.SetLayer(pcbnew.B_SilkS if flipped else pcbnew.F_SilkS)
        norm_text(r, flipped)
        prefix = "".join(ch for ch in ref if ch.isalpha())
        digits = "".join(ch for ch in ref if ch.isdigit())
        if prefix in CELL_REF_POS and digits and int(digits) in keys and prefix != "K":
            kx, ky = keys[int(digits)]
            dx, dy = CELL_REF_POS[prefix]
            r.SetPosition(pcbnew.VECTOR2I_MM(kx + dx, ky + dy))
            n_cell += 1
        elif prefix in ("K", "H"):
            r.SetVisible(False)  # mechanical: no silk
        elif prefix in ("AM", "CM"):
            bb = fp.GetBoundingBox(False, False)       # mux + its cap: below the package, clear of the host cell's HE ref
            r.SetPosition(pcbnew.VECTOR2I(bb.GetCenter().x, bb.GetBottom() + pcbnew.FromMM(0.8)))
            n_other += 1
        elif prefix == "TP":
            pos = fp.GetPosition()                     # 2.54 mm pitch under the LDO block: two staggered rows below the pads
            dy = 1.4 if int(digits) % 2 else 2.4
            r.SetPosition(pcbnew.VECTOR2I(pos.x, pos.y + pcbnew.FromMM(dy)))
            n_other += 1
        elif ref in SIDE_RULES:
            bb = fp.GetBoundingBox(False, False)       # hand-picked spots where the generic rule collides with a neighbour
            side = SIDE_RULES[ref]
            cx, cy = bb.GetCenter().x, bb.GetCenter().y
            pos = {"above": (cx, bb.GetTop() - pcbnew.FromMM(0.8)), "below": (cx, bb.GetBottom() + pcbnew.FromMM(0.8)),
                   "left": (bb.GetLeft() - pcbnew.FromMM(1.6), cy), "right": (bb.GetRight() + pcbnew.FromMM(1.6), cy),
                   "below_left": (cx - pcbnew.FromMM(2.6), bb.GetBottom() + pcbnew.FromMM(0.8))}[side]
            r.SetPosition(pcbnew.VECTOR2I(*pos))
            n_other += 1
        elif prefix == "R" and digits and 10 <= int(digits) <= 16:
            bb = fp.GetBoundingBox(False, False)       # LED driver block resistors (2 mm pitch): alternate above / below
            up = int(digits) % 2 == 0
            r.SetPosition(pcbnew.VECTOR2I(bb.GetCenter().x, (bb.GetTop() - pcbnew.FromMM(0.8)) if up else (bb.GetBottom() + pcbnew.FromMM(0.8))))
            n_other += 1
        elif prefix == "C" and digits and (140 <= int(digits) <= 160 or 210 <= int(digits) <= 218) or prefix == "R" and digits and int(digits) <= 4:
            r.SetVisible(False)                        # 0402 passives packed around the MCU/LDOs/LED driver: no room for readable refs (HE60 has none either)
            n_other += 1
        elif prefix in ("SW", "U"):
            bb = fp.GetBoundingBox(False, False)       # ICs and buttons: below the courtyard (above collides with F1 silk / cell refs)
            r.SetPosition(pcbnew.VECTOR2I(bb.GetCenter().x, bb.GetBottom() + pcbnew.FromMM(0.8)))
            n_other += 1
        else:
            n_other += 1                               # other HE60 block parts (J1, J3, F1, Y1): keep HE60's reference position
        fpid = fp.GetFPIDAsString()
        if "LED_RGB_1206R" in fpid:                    # cosmetic outline crosses the LED stubs / pads: drop it
            todo = [g for g in fp.GraphicalItems() if g.GetLayer() in (pcbnew.B_SilkS, pcbnew.F_SilkS)
                    and isinstance(g, pcbnew.PCB_SHAPE) and g.GetShape() == pcbnew.SHAPE_T_SEGMENT]
            for g in todo:
                fp.Delete(g)                           # Delete, not Remove: Remove leaves dangling SWIG wrappers
    pcbnew.SaveBoard(args.board, b, True)
    print(f"tidy_silk: {n_cell} cell references placed, {n_other} other references normalised, values hidden")
    return 0


if __name__ == "__main__":
    sys.exit(main())
