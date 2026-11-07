#!/usr/bin/env python3
"""Offline stand-in for JLCPCB's assembly preview. Run with KiCad's Python after make_fab.py.

    python.exe hardware/fab/check_jlc_placement.py [--fetch]

JLCPCB places every part with the EasyEDA footprint linked to its LCSC number, at the CPL's
Mid X/Y and Rotation. This script downloads those footprints (--fetch; cached, untrusted data,
in reference/easyeda/, gitignored), places each one the way the CPL says and compares its pads
with our KiCad footprint:

  * geometry: every EasyEDA pad must land on one of our pads (max error 0.45 mm; pad-size
    differences between the libraries are fine),
  * pin 1: EasyEDA pad "1" must land on our pin-1 pad (for the MHT151RGBCT, whose pads we
    number like KiCad's LED_ARGB symbol, every datasheet pin is checked: 1->1, 2->4, 3->3, 4->2),
  * position: the CPL point must be JLCPCB's reference point of the part (within 0.1 mm).

Model, after the Fabrication Toolkit: a bottom-side part's JLC rotation is 180 - (KiCad angle)
plus a per-package correction. Rotating the EasyEDA footprint by (JLC rotation - (180 - angle))
must therefore reproduce the KiCad library footprint. Lines whose correction is wrong report the
rotation and offset that would fit; put them into hardware/fab/jlc_corrections.json.
Exit code 1 if any line fails.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
import urllib.request
from pathlib import Path

import pcbnew  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
PROD = ROOT / "build" / "fab" / "production"
CACHE = ROOT / "reference" / "easyeda"
PCB = ROOT / "hardware" / "kicad" / "openxen-m56" / "openxen-m56.kicad_pcb"
LIBS = {"openxen": ROOT / "hardware" / "kicad" / "lib" / "openxen.pretty"}
SHARE = Path(r"C:\Program Files\KiCad\9.0\share\kicad\footprints")
# EasyEDA pad (datasheet pin) -> our pad number, where they differ
PIN_MAP = {"C409782": {"1": "1", "2": "4", "3": "3", "4": "2"},   # MHT151RGBCT: pins 1=A 2=B 3=G 4=R
           # USB-C: EasyEDA's pad "1" is a shell tab; check the signal pads by name instead
           "C165948": {p: p for p in ("A5", "A6", "A7", "A8", "B5", "B6", "B7", "B8")}}
GEOM_TOL, POS_TOL = 0.45, 0.1


def fetch(lcsc: str) -> None:
    f = CACHE / f"{lcsc}.json"
    if f.exists():
        return
    req = urllib.request.Request(f"https://easyeda.com/api/products/{lcsc}/components?version=6.4.19.5",
                                 headers={"User-Agent": "openxen-fab-check/0.1"})
    data = urllib.request.urlopen(req, timeout=30).read()
    json.loads(data)                                   # must parse; stored as data only
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    time.sleep(0.5)


def easy_pads(lcsc: str) -> list[tuple[str, float, float]]:
    ds = json.loads((CACHE / f"{lcsc}.json").read_text(encoding="utf-8"))["result"]["packageDetail"]["dataStr"]
    ox, oy = float(ds["head"]["x"]), float(ds["head"]["y"])
    return [(f[8], (float(f[2]) - ox) * 0.254, (float(f[3]) - oy) * 0.254)          # 10 mil units, y down
            for f in (s.split("~") for s in ds["shape"]) if f[0] == "PAD"]


def kicad_pads(fp) -> list[tuple[str, float, float]]:
    fid = fp.GetFPID()
    lib = str(fid.GetLibNickname())
    lf = pcbnew.FootprintLoad(str(LIBS.get(lib, SHARE / f"{lib}.pretty")), str(fid.GetLibItemName()))
    return [(p.GetNumber(), pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y)) for p in lf.Pads()
            if p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH and p.GetNumber() != ""]


def rot(pts, a):
    """rotate by a degrees, counter-clockwise as seen on screen (y down)"""
    c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
    return [(n, x * c + y * s, -x * s + y * c) for n, x, y in pts]


def fit(e, k):
    """map every EasyEDA pad to the nearest KiCad pad, both relative to their origins plus the
    best common offset (the centroid difference). Returns (max error, mapping, offset)."""
    ex, ey = sum(p[1] for p in e) / len(e), sum(p[2] for p in e) / len(e)
    kx, ky = sum(p[1] for p in k) / len(k), sum(p[2] for p in k) / len(k)
    off = (kx - ex, ky - ey)
    m, err = {}, 0.0
    for n, x, y in e:
        q = min(k, key=lambda q: (q[1] - x - off[0]) ** 2 + (q[2] - y - off[1]) ** 2)
        m[n] = q[0]
        err = max(err, math.hypot(q[1] - x - off[0], q[2] - y - off[1]))
    return err, m, off


def pins_ok(lcsc, m) -> bool | None:
    want = PIN_MAP.get(lcsc)
    if want:
        return all(m.get(a) == b for a, b in want.items())
    return (m.get("1") == "1") if "1" in m else None


def to_board(fp, v):
    """library-frame vector -> board frame, for a bottom-side (flipped) footprint"""
    th = math.radians(fp.GetOrientationDegrees())
    x, y = v[0], -v[1]                                  # flip about the x axis
    return (x * math.cos(th) + y * math.sin(th), -x * math.sin(th) + y * math.cos(th))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="download missing EasyEDA footprints")
    args = ap.parse_args()
    bom = list(csv.DictReader((PROD / "openxen-m56_bom.csv").open(encoding="utf-8-sig")))
    cpl = {r["Designator"]: r for r in csv.DictReader((PROD / "openxen-m56_positions.csv").open(encoding="utf-8-sig"))}
    b = pcbnew.LoadBoard(str(PCB))
    bad = 0
    for line in bom:
        lcsc = line["LCSC Part #"]
        if args.fetch:
            fetch(lcsc)
        if not (CACHE / f"{lcsc}.json").exists():
            print(f"SKIP {lcsc}: no cached EasyEDA footprint (run with --fetch)")
            bad += 1
            continue
        e = easy_pads(lcsc)
        refs = [d.strip() for d in line["Designator"].split(",")]
        k = kicad_pads(b.FindFootprintByReference(refs[0]))
        problems, notes = [], ""
        for ref in refs:
            fp = b.FindFootprintByReference(ref)
            r = cpl[ref]
            a = (float(r["Rotation"]) - (180.0 - fp.GetOrientationDegrees())) % 360.0
            err, m, off = fit(rot(e, a), k)
            # JLC's reference point (the EasyEDA origin) on the board vs the CPL point
            o = to_board(fp, off)
            want = (pcbnew.ToMM(fp.GetPosition().x) + o[0], pcbnew.ToMM(fp.GetPosition().y) + o[1])
            got = (float(r["Mid X"]), -float(r["Mid Y"]))
            dpos = math.hypot(got[0] - want[0], got[1] - want[1])
            ok = err <= GEOM_TOL and pins_ok(lcsc, m) is not False and dpos <= POS_TOL
            if not ok:
                good = [g for g in (0, 90, 180, 270) if fit(rot(e, g), k)[0] <= GEOM_TOL and pins_ok(lcsc, fit(rot(e, g), k)[1]) is not False]
                fix_rot = sorted(((g - a) % 360 for g in good))
                fix_pos = (round(want[0] - pcbnew.ToMM(fp.GetPosition().x), 3), round(want[1] - pcbnew.ToMM(fp.GetPosition().y), 3))
                problems.append(ref)
                notes = (f"geometry {err:.2f} mm, pin 1 {'ok' if pins_ok(lcsc, m) else 'WRONG'}, position off {dpos:.2f} mm; "
                         f"rotation correction that fits: {fix_rot}, JLC reference point at board offset {fix_pos} (lib frame {tuple(round(v, 3) for v in off)})")
        status = "OK  " if not problems else "FAIL"
        bad += bool(problems)
        print(f"{status} {lcsc:10s} {line['Value'][:16]:16s} x{len(refs):<3d} {notes if problems else ''}{(' ' + ','.join(problems[:4])) if problems else ''}")
    print(f"{bad} line(s) failing")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
