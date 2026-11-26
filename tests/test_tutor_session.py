"""Tutor tools (host/tutor/session.py) against an in-memory xentool: what the tools answer,
what ends up lit and sounded, and that a scripted player is judged correctly. The player
runs on a second thread and presses keys while a tool call waits, as in real use."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
from tutor.board import BoardError  # noqa: E402
from tutor.sample import sample_setup  # noqa: E402
from tutor.session import DIM_BASE, ROLES, Tutor, TutorError  # noqa: E402
from tutor.theory import TheoryError  # noqa: E402
from tutor.xt import FakeXentool, Xentool, XentoolError  # noqa: E402

# Words that would be internals leaking into what the tutor model reads.
INTERNAL_FIELDS = {"board", "x", "y", "pitch", "pitches", "chan", "channel", "address", "offsets", "hz", "steps_per_octave", "edo"}


@pytest.fixture()
def fake():
    return FakeXentool(sample_setup(31, (0, 1, 2, 3)))     # four modules: about four octaves


@pytest.fixture()
def tutor(fake):
    t = Tutor(fake)
    yield t
    t.pump.stop()


def fields(value, found=None) -> set[str]:
    """Every dict key anywhere in a tool result."""
    found = set() if found is None else found
    if isinstance(value, dict):
        for k, v in value.items():
            found.add(k)
            fields(v, found)
    elif isinstance(value, (list, tuple)):
        for v in value:
            fields(v, found)
    return found


class Player(threading.Thread):
    """Presses and releases keys on the fake keyboard: script of (seconds to wait, action,
    key ids), action 'down', 'up' or 'tap' (down, 60 ms, up)."""

    def __init__(self, tutor: Tutor, fake: FakeXentool, script: list[tuple]):
        super().__init__(daemon=True)
        self.tutor, self.fake, self.script = tutor, fake, script

    def run(self):
        kb = self.tutor.keyboard
        for wait, action, ids in self.script:
            time.sleep(wait)
            keys = [kb.key(i) for i in ids]
            if action in ("down", "tap"):
                for k in keys:
                    self.fake.press(k.board, k.key)
            if action == "tap":
                time.sleep(0.06)
            if action in ("up", "tap"):
                for k in keys:
                    self.fake.release(k.board, k.key)


def ids(way: dict) -> list[str]:
    return [k["key"] for k in way["keys"]]


def chord_keys(tutor: Tutor, root: str, quality: str = "major") -> list[str]:
    return ids(tutor.find_shape(root=root, quality=quality, limit=1)["ways"][0])


def address(tutor: Tutor, kid: str) -> tuple[int, int]:
    k = tutor.keyboard.key(kid)
    return (k.board, k.key)


# --- looking things up ---

def test_keyboard_info_is_a_players_description(tutor):
    info = tutor.keyboard_info()
    assert info["tuning"] == "31 equal steps per octave"
    assert info["keys"] == 224
    # the range is given as notes the keyboard really has (one key each, at its ends)
    low, high = tutor.keys(note=info["lowest_note"]), tutor.keys(note=info["highest_note"])
    assert len(low["keys"]) == 1 and len(high["keys"]) == 1
    assert int(info["lowest_note"][-1]) < int(info["highest_note"][-1])
    assert info["directions"]["right"] == "major second up (M2, 5 steps)"
    assert info["directions"]["left"] == "major second down (M2, 5 steps)"
    assert info["directions"]["upper_right"] == "downminor second up (vm2, 2 steps)"
    assert "counted from C = 0 up to 30" in info["note_numbers"]
    assert info["same_shape_everywhere"] is True
    assert "subminor" in info["chords_beyond_12_tone"]
    by_name, by_number = info["map"].split("\n\nthe same keys by number:\n")
    assert len(by_name.splitlines()) == 17          # 11 rows, two more per further module
    assert len(by_number.splitlines()) == 17 and len(by_number.split()) == 224
    assert set(map(int, by_number.split())) == set(range(31))
    assert "map" not in tutor.keyboard_info(include_map=False)
    assert not fields(info) & INTERNAL_FIELDS


def test_keys_by_id_gives_neighbours_and_same_note(tutor):
    c4 = tutor.keys(note="C4")["keys"][0]["key"]
    k = tutor.keys(key=c4)
    assert (k["note"], k["number"]) == ("C4", 0)
    assert k["neighbours"]["right"] == {"key": tutor.keys(note="D4", near=c4)["keys"][0]["key"], "note": "D4", "number": 5,
                                        "interval": "major second up (M2, 5 steps)"}
    assert (k["neighbours"]["upper_right"]["note"], k["neighbours"]["upper_right"]["number"]) == ("C#4", 2)
    assert k["neighbours"]["lower_left"]["interval"] == "downminor second down (vm2, 2 steps)"
    for other in k["same_note_elsewhere"]:
        assert tutor.keys(key=other["key"])["note"] == "C4"
    assert not fields(k) & INTERNAL_FIELDS
    # an edge key says so instead of naming a key
    edge = tutor.keys(note="C2")["keys"][0]["key"]
    assert tutor.keys(key=edge)["neighbours"]["left"] == "edge of the keyboard"


def test_keys_by_note(tutor):
    every_c = tutor.keys(note="C")
    assert {k["note"] for k in every_c["keys"]} >= {"C2", "C3", "C4"}
    near = every_c["keys"][0]["key"]
    listed = tutor.keys(note="E", near=near)["keys"]
    assert "from_near" in listed[0] and "_d" not in listed[0]
    # spelled as asked: Fb stays Fb although the key's plain name differs
    assert tutor.keys(note="Fb4")["keys"][0]["note"] == "Fb4"
    # by number, with or without octave, and in the form results are written in
    e4 = tutor.keys(note="E4")["keys"]
    assert tutor.keys(note="10(4)")["keys"] == e4 == tutor.keys(note="E4 (10)")["keys"]
    assert e4[0]["number"] == 10
    assert {k["number"] for k in tutor.keys(note="10")["keys"]} == {10}
    assert len({k["note"] for k in tutor.keys(note="10")["keys"]}) >= 3     # every octave
    with pytest.raises(TheoryError, match="numbers its notes 0 to 30"):
        tutor.keys(note="31")
    with pytest.raises(TutorError, match="either key"):
        tutor.keys()
    with pytest.raises(TutorError, match="no key for C9"):
        tutor.keys(note="C9")
    with pytest.raises(BoardError, match="Key ids come from tool results"):
        tutor.keys(key="k777")
    with pytest.raises(TheoryError, match="is not a note"):
        tutor.keys(note="do")


def test_theory_tool(tutor):
    chord = tutor.theory("chord", root="Eb", quality="minor7", inversion=1)
    assert chord["chord"] == "Eb minor7, 1st inversion"
    assert [n.split()[0][:-1] for n in chord["notes"]] == ["Gb", "Bb", "Db", "Eb"]
    assert [n.split()[1] for n in chord["notes"]] == ["(16)", "(26)", "(3)", "(8)"]
    assert chord["bass"].startswith("Gb") and chord["bass"].endswith("(16)")
    assert chord["intervals_above_bass"][0] == "major third (M3, 10 steps)"
    assert tutor.theory("chord", root="C4", quality="neutral")["notes"] == ["C4 (0)", "vE4 (9)", "G4 (18)"]
    # the root may be given by number
    assert tutor.theory("chord", root="0(4)", quality="minor")["notes"] == ["C4 (0)", "Eb4 (8)", "G4 (18)"]
    assert tutor.theory("chord", root="18", quality="major")["chord"] == "G major"

    scale = tutor.theory("scale", root="G", mode="major")
    assert [n.split()[0][:-1] for n in scale["notes"]] == ["G", "A", "B", "C", "D", "E", "F#"]
    assert [n.split()[1] for n in scale["notes"]] == ["(18)", "(23)", "(28)", "(0)", "(5)", "(10)", "(15)"]
    assert scale["chords"][4] == "V: D major" and scale["chords"][6] == "vii°: F# diminished"

    prog = tutor.theory("progression", root="C", mode="major", numerals=["I", "vi", "IV", "V7"])
    assert [c["chord"] for c in prog["chords"]] == ["C major", "A minor", "F major", "G dominant7"]
    assert [n.split()[1] for n in prog["chords"][3]["notes"]] == ["(18)", "(28)", "(5)", "(13)"]

    assert tutor.theory("identify", notes=["C4", "E4", "G4"])["chord"] == "C major"
    assert tutor.theory("identify", notes=["E4", "G4", "C5"])["chord"] == "C major, 1st inversion"
    assert tutor.theory("identify", notes=["C4", "Eb4", "G4", "Bb4"])["chord"] == "C minor7"
    assert tutor.theory("identify", notes=["C4", "vEb4", "G4"])["chord"] == "C subminor"
    assert tutor.theory("identify", keys=chord_keys(tutor, "F4", "minor"))["chord"] == "F minor"
    assert tutor.theory("identify", notes=["C4", "D4"]) == {
        "notes": ["C4 (0)", "D4 (5)"], "intervals_above_bass": ["major second (M2, 5 steps)"], "chord": "no common name"}
    assert tutor.theory("identify", notes=["0(4)", "10(4)", "G4 (18)"])["chord"] == "C major"

    assert tutor.theory("tuning")["thirds"][0]["kind"] == "subminor"
    for call in (lambda: tutor.theory("chord"), lambda: tutor.theory("identify"), lambda: tutor.theory("progression", root="C"), lambda: tutor.theory("guess")):
        with pytest.raises(TutorError):
            call()
    for result in (chord, scale, prog):
        assert not fields(result) & INTERNAL_FIELDS


def test_identify_adds_xentools_chord_names(tutor, fake):
    # xentool names chords per pitch class from Scala's chord list; C E G in 31 = 0, 10, 18
    fake._chord_names = lambda edo, pcs: [
        {"root_pc": 0, "rel": [0, 10, 18], "best": "Major Triad~5c", "names": ["Major Triad~5c"]},
        {"root_pc": 10, "rel": [0, 8, 21], "best": "Major Triad 1st inversion", "names": []},
    ] if (edo, pcs) == (31, [0, 10, 18]) else []
    out = tutor.theory("identify", notes=["E4", "G4", "C5"])
    assert out["chord"] == "C major, 1st inversion"
    assert out["as_played"] == "E: Major Triad 1st inversion"
    assert out["other_readings"] == ["C: Major Triad~5c"]


def test_find_shape(tutor):
    out = tutor.find_shape(root="C4", quality="major")
    way = out["ways"][0]
    assert out["for"] == "C major" and [k["note"] for k in way["keys"]] == ["C4", "E4", "G4"]
    assert [k["number"] for k in way["keys"]] == [0, 10, 18]
    assert way["keys"][1]["from_first"] == "2 right"
    fingers = [k["finger"] for k in way["keys"]]
    assert len(set(fingers)) == 3 and set(fingers) <= {1, 2, 3, 4, 5}
    # the fingering comes with how it feels, and with alternatives: it is a suggestion
    assert way["fingering"]["fingers"] == "-".join(map(str, fingers))
    assert way["fingering"]["feel"] in ("easy", "comfortable") and way["fingering"]["effort"] >= 0
    assert len(way["other_fingerings"]) == 2 and all(o["effort"] >= way["fingering"]["effort"] for o in way["other_fingerings"])
    assert "let the player choose" in out["fingers"]
    assert way["reach"] == "easy"
    assert not fields(out) & INTERNAL_FIELDS
    # keys carry the chord's spelling, not the key's plain name
    sub = tutor.find_shape(root="C4", quality="subminor", limit=1)["ways"][0]
    assert [k["note"] for k in sub["keys"]] == ["C4", "vEb4", "G4"]
    # near: the first way starts at the given key if it plays the root
    twins = next(keys for keys in tutor.keyboard._by_pitch.values() if len(keys) > 1)
    for twin in twins:
        assert ids(tutor.find_shape(notes=[twin.name], near=twin.id, limit=1)["ways"][0]) == [twin.id]
    # left hand: fingers mirrored
    left = tutor.find_shape(root="C4", hand="left", limit=1)["ways"][0]
    assert [k["finger"] for k in left["keys"]] != [k["finger"] for k in way["keys"]]
    # free notes; without an octave the nearest one is taken
    notes = tutor.find_shape(notes=["D", "A"], limit=1)
    assert notes["for"].split()[0][0] == "D" and len(notes["ways"][0]["keys"]) == 2
    with pytest.raises(TutorError, match="give a chord"):
        tutor.find_shape()


# --- lights ---

def test_lights_clear_one_key_only(tutor, fake):
    c, e, g = chord_keys(tutor, "C4")
    out = tutor.set_lights([{"key": c, "role": "root"}, {"key": e}, {"key": g, "color": "#102030"}])
    assert out == {"lit": sorted([c, e, g]), "count": 3}
    assert fake.overlay_state == {address(tutor, c): ROLES["root"], address(tutor, e): ROLES["target"], address(tutor, g): (16, 32, 48)}
    assert fake.dim_base == DIM_BASE
    tutor.set_lights(clear=[e])
    assert set(fake.overlay_state) == {address(tutor, c), address(tutor, g)}
    tutor.set_lights([{"key": c, "role": "finger2"}])        # recolour one, the rest stays
    assert fake.overlay_state[address(tutor, c)] == ROLES["finger2"] and address(tutor, g) in fake.overlay_state
    tutor.set_lights(clear="all")
    assert fake.overlay_state == {}


def test_lights_by_note_light_every_key_of_that_note(tutor, fake):
    tutor.set_lights([{"note": "C4", "role": "rh"}])
    expected = {address(tutor, k["key"]) for k in tutor.keys(note="C4")["keys"]}
    assert set(fake.overlay_state) == expected and len(expected) >= 1
    for bad in ([{"note": "C"}], [{"key": "k777"}], [{"key": "k101", "role": "sparkle"}], [{"key": "k101", "color": "red"}], [{}]):
        with pytest.raises((TutorError, BoardError)):
            tutor.set_lights(bad)
    with pytest.raises(TutorError, match='"all" or a list'):
        tutor.set_lights(clear="everything")


# --- demo, listen, exercise ---

def test_demo_lights_and_sounds_each_step(tutor, fake):
    seen = []
    out = tutor.demo([{"chord": "C4 major"}, {"chord": "F4 major"}, {"note": "G4"}], tempo_bpm=240, beats_per_step=0.4,
                     progress=lambda done, total, msg: seen.append((done, total, msg)))
    assert [p["asked"] for p in out["played"]] == ["C major", "F major", "G4"] and not out["stopped_early"]
    assert seen == [(1, 3, "C major"), (2, 3, "F major"), (3, 3, "G4")]
    sounded = [addr for addr, _, _ in fake.sounded]
    assert sounded[:3] == [address(tutor, k["key"]) for k in out["played"][0]["keys"]]
    assert len(sounded) == 7 and all(ms and ms > 0 for _, _, ms in fake.sounded)
    assert fake.overlay_state == {}                 # lights off afterwards
    assert {a for a, _ in fake.seen} == set(sounded)    # everything sounded was lit
    with pytest.raises(TutorError, match="at most 60 s"):
        tutor.demo([{"note": "C4"}] * 40, tempo_bpm=30)
    with pytest.raises(TutorError, match="step 1 needs one of"):
        tutor.demo([{"play": "something"}])


def test_listen_reports_notes_and_chords(tutor, fake):
    c, e, g = chord_keys(tutor, "C4")
    d = tutor.keys(note="D4", near=c)["keys"][0]["key"]
    Player(tutor, fake, [(0.2, "tap", [d]), (0.3, "down", [c, e, g]), (0.3, "up", [c, e, g])]).start()
    t0 = time.monotonic()
    out = tutor.listen(max_seconds=10, stop_after_silence=0.5)
    assert time.monotonic() - t0 < 4, "ends after the pause, not at max_seconds"
    assert out["note_count"] == 4
    first, second = out["played"]
    assert [k["note"] for k in first["keys"]] == ["D4"] and "together" not in first
    assert [k["number"] for k in second["keys"]] == [0, 10, 18]
    assert [k["note"] for k in second["keys"]] == ["C4", "E4", "G4"] and second["together"] == "C major"
    assert second["at_s"] == pytest.approx(0.36, abs=0.2) and second["held_s"] == pytest.approx(0.3, abs=0.2)
    assert out["still_held"] == []
    assert not fields(out) & INTERNAL_FIELDS


def test_listen_returns_when_nothing_is_played(tutor):
    out = tutor.listen(max_seconds=1, stop_after_silence=0.3)
    assert out["played"] == [] and "nothing was played" in out["message"]


def test_exercise_progression_with_a_wrong_note(tutor, fake):
    c, f, g = (chord_keys(tutor, r) for r in ("C4", "F4", "G4"))
    wrong = tutor.keys(note="D4", near=c[0])["keys"][0]["key"]
    script = [
        (0.2, "down", c), (0.2, "up", c),
        (0.2, "down", [wrong]), (0.15, "up", [wrong]),      # a slip before F major
        (0.2, "down", f), (0.2, "up", f),
        (0.2, "down", g), (0.2, "up", g),
    ]
    Player(tutor, fake, script).start()
    seen = []
    out = tutor.run_exercise([{"chord": "C4 major"}, {"chord": "F4 major"}, {"chord": "G4 major"}], timeout_s=20,
                             progress=lambda done, total, msg: seen.append((done, total, msg)))
    assert out["outcome"] == "finished" and out["completed"] == "3 of 3 steps"
    assert [s["result"] for s in out["steps"]] == ["ok", "ok", "ok"]
    assert out["steps"][1]["wrong_notes"] == ["D4 (5)"] and out["steps"][1]["attempts"] == 2
    assert "wrong_notes" not in out["steps"][0] and out["steps"][0]["attempts"] == 1
    assert out["right_first_time"] == 2 and out["accuracy_percent"] == 90
    assert seen == [(1, 3, "C major: done"), (2, 3, "F major: done"), (3, 3, "G major: done")]
    assert "continue_with" not in out and not fields(out) & INTERNAL_FIELDS
    # lights: every chord key was shown as a hint (the root of each chord orange, the other
    # notes white) and turned green; the slip turned red
    for chord_keys_ in (c, f, g):
        assert any((address(tutor, kid), ROLES["root"]) in fake.seen for kid in chord_keys_)
        assert any((address(tutor, kid), ROLES["target"]) in fake.seen for kid in chord_keys_)
    for kid in c + f + g:
        assert (address(tutor, kid), ROLES["correct"]) in fake.seen
    assert (address(tutor, wrong), ROLES["wrong"]) in fake.seen
    assert fake.overlay_state == {}


def test_exercise_melody_without_hints_and_with_fingers(tutor, fake):
    names = ["C4", "D4", "E4"]
    first = tutor.keys(note="C4")["keys"][0]["key"]
    keys = [tutor.keys(note=n, near=first)["keys"][0]["key"] for n in names]
    Player(tutor, fake, [(0.2, "tap", [k]) for k in keys]).start()
    out = tutor.run_exercise([{"note": n} for n in names], hints="never", timeout_s=10)
    assert out["outcome"] == "finished" and [s["needed_hint"] for s in out["steps"]] == [False] * 3
    assert not any(rgb == ROLES["target"] for _, rgb in fake.seen), "no hint lights with hints='never'"

    c = chord_keys(tutor, "C4")
    Player(tutor, fake, [(0.2, "down", c), (0.2, "up", c)]).start()
    tutor.run_exercise([{"chord": "C4 major"}], fingers=True, timeout_s=10)
    finger_colours = {ROLES[f"finger{n}"] for n in range(1, 6)}
    assert len({rgb for a, rgb in fake.seen if a in {address(tutor, k) for k in c}} & finger_colours) == 3


def test_exercise_time_limit_and_continue(tutor, fake):
    c, f = chord_keys(tutor, "C4"), chord_keys(tutor, "F4")
    steps = [{"chord": "C4 major"}, {"chord": "F4 major"}]
    Player(tutor, fake, [(0.2, "down", c), (0.2, "up", c), (0.2, "down", f[:2]), (0.1, "up", f[:2])]).start()
    out = tutor.run_exercise(steps, timeout_s=1.5)
    assert out["outcome"] == "time limit" and out["completed"] == "1 of 2 steps"
    assert out["steps"][1]["result"] == "timed out"
    # missing = not held when the time ran out; the player had let go of F and A again
    assert out["steps"][1]["missing_notes"] == ["F4 (13)", "A4 (23)", "C5 (0)"]
    assert out["steps"][1]["attempts"] == 1
    assert "start_at=2" in out["continue_with"]
    assert fake.overlay_state == {}
    # continue where the player was, without sending the steps again
    Player(tutor, fake, [(0.2, "down", f), (0.2, "up", f)]).start()
    again = tutor.run_exercise(start_at=2, timeout_s=10)
    assert again["outcome"] == "finished" and again["completed"] == "1 of 1 steps"
    assert [s["step"] for s in again["steps"]] == [2]


def test_exact_keys_and_steps_given_as_keys(tutor, fake):
    # a note that lies on two keys: only the key that was asked for counts
    twins = next(keys for keys in tutor.keyboard._by_pitch.values() if len(keys) > 1)
    shown, other = twins[0].id, twins[1].id
    Player(tutor, fake, [(0.2, "tap", [other]), (0.2, "tap", [shown])]).start()
    out = tutor.run_exercise([{"keys": [shown]}], timeout_s=10)
    assert out["steps"][0]["result"] == "ok" and out["steps"][0]["wrong_notes"] == [f"{twins[0].name} ({twins[0].pitch % 31})"]
    # as notes, either key is fine
    Player(tutor, fake, [(0.2, "tap", [other])]).start()
    out = tutor.run_exercise([{"note": f"{twins[0].pitch % 31}({twins[0].pitch // 31})"}], timeout_s=10)     # by number
    assert out["steps"][0]["result"] == "ok" and "wrong_notes" not in out["steps"][0]


def test_stop_ends_a_waiting_call_and_clears_lights(tutor, fake):
    c = chord_keys(tutor, "C4")
    result = {}
    worker = threading.Thread(target=lambda: result.update(tutor.run_exercise([{"chord": "C4 major"}], timeout_s=30)), daemon=True)
    worker.start()
    time.sleep(0.3)
    assert set(fake.overlay_state) == {address(tutor, k) for k in c}, "hint is lit while waiting"
    with pytest.raises(TutorError, match="still running"):
        tutor.listen(max_seconds=1)
    assert tutor.stop() == {"stopped": True}
    worker.join(timeout=3)
    assert not worker.is_alive() and result["outcome"] == "stopped"
    assert fake.overlay_state == {}
    # and the tutor is free again
    assert tutor.listen(max_seconds=1, stop_after_silence=0.2)["played"] == []


def test_exercise_input_errors_name_the_step(tutor):
    with pytest.raises(TutorError, match="steps is empty"):
        tutor.run_exercise([])
    with pytest.raises(TutorError, match="no earlier exercise"):
        tutor.run_exercise()
    with pytest.raises(TutorError, match="step 2 needs one of"):
        tutor.run_exercise([{"chord": "C4 major"}, {}])
    with pytest.raises(TheoryError, match="unknown chord quality 'wobbly'"):
        tutor.run_exercise([{"chord": "C4 wobbly"}])
    with pytest.raises(TutorError, match="start_at must be between 1 and 1"):
        tutor.run_exercise([{"note": "C4"}], start_at=5)
    with pytest.raises(TutorError, match="hints must be"):
        tutor.run_exercise([{"note": "C4"}], hints="maybe")
    # a refused call leaves the tutor free
    assert tutor.listen(max_seconds=1, stop_after_silence=0.2)["played"] == []


# --- the keyboard changes, or is not there ---

def test_modules_plugged_in_and_removed(tutor, fake):
    assert tutor.keyboard_info(include_map=False)["keys"] == 224
    fake.set_setup(sample_setup(31, (0,)))
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and tutor.keyboard_info(include_map=False)["keys"] != 56:
        time.sleep(0.05)
    assert tutor.keyboard_info(include_map=False)["keys"] == 56
    fake.set_setup(sample_setup(31, ()))
    deadline = time.monotonic() + 3
    with pytest.raises(TutorError, match="no keyboard module is connected"):
        while time.monotonic() < deadline:
            tutor.keyboard_info()
            time.sleep(0.05)


def test_xentool_not_running_says_how_to_start_it():
    t = Tutor(Xentool("http://127.0.0.1:9", timeout=0.3))
    try:
        with pytest.raises(XentoolError, match="xentool serve <layout> --api"):
            t.keyboard_info()
    finally:
        t.pump.stop()
