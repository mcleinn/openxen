"""Playing along with a composition: matching played notes to written ones (pure), and the
play_along tool with scripted players on a stand-in keyboard, in real time (short pieces, fast)."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
from tutor import playalong as PA  # noqa: E402
from tutor.player import Player  # noqa: E402
from tutor.sample import sample_setup  # noqa: E402
from tutor.session import Tutor, TutorError  # noqa: E402
from tutor.xt import FakeXentool  # noqa: E402

C4, D4, E4, F4, G4, C3, G3 = 124, 129, 134, 137, 142, 93, 111       # steps of 31 notes per octave
BPM = 240.0
Q = 60.0 / BPM


class Shelf:
    """A library that holds the pieces of a test."""

    def __init__(self, *pieces: dict):
        self.pieces = {p["id"]: p for p in pieces}

    def piece(self, piece_id: str) -> dict | None:
        return self.pieces.get(piece_id)


def piece(bars: list[dict], bpm: float = BPM, name: str = "study") -> dict:
    return {"id": f"score/{name}", "title": name, "tuning": 31, "tempi": [[1, bpm]],
            "score": [{"n": i + 1, "time": "2/4", "length": 2.0, **bar} for i, bar in enumerate(bars)]}


def plain(bars: int = 4) -> dict:
    """Four eighth notes in the right hand over two quarter notes in the left, bar after bar."""
    return piece([{"staves": {"upper": [[0.0, 0.5, [C4]], [0.5, 0.5, [D4]], [1.0, 0.5, [E4]], [1.5, 0.5, [D4]]],
                              "lower": [[0.0, 1.0, [C3]], [1.0, 1.0, [G3]]]}} for _ in range(bars)])


def written(p: dict, part: str = "both", speed: float = 1.0) -> list[dict]:
    """Every note of the piece as a stroke: when (seconds from the start), what, how long."""
    quarter = 60.0 / (p["tempi"][0][1] * speed)
    out, at = [], 0.0
    for bar in p["score"]:
        for hand, events in bar["staves"].items():
            if part in (hand, "both"):
                out += [{"at": at + beat * quarter, "pitch": step, "held": dur * quarter * 0.9, "bar": bar["n"], "beat": beat, "hand": hand}
                        for beat, dur, steps in events for step in steps]
        at += bar["length"] * quarter
    return sorted(out, key=lambda s: s["at"])


def perform(fake: FakeXentool, tutor: Tutor, strokes: list[dict], lead: float | None) -> threading.Thread:
    """Play the strokes on the stand-in keyboard. `lead`: seconds from the first click to the start
    of the first bar; None = no click, start at once."""
    kb = tutor.keyboard
    moves = []
    for s in strokes:
        key = kb.keys_for_pitch(s["pitch"])[0]
        moves += [(s["at"], 1, key), (s["at"] + s["held"], 0, key)]
    moves.sort(key=lambda m: (m[0], m[1]))

    def go():
        if lead is None:
            zero = time.monotonic() + 0.15
        else:
            while not fake.clicks:
                time.sleep(0.001)
            zero = time.monotonic() + lead
        for at, on, key in moves:
            time.sleep(max(0.0, zero + at - time.monotonic()))
            (fake.press if on else fake.release)(key.board, key.key)

    thread = threading.Thread(target=go, daemon=True)
    thread.start()
    return thread


@pytest.fixture
def stage(tmp_path):
    made = []

    def make(*pieces: dict):
        fake = FakeXentool(sample_setup(31, (0, 1, 2, 3)))
        tutor = Tutor(fake, player=Player(tmp_path / f"player{len(made)}.json"), library=Shelf(*pieces))
        made.append(tutor)
        return fake, tutor

    yield make
    for tutor in made:
        tutor.pump.stop()


def take(stage, p: dict, strokes: list[dict], **kwargs) -> dict:
    fake, tutor = stage(p)
    follow = kwargs.get("mode") == "follow"
    bar_s = 2.0 * 60.0 / (p["tempi"][0][1] * kwargs.get("speed", 1.0))
    thread = perform(fake, tutor, strokes, None if follow else bar_s)
    out = tutor.play_along(p["id"], **kwargs)
    thread.join(timeout=5)
    assert "moved" not in out and "left_out" not in out
    out["_fake"] = fake
    return out


# --- the arithmetic ---

def test_where_the_click_falls():
    assert PA.beats_in("2/4", 2.0) == [0.0, 1.0] and PA.beats_in("4/4", 4.0) == [0.0, 1.0, 2.0, 3.0]
    assert PA.beats_in("6/8", 3.0) == [0.0, 1.5] and PA.beats_in("9/8", 4.5) == [0.0, 1.5, 3.0]     # dotted quarters
    assert PA.beats_in("7/8", 3.5) == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0] and PA.beats_in("3/4", 1.0) == [0.0]   # an upbeat bar


def laid_out(p: dict, part: str = "both"):
    notes, rows, left = PA.plan(p["score"], part, lambda n: p["tempi"][0][1], lambda step: step, lambda pitch: True)
    return PA.groups_of(notes), rows


def test_matching_keeps_its_place_through_wrong_missing_and_extra_notes():
    p = piece([{"staves": {"upper": [[0.0, 0.5, [C4]], [0.5, 0.5, [C4]], [1.0, 0.5, [C4]], [1.5, 0.5, [E4]]], "lower": []}} for _ in range(2)])
    groups, rows = laid_out(p, "upper")
    due = [g.at for g in groups]
    # the second of three equal notes left out: time says which two were played
    played = [PA.Played(t, pitch) for t, pitch in ((0.0, C4), (0.31, C4), (0.45, E4), (0.6, C4), (0.75, C4), (0.9, C4), (1.05, E4))]
    assert PA.align(groups, played, due, [1.0] * len(groups)) == []
    assert [g.notes[0].played for g in groups] == [0.0, None, 0.31, 0.45, 0.6, 0.75, 0.9, 1.05]
    # a wrong note in place of one, and a note too many: the rest stays where it belongs
    played = [PA.Played(t, pitch) for t, pitch in ((0.0, C4), (0.15, D4), (0.3, C4), (0.45, E4), (0.52, G4), (0.6, C4), (0.75, C4), (0.9, C4), (1.05, E4))]
    extras = PA.align(groups, played, due, [1.0] * len(groups))
    assert [p.pitch for p, _, absorbed in extras if not absorbed] == [D4, G4]
    assert [g.notes[0].played for g in groups] == [0.0, None, 0.3, 0.45, 0.6, 0.75, 0.9, 1.05]
    told = PA.judge(groups, rows, extras, "click", "beginner", str)
    assert told["notes"] == {"written": 8, "right": 7, "missing": 0, "wrong": 1, "extra": 1,
                             "where": [f"bar 1 beat 1.5: {D4} for {C4}", f"extra {G4} near bar 1 beat 2.5"]}
    # without times (follow mode's first pass) the order alone carries it
    assert PA.align(groups, [PA.Played(i * 0.2, n.pitch) for i, g in enumerate(groups) for n in g.notes]) == []
    assert all(g.notes[0].played is not None for g in groups)


def test_the_follower_knows_where_the_player_is():
    groups, _ = laid_out(plain(2), "upper")
    f = PA.Follower(groups)
    assert f.feed(C4) == 0 and f.feed(G4) is None and f.at == 0          # a wrong note does not move it
    assert f.feed(E4) == 2 and f.at == 2                                  # a note left out: it goes on from the next
    assert f.feed(D4) == 3 and f.feed(C4) == 4 and not f.done
    for pitch in (D4, E4, D4):
        f.feed(pitch)
    assert f.done


# --- scripted players against the click ---

def test_exact_playing_is_on_it(stage):
    p = plain()
    out = take(stage, p, written(p))
    assert out["outcome"] == "finished" and out["by_bar"] == {str(n): "both hands on it" for n in range(1, 5)}
    assert out["notes"] == {"written": 24, "right": 24, "missing": 0, "wrong": 0, "extra": 0}
    assert out["timing"]["on it"] == 24 and out["sits"].startswith("on it") and out["tempo_played"] == "kept the click's tempo"
    assert out["hands"].startswith("together") and out["practise_next"].startswith("This held")
    assert not {"rhythms", "chords", "held", "continue_with", "not_calibrated"} & set(out)
    # one bar of clicks to count in, then two clicks in each of the four bars; nothing else sounded
    assert len(out["_fake"].clicks) == 2 + 8 and not out["_fake"].sounded
    assert out["tempo"] == "240 quarter notes per minute" and out["mode"] == "click"


def test_a_constant_offset_is_not_rushing_or_dragging(stage):
    p = plain()
    late = [{**s, "at": s["at"] + 0.07} for s in written(p)]
    out = take(stage, p, late)
    assert out["sits"].startswith("late by about") and "a constant lag, not dragging" in out["sits"]
    assert out["tempo_played"] == "kept the click's tempo" and "not_calibrated" in out and "calibrate" in out["practise_next"]
    assert all(text.startswith("both hands late") for text in out["by_bar"].values())
    # with the player's offset measured, the same playing is on it
    fake, tutor = stage(p)
    tutor.player.set_offset(70)
    thread = perform(fake, tutor, late, 2 * Q)
    out = tutor.play_along(p["id"])
    thread.join(timeout=5)
    assert out["sits"].startswith("on it") and out["by_bar"]["2"] == "both hands on it" and "not_calibrated" not in out


def test_steady_rushing_is_named(stage):
    p = plain()
    out = take(stage, p, [{**s, "at": s["at"] * 0.95} for s in written(p)])
    assert out["tempo_played"].startswith("rushing steadily") and "faster than the click" in out["tempo_played"]
    assert "runs ahead of the click" in out["practise_next"]
    assert out["by_bar"]["1"] == "both hands on it" and "early" in out["by_bar"]["4"]
    assert out["notes"]["right"] == 24


def test_one_dragged_bar_is_found(stage):
    p = plain()
    bar3 = 2 * 2 * Q
    out = take(stage, p, [{**s, "at": bar3 + (s["at"] - bar3) * 1.2} if s["bar"] == 3 else s for s in written(p)])
    assert "dragged" in out["by_bar"]["3"] and all("dragged" not in out["by_bar"][n] and "rushed" not in out["by_bar"][n] for n in "124")
    assert out["tempo_played"] == "kept the click's tempo, except in bar 3" and out["by_bar"]["4"] == "both hands on it"
    assert "bar 3" in out["practise_next"]


def test_a_dotted_rhythm_played_even(stage):
    dotted = piece([{"staves": {"upper": [[0.0, 0.75, [C4]], [0.75, 0.25, [D4]], [1.0, 0.75, [E4]], [1.75, 0.25, [D4]]], "lower": []}}
                    for _ in range(3)], bpm=150)
    even = [{**s, "at": s["at"] - 0.1} if s["beat"] % 1 else s for s in written(dotted)]
    out = take(stage, dotted, even, part="upper")
    assert out["rhythms"][0] == "bar 1, right hand: the dotted rhythm (long-short) was played even" and len(out["rhythms"]) == 3
    assert "rhythm of bars 1, 2, 3" in out["practise_next"] and out["notes"]["right"] == 12
    # played as written, nothing is said
    fake, tutor = stage(dotted)
    thread = perform(fake, tutor, written(dotted), 2 * 60.0 / 150)
    exact = tutor.play_along(dotted["id"], part="upper")
    thread.join(timeout=5)
    assert "rhythms" not in exact and exact["timing"]["on it"] == 12 and "hands" not in exact


def test_left_hand_late_against_the_right(stage):
    p = plain()
    out = take(stage, p, [{**s, "at": s["at"] + 0.09} if s["hand"] == "lower" else s for s in written(p)])
    assert out["hands"].startswith("not together: the left hand comes about") and "after the right" in out["hands"]
    assert out["by_bar"]["2"].startswith("right hand on it; left hand late (about")
    assert "hands do not strike together" in out["practise_next"]


def test_a_missing_and_a_wrong_note_leave_the_rest_in_place(stage):
    p = plain()
    strokes = written(p, "upper")
    strokes[5]["pitch"] = G4            # bar 2, the second note: a wrong key
    del strokes[10]                     # bar 3, the third note: left out
    out = take(stage, p, strokes, part="upper")
    assert out["notes"] == {"written": 16, "right": 14, "missing": 1, "wrong": 1, "extra": 0,
                            "where": ["bar 2 beat 1.5: G4 (18) for D4 (5)", "bar 3 beat 2: E4 (10) missing"]}
    assert out["timing"]["on it"] == 14 and out["sits"].startswith("on it") and out["by_bar"]["4"] == "on it"
    assert "1 of 4 places not played" in out["by_bar"]["3"]


def test_a_rolled_chord_is_one_onset(stage):
    chords = piece([{"staves": {"upper": [[0.0, 1.0, [C4, E4, G4]], [1.0, 1.0, [D4, F4]]], "lower": []}} for _ in range(3)])
    rolled = []
    for s in written(chords):
        order = {C4: 2, E4: 0, G4: 1, D4: 0, F4: 1}[s["pitch"]]         # not from the bottom up
        rolled.append({**s, "at": s["at"] + 0.03 * order - 0.02})
    out = take(stage, chords, rolled, part="upper")
    assert out["notes"]["right"] == 15 and out["notes"]["extra"] == 0 and "chords" not in out
    assert out["timing"]["on it"] == 6 and out["by_bar"] == {"1": "on it", "2": "on it", "3": "on it"}
    # broken beyond the chord window it is said
    fake, tutor = stage(chords)
    broken = [{**s, "at": s["at"] + (0.2 if s["pitch"] == G4 else 0.0)} for s in written(chords)]
    thread = perform(fake, tutor, broken, 2 * Q)
    out = tutor.play_along(chords["id"], part="upper")
    thread.join(timeout=5)
    assert out["chords"].startswith("3 chords not struck together") and out["notes"]["right"] == 15


def test_trills_and_grace_notes_are_not_judged(stage):
    strokes8 = [[0.0 + 0.125 * i, 0.125, [E4 if i % 2 == 0 else F4]] for i in range(8)]
    ornate = piece([
        {"staves": {"upper": [[0.0, 1.0, [C4]], [1.0, 0.9, [D4]], [1.9, 0.1, [F4]]], "lower": []},
         "marks": [{"staff": "upper", "beat": 1.9, "step": F4, "mark": "grace"}]},
        {"staves": {"upper": strokes8 + [[1.0, 1.0, [C4]]], "lower": []}, "marks": [{"staff": "upper", "beat": 0.0, "step": E4, "mark": "trill"}]},
        {"staves": {"upper": [[0.0, 1.0, [D4]], [1.0, 1.0, [C4]]], "lower": []}}], bpm=170)
    groups, _ = laid_out(ornate, "upper")
    assert [n.kind for g in groups for n in g.notes] == ["note", "note", "grace"] + ["note"] + ["trill"] * 7 + ["note"] * 3
    quarter = 60.0 / 170
    # the grace note left out, the trill played with five strokes of its own speed instead of eight
    mine = [s for s in written(ornate) if not (s["bar"] == 1 and s["beat"] == 1.9) and not (s["bar"] == 2 and 0 < s["beat"] < 1)]
    mine += [{"at": 2 * quarter + 0.07 * i, "pitch": F4 if i % 2 else E4, "held": 0.04, "bar": 2, "beat": 0.1, "hand": "upper"} for i in range(1, 5)]
    out = take(stage, ornate, sorted(mine, key=lambda s: s["at"]), part="upper")
    assert out["notes"] == {"written": 6, "right": 6, "missing": 0, "wrong": 0, "extra": 0}
    assert out["ornaments"].startswith("4 of 8 grace notes and trill strokes were played") and out["timing"]["on it"] == 6
    assert out["by_bar"] == {"1": "on it", "2": "on it", "3": "on it"} and "rhythms" not in out


# --- the player sets the tempo ---

def test_follow_mode_judges_evenness_at_the_players_tempo(stage):
    p = plain()
    slow = written(p, "upper", speed=0.7)
    out = take(stage, p, slow, part="upper", mode="follow", accompany=True)
    assert out["outcome"] == "finished" and out["mode"] == "follow" and out["tempo"] == "240 quarter notes per minute as the target"
    assert 160 <= int(out["tempo_played"].split()[1]) <= 172 and "the target was 240 (7" in out["tempo_played"]
    assert out["evenness"].startswith("even") and out["by_bar"] == {str(n): "on it" for n in range(1, 5)} and "sits" not in out
    assert out["notes"]["right"] == 16 and "with the click" in out["practise_next"]
    # no click; the left hand was played by the keyboard, each note after the player's
    fake = out["_fake"]
    kb_keys = {(k["board"], k["key"]): k["pitch"] for k in fake.setup()["keys"]}
    assert not fake.clicks and [kb_keys[addr] for addr, _, _ in fake.sounded] == [C3, G3] * 4
    assert "waiting for the player" in out["accompanied"]


def test_follow_mode_hears_a_tempo_that_runs_away_a_stop_and_an_early_end(stage):
    p = plain(5)
    quarter = 60.0 / 150
    at, strokes = 0.0, []
    for s in written(p, "upper"):                   # every bar faster than the one before
        strokes.append({**s, "at": at, "held": 0.05})
        at += 0.5 * quarter * (1.0 - 0.09 * (s["bar"] - 1))
    out = take(stage, p, strokes, part="upper", mode="follow")
    assert "sped up steadily (rushing)" in out["tempo_played"] and "tempo runs away" in out["practise_next"]
    # a stop in bar 2 is a stop, not a slow bar; ending after bar 3, the rest is not missing
    fake, tutor = stage(p)
    stopped = [{**s, "at": s["at"] + (1.4 if (s["bar"], s["beat"]) >= (2, 1.0) else 0.0)} for s in written(p, "upper") if s["bar"] <= 3]
    thread = perform(fake, tutor, stopped, None)
    out = tutor.play_along(p["id"], part="upper", mode="follow", pause_s=2.0)
    thread.join(timeout=5)
    assert out["outcome"] == "player paused" and out["by_bar"] == {"1": "on it", "2": "on it", "3": "on it"}
    assert out["stops"] == ["before bar 2 beat 2: about 1 s"] and out["notes"]["missing"] == 0
    assert out["continue_with"].startswith("play_along with from_bar=3")


# --- the tool's edges ---

def test_what_is_refused_and_what_does_not_fit(stage):
    slow = piece([{"staves": {"upper": [[0.0, 2.0, [C4]]], "lower": []}} for _ in range(40)], bpm=60, name="long")
    fake, tutor = stage(plain(), slow, {"id": "makam/x", "title": "x", "tuning": 53})
    with pytest.raises(TutorError, match="give the id"):
        tutor.play_along("score/nope")
    with pytest.raises(TutorError, match="two staves"):
        tutor.play_along("makam/x")
    with pytest.raises(TutorError, match="mode must be"):
        tutor.play_along("score/study", mode="swing")
    with pytest.raises(TutorError, match="between 1 and 4"):
        tutor.play_along("score/study", from_bar=3, to_bar=9)
    with pytest.raises(TutorError, match="nothing to play"):
        tutor.play_along("score/long", part="lower")
    # 40 bars of two seconds do not fit into one call: it takes what fits and says where to go on. Stopped after a moment.
    threading.Timer(1.0, tutor.stop).start()
    began = time.monotonic()
    out = tutor.play_along("score/long", count_in=0, click=False)
    assert time.monotonic() - began < 3 and out["outcome"] == "stopped" and out["bars"] == "1-29"
    assert out["timing"] == "too few right notes to judge the time" and out["continue_with"].startswith("play_along with from_bar=1")
    other = Tutor(FakeXentool(sample_setup(53, (0, 1, 2, 3, 4))), library=Shelf(plain()))
    try:
        with pytest.raises(TutorError, match="nearest=true"):
            other.play_along("score/study")
    finally:
        other.pump.stop()
