#!/usr/bin/env python3
"""JLCPCB production files (Gerbers + drill zip, BOM, pick-and-place) via the Fabrication
Toolkit plugin's CLI, run on a copy of the board so the KiCad project is never modified.

    python hardware/fab/make_fab.py      (system Python; calls KiCad's Python for the plugin)

Output: build/fab/production/ (openxen-m56.zip, openxen-m56_bom.csv, openxen-m56_positions.csv).
Options used: --autoTranslate (the plugin's community rotation table for SOT-23/TSSOP/LQFP/QFN
packages), --nonInteractive, --noBackup. Zones are refilled by the plugin's own step.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRJ = ROOT / "hardware" / "kicad" / "openxen-m56"
FAB = ROOT / "build" / "fab"
TOOLKIT = ROOT / "reference" / "repos" / "Fabrication-Toolkit"
KPY = r"C:\Program Files\KiCad\9.0\bin\python.exe"


def main() -> int:
    if FAB.exists():
        shutil.rmtree(FAB)
    FAB.mkdir(parents=True)
    for f in ("openxen-m56.kicad_pcb", "openxen-m56.kicad_pro", "fp-lib-table", "sym-lib-table"):
        shutil.copy(PRJ / f, FAB / f)
    shutil.copytree(ROOT / "hardware" / "kicad" / "lib", FAB.parent / "lib", dirs_exist_ok=True)   # ${KIPRJMOD}/../lib
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
