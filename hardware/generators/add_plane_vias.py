#!/usr/bin/env python3
"""Connect every +3.3VA pad that has no via yet to the +3.3VA plane (In2.Cu) with a short
stub and a via. GND needs no vias: the bottom GND pour (add_zones.py --bottom-pour) reaches
every GND pad directly and ties to the In1.Cu plane through the cells' GND vias.
Run with KiCad's Python after placement / cell routing, before Freerouting (whose net class
"Plane" = GND, +3.3VA is excluded from autorouting).

The stub leaves the pad along its long axis, away from the footprint centre; the via sits
0.75 mm beyond the pad end. Pads whose copper cluster already contains a via are skipped.
"""
from __future__ import annotations

import argparse
import math
import sys

import pcbnew  # type: ignore

NETS = {"+3.3VA": "In2.Cu"}
VIA_D, VIA_DRILL, W = 0.6, 0.3, 0.35


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    args = ap.parse_args()
    b = pcbnew.LoadBoard(args.board)
    conn = b.GetConnectivity()

    def reaches_via(pad: "pcbnew.PAD") -> bool:
        """BFS over the copper touching the pad: is a via already part of this pad's cluster?"""
        seen, todo = set(), [pad]
        while todo:
            item = todo.pop()
            if item.m_Uuid.AsString() in seen:
                continue
            seen.add(item.m_Uuid.AsString())
            if item.Type() == pcbnew.PCB_VIA_T:
                return True
            for t in conn.GetConnectedTracks(item):
                todo.append(t)
            if item.Type() != pcbnew.PCB_PAD_T:
                for q in conn.GetConnectedPads(item):
                    todo.append(q)
        return False

    added, skipped, refs = 0, 0, []
    fps = sorted(b.GetFootprints(), key=lambda f: (not f.GetReference().startswith(("C", "CM")), f.GetReference()))
    for fp in fps:
        fc = fp.GetPosition()
        for pad in fp.Pads():
            net = pad.GetNetname()
            if net not in NETS or pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                continue
            px, py = pcbnew.ToMM(pad.GetPosition().x), pcbnew.ToMM(pad.GetPosition().y)
            if reaches_via(pad):
                skipped += 1
                continue
            sz = pad.GetSize()
            sx, sy = pcbnew.ToMM(sz.x), pcbnew.ToMM(sz.y)
            ang = math.radians(pad.GetOrientation().AsDegrees())
            # long axis of the pad in board coordinates
            if sx >= sy:
                ax, ay, half = math.cos(ang), -math.sin(ang), sx / 2
            else:
                ax, ay, half = math.sin(ang), math.cos(ang), sy / 2
            # point it away from the footprint centre
            dx, dy = px - pcbnew.ToMM(fc.x), py - pcbnew.ToMM(fc.y)
            if ax * dx + ay * dy < 0:
                ax, ay = -ax, -ay
            dist = half + 0.75
            vx, vy = px + ax * dist, py + ay * dist
            layer = pcbnew.B_Cu if pad.IsOnLayer(pcbnew.B_Cu) else pcbnew.F_Cu
            t = pcbnew.PCB_TRACK(b)
            t.SetStart(pcbnew.VECTOR2I_MM(px, py)); t.SetEnd(pcbnew.VECTOR2I_MM(vx, vy))
            t.SetWidth(pcbnew.FromMM(W)); t.SetLayer(layer); t.SetNet(pad.GetNet()); b.Add(t)
            v = pcbnew.PCB_VIA(b)
            v.SetPosition(pcbnew.VECTOR2I_MM(vx, vy)); v.SetViaType(pcbnew.VIATYPE_THROUGH)
            v.SetDrill(pcbnew.FromMM(VIA_DRILL)); v.SetWidth(pcbnew.FromMM(VIA_D))
            v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); v.SetNet(pad.GetNet()); b.Add(v)
            added += 1
            refs.append(f"{fp.GetReference()}.{pad.GetNumber()}")
            b.BuildConnectivity()                     # so a pad wired to this one is seen as served
            conn = b.GetConnectivity()
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(args.board, b, True)
    print(f"add_plane_vias: {added} stub+via added ({', '.join(refs)}), {skipped} pads already had a via")
    return 0


if __name__ == "__main__":
    sys.exit(main())
