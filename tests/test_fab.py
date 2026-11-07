"""Production files (hardware/fab/make_fab.py -> build/fab/production): complete, consistent with
the board, orderable at JLCPCB (parts database snapshot in reference/jlcparts)."""
from __future__ import annotations

import collections
import csv
import json
import re
import sqlite3
import zipfile

import pytest

import sexp
from conftest import ROOT

PROD = ROOT / "build" / "fab" / "production"
DB = ROOT / "reference" / "jlcparts" / "cache.sqlite3"
BOARDS_TO_ASSEMBLE = 5          # first order: 5 PCBs, all 5 assembled (PROJECT_PLAN phase 6)
NOT_ASSEMBLED = re.compile(r"^(K|H|TP|J3)\d*$")   # switches, holes, test pads, TC2030 pads


@pytest.fixture(scope="module")
def prod():
    if not (PROD / "openxen-m56_bom.csv").exists():
        pytest.skip("production files not generated (python hardware/fab/make_fab.py)")
    bom = list(csv.DictReader((PROD / "openxen-m56_bom.csv").open(encoding="utf-8-sig")))
    cpl = list(csv.DictReader((PROD / "openxen-m56_positions.csv").open(encoding="utf-8-sig")))
    return bom, cpl


def assembled(footprints):
    return {r for r, fp in footprints.items() if not NOT_ASSEMBLED.match(r)}


def test_bom_covers_every_assembled_part_once(prod, footprints):
    bom, _ = prod
    refs = [d.strip() for line in bom for d in line["Designator"].split(",")]
    assert len(refs) == len(set(refs))
    assert set(refs) == assembled(footprints)
    for line in bom:
        assert int(line["Quantity"]) == len(line["Designator"].split(","))
        assert re.fullmatch(r"C\d+", line["LCSC Part #"]), line


def test_cpl_matches_board(prod, footprints):
    _, cpl = prod
    rows = {r["Designator"]: r for r in cpl}
    assert set(rows) == assembled(footprints)
    for ref, r in rows.items():
        assert r["Layer"] == "bottom", ref                           # single-sided assembly
        x, y, _ = sexp.at(footprints[ref])
        if ref.startswith(("D", "HE", "C", "CF", "AM", "U", "R")) and not ref.startswith("CM"):
            assert float(r["Mid X"]) == pytest.approx(x, abs=0.01) and float(r["Mid Y"]) == pytest.approx(-y, abs=0.01), ref


def test_cell_parts_rotated_identically(prod):
    """All 56 copies of a cell part must have the same pick-and-place rotation."""
    _, cpl = prod
    for pre in ("D", "HE", "C", "CF"):
        rots = {r["Rotation"] for r in cpl if re.fullmatch(pre + r"\d+", r["Designator"]) and int(re.sub(r"\D", "", r["Designator"])) < 56}
        assert len(rots) == 1, (pre, rots)
    assert len({r["Rotation"] for r in cpl if r["Designator"].startswith("AM")}) == 1


def test_parts_orderable(prod):
    if not DB.exists():
        pytest.skip("jlcparts database snapshot not present")
    bom, _ = prod
    db = sqlite3.connect(DB)
    report = []
    for line in bom:
        lcsc = int(line["LCSC Part #"][1:])
        row = db.execute("select library_type, stock, assembly, package from jlc_components where lcsc=?", (lcsc,)).fetchone()
        assert row is not None, line
        lib, stock, assembly, package = row
        need = int(line["Quantity"]) * BOARDS_TO_ASSEMBLE
        assert stock >= need, (line["Value"], line["LCSC Part #"], stock, need)
        report.append((line["LCSC Part #"], line["Value"], lib, stock, need))
    extended = sorted({r[0] for r in report if r[2] not in ("base", "basic", "preferred")})
    print("\nextended parts (one-off setup fee each):", extended)


def test_gerber_archive_complete(prod):
    names = zipfile.ZipFile(PROD / "openxen-m56.zip").namelist()
    for layer in ("F_Cu", "In1_Cu", "In2_Cu", "B_Cu", "F_Mask", "B_Mask", "B_Paste", "B_Silkscreen", "Edge_Cuts"):
        assert any(f"-{layer}." in n for n in names), layer
    assert any(n.endswith("-PTH.drl") for n in names) and any(n.endswith("-NPTH.drl") for n in names)


def test_npth_holes(prod):
    """56 x (2 guide pins 1.75 + LED window 2.1) + 8 M3 holes 3.2 (+ connector pegs)."""
    z = zipfile.ZipFile(PROD / "openxen-m56.zip")
    drl = z.read(next(n for n in z.namelist() if n.endswith("-NPTH.drl"))).decode()
    tools = dict(re.findall(r"^(T\d+)C([\d.]+)", drl, re.M))
    hits = collections.Counter()
    current = None
    for line in drl.splitlines():
        m = re.fullmatch(r"(T\d+)", line.strip())
        if m:
            current = m.group(1)
        elif line.startswith("X") and current:
            hits[float(tools[current])] += 1
    assert hits[1.75] == 112 and hits[2.1] == 56 and hits[3.2] == 8, dict(hits)


def test_fuse_carries_worst_case_module_current():
    """F1 (polyfuse) must hold the worst-case module current when warm: 56 sensors at their
    maximum ICC + the LED driver at the firmware's hard current cap + MCU and logic."""
    import json as _json
    from facts import MCU_MISC_MA, PTC_HOLD_DERATING, SENSOR_ICC_MAX_MA
    if not DB.exists():
        pytest.skip("jlcparts database snapshot not present")
    hdr = (ROOT / "firmware" / "libhmk" / "include" / "openxen_led.h").read_text(encoding="utf-8")
    led_ma = int(re.search(r"#define OXL_BUDGET_MAX_MA (\d+)u", hdr).group(1))
    worst = 56 * SENSOR_ICC_MAX_MA + led_ma + MCU_MISC_MA
    parts = _json.loads((ROOT / "hardware" / "parts.json").read_text(encoding="utf-8"))
    lcsc = int(parts["parts"]["polyfuse"]["lcsc"][1:]) if "parts" in parts else int(parts["polyfuse"]["lcsc"][1:])
    attrs = _json.loads(sqlite3.connect(DB).execute("select attributes from jlc_components where lcsc=?", (lcsc,)).fetchone()[0])
    m = re.match(r"([\d.]+)(m?)A", attrs["Hold Current"])
    hold_ma = float(m.group(1)) * (1 if m.group(2) else 1000)
    assert hold_ma * PTC_HOLD_DERATING >= worst, (hold_ma, worst)


def test_jlc_placement_matches_easyeda_footprints(prod):
    """Offline JLCPCB preview (hardware/fab/check_jlc_placement.py): every part, placed with its
    EasyEDA footprint at the CPL position and rotation, lands pin 1 (LED: every pin) on our pads.
    Needs the cached footprints in reference/easyeda (run the script once with --fetch)."""
    import subprocess
    cache = ROOT / "reference" / "easyeda"
    kpy = r"C:\Program Files\KiCad\9.0\bin\python.exe"
    if not cache.exists() or not any(cache.glob("C*.json")):
        pytest.skip("EasyEDA footprint cache missing (check_jlc_placement.py --fetch)")
    r = subprocess.run([kpy, str(ROOT / "hardware" / "fab" / "check_jlc_placement.py")], capture_output=True, text=True)
    assert r.returncode == 0, [l for l in r.stdout.splitlines() if not l.startswith("OK")]
