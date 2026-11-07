#!/usr/bin/env python3
"""Rebuild the whole openxen-m56 board from the sources, deterministically (system Python).

Steps: project files -> schematic -> ERC -> netlist -> board with key field -> HE60 controller
blocks -> muxes and LED driver -> cell routing -> LED sink lines -> plane vias -> silkscreen
-> planes -> autorouted tracks (hardware/routes/*.routes.json) -> DRC -> firmware -> fab
files -> tests.

Autorouting (TraceMaker, see .claude/skills/tracemaker or docs/testing.md) runs off-line on
a copy of this board; an accepted result is captured with import_routes.py --capture and
replayed here, so a rebuild never silently loses it. If the placement changed since the
routing, the replay refuses and the board has to be re-routed (`--no-routes` builds the
unrouted board for that).
"""
from __future__ import annotations

import argparse
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-routes", action="store_true", help="skip replaying the autorouted tracks (board for a new routing run)")
    args = ap.parse_args()
    BUILD.mkdir(exist_ok=True)
    run([sys.executable, str(G / "gen_project.py")], "project")
    run([sys.executable, str(G / "gen_schematic.py")], "schematic")
    run([KCLI, "sch", "erc", "--output", str(BUILD / "erc.json"), "--format", "json", "--severity-all", str(SCH)], "erc")
    run([KCLI, "sch", "export", "netlist", "--format", "kicadsexpr", "--output", str(NET), str(SCH)], "netlist")
    run([KPY, str(G / "apply_netlist.py"), "--board", str(PCB), "--netlist", str(NET), "--create"], "board + key field")
    run([KPY, str(G / "copy_he60_blocks.py"), "--board", str(PCB)], "HE60 controller blocks")
    run([KPY, str(G / "place_rest.py"), "--board", str(PCB)], "muxes + LED driver")
    run([KPY, str(G / "route_cell.py"), "--board", str(PCB), "--all"], "cell routing")
    run([KPY, str(G / "route_led_sw.py"), "--board", str(PCB)], "LED sink lines")
    run([KPY, str(G / "route_led_driver.py"), "--board", str(PCB)], "LED driver fan-out (U10)")
    run([KPY, str(G / "route_vbus.py"), "--board", str(PCB)], "VBUS J1 -> F1 (0.8 mm)")
    run([KPY, str(G / "add_plane_vias.py"), "--board", str(PCB)], "+3.3VA pads -> plane vias")
    run([KPY, str(G / "tidy_silk.py"), "--board", str(PCB)], "silkscreen")
    run([KPY, str(G / "add_zones.py"), "--board", str(PCB)], "planes (GND In1, +3.3VA In2)")
    import os
    if args.no_routes:
        os.environ["OPENXEN_NO_ROUTES"] = "1"     # tests: the unrouted board is expected
    routes = ROOT / "hardware" / "routes" / "openxen-m56.routes.json"
    if routes.exists() and not args.no_routes:
        run([KPY, str(G / "import_routes.py"), "--board", str(PCB), "--routes", str(routes)], "autorouted tracks (TraceMaker)")
        run([KPY, str(G / "widen_power.py"), "--board", str(PCB)], "widen necked-down power tracks")
    run([KCLI, "pcb", "drc", "--output", str(BUILD / "drc.json"), "--format", "json", "--schematic-parity", "--severity-all", str(PCB)], "drc")
    d = json.loads((BUILD / "drc.json").read_text(encoding="utf-8"))
    import collections
    errs = [v for v in d["violations"] if v["severity"] == "error"]
    print("DRC errors:", len(errs), dict(collections.Counter(v["type"] for v in errs)))
    print("unconnected:", len(d.get("unconnected_items", [])), "parity:", len(d.get("schematic_parity", [])))
    run([sys.executable, str(G.parents[1] / "firmware" / "generators" / "gen_keyboard_json.py")], "firmware keyboard.json")
    run([sys.executable, str(G.parents[1] / "firmware" / "build_firmware.py")], "firmware build (libhmk, PlatformIO)")
    run([sys.executable, str(G.parents[1] / "hardware" / "fab" / "make_fab.py")], "production files (Fabrication Toolkit)")
    run([sys.executable, "-m", "pytest", "-q", str(G.parents[1] / "tests")], "consistency tests (tests/)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
