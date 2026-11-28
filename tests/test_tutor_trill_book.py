"""The player's own trill fingerings (`fingering_book` with `trill`): one entry per hand and
per place of the other key as seen from the main note. It wins over the computed pair
wherever a trill of that shape is fingered, from any key and in every tuning, and is kept
apart from the fingering of the same two keys as a chord."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
from tutor import library as lib  # noqa: E402
from tutor.player import Player  # noqa: E402
from tutor.sample import sample_setup  # noqa: E402
from tutor.session import Tutor, TutorError  # noqa: E402
from tutor.xt import FakeXentool  # noqa: E402

FIVE = (0, 1, 2, 3, 4)
UP_RIGHT = "to the key to the upper right"


def tutor(edo: int, player: Player | None = None) -> Tutor:
    return Tutor(FakeXentool(sample_setup(edo, FIVE)), library=lib.Library(Path(__file__).parent / "no-library"), player=player)


def close(*tutors: Tutor) -> None:
    for t in tutors:
        t.stop()
        t.pump.stop()


def trill_of(t: Tutor, main: str, other: str, hand: str = "right", **more) -> dict:
    return t.fingering([{"trill": [main, other], **more}], hand=hand)["steps"][0]


def fingers(step: dict) -> list[int]:
    return [k["finger"] for k in step["keys"]]


def pair(step: dict) -> list[int]:
    """The two fingers of a trill step, the main note's first; the keys carry the same fingers."""
    told = [int(f) for f in step["trill"]["fingers"].split(":")[0].split("-")]
    by_note = {k["note"]: k["finger"] for k in step["keys"]}
    assert [by_note[side[0].split()[0]] for side in (step["trill"]["main"], step["trill"]["other"])] == told
    return told


def test_without_an_entry_the_computed_pair_is_a_suggestion_with_a_question():
    t = tutor(53)
    try:
        step = trill_of(t, "C4", "C#4")
        told = step["trill"]
        computed = told["fingers"].split(":")[0]
        assert told["shape"].startswith(UP_RIGHT + " (5 steps up, a diatonic semitone") and "53 notes per octave" in told["shape"]
        assert "nobody has tried on this keyboard" in told["fingers_from"] and "C. P. E. Bach" in told["fingers_from"] and "yours" not in told
        assert told["ask"] == f"I have no fingering of yours for a trill {UP_RIGHT}; I would try {computed}: which fingers do you use?"
        ids = [k["key"] for k in step["keys"]]
        assert f"keys [{ids[0]}, {ids[1]}]" in told["then"] and "trill true" in told["then"]
        book = t.fingering_book("list")
        assert "own_trill_fingerings" not in book and "nobody has tried" in book["trills"] and book["own_fingerings"] == []
    finally:
        close(t)


def test_an_entry_wins_on_every_root_and_in_another_tuning(tmp_path):
    path = tmp_path / "state" / "player.json"
    t53 = tutor(53, Player(path))
    t31 = None
    try:
        before = trill_of(t53, "C4", "C#4")
        computed = before["trill"]["fingers"].split(":")[0]
        mine = [2, 4] if computed != "2-4" else [3, 4]
        text = "-".join(map(str, mine))
        saved = t53.fingering_book("save", trill=True, notes=["C4", "C#4"], fingers=mine)
        assert saved["saved"]["for"] == "trill " + UP_RIGHT and saved["saved"]["fingers"] == text and saved["saved"]["hand"] == "right"
        assert "5 steps up" in saved["saved"]["now"] and saved["computed_instead"].startswith(computed)
        assert "Your own fingering" in saved["note"] and "another tuning" in saved["note"] and "from any key" in saved["note"]
        # the same two keys, another root, with the keys given
        for main, other in (("C4", "C#4"), ("G4", "G#4"), ("Bb3", "B3")):
            step = trill_of(t53, main, other)
            assert fingers(step) == mine and step["trill"]["yours"].startswith("your own fingering"), (main, other)
            assert step["trill"]["fingers"].startswith(text + ": ") and "ask" not in step["trill"]
            assert computed in [p.split()[0] for p in step["trill"]["other_pairs"]] and "alternatives" in step["trill"]["fingers_from"]
        assert "another tuning" in trill_of(t53, "C4", "C#4")["trill"]["fingers_from"]
        # the file is readable: one entry, the place of the other key in mm, main note's finger first
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["trills"] == [{"hand": "right", "to": [10, 17], "fingers": mine, "label": "trill " + UP_RIGHT}] and data["book"] == []

        # another tuning on the same keys: the same shape is another interval there, the fingers stay
        t31 = tutor(31, Player(path))
        step = trill_of(t31, "C4", "C#4")
        assert fingers(step) == mine and "yours" in step["trill"]
        assert step["trill"]["shape"].startswith(UP_RIGHT + " (2 steps up, a chromatic semitone") and "31 notes per octave" in step["trill"]["shape"]
        listed = t31.fingering_book("list")
        entry, = listed["own_trill_fingerings"]
        assert entry["hand"] == "right" and entry["fingers"] == text and entry["trill"] == UP_RIGHT and "2 steps up" in entry["now"]
        assert "every tuning" in listed["trills"] and listed["own_fingerings"] == []
        entry53, = t53.fingering_book("list")["own_trill_fingerings"]
        assert "5 steps up, a diatonic semitone" in entry53["now"] and entry53["trill"] == UP_RIGHT
        # what is 5 steps in 53 on other keys is not this entry: the interval does not carry it
        # (in 31 the diatonic semitone lies to the lower right)
        other = trill_of(t31, "E4", "F4")
        assert "lower right" in other["trill"]["shape"] and "yours" not in other["trill"] and "ask" in other["trill"]
    finally:
        close(*(x for x in (t53, t31) if x))


def test_direction_and_hand_matter():
    t = tutor(53)
    try:
        t.fingering_book("save", trill=True, notes=["C4", "D4"], fingers=[1, 3])
        assert pair(trill_of(t, "F4", "G4")) == [1, 3]
        # the trill back down from the right neighbour is the mirror: its own shape, no entry yet
        down = trill_of(t, "G4", "F4")
        assert "yours" not in down["trill"] and "the key to the left" in down["trill"]["ask"] and "9 steps down" in down["trill"]["shape"]
        # the left hand has its own
        assert "yours" not in trill_of(t, "F4", "G4", hand="left")["trill"]
        t.fingering_book("save", trill=True, notes=["G4", "F4"], fingers=[4, 2])
        t.fingering_book("save", trill=True, notes=["C4", "D4"], fingers=[3, 2], hand="left")
        assert pair(trill_of(t, "A4", "G4")) == [4, 2] and pair(trill_of(t, "F4", "G4")) == [1, 3]
        assert pair(trill_of(t, "F4", "G4", hand="left")) == [3, 2]
        listed = t.fingering_book("list")["own_trill_fingerings"]
        assert [(e["hand"], e["trill"], e["fingers"]) for e in listed] == [
            ("right", "to the key to the left", "4-2"), ("right", "to the key to the right", "1-3"), ("left", "to the key to the right", "3-2")]
        # a step may still name another pair to try; the player's own is mentioned
        tried = trill_of(t, "F4", "G4", fingers=[2, 3])
        assert fingers(tried) == [2, 3] and "1-3" in tried["trill"]["yours"] and "ask" not in tried["trill"]
        # saving again replaces; forget removes that direction only
        t.fingering_book("save", trill=True, notes=["C4", "D4"], fingers=[2, 3])
        assert pair(trill_of(t, "F4", "G4")) == [2, 3] and len(t.fingering_book("list")["own_trill_fingerings"]) == 3
        gone = t.fingering_book("forget", trill=True, notes=["C4", "D4"])
        assert gone["forgotten"] == "trill to the key to the right, right hand" and "untried" in gone["note"]
        assert "ask" in trill_of(t, "F4", "G4")["trill"] and pair(trill_of(t, "A4", "G4")) == [4, 2]
        assert t.fingering_book("forget", trill=True, notes=["C4", "D4"])["forgotten"] is None
        with pytest.raises(TutorError, match="two different fingers"):
            t.fingering_book("save", trill=True, notes=["C4", "D4"], fingers=[2, 2])
        with pytest.raises(TutorError, match="two different fingers"):
            t.fingering_book("save", trill=True, notes=["C4", "D4"], fingers=[1, 2, 3])
        with pytest.raises(TutorError, match="main note first"):
            t.fingering_book("save", trill=True, fingers=[1, 2])
        with pytest.raises(TutorError, match="one hand"):
            t.fingering_book("save", trill=True, notes=["C4", "D4"], fingers=[1, 2], hand="both")
    finally:
        close(t)


def test_a_trill_entry_and_the_chord_of_the_same_two_keys_do_not_touch_each_other():
    t = tutor(53)
    try:
        chord = t.find_shape(notes=["C4", "D4"], limit=1)["ways"][0]
        computed_chord = fingers(chord)
        t.fingering_book("save", trill=True, notes=["C4", "D4"], fingers=[1, 4])
        after = t.find_shape(notes=["C4", "D4"], limit=1)["ways"][0]
        assert fingers(after) == computed_chord and "yours" not in after["fingering"] and t.fingering_book("list")["own_fingerings"] == []
        # and the other way round: an own fingering for holding the two keys leaves the trill alone
        held = [2, 5] if computed_chord != [2, 5] else [1, 5]
        t.fingering_book("save", notes=["C4", "D4"], fingers=held)
        assert fingers(t.find_shape(notes=["C4", "D4"], limit=1)["ways"][0]) == held
        assert pair(trill_of(t, "C4", "D4")) == [1, 4]
        t.fingering_book("forget", trill=True, notes=["C4", "D4"])
        step = trill_of(t, "C4", "D4")
        assert "ask" in step["trill"] and "yours" not in step["trill"] and fingers(step) != held
        assert fingers(t.find_shape(notes=["C4", "D4"], limit=1)["ways"][0]) == held
    finally:
        close(t)


@pytest.mark.parametrize("edo", [31, 53])
def test_the_trill_drill_takes_the_players_pair(edo):
    t = tutor(edo)
    try:
        plain = t.library("pattern", name="trill", root="A4", interval="whole tone")
        assert len(plain["groups"]) == 3 and all("suggestion" in g and "yours" not in g for g in plain["groups"])
        assert plain["ask"].startswith("I have no fingering of yours for a trill to the key to the right; I would try " + plain["groups"][0]["fingers"])
        assert "nobody has tried" in plain["finger_pairs"] and plain["shape"].startswith("to the key to the right (")
        t.fingering_book("save", trill=True, notes=["C4", "D4"], fingers=[1, 2])
        mine = t.library("pattern", name="trill", root="A4", interval="whole tone")
        group, = mine["groups"]
        assert group["fingers"] == "1-2" and group["yours"].startswith("your own fingering") and "ask" not in mine
        assert all(s["fingers"] == [1, 2] for s in mine["steps"]) and len(mine["steps"]) == 3
        assert "every tuning" in mine["finger_pairs"] and mine["other_pairs"] and not any(p.startswith("1-2") for p in mine["other_pairs"])
        assert "player's own" in mine["note"]
        assert fingers(t.fingering([mine["steps"][0]])["steps"][0]) == [1, 2]
        # more pairs on request: the own one first, computed ones after it as alternatives
        more = t.library("pattern", name="trill", root="A4", interval="whole tone", count=3)
        assert [("yours" in g, "suggestion" in g) for g in more["groups"]] == [(True, False), (False, True), (False, True)]
        assert more["groups"][0]["fingers"] == "1-2" and "alternative" in more["groups"][1]["suggestion"]
        # another interval is another shape
        assert "ask" in t.library("pattern", name="trill", root="A4", interval="step")
        # demo lights the two keys in the player's finger colours
        shown = t.demo([mine["steps"][2]], tempo_bpm=240, trill_rate=16, fingers=True)
        assert fingers(shown["played"][0]) == [1, 2]
    finally:
        close(t)


@pytest.mark.parametrize("edo", [31, 53])
def test_the_shapes_to_ask_about(edo):
    t = tutor(edo)
    try:
        out = t.fingering_book("trill_shapes", hand="right")
        shapes = out["shapes"]
        assert [s["trill"] for s in shapes[:6]] == ["to the key to the " + d for d in (
            "right", "upper right", "upper left", "left", "lower left", "lower right")]
        whole = 9 if edo == 53 else 5
        assert shapes[0]["now"].startswith(f"{whole} steps up, a whole tone") and shapes[3]["now"].startswith(f"{whole} steps down")
        # the next ring: only what is a whole tone or less; straight up is one step of the tuning
        assert len(shapes) == 10 and out["still_to_ask"] == 10 and "10 shapes" in out["which"] and "whole tone" in out["which"]
        up = next(s for s in shapes if "straight away from you" in s["trill"])
        assert up["now"].startswith("1 step " + ("up, a comma" if edo == 53 else "down, a diesis"))
        assert all(set(s) == {"trill", "now", "light", "notes", "yours", "computed"} and s["yours"] is None for s in shapes)
        kb = t.keyboard
        for s in shapes:
            main, other = kb.key(s["light"]["main"]), kb.key(s["light"]["other"])
            assert main.id == out["main_key"]["key"] and kb.distance(main, other) <= 2.01 and abs(other.pitch - main.pitch) <= whole
            assert s["computed"] == "-".join(map(str, pair(t.fingering([{"trill": [main.name, other.name], "near": main.id}])["steps"][0])))
        # an answer is saved with the two lit keys and flagged from then on
        ask = shapes[1]
        t.fingering_book("save", trill=True, keys=[ask["light"]["main"], ask["light"]["other"]], fingers=[3, 4])
        again = t.fingering_book("trill_shapes", hand="right")
        assert [s["yours"] for s in again["shapes"]] == [None, "3-4"] + [None] * 8 and again["still_to_ask"] == 9
        both = t.fingering_book("trill_shapes", hand="both")
        assert both["still_to_ask"] == 19 and both["shapes"][1]["right"]["yours"] == "3-4" and both["shapes"][1]["left"]["yours"] is None
        assert both["shapes"][0]["left"]["computed"] != both["shapes"][0]["right"]["computed"]
        assert "every tuning" in again["note"] and "nobody has tried" in again["how"]
    finally:
        close(t)


def test_an_old_player_file_loads_and_entries_survive_a_restart(tmp_path):
    path = tmp_path / "player.json"
    old = {"hand": {"size": "large", "rest": None, "thumb_span_mm": 210.0, "finger_span_mm": None}, "offset_ms": None,
           "book": [{"hand": "right", "shape": [[0, 0], [38, 0], [67, 17]], "fingers": [1, 2, 5], "label": "major"}]}
    path.write_text(json.dumps(old), encoding="utf-8")
    player = Player(path)
    assert player.trills == {} and player.size == "large" and len(player.book) == 1 and player.trill_entries() == []
    t = tutor(53, player)
    try:
        t.fingering_book("save", trill=True, notes=["C4", "^C4"], fingers=[2, 3], hand="left")
    finally:
        close(t)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["book"] == old["book"] and data["hand"]["thumb_span_mm"] == 210.0 and len(data["trills"]) == 1
    assert data["trills"][0]["hand"] == "left" and data["trills"][0]["fingers"] == [2, 3] and data["trills"][0]["to"] == [0, 33]
    assert "straight away from you" in data["trills"][0]["label"]
    again = tutor(53, Player(path))
    try:
        assert pair(trill_of(again, "E4", "^E4", hand="left")) == [2, 3] and len(again.player.book) == 1
        assert again.fingering_book("forget", trill=True, notes=["C4", "^C4"], hand="left")["forgotten"]
    finally:
        close(again)
    assert json.loads(path.read_text(encoding="utf-8"))["trills"] == [] and Player(path).trills == {}
    # positions a fraction of a millimetre apart are the same shape
    p = Player()
    p.remember_trill("right", (0.0, 0.0), (9.6, 16.63), (2, 3), "x")
    assert p.trill_preferred("right", (100.0, 50.0), (110.4, 66.2)) == (2, 3) and p.trill_preferred("right", (0.0, 0.0), (-9.6, -16.63)) is None
    assert p.trill_preferred("left", (0.0, 0.0), (9.6, 16.63)) is None and p.preferred("right", [(0.0, 0.0), (9.6, 16.63)]) is None
