#!/usr/bin/env python3
"""Rebuild the whole openxen-m56 board from the sources, deterministically (system Python).

Steps: project files -> schematic -> ERC -> netlist -> board with key field -> HE60 controller
blocks -> muxes and LED driver -> cell routing -> silkscreen -> DRC summary -> renders.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
G = ROOT / "hardware" / "generators"
KPY = r"C:\Program Files\KiCad\9.0\bin\python.exe"
KCLI = r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe"
PRJ = ROOT / "hardware" / "kicad" / "openxen-m56"
SCH, PCB = PRJ / "openxen-m56.kicad_sch", PRJ / "openxen-m56.kicad_pcb"
BUILD = ROOT / "build"
NET = BUILD / "openxen-m56.net"


def run(cmd: list[str], label: str) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = "\n".join(l for l in (r.stdout + r.stderr).splitlines() if "memory leak" not in l)
    print(f"--- {label}\n{out.strip()[-600:]}")
    if r.returncode != 0:
        sys.exit(f"step failed: {label}")


def main() -> int:
    BUILD.mkdir(exist_ok=True)
    run([sys.executable, str(G / "gen_project.py")], "project")
    run([sys.executable, str(G / "gen_schematic.py")], "schematic")
    run([KCLI, "sch", "erc", "--output", str(BUILD / "erc.json"), "--format", "json", "--severity-all", str(SCH)], "erc")
    run([KCLI, "sch", "export", "netlist", "--format", "kicadsexpr", "--output", str(NET), str(SCH)], "netlist")
    run([KPY, str(G / "apply_netlist.py"), "--board", str(PCB), "--netlist", str(NET), "--create"], "board + key field")
    run([KPY, str(G / "copy_he60_blocks.py"), "--board", str(PCB)], "HE60 controller blocks")
    run([KPY, str(G / "place_rest.py"), "--board", str(PCB)], "muxes + LED driver")
    run([KPY, str(G / "route_cell.py"), "--board", str(PCB), "--all"], "cell routing")
    run([KPY, str(G / "tidy_silk.py"), "--board", str(PCB)], "silkscreen")
    run([KCLI, "pcb", "drc", "--output", str(BUILD / "drc.json"), "--format", "json", "--schematic-parity", "--severity-all", str(PCB)], "drc")
    d = json.loads((BUILD / "drc.json").read_text(encoding="utf-8"))
    import collections
    errs = [v for v in d["violations"] if v["severity"] == "error"]
    print("DRC errors:", len(errs), dict(collections.Counter(v["type"] for v in errs)))
    print("unconnected:", len(d.get("unconnected_items", [])), "parity:", len(d.get("schematic_parity", [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
