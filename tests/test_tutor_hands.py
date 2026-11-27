"""Which hand plays which note (`host/tutor/scores/hands.py`), on small made-up music.

Pitches are semitones (C4 = 48) unless a test says otherwise; times are seconds.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
from tutor import fingering  # noqa: E402
from tutor.scores import hands as H  # noqa: E402
from tutor.scores import musicxml as mx  # noqa: E402

R, L = H.RIGHT, H.LEFT


def assign(notes, **kw):
    return H.assign_hands(notes, per_octave=12, middle=48, **kw)


def test_reach_is_that_of_the_fingering_model():
    relaxed, comfortable, practical = H.DEFAULT.spans()
    assert (relaxed, comfortable, practical) == fingering._SPANS_UNITS["medium"][(1, 5)][3:]
    assert comfortable == H.UNITS_PER_OCTAVE                    # an octave is comfortable, a ninth the practical limit
    assert H.DEFAULT.reach(relaxed) == 0 and H.DEFAULT.reach(comfortable) == 2 * fingering.W_REL
    assert H.DEFAULT.reach(practical + 1) == 5 * fingering.W_REL + 3 * fingering.W_COMF + fingering.W_PRAC


def test_a_melody_that_dips_below_the_accompaniment_stays_in_the_right_hand():
    # the left hand holds Eb3-G3-Eb4; the melody comes down from G5 to C4, below the chord's top note, and goes up again
    melody = ([67, 65, 64, 62, 60, 58, 57, 55, 53, 52, 50, 48] + [50, 52, 53, 55, 57, 58, 60, 62, 64, 65]) * 2
    notes, want = [], []
    for k, pitch in enumerate(melody):
        if k % 22 == 0:
            notes += [(k * 0.25, k * 0.25 + 5.5, p) for p in (39, 43, 51)]
            want += [L, L, L]
        notes.append((k * 0.25, k * 0.25 + 0.25, pitch))
        want.append(R)
    assert assign(notes) == want
    assert H.playability(notes, want, 12)["crossed"] == 6        # the hands do cross (D4, C4, D4 under the held Eb4): nothing better
    by_pitch = [L if p < 53 else R for _, _, p in notes]         # a split at a fixed pitch hands the low melody notes to the other hand
    assert by_pitch != want


def test_a_chord_too_wide_for_one_hand_is_shared():
    chord = [(0.0, 2.0, p) for p in (36, 43, 48, 60, 64, 72)]             # C3 to C6
    got = assign(chord)
    assert got == sorted(got, reverse=True) and L in got and R in got       # the low notes left, the high ones right
    for side in (L, R):
        mine = [p for (_, _, p), h in zip(chord, got) if h == side]
        assert max(mine) - min(mine) <= 12 and len(mine) <= 5              # each part within an octave
    assert H.playability(chord, got, 12)["over_span"] == [] and H.playability(chord, [R] * 6, 12)["over_span"] == [0.0]


def test_a_held_bass_note_keeps_its_hand():
    notes = [(0.0, 8.0, 36)] + [(0.5 * k, 0.5 * k + 0.5, p) for k, p in enumerate([60, 62, 64, 65, 67, 65, 64, 62, 60, 55, 52, 48, 52, 55, 60, 64])]
    got = assign(notes)
    assert got[0] == L and set(got[1:]) == {R}                   # the line above never takes the bass along, nor the bass the line


def test_an_arpeggio_through_three_octaves_changes_hands_once():
    rising = [36, 40, 43, 48, 52, 55, 60, 64, 67, 72]
    got = assign([(0.2 * k, 0.2 * k + 0.2, p) for k, p in enumerate(rising)])
    assert got[0] == L and got[-1] == R
    assert sum(a != b for a, b in zip(got, got[1:])) == 1


def test_the_same_music_gives_the_same_hands_in_any_order_and_any_pitch_unit():
    notes = [(0.25 * k, 0.25 * k + 0.5, p) for k, p in enumerate([48, 55, 64, 36, 60, 67, 43, 72, 52, 59, 40, 65] * 3)]
    first = assign(notes)
    assert first == assign(notes) and first == assign(list(notes))
    back = assign(notes[::-1])
    assert back[::-1] == first                                    # answers come in the order of the input
    cents = H.assign_hands([(a, b, 100 * p) for a, b, p in notes], per_octave=1200, middle=4800)
    steps = H.assign_hands([(a, b, 2 * p) for a, b, p in notes], per_octave=24, middle=96)
    assert cents == first == steps
    assert H.assign_hands([]) == []


def test_notes_with_a_known_hand_keep_it_and_the_others_follow_their_line():
    # upper line around C5, lower line around C3, both known; one bar in the middle is not
    upper = [(0.5 * k, 0.5 * k + 0.5, p) for k, p in enumerate([60, 62, 64, 62, 60, 59, 57, 59, 60, 62, 64, 65])]
    lower = [(0.5 * k, 0.5 * k + 0.5, p) for k, p in enumerate([36, 43, 40, 43, 36, 43, 41, 43, 36, 43, 40, 43])]
    notes = upper + lower
    known = [R] * 12 + [L] * 12
    hidden = [None if 4 <= k % 12 < 8 else side for k, side in enumerate(known)]
    assert assign(notes, fixed=hidden) == known
    # a known hand is kept even where the model would never put it: the top note in the left hand
    odd = list(known)
    odd[2] = L
    assert assign(notes, fixed=odd) == odd


def test_playability_counts_what_does_not_fit():
    wide = [(0.0, 1.0, p) for p in (36, 52, 60, 76)]                       # two tenths: no two hands of a ninth's reach
    play = H.playability(wide, [L, L, R, R], 12)
    assert play["unplayable"] == [0.0] and play["over_span"] == [0.0] and play["max_struck"] == 4
    six = [(1.0, 2.0, p) for p in (60, 61, 62, 63, 64, 65)]                # six notes in one hand: one finger short
    assert H.playability(six, [R] * 6, 12)["over_span"] == [1.0] and H.playability(six, [L] * 3 + [R] * 3, 12)["over_span"] == []
    held = [(0.0, 4.0, 36), (2.0, 3.0, 60)]                                # fits only if the bass is let go (or pedalled)
    play = H.playability(held, [L, L], 12)
    assert play["held_over"] == [2.0] and play["over_span"] == [] and play["unplayable"] == [] and play["max_sounding"] == 2


# ---- clefs that follow what a staff holds

def note(key: int) -> mx.Note:
    letter, accidental = mx.SHARP_SPELLING[key % 12]
    return mx.Note(letter, key // 12, accidental)


def test_ledger_lines():
    assert [mx.ledger_lines(note(k), "G") for k in (52, 50, 48, 45, 65, 67, 69, 72)] == [0, 0, 1, 2, 0, 0, 1, 2]       # E4 D4 C4 A3 | F5 G5 A5 C6
    assert [mx.ledger_lines(note(k), "F") for k in (31, 29, 28, 24, 45, 47, 48, 52)] == [0, 0, 1, 2, 0, 0, 1, 2]       # G2 F2 E2 C2 | A3 B3 C4 E4
    assert mx.ledger_lines(note(12), "F8vb") == mx.ledger_lines(note(24), "F") and mx.ledger_lines(note(84), "G8va") == mx.ledger_lines(note(72), "G")


def test_the_clef_follows_a_passage_but_not_a_single_note():
    high, low = [note(k) for k in (60, 64, 67, 72)], [note(k) for k in (36, 40, 43, 31)]
    assert mx.choose_clefs([high, high, high + [note(40)], high]) == ["G"] * 4            # one low note among high ones
    assert mx.choose_clefs([high, low, low, high, high]) == ["G", "F", "F", "G", "G"]     # two bars in the bass
    assert mx.choose_clefs([low, [], [], low], first="G") == ["F"] * 4                    # an upper staff may be in the bass clef
    assert mx.choose_clefs([[note(k) for k in (12, 14, 16, 19)]] * 2)[0] == "F8vb"         # C1: the bass clef an octave lower


def test_the_one_player_sheet_keeps_printed_staves_and_changes_clef():
    notes = []
    for bar in range(4):                                         # bars 3 and 4: the right hand's line lies in the bass, as printed
        for k in range(4):
            notes.append({"onset": 4.0 * bar + k, "dur": 1.0, "step": (120 if bar < 2 else 60) + 2 * k, "piano": 1, "bar": bar + 1, "staff": "upper"})
            notes.append({"onset": 4.0 * bar + k, "dur": 1.0, "step": 49 + 2 * k, "piano": 2, "bar": bar + 1, "staff": "lower"})
    prelude = {"number": 1, "bars": 4, "time": "4/4", "notes": notes}
    assert mx.prelude_hands(prelude)[1] == [1, 0] * 16           # in order of onset and pitch: lower staff, upper staff
    score = mx.prelude_score(prelude, updown=True)
    assert sorted((e.staff, e.notes[0].octave) for e in score.events if e.onset >= 8) == [(0, 2)] * 8 + [(1, 2)] * 8      # C2.. stays on the upper staff
    assert score.parts[0].clefs == ["G", "F"] and score.clefs == {(2, 0): "F"}
    xml = mx.to_musicxml(score)
    assert xml.count('<clef number="1"><sign>F</sign><line>4</line></clef>') == 1 and xml.count("<clef number") == 3
    four = mx.prelude_score(prelude)                             # the proofreading sheet: fixed clefs, staff by pitch as before
    assert four.clefs == {} and "<clef-octave-change>" not in mx.to_musicxml(four) and mx.to_musicxml(four).count("<clef number") == 4


def test_a_note_without_printed_staff_follows_the_lines_around_it():
    notes = []
    for k in range(12):
        notes.append({"onset": 0.5 * k, "dur": 0.5, "step": 120 + 2 * (k % 4), "piano": 1, "bar": 1 + k // 4, "staff": "upper"})
        notes.append({"onset": 0.5 * k, "dur": 0.5, "step": 71 + 2 * (k % 3), "piano": 2, "bar": 1 + k // 4, "staff": "lower"})
    for n in notes:
        if n["bar"] == 2:
            del n["staff"]                                       # a bar typed in by hand
    prelude = {"number": 1, "bars": 3, "time": "2/4", "tempi": [{"onset": 0.0, "bpm_quarter": 60.0}], "notes": notes}
    assert mx.prelude_hands(prelude)[1] == [1, 0] * 12


def test_tempo_map_of_a_prelude():
    seconds = mx.prelude_seconds({"tempi": [{"onset": 0.0, "bpm_quarter": 120.0}, {"onset": 4.0, "bpm_quarter": 60.0}, {"onset": 4.0, "bpm_quarter": 30.0}]})
    assert [seconds(q) for q in (0, 2, 4, 5)] == [0.0, 1.0, 2.0, 4.0]      # of two marks at one place the last counts
    assert mx.prelude_seconds({})(4) == 3.0                                # none: 80 to the minute


# ---- the real preludes, if they are there

def test_real_preludes_keep_every_printed_staff_in_library_and_sheet():
    import json
    path = mx.MUSIC / "wyschnegradsky" / "preludes.json"
    if not path.exists():
        import pytest
        pytest.skip("reference/music/wyschnegradsky/preludes.json is not there")
    from tutor import library_build
    preludes = json.loads(path.read_text(encoding="utf-8"))
    pieces = list(library_build.wyschnegradsky(path))
    assert len(pieces) == len(preludes)
    for prelude, piece in zip(preludes, pieces):
        notes, staves = mx.prelude_hands(prelude)
        assert all(staff == {"upper": 0, "lower": 1}[n["staff"]] for n, staff in zip(notes, staves) if n.get("staff")), prelude["number"]
        # the sheet for one player and the library hold the same division: steps per staff
        score = mx.prelude_score(prelude, updown=True)
        sheet = [sum(len(e.notes) for e in score.events if e.staff == s) for s in (0, 1)]
        total = score.bars[-1].start + score.bars[-1].length
        used, per_staff = set(), [0, 0]
        for n, staff in zip(notes, staves):                      # as the sheet counts: one note per length and step at a moment
            key = (staff, n["onset"], n["dur"], n["step"])
            if n["onset"] < total and key not in used:
                used.add(key)
                per_staff[staff] += 1
        assert sheet == per_staff, prelude["number"]
        library = [sum(len(steps) for bar in piece["score"] for _, _, steps in bar["staves"][name]) for name in ("upper", "lower")]
        want = [len({(n["bar"], n["onset"], n["step"]) for n, staff in zip(notes, staves) if staff == s}) for s in (0, 1)]
        assert library == want, prelude["number"]
        hands = piece["two_hands"]
        assert hands["fits"] == (not hands["tight_bars"]) and set(hands["four_hand_bars"]) <= set(hands["tight_bars"])
        assert all(1 <= b <= piece["bars"] for b in hands["tight_bars"] + hands["pedal_bars"])
