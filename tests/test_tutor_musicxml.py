"""MusicXML writer for machine-read scores (host/tutor/scores/musicxml.py).

The writer is checked through a reader written here that knows nothing of it: it walks the
MusicXML (divisions, backup, forward, chords, ties) and gives back the notes with onset,
length and pitch. What goes in must come out, on small made-up scores; the note values are
checked against notation itself (a dotted quarter is three eighths, three in the time of two).
The files under reference/music are third-party material and only read if they are there."""
from __future__ import annotations

import collections
import json
import sys
import xml.etree.ElementTree as ET
from fractions import Fraction as F
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
from tutor.scores import musicxml as mx  # noqa: E402

SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
NOTE_CHILDREN = ["grace", "chord", "pitch", "rest", "duration", "tie", "voice", "type", "dot", "accidental", "time-modification",
                 "notehead", "staff", "beam", "notations"]          # the order MusicXML prescribes


def read_back(xml: str):
    """Notes as (part, staff, onset, length, letter, octave, alter) with ties joined (within a voice),
    and per part the bars as (number, start, length of the longest voice, lengths of all voices)."""
    root = ET.fromstring(xml)
    notes, bars = [], {}
    for p, part in enumerate(root.findall("part")):
        divisions, at, tied = 1, F(0), {}
        for measure in part.findall("measure"):
            start, cursor, last = at, F(0), F(0)
            voices: dict[str, F] = collections.defaultdict(F)
            for el in measure:
                if el.tag == "attributes" and el.find("divisions") is not None:
                    divisions = int(el.find("divisions").text)
                elif el.tag == "backup":
                    cursor -= F(int(el.find("duration").text), divisions)
                elif el.tag == "forward":
                    cursor += F(int(el.find("duration").text), divisions)
                    if el.find("voice") is not None:
                        voices[el.findtext("voice")] += F(int(el.find("duration").text), divisions)
                elif el.tag == "note" and el.find("grace") is None:
                    assert [c.tag for c in el] == sorted((c.tag for c in el), key=NOTE_CHILDREN.index), "children of <note> out of order"
                    length = F(int(el.find("duration").text), divisions)
                    if el.find("chord") is not None:
                        cursor = last
                    else:
                        voices[el.findtext("voice")] += length
                    last = cursor
                    pitch = el.find("pitch")
                    if pitch is not None:
                        key = (p, int(el.findtext("staff") or 1), pitch.findtext("step"), int(pitch.findtext("octave")),
                               float(pitch.findtext("alter") or 0), el.findtext("voice"))
                        ties = {t.get("type") for t in el.findall("tie")}
                        assert ties == {t.get("type") for t in el.findall("notations/tied")}
                        if "stop" in ties and key in tied and sum(tied[key]) == start + cursor:
                            onset, held = tied.pop(key)
                            note = (onset, held + length)
                        else:
                            note = (start + cursor, length)
                        if "start" in ties:
                            tied[key] = note
                        else:
                            notes.append((key[0], key[1], note[0], note[1], key[2], key[3], key[4]))
                    cursor += length
            longest = max(voices.values())
            bars.setdefault(p, []).append((measure.get("number"), start, longest, sorted(voices.values())))
            at = start + longest
        assert not tied, f"ties left open: {tied}"
    return notes, bars


def one_staff(events, bars=None, **kw) -> mx.Score:
    bars = bars or [mx.Bar(1, "4/4", F(0), F(4))]
    return mx.Score("Test", [mx.Part("", ["G"])], bars, events, **kw)


def note(name: str, **kw) -> mx.Note:
    letter, accidental, octave = mx.parse_name(name)
    return mx.Note(letter, octave, accidental, **kw)


def ev(onset, dur, *names, staff=0, **kw) -> mx.Event:
    return mx.Event(staff, F(onset), F(dur), [note(n) if isinstance(n, str) else n for n in names], **kw)


def xml_notes(xml: str) -> list[ET.Element]:
    return [n for n in ET.fromstring(xml).iter("note")]


# ---- note values

def test_note_values_are_those_of_notation():
    assert mx.note_value(F(1)) == ("quarter", 0)
    assert mx.note_value(F(3, 2)) == ("quarter", 1)          # dotted quarter = three eighths
    assert mx.note_value(F(7, 4)) == ("quarter", 2)
    assert mx.note_value(F(3, 8)) == ("16th", 1)
    assert mx.note_value(F(4)) == ("whole", 0)
    assert mx.note_value(F(5, 4)) is None                    # a quarter and a sixteenth is two notes
    assert mx.note_value(F(1, 3)) is None


def test_beat_groups_of_common_time_signatures():
    assert mx.group_bounds("4/4") == [2]
    assert mx.group_bounds("3/4") == []
    assert mx.group_bounds("6/8") == [F(3, 2)]
    assert mx.group_bounds("12/8") == [F(3, 2), 3, F(9, 2)]
    assert mx.group_bounds("5/4") == [2, 4]
    assert mx.group_bounds("7/8") == [1, 2, 3]               # quarters, the odd eighth at the end
    assert mx.bar_length("7/8") == F(7, 2) and mx.bar_length("11/16") == F(11, 4)


def test_a_length_that_is_no_note_value_is_split_at_the_most_even_point():
    assert mx.split_values(F(0), F(5, 4)) == [(0, 1), (1, F(5, 4))]
    assert mx.split_values(F(3, 4), F(2), [F(2)]) == [(F(3, 4), 1), (1, 2)]
    assert mx.split_values(F(0), F(5, 2), [F(2)]) == [(0, 2), (2, F(5, 2))]            # half tied to an eighth
    assert mx.split_values(F(0), F(5), [F(3)]) == [(0, 3), (3, 5)]                     # 6/4: dotted half, half


def test_a_note_crosses_a_beat_group_only_from_a_beat():
    bounds, beat = mx.group_bounds("4/4"), F(1)
    assert mx.split_values(F(1), F(3), bounds, beat=beat) == [(1, 3)]                  # half note on the second quarter stays
    assert mx.split_values(F(3, 2), F(5, 2), bounds, beat=beat) == [(F(3, 2), 2), (2, F(5, 2))]      # quarter on the "and" of two is cut
    assert mx.split_values(F(3, 2), F(5, 2), bounds, keep=True) == [(F(3, 2), F(5, 2))]              # unless it is the printed value
    assert mx.split_values(F(1), F(5, 2), mx.group_bounds("6/8"), beat=F(3, 2)) == [(1, F(3, 2)), (F(3, 2), F(5, 2))]


# ---- tuplets

def test_three_eighths_in_a_quarter_are_a_triplet():
    items = [(F(0), F(1, 3), True), (F(1, 3), F(2, 3), True), (F(2, 3), F(1), True), (F(1), F(4), False)]
    (t,) = mx.find_tuplets(items, F(4))
    assert (t.start, t.end, t.actual, t.normal, t.unit) == (0, 1, 3, 2, F(1, 2))


def test_quarter_triplet_takes_two_beats_and_is_not_cut_in_the_middle():
    items = [(F(0), F(2, 3), True), (F(2, 3), F(4, 3), True), (F(4, 3), F(2), True), (F(2), F(4), False)]
    (t,) = mx.find_tuplets(items, F(4))
    assert (t.start, t.end, t.actual, t.normal, t.unit) == (0, 2, 3, 2, F(1))


def test_unusual_ratios():
    five = [(F(k * 3, 10), F((k + 1) * 3, 10), True) for k in range(5)] + [(F(3, 2), F(3), False)]
    (t,) = mx.find_tuplets(five, F(3))                       # five eighths in the time of three
    assert (t.start, t.end, t.actual, t.normal, t.unit) == (0, F(3, 2), 5, 3, F(1, 2))
    held = [(F(0), F(1), False), (F(1), F(12, 5), True), (F(12, 5), F(18, 5), False), (F(18, 5), F(4), True)]
    (t,) = mx.find_tuplets(held, F(4))                       # a quarter tied into five quarters in the time of two halves
    assert (t.start, t.end, t.actual) == (2, 4, 5) and (t.normal, t.unit) == (4, F(1, 2))
    seven = [(F(0), F(7, 6), True), (F(7, 6), F(7, 3), False), (F(7, 3), F(7, 2), True)]
    (t,) = mx.find_tuplets(seven, F(7, 2))                   # three in the time of seven eighths
    assert (t.actual, t.normal, t.unit) == (3, 7, F(1, 2))
    assert mx.find_tuplets([(F(0), F(3, 8), True), (F(3, 8), F(3, 4), True), (F(3, 4), F(3), False)], F(3)) == []      # dotted values, no tuplet


def test_a_triplet_is_written_with_time_modification_and_bracket():
    xml = mx.to_musicxml(one_staff([ev(0, F(1, 3), "C4"), ev(F(1, 3), F(1, 3), "D4"), ev(F(2, 3), F(1, 3), "E4"), ev(1, 3, "F4")]))
    notes = xml_notes(xml)
    assert [n.findtext("type") for n in notes] == ["eighth", "eighth", "eighth", "half", "quarter"] or \
        [n.findtext("type") for n in notes] == ["eighth", "eighth", "eighth", "half"]
    for n in notes[:3]:
        assert (n.findtext("time-modification/actual-notes"), n.findtext("time-modification/normal-notes")) == ("3", "2")
    assert notes[0].find("notations/tuplet").get("type") == "start" and notes[2].find("notations/tuplet").get("type") == "stop"
    assert notes[3].find("time-modification") is None
    assert [n.findtext("beam") for n in notes[:3]] == ["begin", "continue", "end"]
    back, bars = read_back(xml)
    assert [(o, d) for _, _, o, d, *_ in back] == [(0, F(1, 3)), (F(1, 3), F(1, 3)), (F(2, 3), F(1, 3)), (1, 3)]
    assert bars[0][0][3] == [4]


# ---- bars, voices, ties

def test_every_voice_of_every_bar_fills_the_bar():
    bars = [mx.Bar(1, "3/4", F(0), F(3)), mx.Bar(2, "6/8", F(3), F(3)), mx.Bar(3, "7/8", F(6), F(7, 2))]
    events = [ev(0, F(5, 4), "C4"), ev(F(1, 2), F(1, 2), "E4", "G4"), ev(2, F(1, 5), "A4"), ev(F(11, 5), F(4, 5), "B4"),
              ev(3, F(5, 2), "C5"), ev(F(9, 2), F(1, 2), "D4"), ev(6, F(7, 2), "C4"), ev(F(13, 2), F(2, 3), "E4"), ev(F(43, 6), F(1, 3), "F4")]
    xml = mx.to_musicxml(one_staff(events, bars))
    back, read = read_back(xml)
    for (number, start, longest, voices), bar in zip(read[0], bars):
        assert (int(number), start) == (bar.number, bar.start)
        assert all(v == bar.length for v in voices), (number, voices)
    assert sorted((o, d) for _, _, o, d, *_ in back) == sorted((e.onset, e.dur) for e in events for _ in e.notes)


def test_notes_sounding_together_with_different_lengths_get_two_voices():
    xml = mx.to_musicxml(one_staff([ev(0, 4, "C5"), ev(0, 1, "E4"), ev(1, 1, "F4"), ev(3, 1, "E4")]))
    notes = xml_notes(xml)
    assert {n.findtext("voice") for n in notes} == {"1", "2"}
    assert [n.findtext("voice") for n in notes if n.findtext("pitch/step") == "C"] == ["1"]          # the top note first
    assert "<backup><duration>" in xml
    second = [n for n in notes if n.findtext("voice") == "2"]
    assert [(n.find("rest") is not None, n.findtext("type")) for n in second] == [(False, "quarter"), (False, "quarter"), (True, "quarter"), (False, "quarter")]
    assert [(o, d, letter) for _, _, o, d, letter, *_ in sorted(read_back(xml)[0], key=lambda n: (n[2], n[4]))] == \
        [(0, 4, "C"), (0, 1, "E"), (1, 1, "F"), (3, 1, "E")]


def test_same_length_at_the_same_time_is_a_chord():
    xml = mx.to_musicxml(one_staff([ev(0, 4, "C4", "E4", "G4")]))
    notes = xml_notes(xml)
    assert [n.find("chord") is not None for n in notes] == [False, True, True]
    assert [n.findtext("pitch/step") for n in notes] == ["C", "E", "G"]


def test_a_note_over_the_barline_is_cut_and_tied_and_stays_in_its_voice():
    bars = [mx.Bar(1, "4/4", F(0), F(4)), mx.Bar(2, "4/4", F(4), F(4)), mx.Bar(3, "4/4", F(8), F(4))]
    xml = mx.to_musicxml(one_staff([ev(0, 2, "C4"), ev(2, 7, "G4"), ev(4, 4, "C4"), ev(9, 3, "E4")], bars))
    g = [n for n in xml_notes(xml) if n.findtext("pitch/step") == "G"]
    assert [n.findtext("type") for n in g] == ["half", "whole", "quarter"]
    assert [[t.get("type") for t in n.findall("tie")] for n in g] == [["start"], ["stop", "start"], ["stop"]]
    assert len({n.findtext("voice") for n in g}) == 1
    back, _ = read_back(xml)
    assert (0, 1, F(2), F(7), "G", 4, 0.0) in back and len(back) == 4


def test_ties_marked_in_the_file_join_the_note_before():
    held = note("B3", tie_in=True)
    xml = mx.to_musicxml(one_staff([ev(0, 1, "B3"), ev(1, F(1, 2), "D4"), ev(1, 2, held), ev(F(3, 2), F(1, 2), "E4")], keep_values=True))
    back, _ = read_back(xml)
    assert (0, 1, F(0), F(3), "B", 3, 0.0) in back           # one note of three quarters
    score = one_staff([ev(0, 1, "C4"), ev(2, 1, note("C4", tie_in=True))])
    mx.to_musicxml(score)
    assert any("marked as tied" in w for w in score.warnings)


def test_printed_values_are_kept_and_rests_fill_the_gaps():
    bars = [mx.Bar(1, "6/8", F(0), F(3))]
    xml = mx.to_musicxml(one_staff([ev(1, 1, "C4"), ev(F(5, 2), F(1, 2), "D4")], bars, keep_values=True))
    kinds = [("rest" if n.find("rest") is not None else n.findtext("pitch/step"), n.findtext("type"), len(n.findall("dot"))) for n in xml_notes(xml)]
    assert kinds == [("rest", "quarter", 0), ("C", "quarter", 0), ("rest", "eighth", 0), ("D", "eighth", 0)]


def test_an_empty_staff_gets_a_whole_bar_rest_and_bars_keep_their_numbers():
    score = mx.Score("T", [mx.Part("Piano")], [mx.Bar(7, "5/8", F(0), F(5, 2)), mx.Bar(8, "5/8", F(5, 2), F(5, 2))], [ev(0, 1, "C4")])
    root = ET.fromstring(mx.to_musicxml(score))
    assert [m.get("number") for m in root.iter("measure")] == ["7", "8"]
    rests = [n for n in root.iter("note") if n.find("rest") is not None and n.find("rest").get("measure") == "yes"]
    assert len(rests) == 3                                   # lower staff twice, upper staff in bar 8
    assert root.findtext("part/measure/attributes/time/beats") == "5" and len(list(root.iter("time"))) == 1


# ---- accidentals

def test_microtonal_signs_are_standard_musicxml_values():
    names = {"Ct4": ("0.5", "quarter-sharp"), "Cd4": ("-0.5", "quarter-flat"), "C#t4": ("1.5", "three-quarters-sharp"),
             "Cdb4": ("-1.5", "three-quarters-flat"), "C^4": ("0.25", "natural-up"), "Cv4": ("-0.25", "natural-down"),
             "C#^4": ("1.25", "sharp-up"), "C#v4": ("0.75", "sharp-down"), "Cb^4": ("-0.75", "flat-up"), "Cbv4": ("-1.25", "flat-down"),
             "C#4": ("1", "sharp"), "Cb4": ("-1", "flat"), "Cx4": ("2", "double-sharp"), "C+4": ("0.5", "quarter-sharp")}
    for name, (alter, sign) in names.items():
        (n,) = xml_notes(mx.to_musicxml(one_staff([ev(0, 4, name)])))
        assert (n.findtext("pitch/alter"), n.findtext("accidental")) == (alter, sign), name
    (n,) = xml_notes(mx.to_musicxml(one_staff([ev(0, 4, "C4")])))
    assert n.find("pitch/alter") is None and n.find("accidental") is None


def test_an_accidental_holds_for_its_line_until_the_barline():
    bars = [mx.Bar(1, "4/4", F(0), F(4)), mx.Bar(2, "4/4", F(4), F(4))]
    events = [ev(0, 1, "Ct4"), ev(1, 1, "Ct4"), ev(2, 1, "C4"), ev(3, 1, "Ct5"), ev(4, 2, "Ct4"), ev(6, 2, "C4")]
    signs = [n.findtext("accidental") for n in xml_notes(mx.to_musicxml(one_staff(events, bars)))]
    assert signs == ["quarter-sharp", None, "natural", "quarter-sharp", "quarter-sharp", "natural"]


def test_a_tied_note_gets_no_sign_but_the_next_note_on_its_line_does():
    bars = [mx.Bar(1, "4/4", F(0), F(4)), mx.Bar(2, "4/4", F(4), F(4))]
    signs = [n.findtext("accidental") for n in xml_notes(mx.to_musicxml(one_staff([ev(0, 6, "C#4"), ev(6, 1, "C#4"), ev(7, 1, "C4")], bars)))]
    assert signs == ["sharp", None, "sharp", "natural"]


def test_key_signature_of_any_signs():
    bars = [mx.Bar(1, "4/4", F(0), F(4), key=[("F", "half-sharp"), ("B", "half-flat")])]
    root = ET.fromstring(mx.to_musicxml(one_staff([ev(0, 1, "Ft4"), ev(1, 1, "F4"), ev(2, 1, "Bd4"), ev(3, 1, "G4")], bars)))
    key = root.find("part/measure/attributes/key")
    assert [(c.tag, c.text) for c in key] == [("key-step", "F"), ("key-alter", "0.5"), ("key-accidental", "quarter-sharp"),
                                              ("key-step", "B"), ("key-alter", "-0.5"), ("key-accidental", "quarter-flat")]
    assert [n.findtext("accidental") for n in root.iter("note")] == [None, "natural", None, None]
    assert "<fifths>2</fifths>" in mx.key_xml([("F", "sharp"), ("C", "sharp")]) and "<fifths>-1</fifths>" in mx.key_xml([("B", "flat")])


def test_alter_in_a_tuning_that_is_not_a_multiple_of_twelve():
    assert mx.edo_alter(81, 17, "A", 4) == 0                                 # A4 is the reference
    assert mx.edo_alter(69, 17, "C", 4) == pytest.approx(0.5294, abs=1e-4)   # C half-sharp: 12 steps of 70.6 cents below A, C is 900 below
    assert mx.edo_alter(71, 17, "D", 4) == pytest.approx(-0.0588, abs=1e-4)  # a fifth of 705.9 cents below A
    assert mx.edo_alter(72, 24, "A", 3 - 1 + 1) == mx.edo_alter(72 + 24, 24, "A", 4)


# ---- scores in bars (the Woyten files)

SMALL = {"title": "Small", "composer": "Nobody", "tuning": 17, "key_signatures": {"1-1": "Ft Bd", "2-2": "Ft"},
         "uncertain": [{"bar": 2, "staff": "lower", "beat": 2.0, "why": "test"}], "tempo": [{"bar": 1, "bpm": 84}],
         "bars": [
             {"n": 1, "time": "6/8", "staves": {
                 "upper": [{"beat": 1.0, "dur": 1.5, "notes": [{"step": 69, "name": "Ct4", "tied": False}, {"step": 73, "name": "Ed4", "tied": False}]},
                           {"beat": 2.5, "dur": 1.5, "notes": [{"step": 69, "name": "Ct4", "tied": True}]}],
                 "lower": [{"beat": 1.0, "dur": 3.0, "notes": [{"step": 57, "name": "Fd3", "tied": False, "source": "recording",
                                                                "also": [{"step": 58, "name": "F3", "source": "print"}]}]}]}},
             {"n": 2, "time": "6/8", "staves": {
                 "upper": [{"beat": 1.0, "dur": 0, "notes": [{"step": 70, "name": "Dd4", "tied": False}], "grace": True},
                           {"beat": 1.0, "dur": 3.0, "notes": [{"step": 67, "name": "B3", "tied": False}], "fermata": True}],
                 "lower": [{"beat": 2.0, "dur": 0.5, "notes": [], "rest": True}]}}]}


def test_bars_score_keeps_the_stored_spelling_and_ties():
    score = mx.bars_score(SMALL, ["Machine reading of a test, not proofread; compare with the original."])
    xml = mx.to_musicxml(score)
    root = ET.fromstring(xml)
    assert [c.findtext("credit-words") for c in root.findall("credit")] == ["Small", "Machine reading of a test, not proofread; compare with the original.", "Nobody"]
    back, bars = read_back(xml)
    c = [n for n in back if n[4] == "C"]
    assert [(n[2], n[3]) for n in c] == [(0, 3)]                             # the tied Ct4 is one note
    assert c[0][6] == pytest.approx(0.5294, abs=1e-4)
    notes = list(root.iter("note"))
    first_c = next(n for n in notes if n.findtext("pitch/step") == "C")
    assert first_c.findtext("accidental") == "quarter-sharp"                 # C is not in the key signature
    assert len(list(root.iter("key"))) == 2 and [m.get("number") for m in root.iter("measure")] == ["1", "2"]
    grace = [n for n in notes if n.find("grace") is not None]
    assert len(grace) == 1 and grace[0].findtext("pitch/step") == "D" and grace[0].findtext("accidental") == "quarter-flat"
    assert root.find(".//fermata") is not None
    assert root.findtext(".//metronome/per-minute") == "84"


def test_two_readings_are_marked_on_the_note_and_named_above_the_staff():
    root = ET.fromstring(mx.to_musicxml(mx.bars_score(SMALL)))
    marked = [n for n in root.iter("note") if n.find("notehead") is not None]
    assert len(marked) == 1 and marked[0].find("notehead").get("parentheses") == "yes" and marked[0].findtext("pitch/step") == "F"
    words = [(d.findtext("direction-type/words"), d.findtext("staff")) for d in root.iter("direction") if d.find("direction-type/words") is not None]
    assert ("print: F3", "2") in words


def test_doubtful_places_get_a_question_mark():
    root = ET.fromstring(mx.to_musicxml(mx.bars_score(SMALL, doubtful=[1])))
    marks = [(m.get("number"), d.findtext("staff")) for m in root.iter("measure") for d in m.iter("direction") if d.findtext("direction-type/words") == "?"]
    assert marks == [("1", "1"), ("2", "2")]
    second = root.findall("part/measure")[1]
    assert second.find("forward") is not None                                # the mark stands at the second beat


def test_sixteen_tone_notation_follows_the_stored_sign():
    data = {"title": "S", "tuning": {"edo": 16}, "bars": [{"n": 1, "time": "2/4", "staves": {"upper": [
        {"beat": 1, "dur": 1, "notes": [{"step": 66, "name": "C#^4", "accidental": "sharp-arrow-up"}]},
        {"beat": 2, "dur": 1, "notes": [{"step": 59, "name": "G+3", "accidental": "half-sharp"}]}], "lower": []}}]}
    notes = xml_notes(mx.to_musicxml(mx.bars_score(data)))
    assert [(n.findtext("pitch/alter"), n.findtext("accidental")) for n in notes[:2]] == [("1.25", "sharp-up"), ("0.5", "quarter-sharp")]
    # step = (cents above C0 + 25) / 75: C#^4 is 4800 + 125 cents
    assert (4800 + 125 + 25) / 75 == 66


# ---- the preludes

def prelude(**kw) -> dict:
    base = {"number": 1, "title": "Prélude", "bars": 3, "time_changes": [{"bar": 1, "time": "4/4"}, {"bar": 3, "time": "3/4"}],
            "zero_length_bars": [2], "tempi": [{"onset": 0.0, "bpm_quarter": 92.0}, {"onset": 4.0, "bpm_quarter": 46.0}],
            "uncertain": [{"bar": 3, "piano": 2, "why": "test"}],
            "notes": [{"onset": 0.0, "dur": 1.0, "step": 96, "piano": 1, "bar": 1, "source": "print", "also": [{"step": 94, "source": "engraving"}]},
                      {"onset": 1.0, "dur": 1.0, "step": 98, "piano": 1, "bar": 1},
                      {"onset": 0.0, "dur": 2.0, "step": 95, "piano": 2, "bar": 1},
                      {"onset": 2.0, "dur": 1.0, "step": 97, "piano": 2, "bar": 1},
                      {"onset": 3.0, "dur": 2.0, "step": 59, "piano": 2, "bar": 1},
                      {"onset": 4.0, "dur": 3.0, "step": 120, "piano": 1, "bar": 3}]}
    base.update(kw)
    return base


def test_zero_length_bars_are_skipped_and_the_rest_renumbered():
    bars, starts = mx.prelude_bars(prelude())
    assert [(b.number, b.time, b.start, b.length) for b in bars] == [(1, "4/4", 0, 4), (2, "3/4", 4, 3)]
    assert starts == {1: 0, 2: 4, 3: 4}
    xml = mx.to_musicxml(mx.prelude_score(prelude()))
    back, read = read_back(xml)
    assert [(n, s, length) for n, s, length, _ in read[0]] == [("1", 0, 4), ("2", 4, 3)]
    assert (0, 1, F(4), F(3), "C", 5, 0.0) in back                          # the note of bar 3 stands in the second bar


def test_piano_two_is_written_a_quarter_tone_above_what_sounds():
    score = mx.prelude_score(prelude())
    assert [p.name for p in score.parts] == ["Piano I", "Piano II (sounds a quarter-tone lower)"] and score.parts[1].transpose == -0.5
    back, _ = read_back(mx.to_musicxml(score))
    second = sorted((o, d, letter, octave, alter) for p, _, o, d, letter, octave, alter in back if p == 1)
    assert second == [(0, 2, "C", 4, 0.0), (2, 1, "C", 4, 1.0), (3, 2, "F", 2, 1.0)]       # steps 95, 97, 59: the keys C4, C#4, F#2
    for p, staff, o, d, letter, octave, alter in back:                                      # written pitch back to the step
        step = round(2 * (12 * octave + SEMITONES[letter] + alter)) - p
        assert step in {96, 98, 95, 97, 59, 120}
    assert (1, 2, F(3), F(2), "F", 2, 1.0) in back                                          # low notes on the lower staff, over the barline


def test_sounding_mode_gives_piano_two_quarter_tone_signs():
    score = mx.prelude_score(prelude(), sounding=True)
    xml = mx.to_musicxml(score)
    back, _ = read_back(xml)
    assert sorted((letter, octave, alter) for p, _, _, _, letter, octave, alter in back if p == 1) == [("C", 4, -0.5), ("C", 4, 0.5), ("F", 2, 0.5)]
    for p, _, _, _, letter, octave, alter in back:
        assert round(2 * (12 * octave + SEMITONES[letter] + alter)) in {96, 98, 95, 97, 59, 120}      # now the sounding step itself
    signs = {n.findtext("accidental") for n in ET.fromstring(xml).findall("part")[1].iter("note")} - {None}
    assert signs == {"quarter-flat", "quarter-sharp"}
    assert mx.QUARTER_LOWER == {"natural": "half-flat", "sharp": "half-sharp", "flat": "sesquiflat"}      # a flat a quarter-tone lower: three quarters flat
    assert "sounding pitch" in score.parts[1].name and "<transpose>" not in xml


def test_prelude_marks_tempo_second_reading_and_doubtful_bar():
    root = ET.fromstring(mx.to_musicxml(mx.prelude_score(prelude(), doubtful=[1])))
    first, second = root.findall("part")
    words = [(m.get("number"), d.findtext("direction-type/words")) for m in first.iter("measure") for d in m.iter("direction") if d.find("direction-type/words") is not None]
    assert ("1", "engr.: B3") in words and ("1", "?") in words
    assert [(m.get("number"), d.findtext("direction-type/metronome/per-minute")) for m in first.iter("measure") for d in m.iter("direction")
            if d.find("direction-type/metronome") is not None] == [("1", "92"), ("2", "46")]
    assert [m.get("number") for m in second.iter("measure") for d in m.iter("direction") if d.findtext("direction-type/words") == "?"] == ["2"]
    assert next(n for n in first.iter("note") if n.find("notehead") is not None).findtext("pitch/step") == "C"


def test_spelling_rule_for_black_keys():
    s = mx.Speller()
    assert s.chord(1, [48])[48] == ("C", "natural", 4)
    assert s.chord(1, [49])[49] == ("C", "sharp", 4)             # higher than the note before: sharp
    assert s.chord(1, [61])[61] == ("C", "sharp", 5)             # the same key name as earlier in the bar
    assert s.chord(2, [58])[58] == ("B", "flat", 4)              # lower than the note before: flat
    assert s.chord(3, [60, 61])[61] == ("D", "flat", 5)          # not on the line of the C in the same chord
    assert s.chord(4, [61, 62])[61] == ("C", "sharp", 5)


def test_staff_by_pitch():
    notes = [(F(0), F(1), 60), (F(0), F(1), 36), (F(1), F(2), 43), (F(1), F(2), 52), (F(5), F(6), 47), (F(9), F(10), 50)]
    assert mx.choose_staves(notes) == [0, 1, 1, 0, 1, 0]         # C5 up, C3 down, G3 near the bass note, E4 near neither, B3 and D4 alone


# ---- structure, checked by other programs

def test_music21_reads_a_quarter_tone_score_back():
    music21 = pytest.importorskip("music21")
    xml = mx.to_musicxml(mx.prelude_score(prelude(), sounding=True))
    score = music21.converter.parseData(xml, format="musicxml")
    assert len(score.parts) == 4                                 # music21 makes one part per staff
    pitches = sorted(n.pitch.ps for n in score.recurse().getElementsByClass("Note"))
    assert pitches == sorted(step / 2 + 12 for step in (96, 98, 95, 97, 59, 59, 120))      # the tied note comes twice; C4 = 60 = step 96
    for part in score.parts:
        assert [m.duration.quarterLength for m in part.getElementsByClass("Measure")] == [4.0, 3.0]


def test_rendering_gives_a_pdf_with_the_header():
    pytest.importorskip("verovio")
    pymupdf = pytest.importorskip("pymupdf")
    if mx.find_musescore():
        pytest.skip("MuseScore is installed and would be used; this test is about the Verovio path")
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        score = mx.bars_score(SMALL, ["Machine reading of a test, not proofread; compare with the original."])
        pages = mx.write_sheet(score, Path(folder) / "small")
        assert pages == 1 and (Path(folder) / "small.musicxml").exists()
        with pymupdf.open(Path(folder) / "small.pdf") as doc:
            text = doc[0].get_text()
            assert "not proofread" in text and "Small" in text and "print: F3" in text
            assert abs(doc[0].rect.width - 595) < 1 and len(doc[0].get_drawings()) > 50      # A4, and music was drawn


def test_verovio_draws_the_glyph_each_sign_stands_for():
    verovio = pytest.importorskip("verovio")
    import re
    verovio.enableLog(verovio.LOG_OFF)
    glyphs = {"natural": "E261", "sharp": "E262", "flat": "E260", "double-sharp": "E263", "double-flat": "E264", "half-sharp": "E282",
              "half-flat": "E280", "sesquisharp": "E283", "sesquiflat": "E281", "natural-arrow-up": "E272", "natural-arrow-down": "E273",
              "sharp-arrow-up": "E274", "sharp-arrow-down": "E275", "flat-arrow-up": "E270", "flat-arrow-down": "E271"}       # SMuFL code points
    for name, (_, value, _) in mx.ACCIDENTALS.items():
        score = one_staff([mx.Event(0, F(0), F(4), [mx.Note("B", 4, name)])], bars=[mx.Bar(1, "4/4", F(0), F(4), key=[("B", "sharp" if name != "sharp" else "flat")])])
        toolkit = verovio.toolkit()
        toolkit.setOptions({"header": "none", "footer": "none"})
        assert toolkit.loadData(mx.to_musicxml(score))
        drawn = re.search(r'class="accid"[^>]*>(.*?)</g>', toolkit.renderToSVG(1), re.S)
        found = re.findall(r'href="#(E[0-9A-F]{3})', drawn.group(1)) if drawn else []
        if value in mx.VEROVIO_UNDRAWN:
            assert found == [], (name, found)                    # if this fails, Verovio has learnt the sign: take it off the list
        else:
            assert found == [glyphs[name]], (name, found)


def test_signs_verovio_cannot_draw_are_reported():
    pytest.importorskip("verovio")
    pytest.importorskip("pymupdf")
    if mx.find_musescore():
        pytest.skip("MuseScore is installed and would be used")
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        score = one_staff([ev(0, 4, "Cx^4")])
        mx.write_sheet(score, Path(folder) / "x")
        assert any("draws no sign for double-sharp-up" in w for w in score.warnings)


def test_plain_svg_keeps_only_what_the_pdf_converter_understands():
    svg = ('<svg width="840px" height="1188px" xmlns="http://www.w3.org/2000/svg"><defs></defs><style>x</style>'
           '<svg class="definition-scale" color="black" viewBox="0 0 21000 29700"><g class="page-margin">'
           '<g id="a" class="section placeholder systemMilestone">\n<ellipse cx="1" cy="2" rx="90" ry="90" />\n</g>'
           '<g id="t" class="tempo"><text x="100" y="200" font-size="0px"><tspan class="rend"><tspan class="text">'
           '<tspan font-family="Leipzig" font-size="720px"></tspan></tspan></tspan><tspan font-size="405px"> = 92</tspan></text></g>'
           '<path stroke-width="13" d="M0 0 L10 10" stroke="currentColor"/></g></svg></svg>')
    out = mx.plain_svg(svg)
    assert out.count("<svg") == 1 and 'scale(0.04)' in out and "placeholder" not in out and "currentColor" not in out
    assert "" not in out and "<ellipse" in out and "<rect" in out and 'class="tempo" font-weight="bold"' in out


# ---- the real files, if they are there

def real_preludes():
    path = mx.MUSIC / "wyschnegradsky" / "preludes.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


@pytest.mark.parametrize("sounding", [False, True])
def test_real_preludes_come_back_note_for_note(sounding):
    preludes = real_preludes()
    if not preludes:
        pytest.skip("reference/music/wyschnegradsky/preludes.json is not there")
    for p in preludes:
        score = mx.prelude_score(p, sounding=sounding)
        back, read = read_back(mx.to_musicxml(score))
        got = collections.Counter((part + 1, o, d, round(2 * (12 * octave + SEMITONES[letter] + alter)) - (0 if sounding else part))
                                  for part, _, o, d, letter, octave, alter in back)
        want = collections.Counter({(n["piano"], mx.frac(n["onset"]), mx.frac(n["dur"]), n["step"]) for n in p["notes"]})
        assert got == want, (p["number"], list((want - got).items())[:3], list((got - want).items())[:3])
        bars, _ = mx.prelude_bars(p)
        for part in read.values():
            assert [(str(b.number), b.start, b.length) for b in bars] == [(n, s, length) for n, s, length, _ in part]
            assert all(v == b.length for b, (_, _, _, voices) in zip(bars, part) for v in voices)
        assert not [w for w in score.warnings if "same key twice" not in w], score.warnings


@pytest.mark.parametrize("relative, edo", [("woyten16/dont_take_five.json", 16), ("woyten/final/ephemeral_happiness.json", 17)])
def test_real_scores_in_bars_come_back_note_for_note(relative, edo):
    path = mx.MUSIC / relative
    if not path.exists():
        pytest.skip(f"reference/music/{relative} is not there")
    data = json.loads(path.read_text(encoding="utf-8"))
    score = mx.bars_score(data)
    back, read = read_back(mx.to_musicxml(score))

    def step(letter, octave, alter):
        semitones = 12 * octave + SEMITONES[letter] + alter
        return round((semitones * 100 + 25) / 75, 2) if edo == 16 else round(81 + (semitones - 57) * 17 / 12, 2)

    got = collections.Counter((staff, o, d, step(letter, octave, alter)) for _, staff, o, d, letter, octave, alter in back)
    want, held, at = [], {}, F(0)
    for bar in data["bars"]:
        for staff, name in enumerate(("upper", "lower")):
            for e in sorted(bar["staves"].get(name) or [], key=lambda e: e["beat"]):
                if e.get("rest") or e.get("grace") or not e["dur"]:
                    continue
                onset, dur = at + mx.frac(e["beat"]) - 1, mx.frac(e["dur"])
                for n in e["notes"]:
                    before = held.get((staff, n["name"]))
                    if n.get("tied") and before and before[1] + before[2] == onset:
                        before[2] += dur
                    else:
                        letter, accidental, octave = mx.parse_name(n["name"])
                        spelled = step(letter, octave, mx.ACCIDENTALS[n.get("accidental", accidental)][0]) if edo == 16 else float(n["step"])
                        held[(staff, n["name"])] = record = [staff + 1, onset, dur, spelled]
                        want.append(record)
        at += mx.bar_length(bar["time"])
    assert got == collections.Counter(tuple(r) for r in want)
    assert [(str(b["n"]), mx.bar_length(b["time"])) for b in data["bars"]] == [(n, length) for n, _, length, _ in read[0]]
    assert all(v == length for _, _, length, voices in read[0] for v in voices)
    assert not score.warnings, score.warnings
