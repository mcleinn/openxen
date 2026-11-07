#!/usr/bin/env python3
"""Route the 12 LED sink lines (LED_SW0..11, IS31FL3733 SW outputs) by script. KiCad Python.

    python.exe hardware/generators/route_led_sw.py --board <pcb>

Topology (layout/module.json "led"): four vertical stripes of 14 keys; stripe g uses SW lines
3g (R), 3g+1 (G), 3g+2 (B). Each stripe has a middle key column x_m (19.2, 48.0, 76.8,
105.6) and the other key column at x_m +- 9.6 in the alternate rows.

Geometry (per key, bottom-side LED at (0, -5.08) relative to the key centre, y down):
  pad 1 = anode (-1.55, -4.53), pad 4 = B cathode (-1.55, -5.63), pad 2 = R (+1.55, -4.53),
  pad 3 = G (+1.55, -5.63) (the LED's bottom view, see the footprint); the cell script leaves
  1 mm stubs outward from every pad.
  Between the LED and the sensor the band y in (-4.0, -1.6) is free; the top layer is empty
  apart from holes and via barrels.

Routing:
  * The three SW lines of a stripe are straight vertical 0.4 mm tracks on F.Cu at
    x_m + 2.3 (R), x_m + 3.0 (G) and x_m - 2.3 (B). Those x positions clear the LED holes
    (|dx| >= 1.5), the guide holes and vias of both key columns, and the M3 holes in the
    19.2 / 105.6 columns (0.5 mm).
  * Every LED feeds its three cathodes to the lines on B.Cu and drops a 0.5/0.3 via on the
    line. Middle keys: vias straight on the stubs. Keys left of x_m: R/G feeders run right
    along the stub rows. Keys right of x_m: R/G dip into the LED/sensor band (y - 2.9 / -2.2)
    and run left. B of both side keys leaves its upper-left pad over the top of the LED
    (y - 6.6, clear of the LED hole and of the M3 screw heads) to the shared via on the B line;
    going down would cross the anode stub below it.
  * Lines end 1 mm beyond the last via; the LED driver fan-in (12 short connections at the
    bottom-left) is left to the autorouter.
Re-running deletes all LED_SW copper first (stubs included; they are re-created).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pcbnew  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "layout" / "module.json").read_text(encoding="utf-8"))

LINE_W = 0.4        # SW line (<= 14 LEDs x 42 mA peak at 1/12 duty)
FEED_W = 0.3
STUB_W = 0.25
VIA_D, VIA_DRILL = 0.5, 0.3
X_MID = {0: 19.2, 1: 48.0, 2: 76.8, 3: 105.6}
DX = {"R": 2.3, "G": 3.0, "B": -2.3}          # line offsets from x_m
PAD = {"R": "2", "G": "3", "B": "4"}           # LED pad numbers (Device:LED_ARGB numbering)
PAD_POS = {"R": (1.55, -4.53), "G": (1.55, -5.63), "B": (-1.55, -5.63)}
Y_TOP = -6.6        # B lane over the LED for the side keys


def mm(x: float, y: float) -> "pcbnew.VECTOR2I":
    return pcbnew.VECTOR2I_MM(float(x), float(y))


class SWRouter:
    def __init__(self, b: "pcbnew.BOARD"):
        self.b = b
        self.F, self.B = pcbnew.F_Cu, pcbnew.B_Cu
        self.n = 0
        self.vias_y: dict[tuple[int, str], list[float]] = {}
        self.placed: set[tuple[float, float]] = set()

    def net(self, name: str) -> "pcbnew.NETINFO_ITEM":
        ni = self.b.FindNet(name)
        if ni is None:
            raise SystemExit(f"net {name} missing")
        return ni

    def track(self, a, c, net, w, layer):
        t = pcbnew.PCB_TRACK(self.b)
        t.SetStart(mm(*a)); t.SetEnd(mm(*c)); t.SetWidth(pcbnew.FromMM(w)); t.SetLayer(layer); t.SetNet(net)
        self.b.Add(t); self.n += 1

    def path(self, pts, net, w, layer=None):
        for a, c in zip(pts, pts[1:]):
            self.track(a, c, net, w, self.B if layer is None else layer)

    def via(self, p, net):
        key = (round(p[0], 2), round(p[1], 2))
        if key in self.placed:                          # left and right key of a row share one via
            return
        self.placed.add(key)
        v = pcbnew.PCB_VIA(self.b)
        v.SetPosition(mm(*p)); v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetDrill(pcbnew.FromMM(VIA_DRILL)); v.SetWidth(pcbnew.FromMM(VIA_D))
        v.SetLayerPair(self.F, self.B); v.SetNet(net); self.b.Add(v); self.n += 1

    def clear(self) -> int:
        n = 0
        for t in list(self.b.GetTracks()):
            if t.GetNetname().startswith("LED_SW"):
                self.b.Remove(t); n += 1
        return n

    def route_key(self, k: dict) -> None:
        kid, kx, ky = k["id"], k["x"], k["y"]
        g = SPEC["led"]["key_group"][str(kid)]
        sw = SPEC["led"]["sw_lines"][str(g)]
        xm = X_MID[g]
        parity = "M" if abs(kx - xm) < 0.01 else ("L" if kx < xm else "R")
        for col in ("R", "G", "B"):
            net = self.net(f"LED_SW{sw[col]}")
            px, py = kx + PAD_POS[col][0], ky + PAD_POS[col][1]
            sx = 1 if PAD_POS[col][0] > 0 else -1
            stub_end = (px + sx * 1.0, py)
            self.track((px, py), stub_end, net, STUB_W, self.B)
            lx = xm + DX[col]
            if parity == "M":
                if col == "G":
                    self.track(stub_end, (lx, py), net, FEED_W, self.B)
                vp = (lx, py)
            elif parity == "L":
                if col in ("R", "G"):
                    self.track(stub_end, (lx, py), net, FEED_W, self.B)
                    vp = (lx, py)
                else:                                   # B: over the top of the LED, run right (same lane as the right key's B)
                    yl = ky + Y_TOP
                    self.path([stub_end, (stub_end[0], yl), (lx, yl)], net, FEED_W)
                    vp = (lx, yl)
            else:                                       # right of x_m: everything runs left through the LED/sensor band
                # R (lower pad) takes the inner riser x +3.3 to lane -2.9, G (upper pad) the
                # outer riser x +4.05 to lane -2.2, so no riser crosses another net's lane or
                # stub; B goes over the top like the left key's
                if col == "R":
                    yl = ky - 2.9
                    ext = (stub_end[0] + 0.75, py)
                    self.path([stub_end, ext, (ext[0], yl), (lx, yl)], net, FEED_W)
                elif col == "G":
                    yl = ky - 2.2
                    ext = (stub_end[0] + 1.5, py)
                    self.path([stub_end, ext, (ext[0], yl), (lx, yl)], net, FEED_W)
                else:
                    yl = ky + Y_TOP
                    self.path([stub_end, (stub_end[0], yl), (lx, yl)], net, FEED_W)
                vp = (lx, yl)
            self.via(vp, net)
            self.vias_y.setdefault((g, col), []).append(vp[1])

    def lines(self) -> None:
        for (g, col), ys in sorted(self.vias_y.items()):
            net = self.net(f"LED_SW{SPEC['led']['sw_lines'][str(g)][col]}")
            x = X_MID[g] + DX[col]
            self.track((x, min(ys)), (x, max(ys) + 1.0), net, LINE_W, self.F)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    args = ap.parse_args()
    b = pcbnew.LoadBoard(args.board)
    r = SWRouter(b)
    removed = r.clear()
    for k in sorted(SPEC["keys"], key=lambda k: k["id"]):
        r.route_key(k)
    r.lines()
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())        # new vias through the planes need fresh anti-pads
    pcbnew.SaveBoard(args.board, b, True)
    print(f"route_led_sw: removed {removed} old LED_SW items, added {r.n} tracks/vias; 12 lines on F.Cu")
    return 0


if __name__ == "__main__":
    sys.exit(main())
