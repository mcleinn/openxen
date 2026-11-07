#!/usr/bin/env python3
"""Scripted fan-out of the IS31FL3733 (U10, QFN-48, 0.4 mm pitch). Run with KiCad's Python.

    python.exe hardware/generators/route_led_driver.py --board <pcb>

The 26 LED lines all converge on this package; the autorouter kept walling its pins in with
its own vias (all its open connections were at U10). This script gives every LED pin a
deterministic escape so the router only has to connect vias with room around them:

- left, top and right edges (SW1-9 | SW10-12, CS1-8, +5V pin 20 | CS9-14, +5V pin 29, REXT):
  a 0.2 mm stub straight out of the pad, a 45 deg leg fanning out to a 0.8 mm pitch, a
  straight leg to one of two staggered via rows, and a 0.5/0.3 via. Neighbouring legs turn in staggered order
  (outermost first, 0.3 mm apart) so parallel 45 deg legs keep >= 0.2 mm clearance.
- GND pins: a stub inward to the exposed pad; the exposed pad gets 4 vias to the GND plane.
- bottom edge (supply 37/38, VIO 39, I2C, SDB, INTB, IICRST, SYNC): the same fan-out; the
  support caps/resistors sit in one row below its vias (place_rest.py).
Re-running removes the previous fan-out (tracks/vias touching U10's area on its nets).
"""
from __future__ import annotations

import argparse
import math
import subprocess
import sys

import pcbnew  # type: ignore

REF = "U10"
W = 0.2            # stub/leg width (0.4 pitch - 0.2 pad - 2 x 0.2 clearance would be 0)
PITCH_OUT = 0.8    # via pitch after the fan
VIA_D, VIA_DRILL = 0.5, 0.3
STAGGER = 0.3      # straight length difference between neighbouring legs
FIRST = 0.35       # straight length of the outermost leg before its 45 deg turn
VIA_MARGIN = 0.45  # straight length after the last turn, before the via
ROW_DV = 0.9       # every second via sits this much further out: two staggered rows, so a
                   # track (0.2 + 2 x 0.2 clearance) fits between neighbours of the outer row
EP_VIAS = [(-0.9, -0.9), (0.9, -0.9), (-0.9, 0.9), (0.9, 0.9)]


def mm(x: float, y: float) -> "pcbnew.VECTOR2I":
    return pcbnew.VECTOR2I_MM(float(x), float(y))


class Fan:
    def __init__(self, b):
        self.b = b
        self.n = 0

    def track(self, a, c, net):
        if abs(a[0] - c[0]) < 1e-6 and abs(a[1] - c[1]) < 1e-6:
            return
        t = pcbnew.PCB_TRACK(self.b)
        t.SetStart(mm(*a)); t.SetEnd(mm(*c)); t.SetWidth(pcbnew.FromMM(W))
        t.SetLayer(pcbnew.B_Cu); t.SetNet(net)
        self.b.Add(t); self.n += 1

    def via(self, p, net):
        v = pcbnew.PCB_VIA(self.b)
        v.SetPosition(mm(*p)); v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetDrill(pcbnew.FromMM(VIA_DRILL)); v.SetWidth(pcbnew.FromMM(VIA_D))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); v.SetNet(net)
        self.b.Add(v); self.n += 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    args = ap.parse_args()
    b = pcbnew.LoadBoard(args.board)
    fp = b.FindFootprintByReference(REF)
    cx, cy = pcbnew.ToMM(fp.GetPosition().x), pcbnew.ToMM(fp.GetPosition().y)

    # remove an earlier fan-out: tracks/vias within 9 mm of U10 on U10's nets
    u10_nets = {p.GetNetname() for p in fp.Pads() if p.GetNetname()}
    removed = 0
    for t in list(b.GetTracks()):
        if t.GetNetname() not in u10_nets:
            continue
        via = t.Type() == pcbnew.PCB_VIA_T
        p = t.GetPosition() if via else t.GetStart()
        w = t.GetWidth(pcbnew.F_Cu) if via else t.GetWidth()   # via without a layer asserts
        near = math.hypot(pcbnew.ToMM(p.x) - cx, pcbnew.ToMM(p.y) - cy) < 9.0
        if near and pcbnew.ToMM(w) < (VIA_D + 0.05 if via else 0.39):   # sink lines (0.4) and their vias stay
            b.Remove(t)
            removed += 1
    if removed:   # after BOARD.Remove KiCad's SWIG proxies break (even LoadBoard): save, start afresh
        pcbnew.SaveBoard(args.board, b, True)
        print(f"route_led_driver: {removed} previous fan-out items removed")
        return subprocess.run([sys.executable, __file__, "--board", args.board]).returncode

    pads = list(fp.Pads())
    f = Fan(b)
    edges: dict[str, list] = {"L": [], "T": [], "R": [], "B": []}
    ep = None
    for p in pads:
        net = p.GetNetname()
        x, y = pcbnew.ToMM(p.GetPosition().x) - cx, pcbnew.ToMM(p.GetPosition().y) - cy
        if abs(x) < 2.3 and abs(y) < 2.3:
            if p.GetNumber() and net == "GND" and p.GetSize().x > pcbnew.FromMM(3):
                ep = p
            continue
        if not net or net.startswith("unconnected"):
            continue
        side = ("L" if x < 0 else "R") if abs(x) > abs(y) else ("T" if y < 0 else "B")
        size = p.GetSize()
        half_len = pcbnew.ToMM(max(size.x, size.y)) / 2
        edges[side].append((p, net, x, y, half_len))

    # GND pins: stub inward, then onto the exposed pad (corner pins bend in under 45 deg)
    ep_in = pcbnew.ToMM(ep.GetSize().x) / 2 - 0.3 if ep is not None else 1.8
    for side, pins in edges.items():
        for p, net, x, y, hl in pins:
            if net != "GND":
                continue
            ux, uy = {"L": (1, 0), "R": (-1, 0), "T": (0, 1), "B": (0, -1)}[side]
            p1 = (x + ux * (hl + 0.25), y + uy * (hl + 0.25))
            clamp = lambda t: max(-ep_in, min(ep_in, t))
            p2 = (clamp(x), -uy * ep_in) if uy else (-ux * ep_in, clamp(y))
            f.track((cx + x, cy + y), (cx + p1[0], cy + p1[1]), p.GetNet())
            f.track((cx + p1[0], cy + p1[1]), (cx + p2[0], cy + p2[1]), p.GetNet())
    if ep is not None:
        for dx, dy in EP_VIAS:
            f.via((cx + dx, cy + dy), ep.GetNet())

    # signal fan-outs on L, T, R
    for side in ("L", "T", "R", "B"):
        pins = [e for e in edges[side] if e[1] != "GND"]
        if not pins:
            continue
        # local frame: u along the edge, v outward
        def to_local(x, y):
            return {"L": (y, -x), "R": (y, x), "T": (x, -y), "B": (x, y)}[side]

        def to_board(u, v):
            return {"L": (cx - v, cy + u), "R": (cx + v, cy + u), "T": (cx + u, cy - v), "B": (cx + u, cy + v)}[side]

        loc = sorted(((*to_local(x, y), hl, p, net) for p, net, x, y, hl in pins), key=lambda t: t[0])
        n = len(loc)
        u_mid = (loc[0][0] + loc[-1][0]) / 2
        targets = [u_mid + (i - (n - 1) / 2) * PITCH_OUT for i in range(n)]
        tip = max(v + hl for u, v, hl, p, net in loc)
        offs = [t - l[0] for t, l in zip(targets, loc)]
        # straight length before the turn: the outermost pad (by position) turns first, each
        # pad further in turns STAGGER later, so the parallel 45 deg legs never close up (also
        # across the gap a skipped GND pin leaves)
        straight = [0.0] * n
        for side_sign in (-1, 1):
            idx = [i for i in range(n) if (offs[i] > 1e-6 if side_sign > 0 else offs[i] < -1e-6)]
            idx.sort(key=lambda i: -side_sign * loc[i][0])
            for rank, i in enumerate(idx):
                straight[i] = FIRST + rank * STAGGER
        v_via = tip + max(straight[i] + abs(offs[i]) for i in range(n)) + VIA_MARGIN
        for i, (u, v, hl, p, net) in enumerate(loc):
            a = to_board(u, v)                       # pad centre
            b1 = to_board(u, tip + straight[i])      # end of the straight stub
            b2 = to_board(targets[i], tip + straight[i] + abs(offs[i]))
            b3 = to_board(targets[i], v_via + (i % 2) * ROW_DV)
            f.track(a, b1, p.GetNet())
            f.track(b1, b2, p.GetNet())
            f.track(b2, b3, p.GetNet())
            f.via(b3, p.GetNet())

    pcbnew.SaveBoard(args.board, b, True)
    print(f"route_led_driver: {f.n} tracks/vias added")
    return 0


if __name__ == "__main__":
    sys.exit(main())
