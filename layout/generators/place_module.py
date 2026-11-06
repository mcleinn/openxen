#!/usr/bin/env python3
"""Place the openxen module key field in a KiCad 9 board from ``layout/module.json``.

Run with KiCad's bundled Python (it ships the ``pcbnew`` module):

    "C:\\Program Files\\KiCad\\9.0\\bin\\python.exe" layout/generators/place_module.py \
        --board build/test/openxen-m56-test.kicad_pcb --create

Modes
* ``--create``: start from an empty 4-layer board, add outline, holes and the 56 unit cells.
* default (update): open an existing board, move/rotate footprints found by reference,
  create the ones that are missing, (re)draw outline + LED cutouts on Edge.Cuts.

Reference scheme per key ``n`` (0..55): ``Kn`` switch (``SWn`` is taken by HE60's buttons), ``HEn`` Hall sensor, ``Dn`` LED,
``Cn`` sensor decoupling, ``CFn`` sensor output filter. Holes ``H1..H8``.
Footprints are looked up in the libraries given by ``--lib NAME=PATH`` (defaults cover the
KiCad system libraries and the HE60 library in ``reference/repos``). Commit the board before
running in update mode and diff afterwards.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import pcbnew  # type: ignore
except ImportError:  # pragma: no cover
    sys.exit("pcbnew not importable: run this with KiCad's python.exe (see module docstring)")

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "layout" / "module.json"
KICAD_FP = Path(os.environ.get("KICAD9_FOOTPRINT_DIR", r"C:\Program Files\KiCad\9.0\share\kicad\footprints"))

DEFAULT_LIBS = {
    "openxen": ROOT / "hardware" / "kicad" / "lib" / "openxen.pretty",
    "HE60": ROOT / "reference" / "repos" / "HE60" / "HE60" / "lib" / "HE60.pretty",
    "Package_TO_SOT_SMD": KICAD_FP / "Package_TO_SOT_SMD.pretty",
    "LED_SMD": KICAD_FP / "LED_SMD.pretty",
    "Capacitor_SMD": KICAD_FP / "Capacitor_SMD.pretty",
    "MountingHole": KICAD_FP / "MountingHole.pretty",
}

# Footprint choices (library:name). The switch uses HE60's MX-1U until our own
# ``openxen:SW_Lekker_1u`` exists (identical holes; ours adds the LED cutout keep-out).
FP = {
    "switch": ("openxen", "SW_Lekker_1u"),
    "sensor": ("Package_TO_SOT_SMD", "SOT-23"),
    "led": ("openxen", "LED_RGB_1206R_MHT151RGBCT"),  # reverse-mount 1206 RGB; its 2.1 mm NPTH is the light hole
    "cap": ("Capacitor_SMD", "C_0402_1005Metric"),
    "hole": ("MountingHole", "MountingHole_3.2mm"),  # plain hole, no pad: standoff heads sit between the 14 mm switch housings
}

# Passive offsets relative to the switch centre (mm, x right, y down); bottom side.
# Sensor (SOT-23, rot -90, flipped): VCC pad top-left (-0.95,-0.94), OUT pad top-right (0.95,-0.94),
# GND pad bottom (0,0.94). Decoupling cap left of the sensor, filter cap right of it, both vertical
# with their "pad 1" (VCC / OUT) at the top and GND at the bottom; clear of the guide holes at +-5.08.
CAP_OFFSETS = {"C": (-3.3, 0.0), "CF": (3.3, 0.0)}
CAP_ROT = -90


def mm(x: float, y: float) -> "pcbnew.VECTOR2I":
    return pcbnew.VECTOR2I_MM(float(x), float(y))


class Placer:
    def __init__(self, board: "pcbnew.BOARD", libs: dict[str, Path]):
        self.board = board
        self.libs = libs
        self.by_ref = {fp.GetReference(): fp for fp in board.GetFootprints()}
        self.created = 0
        self.moved = 0

    def load(self, lib: str, name: str) -> "pcbnew.FOOTPRINT":
        path = self.libs[lib]
        fp = pcbnew.FootprintLoad(str(path), name)
        if fp is None:
            raise SystemExit(f"footprint {lib}:{name} not found in {path}")
        return fp

    def ensure(self, ref: str, lib: str, name: str, x: float, y: float, rot: float, bottom: bool, value: str = "") -> None:
        fp = self.by_ref.get(ref)
        if fp is None:
            fp = self.load(lib, name)
            fp.SetFPIDAsString(f"{lib}:{name}")
            fp.SetReference(ref)
            if ref[0] in "KH":  # switches and mounting holes are not in the schematic
                fp.SetBoardOnly(True)
                fp.SetExcludedFromBOM(True)
                fp.SetExcludedFromPosFiles(True)
            if value:
                fp.SetValue(value)
            self.board.Add(fp)
            self.by_ref[ref] = fp
            self.created += 1
        else:
            self.moved += 1
        if bottom and not fp.IsFlipped():
            fp.SetLayerAndFlip(pcbnew.B_Cu)
        elif not bottom and fp.IsFlipped():
            fp.SetLayerAndFlip(pcbnew.F_Cu)
        fp.SetPosition(mm(x, y))
        fp.SetOrientationDegrees(rot)

    # --- drawings -------------------------------------------------------------------
    def clear_edge_cuts(self) -> None:
        for d in list(self.board.GetDrawings()):
            if d.GetLayer() == pcbnew.Edge_Cuts:
                self.board.Remove(d)

    def segment(self, a: tuple[float, float], b: tuple[float, float], layer: int = pcbnew.Edge_Cuts, width: float = 0.1) -> None:
        s = pcbnew.PCB_SHAPE(self.board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(mm(*a))
        s.SetEnd(mm(*b))
        s.SetLayer(layer)
        s.SetWidth(pcbnew.FromMM(width))
        self.board.Add(s)

    def rect(self, cx: float, cy: float, w: float, h: float, layer: int = pcbnew.Edge_Cuts) -> None:
        s = pcbnew.PCB_SHAPE(self.board)
        s.SetShape(pcbnew.SHAPE_T_RECT)
        s.SetStart(mm(cx - w / 2, cy - h / 2))
        s.SetEnd(mm(cx + w / 2, cy + h / 2))
        s.SetLayer(layer)
        s.SetWidth(pcbnew.FromMM(0.1))
        self.board.Add(s)


def place(spec: dict, board: "pcbnew.BOARD", libs: dict[str, Path], redraw_edges: bool = True) -> Placer:
    p = Placer(board, libs)
    uc = spec["unit_cell"]
    for k in spec["keys"]:
        n, x, y = k["id"], k["x"], k["y"]
        p.ensure(f"K{n}", *FP["switch"], x, y, 0, bottom=False, value="Lekker Tikken")
        p.ensure(f"HE{n}", *FP["sensor"], x + uc["sensor"]["x"], y + uc["sensor"]["y"], uc["sensor"]["rot"], bottom=True, value="GH39FKSW")
        p.ensure(f"D{n}", *FP["led"], x + uc["led"]["x"], y + uc["led"]["y"], 0, bottom=True, value="MHT151RGBCT")
        p.ensure(f"C{n}", *FP["cap"], x + CAP_OFFSETS["C"][0], y + CAP_OFFSETS["C"][1], CAP_ROT, bottom=True, value="100n")
        p.ensure(f"CF{n}", *FP["cap"], x + CAP_OFFSETS["CF"][0], y + CAP_OFFSETS["CF"][1], CAP_ROT, bottom=True, value="4.7n")
    for i, h in enumerate(spec["holes"], start=1):
        p.ensure(f"H{i}", *FP["hole"], h["x"], h["y"], 0, bottom=False)
    if redraw_edges:
        p.clear_edge_cuts()
        v = spec["outline"]["vertices"]
        for a, b in zip(v, v[1:] + v[:1]):
            p.segment(tuple(a), tuple(b))
        # LED light holes are NPTH pads inside the LED footprint; nothing to draw on Edge.Cuts.
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", required=True, help="path to .kicad_pcb (created with --create)")
    ap.add_argument("--create", action="store_true", help="start from an empty 4-layer board")
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--lib", action="append", default=[], help="NAME=PATH override for a footprint library")
    ap.add_argument("--no-edges", action="store_true", help="do not touch Edge.Cuts")
    args = ap.parse_args()

    libs = dict(DEFAULT_LIBS)
    for item in args.lib:
        name, path = item.split("=", 1)
        libs[name] = Path(path)
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))

    board_path = Path(args.board)
    if args.create:
        board = pcbnew.CreateEmptyBoard()
        board.GetDesignSettings().SetCopperLayerCount(4)
        board_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        board = pcbnew.LoadBoard(str(board_path))

    p = place(spec, board, libs, redraw_edges=not args.no_edges)
    pcbnew.SaveBoard(str(board_path), board)
    print(f"{board_path}: {p.created} footprints created, {p.moved} repositioned, {len(spec['keys'])} keys")
    return 0


if __name__ == "__main__":
    sys.exit(main())
