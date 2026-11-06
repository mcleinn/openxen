#!/usr/bin/env python3
"""Route the remaining ratsnest of the whole board with Freerouting (headless), keeping all
existing tracks, vias and zones. Run with KiCad's Python.

    python.exe hardware/generators/freeroute_board.py --board <pcb> [--passes 40]

Writes build/freerouting/board.dsn / board.ses and imports the session back into the board.
Net-class widths come from the project's net classes (exported into the DSN; the board must be
loaded with its .kicad_pro next to it). Pre-existing wires are exported as "protect" (fixed).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import pcbnew  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "reference" / "tools"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    ap.add_argument("--passes", type=int, default=40)
    ap.add_argument("--timeout", type=int, default=6 * 3600, help="seconds; Freerouting writes the SES only at the end")
    ap.add_argument("--threads", type=int, default=4, help="optimizer threads (memory grows with it)")
    ap.add_argument("--xmx", default="3g", help="Java heap cap; this machine has 8 GB")
    args = ap.parse_args()
    out_dir = ROOT / "build" / "freerouting"
    out_dir.mkdir(parents=True, exist_ok=True)
    dsn, ses = out_dir / "board.dsn", out_dir / "board.ses"
    board = pcbnew.LoadBoard(args.board)
    before = len(list(board.GetTracks()))
    if not pcbnew.ExportSpecctraDSN(board, str(dsn)):
        raise SystemExit("DSN export failed")
    # Existing tracks (cell routing, HE60 blocks) are reviewed work: mark them "protect" so
    # Freerouting treats them as user-fixed and routes only the open ratsnest around them.
    txt = dsn.read_text(encoding="utf-8")
    fixed = txt.count("(type route)")
    txt = txt.replace("(type route)", "(type protect)")
    # Inner layers are the GND / +3.3VA planes: declare them "power" so Freerouting only
    # routes on F.Cu / B.Cu and never cuts a plane with a trace (vias through them are fine).
    # Drop the plane polygons: Freerouting counts every via of another net inside a plane as
    # a fixed clearance violation (225 of them here) and cannot route around them. KiCad's
    # zone fill makes the anti-pads after the import anyway, and the inner layers are
    # declared "power" below, so Freerouting never needs the planes.
    while "(plane " in txt:
        i = txt.index("(plane ")
        depth, j = 0, i
        while True:
            if txt[j] == "(":
                depth += 1
            elif txt[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        txt = txt[:i] + txt[j + 1:]
    nl = chr(10)
    for lay in ("In1.Cu", "In2.Cu"):
        txt = txt.replace("(layer %s%s      (type signal)" % (lay, nl), "(layer %s%s      (type power)" % (lay, nl))
    dsn.write_text(txt, encoding="utf-8")
    print("DSN:", dsn.stat().st_size, "bytes; tracks before:", before, "; wires protected:", fixed)
    java = next(TOOLS.glob("jre25/*/bin/java.exe"))
    jar = TOOLS / "freerouting-2.5.0.jar"
    if ses.exists():
        ses.unlink()
    # no fanout stage: it would put a via next to every SMD pad (cells are already routed by route_cell.py)
    cmd = [str(java), f"-Xmx{args.xmx}", "-jar", str(jar), "-de", str(dsn), "-do", str(ses), "-mp", str(args.passes), "-l", "en",
           "-mt", str(args.threads), "--router.fanout.enabled=false", "--gui.enabled=false"]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout, cwd=str(out_dir))
    print(f"freerouting: {time.time() - t0:.0f} s")
    print("\n".join((r.stdout + r.stderr).strip().splitlines()[-8:]))
    if not ses.exists():
        raise SystemExit("no SES produced")
    board = pcbnew.LoadBoard(args.board)
    if not pcbnew.ImportSpecctraSES(board, str(ses)):
        raise SystemExit("SES import failed")
    after = len(list(board.GetTracks()))
    pcbnew.SaveBoard(args.board, board, True)
    print("tracks after import:", after, "(+%d)" % (after - before))
    return 0


if __name__ == "__main__":
    sys.exit(main())
