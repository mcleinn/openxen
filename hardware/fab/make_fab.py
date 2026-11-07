#!/usr/bin/env python3
"""JLCPCB production files (Gerbers + drill zip, BOM, pick-and-place) via the Fabrication
Toolkit plugin's CLI, run on a copy of the board so the KiCad project is never modified.

    python hardware/fab/make_fab.py      (system Python; calls KiCad's Python for the plugin)

Output: build/fab/production/ (openxen-m56.zip, openxen-m56_bom.csv, openxen-m56_positions.csv).
Options used: --autoTranslate (the plugin's community rotation table for SOT-23/TSSOP/LQFP/QFN
packages), --nonInteractive, --noBackup. Zones are refilled by the plugin's own step.
Per-part corrections from hardware/fab/jlc_corrections.json (found by check_jlc_placement.py)
are written onto the copy's footprints as the toolkit's 'FT Rotation Offset' / 'FT Position
Offset' fields before it runs.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRJ = ROOT / "hardware" / "kicad" / "openxen-m56"
FAB = ROOT / "build" / "fab"
TOOLKIT = ROOT / "reference" / "repos" / "Fabrication-Toolkit"
KPY = r"C:\Program Files\KiCad\9.0\bin\python.exe"


CORRECTIONS = r"""
import json, sys
import pcbnew
board, table = sys.argv[1], json.load(open(sys.argv[2], encoding="utf-8"))
b = pcbnew.LoadBoard(board)
n = 0
for fp in b.GetFootprints():
    lcsc = fp.GetFieldText("LCSC Part #") if fp.HasFieldByName("LCSC Part #") else ""
    c = table.get(lcsc)
    if not c:
        continue
    if "rotation" in c:
        fp.SetField("FT Rotation Offset", str(c["rotation"]))
    if "position" in c:
        fp.SetField("FT Position Offset", "%s,%s" % tuple(c["position"]))
    n += 1
pcbnew.SaveBoard(board, b)
print("jlc corrections on", n, "footprints")
"""


def apply_corrections(board: Path) -> None:
    r = subprocess.run([KPY, "-c", CORRECTIONS, str(board), str(Path(__file__).with_name("jlc_corrections.json"))],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("applying jlc_corrections.json failed: " + r.stderr[-1500:])
    print(r.stdout.strip().splitlines()[-1])


def main() -> int:
    if FAB.exists():
        shutil.rmtree(FAB)
    FAB.mkdir(parents=True)
    for f in ("openxen-m56.kicad_pcb", "openxen-m56.kicad_pro", "fp-lib-table", "sym-lib-table"):
        shutil.copy(PRJ / f, FAB / f)
    shutil.copytree(ROOT / "hardware" / "kicad" / "lib", FAB.parent / "lib", dirs_exist_ok=True)   # ${KIPRJMOD}/../lib
    apply_corrections(FAB / "openxen-m56.kicad_pcb")
    cmd = [KPY, "-m", "plugins.cli", "-p", str(FAB / "openxen-m56.kicad_pcb"), "-t", "-nI", "-nB", "-aN", "openxen-m56"]
    r = subprocess.run(cmd, cwd=str(TOOLKIT), capture_output=True, text=True)
    out = FAB / "production"
    if r.returncode != 0 or not out.exists():
        print(r.stdout[-2000:], r.stderr[-2000:])
        raise SystemExit("Fabrication Toolkit failed")
    print("production files:", sorted(p.name for p in out.iterdir()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
