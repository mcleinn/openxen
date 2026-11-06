#!/usr/bin/env python3
"""Route the remaining ratsnest of the whole board with Freerouting (headless), keeping all
existing tracks, vias and zones. Run with KiCad's Python.

    python.exe hardware/generators/freeroute_board.py --board <pcb> [--passes 2] [--rounds 6]

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


def export_dsn(board_path: str, dsn: Path) -> int:
    board = pcbnew.LoadBoard(board_path)
    before = len(list(board.GetTracks()))
    if not pcbnew.ExportSpecctraDSN(board, str(dsn)):
        raise SystemExit("DSN export failed")
    # Existing tracks (cell routing, HE60 blocks, earlier rounds) are reviewed work: mark them
    # "protect" so Freerouting treats them as user-fixed and routes only the open ratsnest.
    txt = dsn.read_text(encoding="utf-8")
    fixed = txt.count("(type route)")
    txt = txt.replace("(type route)", "(type protect)")
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
    # KiCad exports every NPTH hole as a keepout circle of hole diameter + 2 x 0.2 mm, and
    # Freerouting then adds its own 0.2 mm clearance on top: the LED stubs (0.47 mm from the
    # LED hole, DRC-clean) were flagged as 224 "unfixable" violations, which crippled the LED
    # matrix routing. Shrink the keepouts back to the bare hole so the clearance applies once.
    import re
    txt = re.sub(r"\(keepout \"\" \(circle (\S+) (\d+)", lambda m: '(keepout "" (circle %s %d' % (m.group(1), int(m.group(2)) - 400), txt)
    nl = chr(10)
    for lay in ("In1.Cu", "In2.Cu"):
        txt = txt.replace("(layer %s%s      (type signal)" % (lay, nl), "(layer %s%s      (type power)" % (lay, nl))
    dsn.write_text(txt, encoding="utf-8")
    print("DSN:", dsn.stat().st_size, "bytes; tracks before:", before, "; wires protected:", fixed)
    return before


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    ap.add_argument("--passes", type=int, default=2, help="auto-routing passes per round")
    ap.add_argument("--rounds", type=int, default=1, help="rounds; the board is saved after every round, so a killed run loses at most one round")
    ap.add_argument("--timeout", type=int, default=6 * 3600, help="seconds per round; Freerouting writes the SES only at the end of a round")
    ap.add_argument("--threads", type=int, default=4, help="optimizer threads (memory grows with it)")
    ap.add_argument("--xmx", default="3g", help="Java heap cap; this machine has 8 GB (use e.g. 24g with --remote)")
    ap.add_argument("--remote", default="", help="user@host: run Freerouting there over SSH (needs ~/jre/*/bin/java and ~/freerouting/freerouting-2.5.0.jar on the host)")
    ap.add_argument("--ssh-key", default=str(Path.home() / ".ssh" / "openxen_vm"))
    args = ap.parse_args()
    out_dir = ROOT / "build" / "freerouting"
    out_dir.mkdir(parents=True, exist_ok=True)
    dsn, ses = out_dir / "board.dsn", out_dir / "board.ses"
    java = next(TOOLS.glob("jre25/*/bin/java.exe"))
    jar = TOOLS / "freerouting-2.5.0.jar"
    for rnd in range(1, args.rounds + 1):
        print(f"=== round {rnd}/{args.rounds}")
        before = export_dsn(args.board, dsn)
        if ses.exists():
            ses.unlink()
        fr_args = ["-mp", str(args.passes), "-l", "en", "-mt", str(args.threads), "--router.fanout.enabled=false", "--gui.enabled=false",
                   "--router.ignore_net_classes=Plane"]   # GND / +3.3VA live on the inner planes (vias by add_plane_vias.py)
        t0 = time.time()
        if args.remote:
            ssh = ["ssh", "-i", args.ssh_key, "-o", "BatchMode=yes", args.remote]
            scp = ["scp", "-i", args.ssh_key, "-o", "BatchMode=yes", "-q"]
            subprocess.run(scp + [str(dsn), f"{args.remote}:~/freerouting/board.dsn"], check=True, timeout=600)
            remote_cmd = ("cd ~/freerouting && rm -f board.ses && ~/jre/*/bin/java -Xmx%s -jar freerouting-2.5.0.jar -de board.dsn -do board.ses %s"
                          % (args.xmx, " ".join(fr_args)))
            r = subprocess.run(ssh + [remote_cmd], capture_output=True, text=True, timeout=args.timeout)
            subprocess.run(scp + [f"{args.remote}:~/freerouting/board.ses", str(ses)], timeout=600)
        else:
            cmd = [str(java), f"-Xmx{args.xmx}", "-jar", str(jar), "-de", str(dsn), "-do", str(ses)] + fr_args
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout, cwd=str(out_dir))
        print(f"freerouting: {time.time() - t0:.0f} s")
        lines = [l for l in (r.stdout + r.stderr).splitlines() if "INFO" in l and ("pass #" in l or "stage completed" in l or "Optimization" in l)]
        print(chr(10).join(l[:200] for l in lines[-6:]))
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
