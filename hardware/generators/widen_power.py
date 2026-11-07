#!/usr/bin/env python3
"""Widen narrow power tracks where there is room. Run with KiCad's Python after import_routes.

    python.exe hardware/generators/widen_power.py --board <pcb>

The autorouter necks +5V/VBUS down to fit between pads (and only partly widens them back).
Each +5V/VBUS track narrower than its class width is widened to the largest width in
WIDTHS that keeps CLEARANCE to every other-net copper item on its layer (pads, tracks,
vias; the plane fills are refilled afterwards and follow). Track ends stay put, so
connectivity is unchanged. Deterministic and idempotent.
"""
from __future__ import annotations

import argparse
import sys

import pcbnew  # type: ignore

NETS = {"+5V": 0.8, "VBUS": 0.8}
WIDTHS = [0.8, 0.6, 0.5, 0.4, 0.3]
CLEARANCE = 0.2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    args = ap.parse_args()
    b = pcbnew.LoadBoard(args.board)
    clr = pcbnew.FromMM(CLEARANCE)

    tracks = [t for t in b.GetTracks()]
    pads = [p for fp in b.GetFootprints() for p in fp.Pads()]
    cands = [t for t in tracks if t.Type() == pcbnew.PCB_TRACE_T and t.GetNetname() in NETS
             and t.GetWidth() < pcbnew.FromMM(NETS[t.GetNetname()]) - 1]
    widened = 0
    for t in cands:
        net, layer = t.GetNetCode(), t.GetLayer()
        others = [o for o in tracks if o.GetNetCode() != net and o.IsOnLayer(layer) and o is not t]
        others += [p for p in pads if p.GetNetCode() != net and p.IsOnLayer(layer)]
        old = t.GetWidth()
        for w in WIDTHS:
            wn = pcbnew.FromMM(w)
            if wn <= old:
                break
            t.SetWidth(wn)
            shape = t.GetEffectiveShape(layer)
            bb = t.GetBoundingBox()
            bb.Inflate(clr + pcbnew.FromMM(1))
            hit = False
            for o in others:
                if not bb.Intersects(o.GetBoundingBox()):
                    continue
                if shape.Collide(o.GetEffectiveShape(layer), clr - 1):
                    hit = True
                    break
            if not hit:
                widened += 1
                break
            t.SetWidth(old)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(args.board, b, True)
    print(f"widen_power: {widened} of {len(cands)} narrow power tracks widened")
    return 0


if __name__ == "__main__":
    sys.exit(main())
