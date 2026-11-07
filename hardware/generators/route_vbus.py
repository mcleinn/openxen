#!/usr/bin/env python3
"""Scripted VBUS run from the USB-C connector to the fuse. Run with KiCad's Python.

    python.exe hardware/generators/route_vbus.py --board <pcb>

VBUS carries the whole module (sensors + LEDs, about 1 A). Left to the autorouter it became
a 27 mm long 0.2 mm track squeezed between signal lines. This draws it at 0.8 mm on F.Cu
(free in this strip: the controller parts are on B.Cu) from J1's VBUS via (HE60 block) to
two 0.8/0.4 vias in a column above the fuse pad F1.1, tied to it on B.Cu. Idempotent (removes its own
earlier run: VBUS copper at least 0.8 mm wide).
"""
from __future__ import annotations

import argparse
import subprocess
import sys

import pcbnew  # type: ignore

W, VIA_D, VIA_DRILL = 0.8, 0.8, 0.4
Y_RUN = 8.1          # J1's VBUS vias sit on this line (HE60 block)


def mm(x, y):
    return pcbnew.VECTOR2I_MM(float(x), float(y))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    args = ap.parse_args()
    b = pcbnew.LoadBoard(args.board)
    old = [t for t in b.GetTracks() if t.GetNetname() == "VBUS" and
           (t.GetWidth(pcbnew.F_Cu) if t.Type() == pcbnew.PCB_VIA_T else t.GetWidth()) >= pcbnew.FromMM(W) - 1]
    if old:   # after BOARD.Remove KiCad's SWIG proxies break: save, start afresh
        for t in old:
            b.Remove(t)
        pcbnew.SaveBoard(args.board, b, True)
        return subprocess.run([sys.executable, __file__, "--board", args.board]).returncode

    pads = {(fp.GetReference(), p.GetNumber()): p for fp in b.GetFootprints() for p in fp.Pads()}
    j1 = pads[("J1", "A9")]
    f1 = pads[("F1", "1")]
    net = f1.GetNet()
    assert f1.GetNetname() == "VBUS" and j1.GetNetname() == "VBUS"
    x_start = pcbnew.ToMM(j1.GetPosition().x)                  # J1's VBUS via column
    fx, fy = pcbnew.ToMM(f1.GetPosition().x), pcbnew.ToMM(f1.GetPosition().y)
    vys = [fy - 3.0, fy - 2.0]                                 # two vias in a column above the pad
    n = 0

    def track(a, c, layer):
        nonlocal n
        t = pcbnew.PCB_TRACK(b); t.SetStart(mm(*a)); t.SetEnd(mm(*c))
        t.SetWidth(pcbnew.FromMM(W)); t.SetLayer(layer); t.SetNet(net); b.Add(t); n += 1

    side = 1 if x_start > fx else -1                           # J1 east or west of the fuse
    corner = (fx + side * (vys[0] - Y_RUN), Y_RUN)
    track((x_start, Y_RUN), corner, pcbnew.F_Cu)
    track(corner, (fx, vys[0]), pcbnew.F_Cu)
    track((fx, vys[0]), (fx, vys[1]), pcbnew.F_Cu)
    for y in vys:
        v = pcbnew.PCB_VIA(b); v.SetPosition(mm(fx, y)); v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetDrill(pcbnew.FromMM(VIA_DRILL)); v.SetWidth(pcbnew.FromMM(VIA_D))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); v.SetNet(net); b.Add(v); n += 1
    track((fx, vys[0]), (fx, fy), pcbnew.B_Cu)
    pcbnew.SaveBoard(args.board, b, True)
    print(f"route_vbus: {n} tracks/vias, J1 -> F1 at {W} mm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
