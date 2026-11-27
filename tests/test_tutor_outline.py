"""The outline of a composition (host/tutor/outline.py) on small made-up pieces: repeats (exact,
transposed, varied, ornamented), sections, phrases, the practice order; the tutor's tools by
section; and, if the library is built, Prelude III of Wyschnegradsky's op. 22."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))

from tutor import library as lib  # noqa: E402
from tutor import library_build as build  # noqa: E402
from tutor import outline  # noqa: E402
from tutor.sample import sample_setup  # noqa: E402
from tutor.session import Tutor, TutorError  # noqa: E402
from tutor.xt import FakeXentool  # noqa: E402


def line(start: int, moves: list[int], step: float = 1.0, length: float | None = None) -> list:
    """Notes of equal length from `start`, each `moves` steps above it: [[beat, dur, [step]], ...]."""
    return [[k * step, length or step, [start + m]] for k, m in enumerate(moves)]


def bar(n: int, upper: list, lower: list, time: str = "4/4", **more) -> dict:
    num, _, den = time.partition("/")
    return {"n": n, "time": time, "length": 4.0 * int(num) / int(den), "staves": {"upper": upper, "lower": lower}, **more}


TUNE = [0, 4, 7, 4]             # a figure of four quarter notes
ANSWER = [7, 5, 4, 0]
BASS = [[0.0, 2.0, [40]], [2.0, 2.0, [47, 52]]]
OTHER_BASS = [[0.0, 4.0, [38, 45]]]


def piece(bars: list, **more) -> dict:
    return {"id": "score/test", "title": "Test", "tuning": 24, "score": bars, **more}


def test_an_exact_repeat_is_found_also_as_a_unit_of_two_bars():
    bars = [bar(1, line(60, TUNE), BASS), bar(2, line(60, ANSWER), OTHER_BASS),
            bar(3, line(60, TUNE), BASS), bar(4, line(60, ANSWER), OTHER_BASS)]
    made = outline.build(piece(bars))
    assert made["made"] == outline.MADE and "not an analysis by a musician" in made["made"]
    assert made["repeats"]["3"]["of"] == 1 and made["repeats"]["3"]["kind"] == "same"
    assert made["repeats"]["4"]["of"] == 2 and made["repeats"]["4"]["kind"] == "same"
    assert "bars 3-4 = bars 1-2" in made["repeat_map"]              # the two bars as one unit
    assert outline.bar_words(made, 3) == "bar 3: the same notes as bar 1" and outline.bar_words(made, 1) is None
    # a tied note is the same note: lengths are not compared
    tied = copy.deepcopy(bars)
    tied[2]["staves"]["upper"][3][1] = 5.0
    assert outline.build(piece(tied))["repeats"]["3"]["kind"] == "same"


def test_a_transposed_repeat_in_one_hand_while_the_other_changes():
    bars = [bar(1, line(60, TUNE), BASS), bar(2, line(54, TUNE), OTHER_BASS), bar(3, line(66, TUNE), [[k, d, [s + 6 for s in steps]] for k, d, steps in BASS])]
    made = outline.build(piece(bars), lambda steps: {6: "minor third"}.get(steps, ""))
    two = made["repeats"]["2"]
    assert two["of"] == 1 and two["kind"] == "hands" and two["right"] == {"kind": "transposed", "shift": -6} and two["left"]["kind"] == "different"
    assert outline.bar_words(made, 2, lambda steps: "minor third") == "bar 2: like bar 1, right hand 6 steps lower (minor third), left hand different"
    assert outline.bar_words(made, 2, part="upper") == "bar 2: like bar 1, 6 steps lower" and outline.bar_words(made, 2, part="lower") is None
    # both hands by the same interval: the whole bar is the same shape elsewhere
    three = made["repeats"]["3"]
    assert three == {"of": 1, "kind": "transposed", "shift": 6, "right": {"kind": "transposed", "shift": 6}, "left": {"kind": "transposed", "shift": 6}}
    assert "bar 3 = bar 1: the same shape, every note 6 steps higher (minor third)" in made["repeat_map"]
    # a whole octave is called one; on another tuning the size is converted
    assert outline._steps_words(-48, outline.namer(None, 24)) == "2 octaves lower"
    assert outline.bar_words(made, 3, scale=lambda steps: steps * 2) == "bar 3: like bar 1, the same shape, every note 12 steps higher"
    # two notes are not enough to claim a transposition
    few = [bar(1, [[0.0, 2.0, [60]], [2.0, 2.0, [64]]], []), bar(2, [[0.0, 2.0, [67]], [2.0, 2.0, [71]]], [])]
    assert outline.build(piece(few))["repeats"] == {}


def test_a_variant_says_which_hand_differs():
    changed = line(60, TUNE)
    changed[2][2] = [69]                    # one note of four changed
    bars = [bar(1, line(60, TUNE), BASS), bar(2, line(60, ANSWER), OTHER_BASS), bar(3, changed, BASS)]
    made = outline.build(piece(bars))
    three = made["repeats"]["3"]
    assert three["of"] == 1 and three["right"]["kind"] == "variant" and three["left"]["kind"] == "same"
    assert outline.bar_words(made, 3) == "bar 3: like bar 1, right hand varied, left hand the same notes"


def test_a_trill_bar_is_its_plain_version_with_ornaments():
    plain = [[0.0, 2.0, [60]], [2.0, 1.0, [64]], [3.0, 1.0, [67]]]
    strokes = [[k * 0.125, 0.125, [60 if k % 2 == 0 else 62]] for k in range(16)]
    trilled = strokes + [[2.0, 1.0, [64]], [2.875, 0.125, [65]], [3.0, 1.0, [67]]]
    marks = [{"staff": "upper", "beat": 0.0, "step": 60, "mark": "trill"}, {"staff": "upper", "beat": 2.875, "step": 65, "mark": "grace"}]
    bars = [bar(1, plain, BASS), bar(2, line(60, ANSWER), OTHER_BASS), bar(3, trilled, BASS, marks=marks)]
    made = outline.build(piece(bars))
    assert made["repeats"]["3"]["of"] == 1 and made["repeats"]["3"]["right"] == {"kind": "ornamented", "shift": 0}
    assert "the same but for the ornaments" in outline.bar_words(made, 3)
    # without the marks the written-out strokes are other notes
    bare = copy.deepcopy(bars)
    del bare[2]["marks"]
    assert outline.build(piece(bare))["repeats"].get("3", {}).get("right", {}).get("kind") != "ornamented"


def long_piece() -> dict:
    """Twenty bars: a two-bar pattern three times, four other bars ending in a long note, a rest in
    both hands, the pattern transposed twice, then "a tempo" and the pattern again with an ending."""
    pattern = lambda n, up=0: [bar(n, line(60 + up, TUNE), [[k, d, [s + up for s in steps]] for k, d, steps in BASS]),      # noqa: E731
                               bar(n + 1, line(60 + up, ANSWER), [[k, d, [s + up for s in steps]] for k, d, steps in OTHER_BASS])]
    bars = pattern(1) + pattern(3) + pattern(5)
    bars += [bar(7, line(72, [0, 2, 3, 5, 7, 8, 10, 12], 0.5), OTHER_BASS), bar(8, line(84, [0, -2, -3, -5, -7, -8, -10, -12], 0.5), OTHER_BASS),
             bar(9, line(70, [0, 1, 3, 4, 6, 7, 9, 10], 0.5), OTHER_BASS), bar(10, [[0.0, 2.0, [77]]], [[0.0, 2.0, [41, 48]]])]      # silent from beat 3
    bars += pattern(11, 10) + pattern(13, 10)
    bars += [bar(15, line(50, [0, 3, 5, 8]), [[0.0, 4.0, [30]]]), bar(16, [[0.0, 4.0, [55]]], [[0.0, 4.0, [31]]],
                                                                    expression=[{"type": "tempo", "beat": 0.0, "hand": "both", "value": "ritardando", "text": "rit."}])]
    bars += pattern(17)
    bars[16]["expression"] = [{"type": "tempo", "beat": 0.0, "hand": "both", "value": "a tempo", "text": "a tempo"}]
    bars += [bar(19, line(60, TUNE), BASS), bar(20, [[0.0, 4.0, [60, 64, 67, 72, 76]]], [[0.0, 4.0, [36]]])]
    return piece(bars, tempi=[[1, 96.0], [16, 60.0], [17, 96.0]], two_hands={"tight_bars": [20]}, checked={"doubtful_bars": [9]})


def test_sections_begin_where_the_music_changes():
    made = outline.build(long_piece())
    starts = {s["bars"][0]: s for s in made["sections"]}
    assert set(starts) >= {1, 7, 11, 17}
    assert "the pattern is left" in starts[7]["begins_at"]              # after the pattern three times
    assert "a rest in both hands" in starts[11]["begins_at"]            # the second half of bar 10 is silent
    assert "a tempo" in starts[17]["begins_at"]                         # the tempo word (and the tempo mark returning)
    assert [s["bars"] for s in made["sections"]][0] == [1, 6] and made["sections"][-1]["bars"][1] == 20
    # every bar is in exactly one section, every section is cut into phrases that cover it
    assert [s["bars"][0] for s in made["sections"]][1:] == [s["bars"][1] + 1 for s in made["sections"]][:-1]
    for s in made["sections"]:
        assert s["phrases"][0][0] == s["bars"][0] and s["phrases"][-1][1] == s["bars"][1]
        assert all(z + 1 == a for (_, z), (a, _) in zip(s["phrases"], s["phrases"][1:]))
        assert all(z - a + 1 <= outline.MAX_PHRASE for a, z in s["phrases"])
    # labels: the pattern's sections share a letter, the run of scales has its own
    labels = {s["bars"][0]: s["label"] for s in made["sections"]}
    assert labels[1] == "A" and labels[7] == "B" and labels[11].startswith("A") and labels[17].startswith("A")
    assert "2-bar pattern a (bars 1-2), 3 times" in starts[1]["says"] and "returns transposed" in starts[11]["says"]
    # a section that persists in another time signature begins there
    bars = [bar(n, line(60 + n % 3, TUNE), BASS) for n in range(1, 7)] + [bar(n, line(60 + n % 2, [0, 4, 7]), [[0.0, 3.0, [40 + n]]], "3/4") for n in range(7, 13)]
    assert "the time signature changes" in outline.build(piece(bars))["sections"][1]["begins_at"]
    # ... and after a fermata
    bars = [bar(n, line(60 + 2 * n, TUNE), BASS) for n in range(1, 9)]
    bars[3]["expression"] = [{"type": "fermata", "beat": 3.0, "hand": "right"}]
    assert [s["bars"] for s in outline.build(piece(bars))["sections"]] == [[1, 4], [5, 8]]


def test_phrases_follow_the_pattern_and_the_rests():
    made = outline.build(long_piece())
    first = made["sections"][0]
    assert first["phrases"] == [[1, 2], [3, 4], [5, 6]]                 # the pattern starts over
    assert [11, 12] in next(s for s in made["sections"] if s["bars"][0] == 11)["phrases"]
    # a rest in both hands ends a phrase where nothing repeats
    bars = [bar(n, line(60 + 3 * n, [0, n, 2 * n, 1]), [[0.0, 4.0, [40 + n]]]) for n in range(1, 7)]
    bars[2] = bar(3, [[0.0, 2.0, [70]]], [[0.0, 2.0, [41]]])
    assert outline.build(piece(bars))["sections"][0]["phrases"][0] == [1, 3]


def test_difficulty_and_the_practice_order():
    made = outline.build(long_piece(), lambda steps: {10: "fourth"}.get(steps, ""))
    order = made["practice_order"]
    learn = next(k for k, text in enumerate(order) if "Learn pattern a first, bars 1-2" in text)
    again = next(k for k, text in enumerate(order) if "comes back unchanged in bars 3-4, 5-6, 17-18" in text)
    moved = next(k for k, text in enumerate(order) if "transpositions, the same hand shape on other keys: bars 11-12 (10 steps higher (fourth)); bars 13-14" in text)
    passages = next(k for k, text in enumerate(order) if "passages that are not a pattern" in text)
    assert learn < again < moved < passages < len(order) - 1 and order[-1].endswith("play the whole piece slowly.")
    assert order[passages].index("bars 15-16") < order[passages].index("bars 7-10")        # the easier passage first
    assert "Hands separately where one hand has more than it reaches: bar 20" in order[passages]
    by_start = {s["bars"][0]: s["difficulty"] for s in made["sections"]}
    assert by_start[7]["points"] > by_start[1]["points"] and by_start[7]["doubtful_bars"] == [9]
    assert by_start[11]["repeats_earlier"] == "4 of 6 bars" and by_start[11]["points"] < by_start[7]["points"]
    assert by_start[17]["tight_bars"] == [20] and by_start[17]["largest_chord"] == 5 and "notes_per_second" in by_start[1]
    # without a tempo the rate is per beat
    untimed = long_piece()
    del untimed["tempi"]
    assert "notes_per_beat" in outline.build(untimed)["sections"][0]["difficulty"]
    # nothing recurring: said so, and the passages in order of difficulty
    bars = [bar(n, line(60 + 5 * n, [0, n, 3 * n, 2]), [[0.0, 4.0, [40 + 2 * n]]]) for n in range(1, 5)]
    assert outline.build(piece(bars))["practice_order"][0].startswith("1. No recurring pattern was found.")


def test_the_outline_is_deterministic_and_small():
    one = outline.build(long_piece())
    shuffled = long_piece()
    for b in shuffled["score"]:             # the order of notes in the file does not matter
        b["staves"] = {"lower": list(reversed(b["staves"]["lower"])), "upper": list(reversed(b["staves"]["upper"]))}
    assert json.dumps(one, sort_keys=True) == json.dumps(outline.build(long_piece()), sort_keys=True) == json.dumps(outline.build(shuffled), sort_keys=True)
    seen = outline.overview(one)
    assert set(seen) == {"made", "sections", "repeats", "practice_order", "how"} and len(json.dumps(seen)) < 2500
    assert seen["sections"][0].startswith("1. A, bars 1-6: ") and "suggestions" in seen["how"]
    assert outline.build({"score": []}) is None
    assert outline.find_section(one, "2")["bars"][0] == 7 and outline.find_section(one, "b")["label"] == "B" and outline.find_section(one, 1)["n"] == 1
    with pytest.raises(ValueError, match="there is no section 'Z'"):
        outline.find_section(one, "Z")


def test_the_tutor_gives_the_outline_and_music_by_section(tmp_path):
    source, out = tmp_path / "src", tmp_path / "lib"
    (source / "woyten16").mkdir(parents=True)
    made_up = long_piece()
    score = {"title": "Little Piece", "composer": "Some One", "tuning": 31, "tempo": [{"bar": 1, "bpm": 240}], "bars": [
        {"n": b["n"], "time": b["time"], "staves": {staff: [{"beat": beat + 1.0, "dur": dur, "notes": [{"step": s + 64} for s in steps]}
                                                            for beat, dur, steps in events] for staff, events in b["staves"].items()}}
        for b in made_up["score"]]}
    (source / "woyten16" / "dont_take_five.json").write_text(json.dumps(score), encoding="utf-8")
    assert build.build(source, out) == {"scores": 1}
    library = lib.Library(out)
    pid = "score/dont-take-five"
    assert library.piece(pid)["outline"]["made"] == outline.MADE
    fake = FakeXentool(sample_setup(31, (0, 1, 2, 3, 4)))
    t = Tutor(fake, library=library)
    try:
        head = t.library("get", id=pid)
        assert "steps" not in head and head["outline"]["sections"][0].startswith("1. A, bars 1-6: the opening 2-bar pattern a (bars 1-2), 3 times")
        assert any("bars 3-4, 5-6" in text and "the same notes" in text for text in head["outline"]["repeats"])
        assert "section" in head["note"] and len(json.dumps(head["outline"])) < 3000
        # a short section comes whole, with its phrases listed and what its bars repeat
        first = t.library("get", id=pid, section=1, part="both")
        assert first["bars_given"] == "1-6" and first["given"] == "the whole section" and first["phrases"] == ["1: bars 1-2", "2: bars 3-4", "3: bars 5-6"]
        assert first["repeats"][0] == "bar 3: the same notes as bar 1" and len(first["repeats"]) == 4 and first["next"] == "library get with section=2"
        assert first["note"].endswith("Phrases are suggestions.") and len(first["steps"]) >= 24
        assert t.library("get", id=pid, section="A", phrase=2, part="both")["bars_given"] == "3-4"
        assert t.library("get", id=pid, section=1, phrase=2, phrases=2, part="both")["given"] == "phrases 2-3 of 3"
        # a transposed return says so with the interval's name in the keyboard's tuning; for one hand that hand only
        third = next(s for s in library.piece(pid)["outline"]["sections"] if s["bars"][0] == 11)
        moved = t.library("get", id=pid, section=third["n"], phrase=1, part="upper")
        assert moved["repeats"][0].startswith("bar 11: like bar 1, 10 steps higher (") and moved["part"] == "upper"
        # bars by number still come, at most four, and say what they repeat too
        assert t.library("get", id=pid, phrase=3, phrases=9)["bars_given"] == "3-6" and "repeats" in t.library("get", id=pid, phrase=3)
        with pytest.raises(TutorError, match="there is no section '12'"):
            t.library("get", id=pid, section=12)
        with pytest.raises(TutorError, match="phrase must be between 1 and 3 in section 1"):
            t.library("get", id=pid, section=1, phrase=4)
        # play_piece and play_along take the section instead of the bars
        played = t.play_piece(id=pid, section=1, octave=0)
        assert played["bars"] == "1-6" and t.stop() == {"stopped": True}
        with pytest.raises(TutorError, match="there is no section 'Q'"):
            t.play_piece(id=pid, section="Q")
        with pytest.raises(TutorError, match="there is no section 'Q'"):
            t.play_along(id=pid, section="Q")
    finally:
        t.stop()
        t.pump.stop()


def test_prelude_iii_of_the_real_library():
    """What the outline says about Prelude III of Wyschnegradsky's op. 22 (bar 1 is the upbeat): the
    two-bar pattern and its returns, the trill bars a step lower each, the close on its own."""
    library = lib.Library()
    found = library.piece("score/wyschnegradsky-prelude-03") if library.counts().get("composition") else None
    if not found or not found.get("outline"):
        pytest.skip("the library is not built (python -m tutor.library_build)")
    made = found["outline"]
    assert made == outline.build(found, outline.namer(lambda steps: lib_interval(steps), 24))           # as stored, and the same again
    main = made["patterns"][0]
    assert main["bars"] == [2, 3]
    same = [r["bars"] for r in main["returns"] if r["kind"] == "same"]
    assert same == [[4, 5], [12, 13], [14, 15], [34, 35], [42, 43]]
    # the pattern climbs in bar 16: most of the right hand 11 quarter-tones higher, the rest changed
    assert made["repeats"]["16"]["right"] == {"kind": "variant", "shift": 11} and made["repeats"]["16"]["of"] in (2, 4)
    # transposed repeats: the trill bars step down (bar 11 = bar 10 a semitone lower, bar 27 a whole tone), the falling line of 23 again in 25
    assert made["repeats"]["11"]["of"] == 10 and made["repeats"]["11"]["right"] == {"kind": "transposed", "shift": -2}
    assert made["repeats"]["27"]["of"] == 10 and made["repeats"]["27"]["right"] == {"kind": "transposed", "shift": -4}
    assert made["repeats"]["25"]["right"] == {"kind": "transposed", "shift": -18} and made["repeats"]["22"]["right"]["shift"] == -13
    section_of = {n: s for s in made["sections"] for n in range(s["bars"][0], s["bars"][1] + 1)}
    assert section_of[2]["label"] == "A" and section_of[2]["bars"] == [1, 5]
    assert section_of[10] is section_of[11] is not section_of[2] and section_of[10] is not section_of[12]      # the trill bars are apart
    assert section_of[12]["label"].startswith("A") and section_of[34]["bars"][0] == 34 and "a tempo" in section_of[34]["begins_at"]
    assert section_of[46]["bars"] == [46, 50] and not section_of[46]["label"].startswith("A")                 # the closing arpeggio
    assert "a rest in both hands" in section_of[46]["begins_at"]
    assert made["practice_order"][0].startswith("1. Learn pattern a first, bars 2-3")
    assert len(json.dumps(outline.overview(made), ensure_ascii=False)) < 3000


def lib_interval(steps: int) -> str:
    from tutor.theory import tuning_for
    t = tuning_for(24)
    return t.words(t.interval(steps))
