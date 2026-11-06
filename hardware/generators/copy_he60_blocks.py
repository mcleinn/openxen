#!/usr/bin/env python3
"""Place HE60's controller sub-blocks (footprints + their internal tracks/vias) into the
top-right controller strip of the openxen module. Run with KiCad's Python.

Input: build/he60_blocks.json (from the extraction step in hardware/generators/extract_he60_blocks.py
or the inline script that produced it). Blocks keep their internal geometry; each block is
translated by (target - anchor). Nets are matched by name (our schematic copies HE60's).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pcbnew  # type: ignore

ROOT = Path(__file__).resolve().parents[2]

# target position (mm, our board) of each block's anchor footprint, all on the bottom side
TARGETS = {
    "usb":     ("J1", (48.0, 2.5)),       # USB-C on the top edge, opening outward (HE60 puts J1 2.0 mm from its edge)
    "buttons": ("SW1", (55.5, 36.5)),     # BOOT/RESET buttons + pull-down, pocket below keys 3/4 (right of mux AM0)
    "swd":     ("J3", (54.5, 15.6)),      # TC2030 pads
    "ldo":     ("U2", (66.0, 13.9)),      # LDOs, ESD, fuse in a row (x 61..85)
    "mcu":     ("U4", (97.5, 9.5)),       # MCU + crystal + decoupling, right end of the strip
}


def mm(x: float, y: float) -> "pcbnew.VECTOR2I":
    return pcbnew.VECTOR2I_MM(float(x), float(y))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    ap.add_argument("--blocks", default=str(ROOT / "build" / "he60_blocks.json"))
    args = ap.parse_args()
    blocks = json.loads(Path(args.blocks).read_text(encoding="utf-8"))
    b = pcbnew.LoadBoard(args.board)
    nets = {b.GetNetInfo().GetNetItem(i).GetNetname(): b.GetNetInfo().GetNetItem(i) for i in range(1, b.GetNetInfo().GetNetCount())}
    layer_id = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu}
    moved = tracks = vias = skipped = 0
    for name, (anchor_ref, target) in TARGETS.items():
        blk = blocks[name]
        anchor = [f for f in blk["footprints"] if f["ref"] == anchor_ref][0]
        dx, dy = target[0] - anchor["x"], target[1] - anchor["y"]
        for f in blk["footprints"]:
            fp = b.FindFootprintByReference(f["ref"])
            if fp is None:
                if f["ref"] != "J2":
                    print("  missing footprint", f["ref"])
                continue
            if f["layer"] == "B.Cu" and not fp.IsFlipped():
                fp.SetLayerAndFlip(pcbnew.B_Cu)
            elif f["layer"] == "F.Cu" and fp.IsFlipped():
                fp.SetLayerAndFlip(pcbnew.F_Cu)
            fp.SetPosition(mm(f["x"] + dx, f["y"] + dy))
            fp.SetOrientationDegrees(f["rot"])
            moved += 1
        # the ESD-to-connector USB pair is re-routed to our connector position: skip HE60's copy of it
        drop_nets = {"USB_PLUG_D+", "USB_PLUG_D-"} if name == "ldo" else set()
        for s in blk["segments"]:
            net = nets.get(s["net"])
            if net is None or s["net"] in drop_nets:
                skipped += 1
                continue
            t = pcbnew.PCB_TRACK(b)
            t.SetStart(mm(s["start"][0] + dx, s["start"][1] + dy))
            t.SetEnd(mm(s["end"][0] + dx, s["end"][1] + dy))
            t.SetWidth(pcbnew.FromMM(s["width"]))
            t.SetLayer(layer_id[s["layer"]])
            t.SetNet(net)
            b.Add(t)
            tracks += 1
        for v in blk["vias"]:
            net = nets.get(v["net"])
            if net is None or v["net"] in drop_nets:
                skipped += 1
                continue
            via = pcbnew.PCB_VIA(b)
            via.SetPosition(mm(v["at"][0] + dx, v["at"][1] + dy))
            via.SetWidth(pcbnew.FromMM(v["size"]))
            via.SetDrill(pcbnew.FromMM(v["drill"]))
            via.SetViaType(pcbnew.VIATYPE_THROUGH)
            via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            via.SetNet(net)
            b.Add(via)
            vias += 1
        print(f"{name:8} anchored {anchor_ref} -> {target}: shift ({dx:+.2f},{dy:+.2f})")
    # drop copied tracks/vias that do not reach any pad (stubs that led to other HE60 regions)
    b.BuildConnectivity()
    conn = b.GetConnectivity()
    def reaches_pad(start) -> bool:
        seen = {start.m_Uuid.AsString()}
        frontier = [start]
        while frontier:
            it = frontier.pop()
            if conn.GetConnectedPads(it):
                return True
            for nb in conn.GetConnectedTracks(it):
                k = nb.m_Uuid.AsString()
                if k not in seen:
                    seen.add(k)
                    frontier.append(nb)
        return False
    dropped = 0
    for t in list(b.GetTracks()):
        if not reaches_pad(t):
            b.Remove(t)
            dropped += 1
    # prune dangling leaf tracks iteratively (stubs that led to other HE60 regions)
    while True:
        b.BuildConnectivity()
        conn = b.GetConnectivity()
        leaf = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T and conn.TestTrackEndpointDangling(t, False)]
        # vias left with a single connection are dead ends too
        leaf += [v for v in b.GetTracks() if v.Type() == pcbnew.PCB_VIA_T and (len(conn.GetConnectedTracks(v)) + len(conn.GetConnectedPads(v))) < 2]
        if not leaf:
            break
        for t in leaf:
            b.Remove(t)
            dropped += 1
    pcbnew.SaveBoard(args.board, b, True)
    print(f"moved {moved} footprints, copied {tracks} tracks and {vias} vias, skipped {skipped} items on unknown nets, dropped {dropped} floating stubs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
