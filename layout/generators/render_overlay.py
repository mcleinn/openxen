#!/usr/bin/env python3
"""Geometry check image: our spec vs the existing CNC plate DXF vs the last freexen PCB.

Draws, in one figure (mm, y down):
* black: our outline polygon and M3 holes (from module.json)
* red squares: the 14 mm plate cutouts and plate holes parsed from freexen module_top.dxf
* blue crosses: switch centres of the last freexen xenIO board
* green dots: our 56 key centres; grey: sensor (centre) and LED hole (north)
Writes layout/geometry_check.png.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon, Rectangle

ROOT = Path(__file__).resolve().parents[2]
spec = json.loads((ROOT / "layout" / "module.json").read_text(encoding="utf-8"))
ext = json.loads((ROOT / "layout" / "source" / "freexen_extract.json").read_text(encoding="utf-8"))

fig, ax = plt.subplots(figsize=(7.5, 12), dpi=150)
ax.add_patch(Polygon(spec["outline"]["vertices"], closed=True, fill=False, lw=1.4, ec="black", label="openxen outline (= freexen PCB)"))
for h in spec["holes"]:
    ax.add_patch(Circle((h["x"], h["y"]), 1.6, fill=False, ec="black", lw=1.2))
for c in ext["plate"]["cutouts"]:
    ax.add_patch(Rectangle((c["x"] - c["w"] / 2, c["y"] - c["h"] / 2), c["w"], c["h"], fill=False, ec="red", lw=0.9))
for h in ext["plate"]["holes"]:
    ax.add_patch(Circle((h["x"], h["y"]), h["r"], fill=False, ec="red", lw=0.9, ls="--"))
ax.plot([k["x"] for k in ext["keys"]], [k["y"] for k in ext["keys"]], "x", color="blue", ms=7, mew=1.2, label="freexen switch centres")
ax.plot([k["x"] for k in spec["keys"]], [k["y"] for k in spec["keys"]], "o", color="green", ms=3.5, label="openxen key centres")
led = spec["unit_cell"]["led"]
for k in spec["keys"]:
    ax.add_patch(Circle((k["x"] + led["x"], k["y"] + led["y"]), led["hole_d"] / 2, fill=False, ec="gray", lw=0.6))
    ax.add_patch(Rectangle((k["x"] - 1.45, k["y"] - 0.65), 2.9, 1.3, fill=True, fc="gray", alpha=0.5, lw=0))
    ax.text(k["x"], k["y"] + 4.2, str(k["id"]), ha="center", va="center", fontsize=5)
for z in spec["controller_zones"]:
    ax.add_patch(Rectangle((z["x0"], z["y0"]), z["x1"] - z["x0"], z["y1"] - z["y0"], fill=True, fc="green" if z["preferred"] else "orange", alpha=0.12, ec="none"))
ax.set_xlim(-5, 130)
ax.set_ylim(216, -5)
ax.set_aspect("equal")
ax.set_xlabel("mm")
ax.legend(loc="lower left", fontsize=6)
ax.set_title("Geometry check: outline/holes (black) · plate DXF cutouts/holes (red) · freexen switches (blue) · openxen keys (green)", fontsize=7)
fig.tight_layout()
out = ROOT / "layout" / "geometry_check.png"
fig.savefig(out)
print("wrote", out)
