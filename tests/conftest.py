"""Shared fixtures for the openxen consistency tests.

The tests read the generated artefacts (layout spec, parts list, schematic, board, firmware
JSON) and check them against each other and against datasheet facts, so a regeneration that
silently breaks a mapping (mux channel, MCU pin, LED colour, sensor polarity, ...) fails here.

KiCad-backed fixtures (netlist export, ERC, DRC) run kicad-cli once per session; they are
skipped when KiCad 9 is not installed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hardware" / "generators"))
import sexp  # noqa: E402

PRJ = ROOT / "hardware" / "kicad" / "openxen-m56"
SCH = PRJ / "openxen-m56.kicad_sch"
PCB = PRJ / "openxen-m56.kicad_pcb"
KCLI_CANDIDATES = [r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe", "kicad-cli"]


def _kcli() -> str | None:
    for c in KCLI_CANDIDATES:
        if Path(c).exists() or shutil.which(c):
            return c
    return None


@pytest.fixture(scope="session")
def spec() -> dict:
    return json.loads((ROOT / "layout" / "module.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def parts() -> dict:
    return json.loads((ROOT / "hardware" / "parts.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def keyboard() -> dict:
    return json.loads((ROOT / "firmware" / "keyboards" / "openxen-m56" / "keyboard.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def keys(spec) -> dict[int, dict]:
    return {k["id"]: k for k in spec["keys"]}


@pytest.fixture(scope="session")
def kcli() -> str:
    k = _kcli()
    if k is None:
        pytest.skip("kicad-cli (KiCad 9) not installed")
    return k


@pytest.fixture(scope="session")
def netlist(kcli, tmp_path_factory) -> dict[str, set[tuple[str, str, str]]]:
    """net name -> {(ref, pin number, pin function)} from a fresh export of the schematic."""
    out = tmp_path_factory.mktemp("net") / "openxen.net"
    r = subprocess.run([kcli, "sch", "export", "netlist", "--format", "kicadsexpr", "--output", str(out), str(SCH)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    doc = sexp.loads(out.read_text(encoding="utf-8"))
    nets: dict[str, set[tuple[str, str, str]]] = {}
    for n in sexp.kids(sexp.kid(doc, "nets"), "net"):
        name = sexp.q(n, "name")
        nets[name] = {(sexp.q(nd, "ref"), sexp.q(nd, "pin"), sexp.q(nd, "pinfunction")) for nd in sexp.kids(n, "node")}
    return nets


@pytest.fixture(scope="session")
def pin_net(netlist) -> dict[tuple[str, str], str]:
    """(ref, pin number) -> net name."""
    return {(ref, pin): name for name, nodes in netlist.items() for ref, pin, _ in nodes}


@pytest.fixture(scope="session")
def pin_by_function(netlist) -> dict[tuple[str, str], str]:
    """(ref, pin function) -> net name, e.g. ('U4', 'PA3') -> 'MUX_OUT_1'."""
    return {(ref, fn): name for name, nodes in netlist.items() for ref, _, fn in nodes if fn}


@pytest.fixture(scope="session")
def board() -> list:
    return sexp.loads(PCB.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def footprints(board) -> dict[str, list]:
    return {sexp.prop(fp, "Reference"): fp for fp in sexp.kids(board, "footprint")}


@pytest.fixture(scope="session")
def board_nets(board) -> dict:
    return {n[1]: getattr(n[2], "s", n[2]) for n in sexp.kids(board, "net")}


@pytest.fixture(scope="session")
def drc(kcli, tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("drc") / "drc.json"
    r = subprocess.run([kcli, "pcb", "drc", "--output", str(out), "--format", "json", "--schematic-parity",
                        "--severity-all", str(PCB)], capture_output=True, text=True)
    assert out.exists(), r.stdout + r.stderr
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def erc(kcli, tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("erc") / "erc.json"
    r = subprocess.run([kcli, "sch", "erc", "--output", str(out), "--format", "json", "--severity-all", str(SCH)],
                       capture_output=True, text=True)
    assert out.exists(), r.stdout + r.stderr
    return json.loads(out.read_text(encoding="utf-8"))
