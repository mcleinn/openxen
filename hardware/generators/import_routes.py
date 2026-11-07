#!/usr/bin/env python3
"""Copy autorouted tracks/vias into the generated board. Run with KiCad's Python.

    python.exe hardware/generators/import_routes.py --board <pcb> --routes <routed pcb>

The routed board comes from TraceMaker run on a copy of the generated board in which every
existing track/via was locked. Its unlocked tracks and vias are therefore exactly the
router's work; they are copied into `--board` by net name (layer, geometry, width, drill
unchanged). Refuses when the footprints moved between the two boards (the routes would no
longer fit): re-route in that case. Zones are refilled afterwards (the router ran with
--soft-zones, i.e. it ignored the fills).
"""
from __future__ import annotations

import argparse
import sys

import pcbnew  # type: ignore


def fp_positions(b) -> dict[str, tuple[int, int, float, int]]:
    return {fp.GetReference(): (fp.GetPosition().x, fp.GetPosition().y, round(fp.GetOrientationDegrees(), 3), fp.GetLayer())
            for fp in b.GetFootprints()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    ap.add_argument("--routes", required=True)
    args = ap.parse_args()
    b = pcbnew.LoadBoard(args.board)
    r = pcbnew.LoadBoard(args.routes)

    pa, pr = fp_positions(b), fp_positions(r)
    moved = sorted(ref for ref in pa if ref in pr and pa[ref] != pr[ref])
    missing = sorted(set(pa) ^ set(pr))
    if moved or missing:
        sys.exit(f"import_routes: placement differs from the routed board (moved {moved[:8]}, "
                 f"missing {missing[:8]}); re-route the current board")

    def sig(t):
        if t.Type() == pcbnew.PCB_VIA_T:
            return ("v", t.GetNetname(), t.GetPosition().x, t.GetPosition().y)
        return ("t", t.GetNetname(), t.GetLayer(), t.GetStart().x, t.GetStart().y, t.GetEnd().x, t.GetEnd().y)

    routed = [t for t in r.GetTracks() if not t.IsLocked()]
    routed_sigs = {sig(t) for t in routed}
    # an earlier import of the same routes is removed (idempotent); everything else on the
    # board is scripted copper and gets locked, like on the copy TraceMaker routed
    removed = 0
    for t in list(b.GetTracks()):
        if sig(t) in routed_sigs:
            b.Remove(t)
            removed += 1
        else:
            t.SetLocked(True)

    nets = {n: b.FindNet(n) for n in set(t.GetNetname() for t in r.GetTracks())}
    added = skipped = 0
    for t in routed:
        net = nets.get(t.GetNetname())
        if net is None:
            skipped += 1
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            v = pcbnew.PCB_VIA(b)
            v.SetPosition(t.GetPosition())
            v.SetViaType(t.GetViaType())
            v.SetDrill(t.GetDrillValue())
            v.SetWidth(t.GetWidth(pcbnew.F_Cu))
            top, bottom = t.TopLayer(), t.BottomLayer()
            v.SetLayerPair(top, bottom)
            v.SetNet(net)
            b.Add(v)
        else:
            n = pcbnew.PCB_TRACK(b)
            n.SetStart(t.GetStart())
            n.SetEnd(t.GetEnd())
            n.SetWidth(t.GetWidth())
            n.SetLayer(t.GetLayer())
            n.SetNet(net)
            b.Add(n)
        added += 1
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(args.board, b, True)
    print(f"import_routes: {added} routed tracks/vias imported ({removed} previous removed, {skipped} on unknown nets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
