#!/usr/bin/env python3
"""Regenerate build/screenshots from scratch (the folder is wiped first). System Python.

01 geometry check (spec vs plate DXF vs freexen)   02 spec preview
03/04 board 3D bottom/top                          05 board 2D bottom (copper + silk)
06 controller strip   07 LED driver strip   08 mux + cells close-up   09 one cell copper
10.. schematic sheets (root, controller, sensors, muxes, LEDs)
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
KCLI = r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe"
PRJ = ROOT / "hardware" / "kicad" / "openxen-m56"
PCB, SCH = PRJ / "openxen-m56.kicad_pcb", PRJ / "openxen-m56.kicad_sch"
OUT = ROOT / "build" / "screenshots"
W, H = 124.842, 211.2


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-400:], r.stderr[-400:])
        raise SystemExit(f"failed: {cmd[1:3]}")


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    tmp = ROOT / "build" / "_render"
    tmp.mkdir(exist_ok=True)
    subprocess.run([sys.executable, str(ROOT / "layout" / "generators" / "render_overlay.py")], check=True, capture_output=True)
    subprocess.run([sys.executable, str(ROOT / "layout" / "generators" / "render_preview.py")], check=True, capture_output=True)
    shutil.copy(ROOT / "layout" / "geometry_check.png", OUT / "01-geometry-check-vs-plate-and-freexen.png")
    shutil.copy(ROOT / "layout" / "module_preview.png", OUT / "02-spec-preview.png")
    run([KCLI, "pcb", "render", "--output", str(OUT / "03-board-3d-bottom.png"), "--side", "bottom", "--width", "1300", "--height", "2200", "--quality", "high", "--background", "opaque", str(PCB)])
    run([KCLI, "pcb", "render", "--output", str(OUT / "04-board-3d-top.png"), "--side", "top", "--width", "1300", "--height", "2200", "--quality", "high", "--background", "opaque", str(PCB)])
    svg = tmp / "bottom.svg"
    run([KCLI, "pcb", "export", "svg", "--output", str(svg), "--layers", "B.Cu,F.Cu,B.SilkS,Edge.Cuts", "--page-size-mode", "2", "--exclude-drawing-sheet", "--mirror", str(PCB)])
    pg = pymupdf.open(str(svg))[0]
    r = pg.rect
    sx, sy = r.width / W, r.height / H

    def crop(name: str, x0: float, y0: float, x1: float, y1: float, dpi: int) -> None:
        pix = pg.get_pixmap(dpi=dpi, clip=pymupdf.Rect((W - x1) * sx, y0 * sy, (W - x0) * sx, y1 * sy))
        pix.save(str(OUT / name))

    crop("05-board-2d-bottom-copper-silk.png", 0, 0, W, H, 130)
    crop("06-controller-strip.png", 34, 0, 118, 44, 280)
    crop("07-led-driver-strip.png", 28, 186, 70, 212, 320)
    crop("08-mux-and-cells-closeup.png", 28, 22, 70, 62, 300)
    crop("09-one-cell-copper.png", 0, 0, 19.2, 19.2, 900)
    pdf = tmp / "sch.pdf"
    run([KCLI, "sch", "export", "pdf", "--output", str(pdf), str(SCH)])
    names = ["10-schematic-root", "11-schematic-controller", "12-schematic-sensors", "13-schematic-muxes", "14-schematic-leds"]
    doc = pymupdf.open(str(pdf))
    for i, page in enumerate(doc):
        if i < len(names):
            page.get_pixmap(dpi=110 if i else 90).save(str(OUT / f"{names[i]}.png"))
    print("screenshots:", sorted(p.name for p in OUT.iterdir()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
