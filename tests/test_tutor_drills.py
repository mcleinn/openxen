"""Drills of the tutor: chord inversions as library patterns, and trills (a written-out trill
of a score as one step, judged by its effect, demonstrated as an even alternation, with a
finger pair; the trill drill). On made-up data; one test on the real library if it is built."""
from __future__ import annotations

import itertools
import json
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
from tutor import library as lib  # noqa: E402
from tutor import library_build as build  # noqa: E402
from tutor import playalong, trills  # noqa: E402
from tutor.engine import Exercise, Finished, Mark, Press, Step, StepDone  # noqa: E402
from tutor.sample import sample_setup  # noqa: E402
from tutor.session import Tutor, TutorError  # noqa: E402
from tutor.xt import FakeXentool  # noqa: E402

FIVE = (0, 1, 2, 3, 4)
THIRD = {31: "E", 53: "vE"}         # the major third above C: the comma-lowered one in 53


@pytest.fixture(scope="module", params=[31, 53])
def tuned(request):
    fake = FakeXentool(sample_setup(request.param, FIVE))
    t = Tutor(fake, library=lib.Library(Path(__file__).parent / "no-library"))
    yield request.param, t, fake
    t.stop()
    t.pump.stop()


def numbers(step: dict) -> list[int]:
    return [int(n.split("(")[1].rstrip(")")) for n in step["notes"]]


def plain(label: str) -> str:
    return label.split()[0].rstrip("0123456789")


# --- inversions ---

def test_all_inversions_of_a_chord_up_and_back(tuned):
    edo, t, _ = tuned
    third = THIRD[edo]
    out = t.library("pattern", name="inversions", root="C", quality="major", count=1)
    steps = out["steps"]
    assert [s["label"] for s in steps] == ["C major, root position", "C major, 1st inversion", "C major, 2nd inversion",
                                           "C major, root position", "C major, 2nd inversion", "C major, 1st inversion",
                                           "C major, root position"]
    # spelled for the tuning: the third of a major chord is the comma-lowered one in 53
    assert [plain(n) for n in steps[1]["notes"]] == [third, "G", "C"] and [plain(n) for n in steps[2]["notes"]] == ["G", "C", third]
    assert steps[1]["say"] == f"C major, 1st inversion: {third}, the third, is lowest; the root C is on top"
    assert steps[2]["say"] == "C major, 2nd inversion: G, the fifth, is lowest; the root C is second from the top"
    assert steps[0]["say"] == "C major, root position: the root C is lowest"
    assert steps[1]["also_written"] == f"C/{third} (slash chord); figured bass 6" and "6/4" in steps[2]["also_written"]
    assert plain(steps[1]["root"]) == "C" and steps[1]["lowest"] == steps[1]["notes"][0] and steps[1]["inversion"] == 1
    assert numbers(steps[3]) == numbers(steps[0]) and steps[3]["notes"] != steps[0]["notes"]       # the next octave
    assert "ONE hand shape" in out["note"] and "three shapes for a major chord" in out["note"]
    # one shape per inversion wherever it is played: the same hand shape an octave higher
    low, high = (t.find_shape(notes=s["notes"], limit=1)["ways"][0] for s in (steps[0], steps[3]))
    assert [k.get("from_first") for k in low["keys"]] == [k.get("from_first") for k in high["keys"]]
    # the other tools take the steps unchanged, and the root keeps its colour
    told = t.fingering(steps[:3])["steps"]
    assert [s["asked"] for s in told] == [s["label"] for s in steps[:3]]
    for entry in told:
        assert [plain(k["note"]) for k in entry["keys"] if k.get("role") == "root"] == ["C"]
    shown = t.demo(steps[:3], tempo_bpm=240, beats_per_step=0.25)
    assert len(shown["played"]) == 3 and "root" in shown["say"]
    two = t.library("pattern", name="inversions", root="C", quality="major")
    assert two["octaves"] == 2 and len(two["steps"]) == 13
    down = t.library("pattern", name="inversions", root="C", quality="major", count=1, direction="down")["steps"]
    assert [s["inversion"] for s in down] == [0, 2, 1, 0, 1, 2, 0] and down[0]["notes"] == steps[3]["notes"]


def test_four_note_chords_and_the_broken_form(tuned):
    edo, t, _ = tuned
    out = t.library("pattern", name="inversions", root="C", quality="dominant7", voicing="arpeggio", count=1)
    assert out["form"] == "broken" and [g["label"].split(", ")[1] for g in out["groups"]][:5] == [
        "root position", "1st inversion", "2nd inversion", "3rd inversion", "root position"]
    third = out["groups"][3]
    assert "the seventh, is lowest" in third["say"] and [s["beats"] for s in third["steps"]] == [0.5, 0.5, 0.5, 1]
    assert "played from the top down" in out["groups"][-2]["say"]
    assert out["steps"] == [s for g in out["groups"] for s in g["steps"]]
    assert "four shapes for a dominant7 chord" in out["note"]
    t.demo(third["steps"], tempo_bpm=240, outline=True)
    assert [s["asked"] for s in t.fingering(third["steps"])["steps"]] == [n["note"].split(" (")[0] for n in third["steps"]]
    with pytest.raises(TutorError, match="voicing must be full"):
        t.library("pattern", name="inversions", root="C", voicing="shell")
    xen = "neutral" if edo == 31 else "subminor"            # a quality a piano lacks, if the tuning has it
    assert t.library("pattern", name="inversions", root="D", quality=xen, count=1)["steps"][1]["label"] == f"D {xen}, 1st inversion"


def test_one_inversion_through_a_progression(tuned):
    edo, t, _ = tuned
    scale = t.library("pattern", name="inversion_through", root="C", scale="major", inversion=1)
    assert [s["label"] for s in scale["steps"]] == [f"{c}, 1st inversion" for c in (
        "C major", "D minor", "E minor", "F major", "G major", "A minor", "B diminished", "C major")]
    assert all(s["inversion"] == 1 and "the third, is lowest" in s["say"] for s in scale["steps"])
    assert [plain(n) for n in scale["steps"][0]["notes"]] == [THIRD[edo], "G", "C"]
    assert [s["in_the_source"] for s in scale["steps"]][:3] == ["I", "ii", "iii"]
    romans = t.library("pattern", name="inversion_through", root="G", chords=["I", "IV", "V7", "I"], inversion=2)
    assert [s["label"] for s in romans["steps"]] == ["G major, 2nd inversion", "C major, 2nd inversion", "D dominant7, 2nd inversion",
                                                     "G major, 2nd inversion"]
    assert plain(romans["steps"][0]["lowest"]) == "D" and "second from the top" in romans["steps"][0]["say"]
    named = t.library("pattern", name="inversion_through", chords=["C major", "A minor", "Dm7"], inversion=1)
    assert [s["label"] for s in named["steps"]] == ["C major, 1st inversion", "A minor, 1st inversion", "D minor7, 1st inversion"]
    with pytest.raises(TutorError, match="has three notes and no 3rd inversion"):
        t.library("pattern", name="inversion_through", chords=["C major"], inversion=3)
    assert len(t.fingering(named["steps"])["steps"]) == 3


def test_nearest_inversion_holds_the_common_notes(tuned):
    edo, t, _ = tuned
    third = THIRD[edo]
    out = t.library("pattern", name="nearest_inversions", root="C", chords=["I", "IV", "V", "I"])
    steps = out["steps"]
    assert steps[0]["label"] == "C major, root position" and steps[1]["label"] == "F major, 2nd inversion"
    assert steps[1]["voices"].startswith("C stays; ") and f"{third} moves up to F" in steps[1]["voices"]
    assert "C stays" in steps[1]["say"] and steps[1]["notes"][0] == steps[0]["notes"][0]            # C is the same key
    tuning = t.keyboard.tuning
    for before, after in zip(steps, steps[1:]):
        a, b = ({tuning.parse(n)[0] for n in s["notes"]} for s in (before, after))
        shared = {p % edo for p in a} & {p % edo for p in b}
        assert {p for p in a if p % edo in shared} == {p for p in b if p % edo in shared}, "a note both chords have stays where it is"
        assert ("no note stays" not in after["voices"]) == bool(shared)
        # no other inversion of the chord lies nearer: the voices could not move less
        def way(target) -> int:         # the least all voices together move to reach this voicing
            return min(sum(abs(x - y) for x, y in zip(sorted(a), order)) for order in itertools.permutations(target))

        root, quality = after["label"].split(", ")[0].split()
        for inversion in range(3):
            for octave in (3, 4):
                assert way(tuning.chord(tuning.parse(f"{root}{octave}")[0], quality, inversion).pitches) >= way(b)
    sevenths = t.library("pattern", name="nearest_inversions", chords=["Dm7", "G7", "Cmaj7"])["steps"]
    assert [s["label"] for s in sevenths] == ["D minor7, root position", "G dominant7, 2nd inversion", "C major7, root position"]
    assert "stay; A moves down to G" in sevenths[1]["voices"] and sevenths[1]["voices"].startswith("D and ")
    assert len(t.demo(steps, tempo_bpm=240, beats_per_step=0.25)["played"]) == 4


def test_the_naming_drill_is_shuffled_and_reproducible(tuned):
    edo, t, fake = tuned
    chords = ["C major", "F major", "G major"]
    a = t.library("pattern", name="name_inversions", chords=chords, seed=7)
    b = t.library("pattern", name="name_inversions", chords=chords, seed=7)
    c = t.library("pattern", name="name_inversions", chords=chords, seed=8)
    in_order = [f"{ch}, {inv}" for ch in chords for inv in ("root position", "1st inversion", "2nd inversion")]
    assert a["steps"] == b["steps"] and [s["label"] for s in a["steps"]] != [s["label"] for s in c["steps"]]
    assert sorted(s["label"] for s in a["steps"]) == sorted(in_order) and [s["label"] for s in a["steps"]] != in_order
    assert a["answers"] == [f"{n}. {s['answer']}" for n, s in enumerate(a["steps"], 1)] and a["seed"] == 7
    one = t.library("pattern", name="name_inversions", root="C", quality="major", seed=3, count=2)
    assert len(one["steps"]) == 2 and all(s["answer"].startswith("C major, ") and "lowest" in s["answer"] for s in one["steps"])
    # the reverse: the tutor names it, the player plays it (run_exercise on the same steps, no lights)
    step = a["steps"][0]
    keys = [k["key"] for k in t.fingering([step])["steps"][0]["keys"]]
    Player(t, fake, [(0.2, "down", keys), (0.2, "up", keys)]).start()
    played = t.run_exercise([step], hints="never", timeout_s=10)
    assert played["outcome"] == "finished" and played["steps"][0]["asked"] == step["label"]


def test_drills_are_listed_and_a_tune_of_the_library_can_be_drilled(tmp_path):
    source, out = tmp_path / "src", tmp_path / "lib"
    (source / "jazz").mkdir(parents=True)
    tune = {"Title": "Two Five", "Composer": "Nobody", "Key": "C", "Rhythm": "Ballad", "TimeSignature": "4/4",
            "Sections": [{"Label": "A", "MainSegment": {"Chords": "Dm7|G7|Cmaj7|Cmaj7"}}]}
    (source / "jazz" / "JazzStandards.json").write_text(json.dumps([tune]), encoding="utf-8")
    build.build(source, out)
    t = Tutor(FakeXentool(sample_setup(53, FIVE)), library=lib.Library(out))
    try:
        listed = t.library("overview")["patterns"]
        assert "threes" in listed["names"] and set(lib.DRILLS) <= set(listed["drills"])
        steps = t.library("pattern", name="nearest_inversions", id="jazz/two-five")["steps"]
        assert [s["in_the_source"] for s in steps] == ["Dm7", "G7", "Cmaj7"]
        # the roots follow the key as the jazz changes do: the second-degree chord a comma low in 53
        assert steps[0]["label"] == "vD minor7, root position" and numbers(steps[0])[0] == 8
        assert "stay" in steps[1]["voices"] and steps[1]["inversion"] == 2
        first = t.library("pattern", name="inversion_through", id="jazz/two-five", section="A", inversion=3)
        assert [s["inversion"] for s in first["steps"]] == [3, 3, 3] and "section 1 (A)" in first["progression"]
        with pytest.raises(TutorError, match="Or a drill: inversions"):
            t.library("pattern", name="nothing")
    finally:
        t.stop()
        t.pump.stop()


# --- trills: finding them in a score ---

def events(*rows) -> list[trills.Event]:
    return [trills.Event(at, dur, tuple(pitches), tuple(marked), tuple(grace)) for at, dur, pitches, marked, grace in
            ((*row, (), ())[:5] for row in rows)]


def test_a_written_out_trill_is_found_with_its_two_notes_and_its_length():
    strokes = [(0.125 * i, 0.125, [60 + 2 * (i % 2)], [60] if i == 0 else []) for i in range(12)]
    run, = trills.find_runs(events(*strokes, (1.5, 0.5, [60]), (2.0, 0.5, [57])))
    assert (run.main, run.other, run.start, run.end, run.quarters, len(run.strokes), run.marked) == ((60,), (62,), 0.0, 1.5, 1.5, 12, True)
    # it ends at a long closing note, at another note, at the next trill sign; a missing stroke and a note in between do not end it
    gapped = [s for i, s in enumerate(strokes) if i != 5] + [(0.9, 0.3, [40])]
    assert trills.find_runs(events(*sorted(gapped), (1.5, 0.5, [60])))[0].quarters == 1.5
    second = [(1.5 + 0.125 * i, 0.125, [62 + 2 * (i % 2)], [62] if i == 0 else []) for i in range(8)]
    one, two = trills.find_runs(events(*strokes, *second))
    assert (one.quarters, two.main, two.other, two.quarters) == (1.5, (62,), (64,), 1.0)
    # grace notes are never strokes: before it they lead in, among its last strokes they are its ending
    graced = [(-0.1, 0.05, [59], [], [59])] + strokes + [(1.41, 0.04, [65], [], [65])]
    run, = trills.find_runs(events(*sorted(graced)))
    assert (run.lead_in, run.ending, len(run.strokes)) == ((59,), (65,), 12)
    # the first stroke may stand in a chord with held notes: only the note under the sign trills
    chord = [(0.0, 2.0, [48, 60], [60])] + strokes[1:]
    run, = trills.find_runs(events(*chord))
    assert (run.main, run.other, len(run.strokes)) == ((60,), (62,), 12)


def test_tremolos_without_a_sign_and_what_is_not_one():
    chord, low = [72, 76, 79], [60]
    tremolo = [(0.125 * i, 0.125, chord if i % 2 == 0 else low) for i in range(16)]
    run, = trills.find_runs(events(*tremolo, (2.0, 1.0, [60])))
    assert (run.main, run.other, run.quarters, run.marked) == (tuple(chord), (60,), 2.0, False)
    assert trills.kind_of(run.main, run.other, 2) == "tremolo" and trills.kind_of((60,), (62,), 2) == "trill"
    assert trills.kind_of((60,), (67,), 2) == "tremolo"
    # too short, too slow (sixteenth notes: a written figure), or not taking turns: left as written
    assert trills.find_runs(events(*tremolo[:5], (0.625, 1.0, [50]))) == []
    assert trills.find_runs(events(*[(0.25 * i, 0.25, [60 + 7 * (i % 2)]) for i in range(16)])) == []
    assert trills.find_runs(events(*[(0.125 * i, 0.125, [60 + (i % 4)]) for i in range(16)])) == []
    assert trills.find_runs(events(*[(0.125 * i, 0.125, [[66], [70], [66], [73]][i % 4]) for i in range(16)])) == []
    assert trills.beats_words(1.5) == "a beat and a half" and trills.beats_words(3) == "three beats" and trills.beats_words(1.25) == "1.25 beats"


@pytest.fixture(scope="module")
def trill_piece(tmp_path_factory):
    """One bar in 24 notes per octave: the right hand trills C4-D4 for a beat and a half, written
    out in thirty-second notes under a trill sign, then holds E4; the left hand strikes a note
    with the trill's start and a chord on the second beat, while the trill goes on."""
    source, out = tmp_path_factory.mktemp("src"), tmp_path_factory.mktemp("lib")
    (source / "wyschnegradsky").mkdir()
    C4 = 96
    notes = [{"onset": 0.125 * i, "dur": 0.125, "step": C4 + 4 * (i % 2), "piano": 1, "bar": 1, "hand": "right", **({"trill": True} if i == 0 else {})}
             for i in range(12)]
    notes += [{"onset": 1.5, "dur": 2.5, "step": C4 + 8, "piano": 1, "bar": 1, "hand": "right"},
              {"onset": 0.0, "dur": 1.0, "step": C4 - 24, "piano": 1, "bar": 1, "hand": "left"},
              {"onset": 1.0, "dur": 3.0, "step": C4 - 24 + 8, "piano": 1, "bar": 1, "hand": "left"},
              {"onset": 1.0, "dur": 3.0, "step": C4 - 24 + 14, "piano": 1, "bar": 1, "hand": "left"}]
    prelude = {"number": 3, "tuning": 24, "bars": 1, "time": "4/4", "time_changes": [{"bar": 1, "time": "4/4"}], "notes": notes,
               "hands_from": "op. 22a (Belaieff 418)"}
    (source / "wyschnegradsky" / "preludes.json").write_text(json.dumps([prelude]), encoding="utf-8")
    build.build(source, out)
    fake = FakeXentool(sample_setup(24, FIVE))
    t = Tutor(fake, library=lib.Library(out))
    t.layouts_dir = out / "none"
    yield t, fake, "score/wyschnegradsky-prelude-03"
    t.stop()
    t.pump.stop()


def test_a_written_out_trill_of_a_score_is_one_step(trill_piece):
    t, _, piece = trill_piece
    assert len(t.music.piece(piece)["score"][0]["staves"]["upper"]) == 13          # the file keeps every stroke
    right = t.library("get", id=piece, phrase=1, part="upper")
    trill, held = right["steps"]
    assert trill["trill"] == ["C4 (0)", "D4 (4)"] and trill["kind"] == "trill" and trill["lasts"] == 1.5 and trill["beats"] == 1.5
    assert trill["say"] == ("a trill: alternate these two keys quickly and evenly for a beat and a half, starting on C4; "
                            "how many times does not matter")
    assert "12 strokes" in trill["written"] and "trill sign" in trill["written"] and trill["stroke_beats"] == 0.125
    assert "major second" in trill["interval"] and held == {"note": "E4 (8)", "beats": 2.5}
    assert "ONE step" in right["trills"]
    # with the left hand: its note is struck with the trill's start, its chord enters on beat 2 while the trill goes on
    both = t.library("get", id=piece, phrase=1, part="both")["steps"]
    assert [s.get("beats", 1) for s in both] == [1.0, 0.5, 2.5] and sum(s.get("beats", 1) for s in both) == 4
    assert both[0]["trill"] == ["C4 (0)", "D4 (4)"] and both[0]["with"] == ["C3 (0)"] and both[0]["lasts"] == 1.5
    assert both[1]["notes"] == ["E3 (8)", "G3 (14)"] and "trill goes on" in both[1]["over_trill"]
    assert "over_trill" not in both[2] and "over_trill" not in both[0]
    left = t.library("get", id=piece, phrase=1, part="lower")
    assert "trills" not in left and [s.get("beats", 1) for s in left["steps"]] == [1, 3.0]


def test_play_along_takes_the_same_notes_for_strokes(trill_piece):
    t, _, piece = trill_piece
    bars = t.music.piece(piece)["score"]
    notes, _, _ = playalong.plan(bars, "both", lambda n: 60.0, lambda step: step, lambda pitch: True)
    right = sorted((n for n in notes if n.hand == "upper"), key=lambda n: n.q)
    assert [n.kind for n in right] == ["note"] + ["trill"] * 11 + ["note"]         # the first stroke is judged, the rest are ornaments
    assert all(n.absorb == frozenset({96, 100}) for n in right[:12]) and not right[12].absorb
    assert all(n.kind == "note" for n in notes if n.hand == "lower")
    # a tremolo without a sign is taken the same way, since the same rule finds it
    bar = {"n": 1, "time": "4/4", "length": 4.0, "staves": {"upper": [[0.125 * i, 0.125, [60, 64] if i % 2 == 0 else [72]] for i in range(16)]
                                                           + [[2.0, 2.0, [67]]], "lower": []}}
    notes, _, _ = playalong.plan([bar], "upper", lambda n: 60.0, lambda step: step, lambda pitch: True)
    assert [n.kind for n in sorted(notes, key=lambda n: (n.q, n.pitch))] == ["note", "note"] + ["trill"] * 22 + ["note"]


# --- trills: judging by effect ---

A, B, X = 60, 62, 65
TRILL = Step("trill", (), ("a", "b"), trill=((A,), (B,)))


def alternate(ex: Exercise, changes: int, gap=0.1, start: float = 1.0, first: int = A, velocity=(80, 80)) -> tuple[list, float]:
    """Strike the two keys in turn: `changes` + 1 strokes. `gap` may be a pair (the way there, the way back)."""
    gaps = gap if isinstance(gap, tuple) else (gap, gap)
    out, t = [], start
    for i in range(changes + 1):
        pitch = first if i % 2 == 0 else (B if first == A else A)
        key = "a" if pitch == A else "b"
        out += ex.feed(Press(t, key, pitch, True, velocity[i % 2]))
        out += ex.feed(Press(t + 0.05, key, pitch, False))
        t += gaps[i % 2]
    return out, t


@pytest.mark.parametrize("changes", [5, 9, 14])
def test_a_trill_is_accepted_whatever_the_number_of_strokes(changes):
    ex = Exercise([TRILL])
    ex.start(0.0)
    actions, t = alternate(ex, changes)
    assert StepDone(0) not in actions and ex.tick(t + 0.3) == [], "not judged while it may still be going on"
    assert ex.tick(t + 1.0) == [StepDone(0), Finished()]
    r = ex.results[0]
    assert r.status == "ok" and r.attempts == 1 and r.trill["ok"] and r.trill["changes"] == changes and r.trill["evenness"] == "even"
    assert trills.words(r.trill, "C4", "D4").startswith("fast (about 10 strokes a second") and ex.accuracy == 100


def test_holding_one_key_or_playing_other_keys_is_not_a_trill():
    ex = Exercise([TRILL])
    ex.start(0.0)
    assert ex.feed(Press(1.0, "a", A, True)) == [Mark("a", True)]
    assert ex.tick(1.3) == [] and ex.tick(3.0) == []        # held: judged, and not a trill
    assert not ex.finished and ex.results[0].attempts == 1 and ex.results[0].trill["why"] == "one side only: no alternation"
    ex.feed(Press(3.1, "a", A, False))
    for i in range(6):                                      # the same key again and again
        ex.feed(Press(4.0 + 0.1 * i, "a", A, True))
        ex.feed(Press(4.05 + 0.1 * i, "a", A, False))
    ex.tick(6.0)
    assert not ex.finished and ex.results[0].trill["why"] == "one side only: no alternation" and ex.results[0].trill["missing"] == [B]
    # other keys in it
    for i, (key, pitch) in enumerate([("a", A), ("x", X), ("b", B), ("x", X), ("a", A), ("b", B)]):
        ex.feed(Press(7.0 + 0.1 * i, key, pitch, True))
        ex.feed(Press(7.05 + 0.1 * i, key, pitch, False))
    ex.tick(9.0)
    assert not ex.finished and ex.results[0].trill["why"] == "other keys were pressed" and ex.results[0].wrong == [X, X]
    # two changes are too few; begun on the wrong note
    alternate(ex, 2, start=10.0)
    ex.tick(12.0)
    assert "too few changes: 2" in ex.results[0].trill["why"]
    alternate(ex, 8, start=13.0, first=B)
    ex.tick(15.0)
    assert ex.results[0].trill["why"] == "it started on the other note" and ex.results[0].attempts == 5
    _, t = alternate(ex, 8, start=16.0)
    assert ex.tick(t + 1.0) == [StepDone(0), Finished()] and ex.results[0].attempts == 6
    stopped = Exercise([TRILL])
    stopped.start(0.0)
    stopped.feed(Press(1.0, "a", A, True))
    stopped.stop(1.2)
    assert stopped.results[0].missing == [B]
    free = Exercise([Step("trill", (), ("a", "b"), trill=((A,), (B,)), start_on_main=False)])
    free.start(0.0)
    _, t = alternate(free, 6, first=B)
    assert free.tick(t + 1.0) == [StepDone(0), Finished()] and free.results[0].trill["started_on"] == "other"


def test_an_uneven_trill_is_reported_and_a_lumpy_one_refused():
    ex = Exercise([TRILL])
    ex.start(0.0)
    _, t = alternate(ex, 9, gap=(0.1, 0.25), velocity=(90, 50))
    assert ex.tick(t + 1.5) == [StepDone(0), Finished()]
    facts = ex.results[0].trill
    assert facts["evenness"] == "uneven" and facts["limps"] == "other" and facts["weaker"] == "other" and facts["speed"] == "at a moderate speed"
    said = trills.words(facts, "C4", "D4")
    assert "uneven" in said and "it limps: it lingers on D4" in said and "D4 is the weaker note" in said
    # getting faster is called rushing, as in the rhythm tools
    ex = Exercise([TRILL])
    ex.start(0.0)
    t = 1.0
    for i in range(12):
        ex.feed(Press(t, "ab"[i % 2], (A, B)[i % 2], True))
        t += 0.30 - 0.02 * i
    ex.tick(t + 2.0)
    assert ex.results[0].trill["trend"] == "rushing" and "rushing (getting faster)" in trills.words(ex.results[0].trill, "C4", "D4")
    # lumpy: bursts with long holes are not a trill yet
    ex = Exercise([TRILL])
    ex.start(0.0)
    t = 1.0
    for i in range(10):
        ex.feed(Press(t, "ab"[i % 2], (A, B)[i % 2], True))
        t += 0.05 if i % 3 else 0.5
    ex.tick(t + 2.0)
    assert not ex.finished and "too lumpy" in ex.results[0].trill["why"]


def test_the_written_time_counts_when_a_tempo_is_known():
    ex = Exercise([Step("trill", (), ("a", "b"), trill=((A,), (B,)), seconds=3.0)])
    ex.start(0.0)
    _, t = alternate(ex, 6)                 # 0.7 s of 3 s
    ex.tick(t + 1.0)
    assert not ex.finished and ex.results[0].trill["why"] == "much shorter than written"
    _, t = alternate(ex, 22, start=5.0)     # 2.3 s
    assert ex.tick(t + 1.0) == [StepDone(0), Finished()] and ex.results[0].trill["length"] == "about as long as written"
    assert "about as long as written (about 3 s at this tempo)" in trills.words(ex.results[0].trill, "C4", "D4")


def test_a_chord_enters_while_the_trill_goes_on_and_chords_can_alternate():
    chord = Step("chord", (48, 52), ("e", "g"), under=(A, B))
    ex = Exercise([Step("trill", (36,), ("a", "b", "c"), trill=((A,), (B,)), goes_on=True), chord, Step("after", (67,), ("h",))])
    ex.start(0.0)
    actions, t = alternate(ex, 3)
    assert StepDone(0) not in actions, "the note struck with its start is still missing"
    actions = ex.feed(Press(t, "c", 36, True))
    assert StepDone(0) in actions and ex.index == 1, "done as soon as it is going: the next step enters under it"
    more, t = alternate(ex, 5, start=t + 0.1)
    assert all(a == Mark(a.key, True) for a in more if isinstance(a, Mark)) and ex.results[1].wrong == []
    assert ex.feed(Press(t, "e", 48, True)) == [Mark("e", True)]
    assert StepDone(1) in ex.feed(Press(t + 0.02, "g", 52, True))
    assert ex.trill_facts(0)["changes"] >= 8, "what was struck under the chord still counts for the trill's report"
    assert ex.feed(Press(t + 0.5, "a", A, True)) == [Mark("a", False)], "after it has ended its notes are wrong again"
    # two chords taking turns: a chord's notes struck together are one stroke
    tremolo = Exercise([Step("tremolo", (), (), trill=((60, 64), (67, 72)))])
    tremolo.start(0.0)
    t = 1.0
    for i in range(8):
        for n, pitch in enumerate(((60, 64), (67, 72))[i % 2]):
            tremolo.feed(Press(t + 0.01 * n, str(pitch), pitch, True))
        t += 0.15
    assert tremolo.tick(t + 1.5) == [StepDone(0), Finished()]
    assert tremolo.results[0].trill["strokes"] == 8 and tremolo.results[0].trill["changes"] == 7


# --- trills: the tools ---

class Player(threading.Thread):
    """Presses keys on the fake keyboard: (seconds to wait, 'down' | 'up' | 'tap', key ids)."""

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
                time.sleep(0.03)
            if action in ("up", "tap"):
                for k in keys:
                    self.fake.release(k.board, k.key)


def test_run_exercise_judges_a_trill_step_by_its_effect(trill_piece):
    t, fake, piece = trill_piece
    steps = t.library("get", id=piece, phrase=1, part="upper")["steps"]
    told = t.fingering(steps)["steps"]
    a, b = (k["key"] for k in told[0]["keys"])
    e = told[1]["keys"][0]["key"]
    # seven strokes instead of the twelve of the file, then the note that follows
    Player(t, fake, [(0.3, "tap", [a])] + [(0.07, "tap", [k]) for k in (b, a, b, a, b, a)] + [(1.2, "tap", [e])]).start()
    out = t.run_exercise(steps, timeout_s=15)
    assert out["outcome"] == "finished" and [s["result"] for s in out["steps"]] == ["ok", "ok"]
    first = out["steps"][0]
    assert first["asked"] == "trill C4 / D4" and first["attempts"] == 1 and "wrong_notes" not in first
    assert "strokes a second" in first["trill"] and "even" in first["trill"] and "never counted" in out["trills"]
    # holding one key is no trill: the step waits, and the pause is reported with why
    Player(t, fake, [(0.3, "down", [a]), (1.2, "up", [a])]).start()
    held = t.run_exercise(steps, timeout_s=15, pause_s=1.0)
    assert held["outcome"] == "player paused" and held["steps"][0]["result"] == "tried, then paused"
    assert "one side only: no alternation" in held["steps"][0]["trill"]
    with pytest.raises(TutorError, match="two sides"):
        t.run_exercise([{"trill": ["C4"]}])
    with pytest.raises(TutorError, match="different notes"):
        t.fingering([{"trill": ["C4", "C4"]}])


def test_demo_plays_a_trill_as_an_even_alternation(trill_piece):
    t, fake, piece = trill_piece
    step = t.library("get", id=piece, phrase=1, part="upper")["steps"][0]
    keys = {k["note"]: t.keyboard.key(k["key"]) for k in t.fingering([step])["steps"][0]["keys"]}
    c, d = ((keys[n].board, keys[n].key) for n in ("C4", "D4"))
    times: list[float] = []
    notes = fake.notes

    def timed(on=None, off=None):
        times.extend([time.monotonic()] * bool(on))
        notes(on=on, off=off)

    fake.notes = timed
    try:
        fake.sounded.clear()
        out = t.demo([step], tempo_bpm=60)              # a beat and a half of thirty-second notes: twelve strokes at eight a second
        sounded = [addr for addr, _, _ in fake.sounded]
        assert sounded == [c, d] * 6 and "8 strokes a second" in out["trills"]
        gaps = [y - x for x, y in zip(times, times[1:])]
        assert all(abs(g - 0.125) < 0.06 for g in gaps) and abs(sum(gaps) / len(gaps) - 0.125) < 0.015
        assert {(c, rgb) for addr, rgb in fake.seen if addr == c} and {addr for addr, _ in fake.seen} >= {c, d}       # both keys lit
        fake.sounded.clear()
        slow = t.demo([step], tempo_bpm=60, trill_rate=4)       # shown slowly: the rate, not the number of strokes
        assert [addr for addr, _, _ in fake.sounded] == [c, d] * 3 and "4 strokes a second" in slow["trills"]
        # the trill goes on while the left hand's chord enters
        fake.sounded.clear()
        both = t.library("get", id=piece, phrase=1, part="both")["steps"]
        t.demo(both[:2], tempo_bpm=120)             # 0.75 s at the fastest rate the sound tells apart, twelve a second
        sounded = [addr for addr, _, _ in fake.sounded]
        chord = {(k.board, k.key) for n in ("E3 (8)", "G3 (14)") for k in t.keyboard.keys_for_pitch(t.keyboard.tuning.parse(n)[0])}
        at = min(i for i, addr in enumerate(sounded) if addr in chord)
        assert sum(addr in (c, d) for addr in sounded) == 9 and any(addr in (c, d) for addr in sounded[at:]) and at > 4
    finally:
        fake.notes = notes


def test_fingering_proposes_a_finger_pair_for_a_trill(tuned):
    edo, t, _ = tuned
    told = t.fingering([{"trill": ["C4", "D4"]}, {"note": "E4"}])["steps"]
    trill = told[0]["trill"]
    first, second = (k["finger"] for k in told[0]["keys"])
    assert trill["fingers"].startswith(f"{first}-{second}: ") and first != second and "C. P. E. Bach" in trill["fingers_from"]
    assert "fingering" not in told[0] and trill["other_pairs"] and trill["kind"] == "trill" and "does not matter" in trill["how"]
    left = t.fingering([{"trill": ["C4", "D4"]}], hand="left")["steps"][0]
    assert {k["finger"] for k in left["keys"]} != {first, second} or left["trill"]["fingers"] != trill["fingers"]
    asked = t.fingering([{"trill": ["C4", "D4"], "fingers": [3, 5]}])["steps"][0]
    assert [k["finger"] for k in asked["keys"]] == [3, 5] and asked["trill"]["fingers"].startswith("3-5: middle finger on C4")
    with pytest.raises(TutorError, match="two different fingers"):
        t.fingering([{"trill": ["C4", "D4"], "fingers": [2, 2]}])
    chords = t.fingering([{"trill": [["C4", "E4"], ["G4", "C5"]]}])["steps"][0]
    assert chords["trill"]["kind"] == "tremolo" and "fingers" not in chords["trill"] and len(chords["keys"]) == 4


def test_the_trill_drill(tuned):
    edo, t, _ = tuned
    out = t.library("pattern", name="trill", root="A4", interval="step")
    assert out["between"] == ["A4 (%d)" % (23 if edo == 31 else 40), "^A4 (%d)" % (24 if edo == 31 else 41)]
    assert ("a comma" if edo == 53 else "a diesis") in out["interval"] and out["intervals_here"]["whole tone"] == f"{9 if edo == 53 else 5} steps"
    assert len(out["groups"]) == 3 and len({g["fingers"] for g in out["groups"]}) == 3
    slow, moderate, fast = out["groups"][0]["steps"]
    assert (slow["stroke_beats"], moderate["stroke_beats"], fast["stroke_beats"]) == (0.5, 0.25, 0.125)
    assert slow["trill"] == out["between"] and slow["fingers"] == [int(f) for f in out["groups"][0]["fingers"].split("-")]
    assert slow["label"].endswith(", slow") and "2 strokes to a beat" in slow["say"] and out["steps"][:3] == [slow, moderate, fast]
    assert [k["finger"] for k in t.fingering([slow])["steps"][0]["keys"]] == slow["fingers"]
    assert "never a number of strokes" in out["note"] and "C. P. E. Bach" in out["note"]
    tone = t.library("pattern", name="trill", root="C4", interval="whole tone", count=1, hand="left")
    assert tone["between"] == ["C4 (0)", "D4 (%d)" % (9 if edo == 53 else 5)] and len(tone["groups"]) == 1
    wide = t.library("pattern", name="tremolo", root="C4", interval="fifth", count=2)
    assert wide["pattern"] == "tremolo" and [plain(n) for n in wide["between"]] == ["C", "G"] and len(wide["groups"]) == 2
    split = t.library("pattern", name="tremolo", chords=["C4 major"])
    assert [plain(n) for n in split["between"][1]] == [THIRD[edo], "G"] and plain(split["between"][0]) == "C" and "fingers" not in split["steps"][0]
    two = t.library("pattern", name="tremolo", chords=["C major", "D minor"])
    assert len(two["between"][0]) == 3 and len(two["between"][1]) == 3
    with pytest.raises(TutorError, match="share"):
        t.library("pattern", name="tremolo", chords=["C major", "C minor"])
    with pytest.raises(TutorError, match="interval must be"):
        t.library("pattern", name="trill", interval="a lot")
    shown = t.demo([fast], tempo_bpm=240, trill_rate=16)
    assert len(shown["played"]) == 1 and "trills" in shown


# --- the real library, if it is built ---

def test_bar_10_of_prelude_3_is_a_trill_step():
    library = lib.Library()
    piece = library.piece("score/wyschnegradsky-prelude-03")
    if piece is None:
        pytest.skip("the library is not built (python -m tutor.library_build)")
    t = Tutor(FakeXentool(sample_setup(24, FIVE)), library=library)
    try:
        assert len(piece["score"][9]["staves"]["upper"]) > 20          # the file: more than twenty notes
        out = t.library("get", id=piece["id"], phrase=10, part="upper")
        trill = out["steps"][0]
        assert len(out["steps"]) <= 4 and trill["kind"] == "trill" and trill["lasts"] == 3.0 and "24 strokes" in trill["written"]
        assert "minor second" in trill["interval"] and "for three beats" in trill["say"] and "lead on" in trill["say"]
        assert all("grace" in s and "over_trill" in s for s in out["steps"][1:])
    finally:
        t.stop()
        t.pump.stop()
