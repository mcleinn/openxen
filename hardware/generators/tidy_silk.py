#!/usr/bin/env python3
"""Silkscreen/fab text cleanup (run with KiCad's Python after any placement step).

Rules (HE60 style): values hidden; references 0.6 mm, 0.1 mm stroke, mirrored on the back
side as KiCad expects; per-key references in fixed spots clear of pads and the LED hole:
  HE{n} below the sensor, C{n}/CF{n} above their caps, D{n} above the LED.
Other footprints keep their reference but it is normalised in size and mirroring.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pcbnew  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "layout" / "module.json").read_text(encoding="utf-8"))

REF_SIZE = 0.6
REF_THICK = 0.1
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
        else:
            # keep near the part: just above its courtyard
            bb = fp.GetBoundingBox(False, False)
            r.SetPosition(pcbnew.VECTOR2I(bb.GetCenter().x, bb.GetTop() - pcbnew.FromMM(0.8)))
            n_other += 1
    pcbnew.SaveBoard(args.board, b)
    print(f"tidy_silk: {n_cell} cell references placed, {n_other} other references normalised, values hidden")
    return 0


if __name__ == "__main__":
    sys.exit(main())
