#!/usr/bin/env python3
"""Add the copper planes: GND on In1.Cu (layer 2) and +3.3VA on In2.Cu (layer 3), both
filling the whole outline, plus a GND pour on B.Cu for stitching. Run with KiCad's Python.
Existing zones with the same (net, layer) are replaced.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pcbnew  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "layout" / "module.json").read_text(encoding="utf-8"))


def add_zone(b: "pcbnew.BOARD", net: str, layer: int, verts: list, clearance: float = 0.25, min_w: float = 0.25, priority: int = 0, name: str = "") -> None:
    ni = b.FindNet(net)
    if ni is None:
        raise SystemExit(f"net {net} not found")
    for z in list(b.Zones()):
        if z.GetNetname() == net and z.GetFirstLayer() == layer:
            b.Remove(z)
    z = pcbnew.ZONE(b)
    z.SetNet(ni)
    z.SetLayer(layer)
    z.SetZoneName(name or f"{net}_{b.GetLayerName(layer)}")
    z.SetLocalClearance(pcbnew.FromMM(clearance))
    z.SetMinThickness(pcbnew.FromMM(min_w))
    z.SetAssignedPriority(priority)
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
    z.SetThermalReliefGap(pcbnew.FromMM(0.3))
    z.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.35))
    outline = z.Outline()
    outline.NewOutline()
    for x, y in verts:
        outline.Append(pcbnew.VECTOR2I_MM(float(x), float(y)))
    b.Add(z)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    ap.add_argument("--bottom-pour", action="store_true")
    args = ap.parse_args()
    b = pcbnew.LoadBoard(args.board)
    verts = SPEC["outline"]["vertices"]
    add_zone(b, "GND", b.GetLayerID("In1.Cu"), verts, name="GND_plane")
    add_zone(b, "+3.3VA", b.GetLayerID("In2.Cu"), verts, name="AVCC_pour")
    if args.bottom_pour:  # added after routing so the autorouter is not blocked by it
        add_zone(b, "GND", pcbnew.B_Cu, verts, clearance=0.3, name="GND_bottom", priority=0)
    filler = pcbnew.ZONE_FILLER(b)
    filler.Fill(b.Zones())
    pcbnew.SaveBoard(args.board, b, True)
    print("zones:", [(z.GetZoneName(), z.GetNetname(), b.GetLayerName(z.GetFirstLayer())) for z in b.Zones()])
    return 0


if __name__ == "__main__":
    sys.exit(main())
