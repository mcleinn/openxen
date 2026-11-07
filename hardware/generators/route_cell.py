#!/usr/bin/env python3
"""Route the per-key unit cell (sensor, decoupling cap, filter cap, LED stubs) by script.

Run with KiCad's Python:

    python.exe hardware/generators/route_cell.py --board <pcb> [--keys 0] [--all]

Everything is on the bottom copper (B.Cu, the side the parts sit on); vias go to the inner
planes: GND on In1.Cu (L2), +3.3VA pour on In2.Cu (L3). Track geometry is derived from the
actual pad positions, so the same code routes every key. Tracks are tagged by being inside
the cell; re-running first deletes the cell's previous tracks/vias (those within the cell box).

Per key n (nets from the netlist):
  HE{n}.1 (+3.3VA) -> C{n} pad(+3.3VA)   + via to L3 at the cap
  HE{n}.3 (GND)    -> C{n} pad(GND) and CF{n} pad(GND) + vias to L2 at both caps
  HE{n}.2 (HE{n})  -> CF{n} pad(HE{n})   (the mux fan-in continues from this pad later)
  D{n}: short stubs from the four LED pads outward (bus routing joins them later)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pcbnew  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "layout" / "module.json").read_text(encoding="utf-8"))

TRACK_W = 0.25     # mm, signal
POWER_W = 0.35     # mm, VCC/GND inside the cell
VIA_D, VIA_DRILL = 0.6, 0.3
CELL_HALF = 7.0    # cell box half-size around the key centre (inside the 14 mm switch cutout)


def mm(x: float, y: float) -> "pcbnew.VECTOR2I":
    return pcbnew.VECTOR2I_MM(float(x), float(y))


class CellRouter:
    def __init__(self, board: "pcbnew.BOARD"):
        self.b = board
        self.B = pcbnew.B_Cu
        self.L2 = board.GetLayerID("In1.Cu")
        self.L3 = board.GetLayerID("In2.Cu")
        self.added = 0

    # --- primitives -------------------------------------------------------------------
    def track(self, a: tuple[float, float], c: tuple[float, float], net: "pcbnew.NETINFO_ITEM", w: float = TRACK_W, layer: int | None = None) -> None:
        t = pcbnew.PCB_TRACK(self.b)
        t.SetStart(mm(*a))
        t.SetEnd(mm(*c))
        t.SetWidth(pcbnew.FromMM(w))
        t.SetLayer(self.B if layer is None else layer)
        t.SetNet(net)
        self.b.Add(t)
        self.added += 1

    def via(self, p: tuple[float, float], net: "pcbnew.NETINFO_ITEM", to_layer: int) -> None:
        v = pcbnew.PCB_VIA(self.b)
        v.SetPosition(mm(*p))
        v.SetDrill(pcbnew.FromMM(VIA_DRILL))
        v.SetWidth(pcbnew.FromMM(VIA_D))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(net)
        self.b.Add(v)
        self.added += 1

    def route45(self, a: tuple[float, float], c: tuple[float, float], net, w: float = TRACK_W) -> None:
        """Two-segment route: diagonal (45 deg) then straight, from a to c."""
        dx, dy = c[0] - a[0], c[1] - a[1]
        if abs(dx) < 1e-6 or abs(dy) < 1e-6 or abs(abs(dx) - abs(dy)) < 1e-6:
            self.track(a, c, net, w)
            return
        d = min(abs(dx), abs(dy))
        mid = (a[0] + d * (1 if dx > 0 else -1), a[1] + d * (1 if dy > 0 else -1))
        self.track(a, mid, net, w)
        self.track(mid, c, net, w)

    # --- helpers ------------------------------------------------------------------------
    def pads(self, ref: str) -> dict[str, tuple[tuple[float, float], "pcbnew.NETINFO_ITEM"]]:
        fp = self.b.FindFootprintByReference(ref)
        if fp is None:
            raise KeyError(ref)
        out = {}
        for p in fp.Pads():
            if not p.GetNumber():
                continue
            pos = p.GetPosition()
            out[p.GetNumber()] = ((pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)), p.GetNet())
        return out

    def clear_cell(self, cx: float, cy: float) -> int:
        n = 0
        x0, y0, x1, y1 = cx - CELL_HALF, cy - CELL_HALF, cx + CELL_HALF, cy + CELL_HALF
        for t in list(self.b.GetTracks()):
            s, e = t.GetStart(), t.GetEnd()
            sx, sy, ex, ey = (pcbnew.ToMM(v) for v in (s.x, s.y, e.x, e.y))
            if x0 <= sx <= x1 and y0 <= sy <= y1 and x0 <= ex <= x1 and y0 <= ey <= y1:
                self.b.Remove(t)
                n += 1
        return n

    # --- the cell ------------------------------------------------------------------------
    def route_key(self, n: int) -> None:
        k = [k for k in SPEC["keys"] if k["id"] == n][0]
        cx, cy = k["x"], k["y"]
        self.clear_cell(cx, cy)
        he, c, cf, d = self.pads(f"HE{n}"), self.pads(f"C{n}"), self.pads(f"CF{n}"), self.pads(f"D{n}")
        vcc_p, vcc_net = he["1"]
        out_p, out_net = he["2"]
        gnd_p, gnd_net = he["3"]
        c_vcc = [p for p, net in c.values() if net.GetNetname() == vcc_net.GetNetname()][0]
        c_gnd = [p for p, net in c.values() if net.GetNetname() == "GND"][0]
        cf_out = [p for p, net in cf.values() if net.GetNetname() == out_net.GetNetname()][0]
        cf_gnd = [p for p, net in cf.values() if net.GetNetname() == "GND"][0]

        # VCC: sensor pad 1 -> decoupling cap -> via to the +3.3VA pour (L3), placed outboard of the cap
        self.route45(vcc_p, c_vcc, vcc_net, POWER_W)
        v = (c_vcc[0] - 0.9, c_vcc[1] - 0.9)
        self.track(c_vcc, v, vcc_net, POWER_W)
        self.via(v, vcc_net, self.L3)
        # GND: sensor pad 3 -> both caps' GND pads -> vias to the GND plane (L2)
        self.route45(gnd_p, c_gnd, gnd_net, POWER_W)
        self.route45(gnd_p, cf_gnd, gnd_net, POWER_W)
        for g, sgn in ((c_gnd, -1), (cf_gnd, 1)):
            v = (g[0] + sgn * 0.9, g[1] + 0.9)
            self.track(g, v, gnd_net, POWER_W)
            self.via(v, gnd_net, self.L2)
        # OUT: sensor pad 2 -> filter cap
        self.route45(out_p, cf_out, out_net, TRACK_W)
        # OUT escape: on B.Cu the output is enclosed (GND bar below, guide hole + GND via to the
        # right, LED sink lanes above for keys right of their stripe centre), so it leaves the
        # cell through a via to F.Cu, which runs over the GND plane. Middle keys of a stripe have
        # sink lines at x +-2.3 / +3.0 on F.Cu: their via sits in the pocket between them.
        g = SPEC["led"]["key_group"][str(n)]
        middle = abs(cx - (19.2 + 28.8 * g)) < 0.01
        esc = (cx + 1.55, cy - 2.4) if middle else (cx + 1.8, cy - 1.5)
        self.track(out_p, esc, out_net, TRACK_W)
        self.via(esc, out_net, pcbnew.F_Cu)
        # LED: stubs outward (anode/CS to the left, cathodes/SW to the right / up), 1.0 mm
        for num, (p, net) in d.items():
            sx = -1 if p[0] < cx else 1
            self.track(p, (p[0] + sx * 1.0, p[1]), net, TRACK_W)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    ap.add_argument("--keys", default="0", help="comma-separated key ids")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    board = pcbnew.LoadBoard(args.board)
    r = CellRouter(board)
    keys = [k["id"] for k in SPEC["keys"]] if args.all else [int(x) for x in args.keys.split(",")]
    for n in keys:
        r.route_key(n)
    pcbnew.SaveBoard(args.board, board, True)
    print(f"routed {len(keys)} cell(s): {r.added} tracks/vias added")
    return 0


if __name__ == "__main__":
    sys.exit(main())
