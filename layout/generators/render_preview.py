#!/usr/bin/env python3
"""Render ``layout/module.json`` to ``layout/module_preview.png`` for visual checking.

Shows the outline, mounting holes, every key (id, mux colour), the unit cell (sensor,
LED cutout, guide holes, plate cutout), mux centroids and the controller zones.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon, Rectangle

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "layout" / "module.json"
OUT = ROOT / "layout" / "module_preview.png"


def main() -> int:
    s = json.loads(SPEC.read_text(encoding="utf-8"))
    fig, ax = plt.subplots(figsize=(7, 11.5), dpi=150)
    ax.add_patch(Polygon(s["outline"]["vertices"], closed=True, fill=False, lw=1.2, ec="black"))
    for h in s["holes"]:
        ax.add_patch(Circle((h["x"], h["y"]), h["d"] / 2, fill=False, ec="gray", lw=0.8))
    uc = s["unit_cell"]
    cmap = plt.get_cmap("tab10")
    for k in s["keys"]:
        x, y, c = k["x"], k["y"], cmap(k["mux"])
        half = uc["switch"]["plate_cutout_mm"] / 2
        ax.add_patch(Rectangle((x - half, y - half), 2 * half, 2 * half, fill=True, fc=c, alpha=0.15, ec=c, lw=0.6))
        for g in uc["switch"]["guide_holes"]:
            ax.add_patch(Circle((x + g["x"], y + g["y"]), g["d"] / 2, fill=False, ec="gray", lw=0.5))
        ax.add_patch(Rectangle((x - 1.5, y - 0.75), 3.0, 1.5, fill=True, fc="black", alpha=0.6))  # sensor
        led = uc["led"]
        ax.add_patch(Circle((x + led["x"], y + led["y"]), led["hole_d"] / 2, fill=False, ec="red", lw=0.6))
        ax.text(x, y + 4.5, str(k["id"]), ha="center", va="center", fontsize=5)
    kb = {k["id"]: k for k in s["keys"]}
    for m in s["mux"]["groups"]:
        mx, my = m["pos"]
        for ch, kid in enumerate(m["keys"]):                      # analog path (straight line) and channel
            k = kb[kid]
            ax.plot([k["x"] + 3.3, mx], [k["y"], my], color=cmap(m["index"]), lw=0.4, alpha=0.7)
            ax.text(k["x"] + 3.3, k["y"] + 1.6, f"Y{ch}", fontsize=4, color=cmap(m["index"]))
        ax.add_patch(Rectangle((mx - 2.9, my - 2.5), 5.8, 5.0, fill=True, fc=cmap(m["index"]), ec="black", lw=0.6))
        ax.text(mx + 3.4, my, f"MUX{m['index']}", fontsize=5, va="center")
    for z in s["controller_zones"]:
        ax.add_patch(Rectangle((z["x0"], z["y0"]), z["x1"] - z["x0"], z["y1"] - z["y0"], fill=True,
                               fc="green" if z["preferred"] else "orange", alpha=0.15, ec="green" if z["preferred"] else "orange", ls="--"))
        ax.text(z["x0"] + 1, z["y0"] + 3, z["name"], fontsize=5)
        for ko in z["keepouts"]:
            ax.add_patch(Circle((ko["x"], ko["y"]), ko["r"], fill=False, ec="red", ls=":", lw=0.6))
    ax.set_xlim(-3, 128)
    ax.set_ylim(214, -3)
    ax.set_aspect("equal")
    ax.set_title(f"{s['name']} v{s['version']} — {len(s['keys'])} keys, 19.2 mm pitch (bottom-side parts shown through)", fontsize=8)
    ax.set_xlabel("mm")
    fig.tight_layout()
    fig.savefig(OUT)
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
