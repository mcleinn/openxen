#!/usr/bin/env python3
"""Autorouted tracks/vias: capture them from a routed board, replay them onto the generated
board. Run with KiCad's Python.

    python.exe hardware/generators/import_routes.py --board <pcb> --capture <routed pcb> [--routes JSON]
    python.exe hardware/generators/import_routes.py --board <pcb> [--routes JSON]

TraceMaker routes a copy of the generated board in which every existing track/via was
locked, so its unlocked tracks and vias are exactly the router's work. `--capture` stores
them in `--routes` (default hardware/routes/openxen-m56.routes.json: net name, layer,
geometry in nm, width, drill, plus the footprint placement they were routed against) and
then applies them. Without `--capture` the stored routes are applied (build_board.py step).

Refuses when the footprints moved since the routing (the routes would no longer fit): re-route
in that case. Re-applying is idempotent (identical items are replaced). All other copper is
locked. Zones are refilled afterwards (the router ran with --soft-zones).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pcbnew  # type: ignore

DEFAULT = Path(__file__).resolve().parents[1] / "routes" / "openxen-m56.routes.json"


def placement(b) -> dict[str, list]:
    return {fp.GetReference(): [fp.GetPosition().x, fp.GetPosition().y, round(fp.GetOrientationDegrees(), 3),
                                b.GetLayerName(fp.GetLayer())] for fp in b.GetFootprints()}


def capture(r) -> dict:
    tracks, vias = [], []
    for t in r.GetTracks():
        if t.IsLocked():
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            vias.append([t.GetNetname(), t.GetPosition().x, t.GetPosition().y, t.GetWidth(pcbnew.F_Cu),
                         t.GetDrillValue(), r.GetLayerName(t.TopLayer()), r.GetLayerName(t.BottomLayer())])
        elif t.Type() == pcbnew.PCB_TRACE_T:
            tracks.append([t.GetNetname(), r.GetLayerName(t.GetLayer()), t.GetStart().x, t.GetStart().y,
                           t.GetEnd().x, t.GetEnd().y, t.GetWidth()])
        else:
            sys.exit(f"import_routes: unsupported routed item type {t.GetClass()} (arcs are not captured)")
    tracks.sort(); vias.sort()
    return {"placement": placement(r), "tracks": tracks, "vias": vias}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    ap.add_argument("--capture", help="routed board to take the unlocked tracks/vias from")
    ap.add_argument("--routes", default=str(DEFAULT))
    args = ap.parse_args()
    b = pcbnew.LoadBoard(args.board)
    if args.capture:
        data = capture(pcbnew.LoadBoard(args.capture))
        Path(args.routes).parent.mkdir(parents=True, exist_ok=True)
        with open(args.routes, "w", encoding="utf-8", newline="\n") as f:
            f.write("{\n")
            f.write('"placement": ' + json.dumps(data["placement"], sort_keys=True) + ",\n")
            for key in ("tracks", "vias"):
                f.write(f'"{key}": [\n' + ",\n".join(json.dumps(x) for x in data[key]) + "\n]" + (",\n" if key == "tracks" else "\n"))
            f.write("}\n")
        print(f"import_routes: captured {len(data['tracks'])} tracks, {len(data['vias'])} vias -> {args.routes}")
    data = json.loads(Path(args.routes).read_text(encoding="utf-8"))

    pa, pr = placement(b), data["placement"]
    moved = sorted(ref for ref in pa if ref in pr and pa[ref] != pr[ref])
    missing = sorted(set(pa) ^ set(pr))
    if moved or missing:
        sys.exit(f"import_routes: placement differs from the routed board (moved {moved[:8]}, "
                 f"missing {missing[:8]}); re-route the current board")

    layer = {b.GetLayerName(i): i for i in range(pcbnew.PCB_LAYER_ID_COUNT)}
    wanted = {("t", n, layer[l], x1, y1, x2, y2) for n, l, x1, y1, x2, y2, w in data["tracks"]}
    wanted |= {("v", n, x, y) for n, x, y, *_ in data["vias"]}

    def sig(t):
        if t.Type() == pcbnew.PCB_VIA_T:
            return ("v", t.GetNetname(), t.GetPosition().x, t.GetPosition().y)
        return ("t", t.GetNetname(), t.GetLayer(), t.GetStart().x, t.GetStart().y, t.GetEnd().x, t.GetEnd().y)

    removed = 0
    for t in list(b.GetTracks()):
        if sig(t) in wanted:
            b.Remove(t)
            removed += 1
        else:
            t.SetLocked(True)

    def net(name):
        n = b.FindNet(name)
        if n is None:
            sys.exit(f"import_routes: net {name} not on the board; re-route the current board")
        return n

    for n, l, x1, y1, x2, y2, w in data["tracks"]:
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(pcbnew.VECTOR2I(x1, y1)); t.SetEnd(pcbnew.VECTOR2I(x2, y2))
        t.SetWidth(w); t.SetLayer(layer[l]); t.SetNet(net(n))
        b.Add(t)
    for n, x, y, d, drill, top, bot in data["vias"]:
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(pcbnew.VECTOR2I(x, y)); v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetDrill(drill); v.SetWidth(d); v.SetLayerPair(layer[top], layer[bot]); v.SetNet(net(n))
        b.Add(v)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(args.board, b, True)
    print(f"import_routes: {len(data['tracks'])} tracks, {len(data['vias'])} vias applied ({removed} previous replaced)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
