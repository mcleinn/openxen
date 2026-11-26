"""Isomorphic layout generator (host/layouts/isomorphic.py).

What is checked is the definition of such a layout, not the generator's own arithmetic: on
the lattice the tutor uses (layout/module.json, the module offset and the six directions of
host/tutor/sample.py) every step to the right and every step up-right changes the pitch by
the same amount, also from one module to the next. That the lattice is the real one is
shown by the existing 53ET-bosanquet.otn (converted from the Lumatone preset), which comes
out key for key."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
sys.path.insert(0, str(ROOT / "host" / "layouts"))
import isomorphic  # noqa: E402
from tutor.board import Keyboard  # noqa: E402
from tutor.sample import BOARD_SHIFT, DIRECTIONS, module_positions  # noqa: E402

EXISTING_53 = ROOT / "build" / "layouts" / "53ET-bosanquet.otn"
CASES = [(17, 3, 2), (16, 2, -1), (53, 9, 5), (31, 5, 2), (12, 2, 1), (22, 4, 3)]


def parse_otn(text: str) -> dict:
    """The file as xentool reads it (src/wooting/wtn.rs): header, then Key/Chan/Col per board."""
    head, cells, board = {}, {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        if m := re.fullmatch(r"\[Board(\d+)\]", line):
            board = int(m[1])
            continue
        key, value = (x.strip() for x in line.split("=", 1))
        if board is None:
            head[key] = value
        elif m := re.fullmatch(r"(Key|Chan|Col)_(\d+)", key):
            cells.setdefault((board, int(m[2])), {})[m[1]] = value
    edo, offset = int(head["Edo"]), int(head.get("PitchOffset", 0))
    out = {"edo": edo, "offset": offset, "pitch": {}, "colour": {}, "cells": cells}
    for cell, c in cells.items():
        if int(c["Chan"]):                                   # channel 0 = key switched off
            out["pitch"][cell] = (int(c["Chan"]) - 1) * edo + int(c["Key"]) + offset     # serve.rs cell_pitch
            out["colour"][cell] = c["Col"][-6:].lower()
    return out


def lattice_of(cell: tuple[int, int]) -> tuple[int, int]:
    """Lattice position of (board, key), as the tutor builds it."""
    row, col = module_positions()[cell[1]]
    return row + BOARD_SHIFT[0] * cell[0], col + BOARD_SHIFT[1] * cell[0]


def by_position(pitch: dict) -> dict:
    return {lattice_of(cell): p for cell, p in pitch.items()}


@pytest.mark.parametrize("edo,right,upper_right", CASES)
def test_all_keys_get_a_pitch_and_the_file_parses(edo, right, upper_right):
    layout = parse_otn(isomorphic.render(edo, right, upper_right))
    assert layout["edo"] == edo
    assert len(layout["pitch"]) == 280
    assert set(layout["cells"]) == {(b, k) for b in range(5) for k in range(56)}
    for c in layout["cells"].values():
        assert 0 <= int(c["Key"]) <= 127 and 1 <= int(c["Chan"]) <= 16
        assert re.fullmatch(r"[0-9a-f]{8}", c["Col"])
    assert layout["pitch"] == isomorphic.pitches(edo, right, upper_right)
    assert min(layout["pitch"].values()) >= 0


@pytest.mark.parametrize("edo,right,upper_right", CASES)
def test_the_same_move_is_the_same_interval_everywhere(edo, right, upper_right):
    layout = parse_otn(isomorphic.render(edo, right, upper_right))
    at = by_position(layout["pitch"])
    assert len(at) == 280                                    # no two keys on one lattice point
    board_at = {lattice_of((b, k)): b for b in range(5) for k in range(56)}
    expected = {"right": right, "upper_right": upper_right, "left": -right, "lower_left": -upper_right,
                "upper_left": upper_right - right, "lower_right": right - upper_right}
    for name, (d_row, d_col) in DIRECTIONS.items():
        pairs = [(p, (p[0] + d_row, p[1] + d_col)) for p in at if (p[0] + d_row, p[1] + d_col) in at]
        across = [1 for a, b in pairs if board_at[a] != board_at[b]]
        assert len(pairs) > 200 and len(across) >= 10, name   # also over the borders of the modules
        assert {at[b] - at[a] for a, b in pairs} == {expected[name]}, name


@pytest.mark.parametrize("edo,right,upper_right", CASES)
def test_every_note_of_the_tuning_is_there(edo, right, upper_right):
    pitch = isomorphic.pitches(edo, right, upper_right)
    assert {p % edo for p in pitch.values()} == set(range(edo))
    if edo <= 31:                                            # and every note in at least three octaves
        octaves = {pc: {p // edo for p in pitch.values() if p % edo == pc} for pc in range(edo)}
        assert min(len(o) for o in octaves.values()) >= 3


def test_default_steps_are_tone_and_chromatic_semitone():
    assert isomorphic.default_steps(53) == (9, 5)
    assert isomorphic.default_steps(31) == (5, 2)
    assert isomorphic.default_steps(19) == (3, 1)
    assert isomorphic.default_steps(12) == (2, 1)
    assert isomorphic.default_steps(17) == (3, 2)            # fifth 10: tone 3, apotome 2, limma 1
    assert isomorphic.default_steps(16) == (2, -1)           # fifth 9 (mavila): a sharp lowers
    assert isomorphic.default_name(17, 3, 2) == "17ET-bosanquet"
    assert isomorphic.default_name(16, 2, -1) == "16ET-mavila"
    assert isomorphic.default_name(16, 2, 1) == "16ET-isomorphic-2-1"


@pytest.mark.parametrize("edo,scale", [(17, [3, 3, 1, 3, 3, 3, 1]), (16, [2, 2, 3, 2, 2, 2, 3]),
                                       (53, [9, 9, 4, 9, 9, 9, 4])])
def test_the_seven_note_scale_has_the_same_shape_in_every_layout(edo, scale):
    # C D E F G A B C: right, right, lower-right, right, right, right, lower-right
    at = by_position(isomorphic.pitches(edo, *isomorphic.default_steps(edo)))
    pos, walked = (4, 4), []
    for move in ("right", "right", "lower_right", "right", "right", "right", "lower_right"):
        nxt = (pos[0] + DIRECTIONS[move][0], pos[1] + DIRECTIONS[move][1])
        walked.append(at[nxt] - at[pos])
        pos = nxt
    assert walked == scale and sum(scale) == edo


def test_reference_pitch_is_c2_on_key_19_of_module_0():
    assert module_positions()[19] == (4, 0) == isomorphic.ORIGIN
    assert isomorphic.BOARD_SHIFT == BOARD_SHIFT
    for edo in (16, 17, 31):
        assert isomorphic.pitches(edo, *isomorphic.default_steps(edo))[0, 19] == 2 * edo
    assert isomorphic.pitches(17, 3, 2, origin_pitch=100)[0, 19] == 100


def test_colours_show_the_chain_of_fifths():
    for edo, fifth in ((17, 10), (16, 9)):
        right, upper_right = isomorphic.default_steps(edo)
        assert isomorphic.generating_fifth(edo, right, upper_right) == fifth
        colour = isomorphic.colours(edo, right, upper_right)
        assert set(colour) == set(range(edo))
        naturals = {(k * fifth) % edo for k in range(-1, 6)}             # F C G D A E B
        assert {pc for pc, c in colour.items() if c == isomorphic.NATURALS} == naturals
        sharps = {(k * fifth) % edo for k in range(6, 11)}
        assert {colour[pc] for pc in sharps} == {isomorphic.BANDS_UP[0]}
        flats = {(k * fifth) % edo for k in range(-2, -2 - (edo - 12), -1)}
        assert {colour[pc] for pc in flats} == {isomorphic.BANDS_DOWN[0]}
    assert sorted(set(isomorphic.fifth_bands(17).values())) == [-1, 0, 1]
    # two steps that do not come from one fifth still give every note a colour, C white
    wheel = isomorphic.colours(16, 3, 2)
    assert len(wheel) == 16 and wheel[0] == "ffffff" and len(set(wheel.values())) == 16


def test_steps_that_miss_notes_are_refused(tmp_path):
    with pytest.raises(ValueError):
        isomorphic.pitches(24, 4, 2)
    assert isomorphic.main(["24", "--right", "4", "--upper-right", "1", "--out", str(tmp_path)]) == 0
    written = parse_otn((tmp_path / "24ET-isomorphic-4-1.otn").read_text())
    assert written["edo"] == 24 and len(written["pitch"]) == 280


def test_the_tutor_keyboard_model_accepts_the_layout():
    # the tutor gets its keys from xentool as (board, key, lattice position, pitch); build that
    # description from the generated file and let the tutor's own model read it
    layout = parse_otn(isomorphic.render(17))
    keys = [{"board": b, "key": k, "x": lattice_of((b, k))[0], "y": lattice_of((b, k))[1],
             "pitch": p, "hz": 16.351597831287414 * 2 ** (p / 17), "color": layout["colour"][b, k]}
            for (b, k), p in sorted(layout["pitch"].items())]
    board = Keyboard({"backend": "sample", "geometry": "lumatone", "layout": "17ET-bosanquet", "edo": 17,
                      "boards": [0, 1, 2, 3, 4], "directions": DIRECTIONS, "keys": keys})
    assert len(board.keys) == 280


@pytest.mark.skipif(not EXISTING_53.exists(), reason="53ET-bosanquet.otn is generated from third-party presets")
def test_reproduces_the_existing_53_layout():
    existing = parse_otn(EXISTING_53.read_text())
    assert len(existing["pitch"]) == 280
    origin = existing["pitch"][0, 19]
    assert origin == 2 * 53 + 60
    mine = parse_otn(isomorphic.render(53, 9, 5, origin_pitch=origin))
    assert mine["pitch"] == existing["pitch"]                # the proof of the geometry
    assert mine["colour"] == existing["colour"]              # and the colour scheme is the same one
    assert mine["offset"] == existing["offset"] == 106
