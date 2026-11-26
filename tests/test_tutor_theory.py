"""Tutor theory (host/tutor/theory.py): note names, intervals, chords and scales come out
right in 12, 31 and 53 equal steps per octave. Expected values are standard music theory
and ups-and-downs notation, not copies of the code's output."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
from tutor.theory import CHORDS, TheoryError, Tuning  # noqa: E402


@pytest.fixture(scope="module")
def t12():
    return Tuning(12)


@pytest.fixture(scope="module")
def t31():
    return Tuning(31)


@pytest.fixture(scope="module")
def t53():
    return Tuning(53)


def chord(t: Tuning, root: str, quality: str, inversion: int = 0):
    return t.chord(t.parse(root)[0], quality, inversion, root)


def test_pitch_numbering_matches_xentool(t12, t31, t53):
    # xentool: pitch 0 = C0 = 16.3516 Hz, an octave is `edo` steps
    for t in (t12, t31, t53):
        assert t.parse("C0") == (0, True)
        assert t.parse("C4") == (4 * t.edo, True)
        assert t.hz(0) == pytest.approx(16.3516, abs=1e-4)
    assert t12.hz(t12.parse("A4")[0]) == pytest.approx(440.0, abs=0.01)
    assert t31.parse("C") == (4 * 31, False)        # no octave: octave 4, flagged
    # Cb belongs to the octave of its letter: just below C4
    assert t31.parse("Cb4")[0] == 4 * 31 - 2


def test_note_names_round_trip_and_are_plain(t12, t31, t53):
    for t in (t12, t31, t53):
        for pitch in range(3 * t.edo, 5 * t.edo):
            name = t.name(pitch)
            assert t.parse(name)[0] == pitch, name
            for s in t.spellings(pitch):
                assert t.parse(s)[0] == pitch, s
    assert [t12.name(48 + i) for i in range(12)] == ["C4", "C#4", "D4", "D#4", "E4", "F4", "F#4", "G4", "G#4", "A4", "A#4", "B4"]
    # 31: sharps and flats are different notes; single steps are written with ^ and v
    assert t31.name(124 + 1) == "^C4" and t31.name(124 + 2) == "C#4" and t31.name(124 + 3) == "Db4"
    assert t31.parse("E4")[0] != t31.parse("Fb4")[0]
    # 53: nine steps to the whole tone
    assert t53.parse("D4")[0] - t53.parse("C4")[0] == 9
    assert t53.name(212 + 17) == "vE4"


def test_notes_by_number(t12, t31, t53):
    # the number of a note is its step within the octave, C = 0; players of large tunings use it
    assert t53.number(t53.parse("vE4")[0]) == 17 and t53.number(t53.parse("G2")[0]) == 31
    assert t12.number(t12.parse("A4")[0]) == 9
    assert t53.label(t53.parse("vE4")[0]) == "vE4 (17)"
    assert t53.label(t53.parse("C4")[0] + 14, "^Eb4") == "^Eb4 (14)"
    # a number is accepted wherever a name is: alone (octave 4, flagged), or with its octave
    assert t53.parse("17") == (4 * 53 + 17, False)
    assert t53.parse("17(3)") == (3 * 53 + 17, True) == t53.parse(" 17 ( 3 ) ")
    assert t53.parse("0(4)") == t53.parse("C4")
    # and the way the tools write a note is read back
    assert t53.parse("vE4 (17)") == t53.parse("vE4")
    assert t31.parse("Eb (8)") == t31.parse("Eb")
    for t in (t12, t31, t53):
        for pitch in range(2 * t.edo, 4 * t.edo):
            assert t.parse(t.label(pitch))[0] == pitch
            assert t.parse(f"{t.number(pitch)}({pitch // t.edo})") == (pitch, True)
    with pytest.raises(TheoryError, match="numbers its notes 0 to 52"):
        t53.parse("53")
    assert t53.letter_of("^^Gb4") == "G" and t53.letter_of("17(4)") is None


def test_note_input_is_forgiving_and_errors_explain(t31):
    assert t31.parse("e♭4") == t31.parse("Eb4")
    assert t31.parse(" F♯3 ")[0] == t31.parse("F#3")[0]
    with pytest.raises(TheoryError, match="is not a note. Write a name .* or a number"):
        t31.parse("H4")
    with pytest.raises(TheoryError, match="5 to 72"):
        Tuning(200)
    assert Tuning(12).parse_safe("^C4") is None     # no ups and downs in 12


@pytest.mark.parametrize("root,quality,notes", [
    ("C4", "major", ["C4", "E4", "G4"]),
    ("C4", "minor", ["C4", "Eb4", "G4"]),
    ("C4", "diminished", ["C4", "Eb4", "Gb4"]),
    ("C4", "augmented", ["C4", "E4", "G#4"]),
    ("C4", "sus4", ["C4", "F4", "G4"]),
    ("C4", "sus2", ["C4", "D4", "G4"]),
    ("C4", "dominant7", ["C4", "E4", "G4", "Bb4"]),
    ("C4", "major7", ["C4", "E4", "G4", "B4"]),
    ("A3", "minor7", ["A3", "C4", "E4", "G4"]),
    ("B3", "half-diminished7", ["B3", "D4", "F4", "A4"]),
    ("Eb4", "major", ["Eb4", "G4", "Bb4"]),
    ("F#3", "minor", ["F#3", "A3", "C#4"]),
    ("Db4", "major", ["Db4", "F4", "Ab4"]),
])
def test_ordinary_chords_are_spelled_the_same_in_12_and_31(t12, t31, root, quality, notes):
    # 31 is a meantone tuning: common-practice spelling holds unchanged
    assert list(chord(t12, root, quality).names) == notes
    assert list(chord(t31, root, quality).names) == notes


def test_53_uses_the_pure_thirds(t53):
    # 5/4 is 17 steps (one below E), 6/5 is 14 (one above Eb): ups-and-downs spelling
    assert list(chord(t53, "C4", "major").names) == ["C4", "vE4", "G4"]
    assert list(chord(t53, "C4", "minor").names) == ["C4", "^Eb4", "G4"]
    assert chord(t53, "C4", "major").intervals == ("P1", "vM3", "P5")
    assert list(chord(t53, "F4", "major").names) == ["F4", "vA4", "C5"]
    assert list(chord(t53, "A3", "minor").names) == ["A3", "^C4", "E4"]
    # every tone within 2 cents of pure, and the text says so
    assert all("-1 cents" in p or "+1 cents" in p or "0 cents" in p for p in chord(t53, "C4", "major").purity)


def test_chord_sizes_are_the_nearest_to_pure(t12, t31, t53):
    for t in (t12, t31, t53):
        major = chord(t, "C4", "major").pitches
        steps = [p - major[0] for p in major]
        assert abs(t.cents_of(steps[1]) - 386.31) <= 600 / t.edo
        assert abs(t.cents_of(steps[2]) - 701.96) <= 600 / t.edo
    assert [p - 124 for p in chord(t31, "C4", "major").pitches] == [0, 10, 18]
    assert [p - 212 for p in chord(t53, "C4", "major").pitches] == [0, 17, 31]


def test_inversions(t31):
    assert list(chord(t31, "C4", "major", 1).names) == ["E4", "G4", "C5"]
    assert list(chord(t31, "C4", "major", 2).names) == ["G4", "C5", "E5"]
    assert chord(t31, "C4", "major", 1).label == "C major, 1st inversion"
    assert chord(t31, "C4", "major", 1).intervals == ("P1", "m3", "m6")
    assert list(chord(t31, "C4", "dominant7", 3).names) == ["Bb4", "C5", "E5", "G5"]
    with pytest.raises(TheoryError, match="inversions 0 to 2"):
        chord(t31, "C4", "major", 3)


def test_qualities_beyond_12_tone(t12, t31, t53):
    assert not any(CHORDS[q].get("xen") for q in t12.qualities())
    with pytest.raises(TheoryError, match="no subminor chord of its own"):
        chord(t12, "C4", "subminor")
    for t in (t31, t53):
        assert {"subminor", "supermajor", "neutral", "harmonic7"} <= set(t.qualities())
    assert list(chord(t31, "C4", "subminor").names) == ["C4", "vEb4", "G4"]
    assert list(chord(t31, "C4", "neutral").names) == ["C4", "vE4", "G4"]
    assert list(chord(t31, "C4", "harmonic7").names) == ["C4", "E4", "G4", "vBb4"]
    # 7/4 in 31: 25 steps, about 968 cents
    assert t31.cents_of(chord(t31, "C4", "harmonic7").pitches[3] - 124) == pytest.approx(968, abs=1.5)


def test_quality_names_are_forgiving(t31):
    for text, want in [("maj", "major"), ("Minor", "minor"), ("m7", "minor7"), ("7", "dominant7"),
                       ("dominant seventh", "dominant7"), ("half diminished7", "half-diminished7"), ("dim", "diminished")]:
        assert t31.quality_key(text) == want
    with pytest.raises(TheoryError, match="Available: major"):
        t31.quality_key("jazzy")


def test_interval_names(t12, t31, t53):
    assert [t12.interval(s) for s in (0, 3, 4, 7, 10, 12)] == ["P1", "m3", "M3", "P5", "m7", "P8"]
    assert [t31.interval(s) for s in (8, 10, 18, 26, 31)] == ["m3", "M3", "P5", "m7", "P8"]
    assert t31.interval(7) == "vm3" and t31.interval(25) == "vm7"
    assert t53.interval(17) == "vM3" and t53.interval(14) == "^m3" and t53.interval(31) == "P5"
    assert t53.interval_words(17) == "downmajor third (vM3, 17 steps)"
    assert t31.interval_words(18) == "perfect fifth (P5, 18 steps)"
    assert t31.interval_words(1) == "up unison (^1, 1 step)"
    # a name that follows from a chord's spelling can be given
    assert t31.interval_words(7, "A2") == "augmented second (A2, 7 steps)"
    assert t31.words("P8") == "octave" and t31.words("-M2") == "major second down"
    # named after the spelling: C up to D# is a second, C up to Eb a third
    assert t31.interval_between("C4", "Eb4") == "m3"
    assert t31.interval_between("C4", "D#4") == "A2"
    assert t31.interval_between("E4", "C4") == "-M3"


def test_scales_and_their_chords(t12, t31, t53):
    for t in (t12, t31, t53):
        c = t.parse("C4")[0]
        assert [n for _, n in t.scale(c, "major", "C4")] == ["C4", "D4", "E4", "F4", "G4", "A4", "B4"]
        assert [n for _, n in t.scale(t.parse("Eb4")[0], "major", "Eb4")] == ["Eb4", "F4", "G4", "Ab4", "Bb4", "C5", "D5"]
        assert [n for _, n in t.scale(t.parse("A3")[0], "minor", "A3")] == ["A3", "B3", "C4", "D4", "E4", "F4", "G4"]
        assert [n for _, n in t.scale(t.parse("D4")[0], "dorian", "D4")] == ["D4", "E4", "F4", "G4", "A4", "B4", "C5"]
        degrees = t.diatonic_chords(c, "major")
        assert [d["numeral"] for d in degrees] == ["I", "ii", "iii", "IV", "V", "vi", "vii°"]
        assert [d["quality"] for d in degrees] == ["major", "minor", "minor", "major", "major", "minor", "diminished"]
        sevenths = t.diatonic_chords(c, "major", sevenths=True)
        assert [d["quality"] for d in sevenths] == ["major7", "minor7", "minor7", "major7", "dominant7", "minor7", "half-diminished7"]
    with pytest.raises(TheoryError, match="unknown scale"):
        t31.scale(124, "bebop")


def test_progressions(t31, t53):
    c = t31.parse("C4")[0]
    prog = t31.progression(c, "major", ["I", "IV", "V7", "vi"], "C4")
    assert [p.label for p in prog] == ["C major", "F major", "G dominant7", "A minor"]
    assert list(prog[2].names) == ["G4", "B4", "D5", "F5"]
    # a numeral against the key's own chord is taken at its word
    assert t31.progression(c, "major", ["II", "iv"], "C4")[0].label == "D major"
    assert t31.progression(c, "major", ["II", "iv"], "C4")[1].label == "F minor"
    assert t31.progression(c, "minor", ["i", "iv", "V"], "C4")[2].label == "G major"
    # 53: the roots follow the scale, each chord gets its pure third
    prog = t53.progression(t53.parse("C4")[0], "major", ["I", "IV", "V"], "C4")
    assert [list(p.names) for p in prog] == [["C4", "vE4", "G4"], ["F4", "vA4", "C5"], ["G4", "vB4", "D5"]]
    with pytest.raises(TheoryError, match="not a Roman numeral"):
        t31.progression(c, "major", ["one"], "C4")


def test_tuning_description(t12, t31, t53):
    d = t31.describe()
    assert d["steps_per_octave"] == 31
    assert d["fifth"]["from_pure_cents"] == pytest.approx(-5.2, abs=0.1)
    assert [x["kind"] for x in d["thirds"]] == ["subminor", "minor", "neutral", "major", "supermajor"]
    assert [x["steps"] for x in d["thirds"]] == [7, 8, 9, 10, 11] and d["fifth"]["steps"] == 18
    assert next(x for x in d["thirds"] if x["kind"] == "major")["from_pure_cents"] == pytest.approx(0.8, abs=0.1)
    assert any("different notes" in n for n in d["notes"])
    assert [x["kind"] for x in t12.describe()["thirds"]] == ["minor", "major"]
    assert t12.describe()["beyond_12_tone"] == {} and t12.describe()["notes"] == []
    assert any("vE, not E" in n for n in t53.describe()["notes"])
