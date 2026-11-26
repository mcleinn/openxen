"""Tutor keyboard model (host/tutor/board.py): one keyfield from xentool's description,
neighbours, same-note keys, hand shapes, directions as the player sees them.

The sample keyboard is the openxen module geometry (layout/module.json, the same key order
as xentool's LTN_BOARD0_TUPLES) with a Bosanquet layout, like the Lumatone presets."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
from tutor.board import LUMATONE_TILT_DEG, BoardError, Keyboard  # noqa: E402
from tutor.sample import sample_setup  # noqa: E402


@pytest.fixture(scope="module")
def one():
    return Keyboard(sample_setup(31, (0,)))


@pytest.fixture(scope="module")
def five():
    return Keyboard(sample_setup(31, (0, 1, 2, 3, 4)))


@pytest.fixture(scope="module")
def tilted():
    return Keyboard(sample_setup(31, (0, 1, 2, 3, 4)), tilt_deg=LUMATONE_TILT_DEG)


def note(kb: Keyboard, name: str):
    return kb.keys_for_pitch(kb.tuning.parse(name)[0])


def test_sample_geometry_is_the_module(spec):
    # the sample takes its key positions from the layout spec the PCB is built from
    setup = sample_setup(31, (0, 1))
    assert len(setup["keys"]) == 112
    by_addr = {(k["board"], k["key"]): (k["x"], k["y"]) for k in setup["keys"]}
    for k in spec["keys"]:
        assert by_addr[(0, k["id"])] == tuple(k["hex"])
        # xentool geometry.rs: board 1 = board 0 shifted by (2 rows, 12 half-keys)
        assert by_addr[(1, k["id"])] == (k["hex"][0] + 2, k["hex"][1] + 12)


def test_modules_form_one_keyfield(one, five):
    assert len(one.keys) == 56 and len(five.keys) == 280
    # ids are unique and do not change when more modules are connected
    assert set(one.keys) <= set(five.keys)
    for kid, k in one.keys.items():
        assert (five.keys[kid].pitch, five.keys[kid].name) == (k.pitch, k.name)
    # a neighbour can be on the next module: every lattice position holds one key
    assert len({(k.x, k.y) for k in five.keys.values()}) == 280
    crossing = [k for k in five.keys.values() if any(n and n.board != k.board for n in five.neighbours(k).values())]
    assert crossing, "some keys must have a neighbour on another module"
    # each module adds an octave: the same key one module to the right is 31 steps higher
    assert five.at_address(1, 20).pitch - five.at_address(0, 20).pitch == 31


def test_neighbours_and_direction_intervals(one):
    c = note(one, "C2")[0]
    n = one.neighbours(c)
    # Bosanquet: whole tone to the right, chromatic semitone to the upper right
    assert n["right"].name == "D2" and n["upper_right"].name == "C#2" and n["lower_right"].name == "Db2"
    assert n["left"] is None    # C2 is on the left edge of its row
    for k in one.keys.values():
        for d, other in one.neighbours(k).items():
            if other:
                assert one.distance(k, other) == pytest.approx(1.0), (k.id, d)
                back = {v.id: d2 for d2, v in one.neighbours(other).items() if v}
                assert k.id in back
    steps = one.direction_intervals()
    assert steps == {"right": 5, "upper_right": 2, "upper_left": -3, "left": -5, "lower_left": -2, "lower_right": 3}
    assert one.directions == ("right", "upper_right", "upper_left", "left", "lower_left", "lower_right")


def test_same_note_on_several_keys(five):
    # an isomorphic layout repeats notes: two keys with the same pitch are a fixed move apart
    pairs = [(k, o) for k in five.keys.values() for o in five.same_note(k)]
    assert pairs
    for k, o in pairs:
        assert o.pitch == k.pitch and o.id != k.id
    k, o = pairs[0]
    assert five.keys_for_pitch(k.pitch, near=k)[0].id == k.id       # nearest first
    with pytest.raises(BoardError, match="no key 'k999'"):
        five.key("k999")


def test_moves_lead_from_one_key_to_the_other(five, tilted):
    for kb in (five, tilted):
        keys = sorted(kb.keys.values(), key=lambda k: k.id)
        for a, b in zip(keys[::17], keys[5::13]):
            moves = kb.moves(a, b)
            assert len(moves) <= 2
            x, y = a.x, a.y
            for d, count in moves.items():
                assert count > 0
                x, y = x + kb.offsets[d][0] * count, y + kb.offsets[d][1] * count
            assert (x, y) == (b.x, b.y)
        assert kb.moves(keys[0], keys[0]) == {}


def test_tilt_renames_directions_as_the_player_sees_them(five, tilted):
    # lattice slope of the module staircase: two rows down per six keys to the right
    assert LUMATONE_TILT_DEG == pytest.approx(math.degrees(math.atan2(math.sqrt(3), 6)))
    assert LUMATONE_TILT_DEG == pytest.approx(16.1, abs=0.05)
    # turned by that angle, what the lattice calls upper right is nearly straight up
    assert tilted.directions == ("right", "up", "upper_left", "left", "down", "lower_right")
    assert tilted.offsets["up"] == five.offsets["upper_right"]
    assert tilted.offsets["down"] == five.offsets["lower_left"]
    # and an octave lies level: same height, to the right
    c3 = note(tilted, "C3")[0]
    c4 = tilted.keys_for_pitch(c3.pitch + 31, near=c3)[0]
    assert tilted._height(c4) == pytest.approx(tilted._height(c3), abs=1e-9)
    assert tilted._lateral(c4) > tilted._lateral(c3)
    assert five._height(c4) < five._height(c3)      # untilted, the next octave sits lower
    # distances do not depend on the tilt
    assert tilted.distance(c3, c4) == pytest.approx(five.distance(c3, c4))


def test_chord_shapes(five):
    t = five.tuning
    major = t.chord(t.parse("C4")[0], "major")
    shapes = five.shapes(list(major.pitches), limit=3)
    assert shapes and [k.name for k in shapes[0].keys] == ["C4", "E4", "G4"]
    # tightest first; a triad fits easily under one hand
    assert [s.span for s in shapes] == sorted(s.span for s in shapes)
    assert shapes[0].reach == "easy"
    # C to E is two whole tones: two keys to the right
    assert shapes[0].moves[0] == {"right": 2}
    # isomorphic: the same quality on another root is the same shape, moved
    f_major = five.shapes(list(t.chord(t.parse("F4")[0], "major").pitches), limit=1)[0]
    d_minor = five.shapes(list(t.chord(t.parse("D4")[0], "minor").pitches), limit=1)[0]
    assert f_major.offsets == shapes[0].offsets
    assert d_minor.offsets != shapes[0].offsets
    # near: the way closest to the given key comes first
    far = max(five.keys_for_pitch(major.pitches[0]), key=lambda k: k.id)
    assert five.shapes(list(major.pitches), near=far, limit=1)[0].keys[0].id == far.id
    with pytest.raises(BoardError, match="try another octave"):
        five.shapes([t.parse("C9")[0]])


def test_fingering_gives_each_key_its_own_finger(five):
    """The model itself is tested in test_tutor_fingering.py; here: it gets the real key
    positions in millimetres and answers per key."""
    t = five.tuning
    keys = five.shapes(list(t.chord(t.parse("C4")[0], "dominant7").pitches), limit=1)[0].keys
    right = five.fingering(keys, "right")
    left = five.fingering(keys, "left")
    assert set(right) == set(left) == {k.id for k in keys}
    assert len(set(right.values())) == len(set(left.values())) == 4
    assert right != left
    a, b = keys[0], five.neighbours(keys[0])["right"]
    (ax, ay), (bx, by) = five.position_mm(a), five.position_mm(b)
    assert math.hypot(bx - ax, by - ay) == pytest.approx(19.2)
    assert five.fingering(list(five.keys.values())[:6]) == {}
    with pytest.raises(BoardError, match="'left' or 'right'"):
        five.fingering(keys, "both")


def test_text_map_shows_every_key_once(one):
    text = one.text_map()
    lines = text.splitlines()
    assert len(lines) == 11                                 # the module has 11 key rows
    assert [len(line.split()) for line in lines] == [2, 5, 6, 6, 6, 6, 6, 6, 6, 5, 2]
    assert sorted(text.split()) == sorted(k.name for k in one.keys.values())
    # far row first: the top row of the module holds its first two keys
    assert lines[0].split() == [one.at_address(0, 0).name, one.at_address(0, 1).name]
    assert "4" not in one.text_map(octaves=False).replace("^", "")
    # the same picture by note number
    numbers = one.text_map(numbers=True)
    assert [len(line.split()) for line in numbers.splitlines()] == [2, 5, 6, 6, 6, 6, 6, 6, 6, 5, 2]
    assert sorted(map(int, numbers.split())) == sorted(k.pitch % 31 for k in one.keys.values())
