"""Score reader for MuseScore PDFs (host/tutor/scores/musescore_pdf.py).

The pure parts are checked against music notation itself (which line of which clef is
which note, how long a dotted eighth is), and the reader as a whole against a small page
made up here: one staff, two bars in 3/4 with a key signature of one sharp. The real PDF
is third-party material outside the repository and is only read if it is there."""
from __future__ import annotations

import sys
from fractions import Fraction as F
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
from tutor.scores import musescore_pdf as mp  # noqa: E402

REAL_PDF = Path(r"C:\Users\tobia\Desktop\Microtonal\Don't Take Five (Woyten) 16edo.pdf")
LINES = [100.0, 104.0, 108.0, 112.0, 116.0]          # a staff, top line first, 4 units per space


# ---- staff position and pitch

def test_staff_position_counts_lines_and_spaces_from_the_bottom_line():
    assert mp.staff_position(116.0, LINES) == 0       # bottom line
    assert mp.staff_position(114.0, LINES) == 1       # first space
    assert mp.staff_position(100.0, LINES) == 8       # top line
    assert mp.staff_position(108.2, LINES) == 4       # a little off the middle line
    assert mp.staff_position(120.0, LINES) == -2      # first ledger line below
    assert mp.staff_position(92.0, LINES) == 12       # second ledger line above
    assert mp.staff_position(100.0, list(reversed(LINES))) == 8


def test_position_error_is_large_between_two_positions():
    assert mp.position_error(108.0, LINES) == pytest.approx(0)
    assert mp.position_error(109.0, LINES) == pytest.approx(0.5)


def test_pitch_at_follows_the_clef():
    assert mp.pitch_at(0, "treble") == ("E", 4)
    assert mp.pitch_at(-2, "treble") == ("C", 4)      # middle C on its ledger line
    assert mp.pitch_at(8, "treble") == ("F", 5)
    assert mp.pitch_at(0, "bass") == ("G", 2)
    assert mp.pitch_at(10, "bass") == ("C", 4)        # middle C above the bass staff
    assert mp.pitch_at(4, "alto") == ("C", 4)
    assert mp.pitch_at(-3, "bass") == ("D", 2)


# ---- durations

def test_duration_from_notehead_beams_and_dots():
    assert mp.note_duration("whole") == 4
    assert mp.note_duration("half") == 2
    assert mp.note_duration("black") == 1
    assert mp.note_duration("black", 1) == F(1, 2)
    assert mp.note_duration("black", 2) == F(1, 4)
    assert mp.note_duration("black", 0, dots=1) == F(3, 2)
    assert mp.note_duration("half", 0, dots=1) == 3
    assert mp.note_duration("black", 1, dots=2) == F(7, 8)
    with pytest.raises(ValueError):
        mp.note_duration("diamond")


def test_beams_are_counted_where_the_stem_meets_them():
    long_beam = [(10.0, 50.0), (10.0, 48.0), (40.0, 46.0), (40.0, 48.0)]
    stub = [(34.0, 52.6), (34.0, 50.6), (40.0, 50.2), (40.0, 52.2)]       # second beam of a sixteenth
    pedal = [(10.0, 90.0), (10.0, 88.0), (40.0, 88.0), (40.0, 90.0)]      # far below the stem
    quads = [long_beam, stub, pedal]
    assert mp.beams_at(10.2, 49.0, 70.0, quads) == [0]
    assert mp.beams_at(40.2, 47.0, 66.0, quads) == [0, 1]
    assert mp.beams_at(60.0, 47.0, 66.0, quads) == []


def test_bar_sums():
    events = [{"dur": 2}, {"dur": 0.5}, {"dur": 0.5}]
    assert mp.bar_length((3, 4)) == 3 and mp.bar_length((6, 8)) == 3 and mp.bar_length((3, 8)) == F(3, 2)
    assert mp.bar_adds_up(events, (3, 4))
    assert not mp.bar_adds_up(events, (4, 4))
    assert not mp.bar_adds_up([], (3, 4))
    two = events + [{"dur": 1.5, "voice": 2}, {"dur": 1.5, "voice": 2}]
    assert mp.voice_sums(two) == {1: 3, 2: 3}
    assert mp.bar_adds_up(two, (6, 8))
    assert not mp.bar_adds_up(two + [{"dur": 1, "voice": 2}], (6, 8))
    assert mp.bar_adds_up(events + [{"dur": 0, "grace": True}], (3, 4))


def ev(x, dur, stem=1, rest=False, y=100.0, **more):
    return dict({"x": x, "dur": F(dur), "stem": stem, "rest": rest, "y": y}, **more)


def test_one_voice_when_the_bar_fills_up_in_order():
    events, ok = mp.split_voices([ev(0, 1, 1), ev(10, 1, -1), ev(20, 1, 1)], F(3))
    assert ok and [e["voice"] for e in events] == [1, 1, 1]
    assert [e["beat"] for e in events] == [1, 2, 3]


def test_two_voices_by_stem_direction_and_rests_where_they_fit():
    # 6/8: eighth rest + two eighths, twice (stems up) over two dotted quarters (stems down)
    events = [ev(0, F(1, 2), 0, True, 95), ev(0.4, F(3, 2), -1), ev(10, F(1, 2)), ev(20, F(1, 2)),
              ev(30, F(1, 2), 0, True, 95), ev(30.4, F(3, 2), -1), ev(40, F(1, 2)), ev(50, F(1, 2))]
    events, ok = mp.split_voices(events, F(3))
    assert ok
    assert [e["voice"] for e in events] == [1, 2, 1, 1, 1, 2, 1, 1]
    assert [e["beat"] for e in events if e["voice"] == 2] == [1, F(5, 2)]
    assert [e["beat"] for e in events if e["voice"] == 1] == [1, F(3, 2), 2, F(5, 2), 3, F(7, 2)]


def test_a_rest_goes_to_the_second_voice_if_only_that_adds_up():
    # eighth rest, quarter, quarter, eighth above a half note and a quarter rest
    events = [ev(0, F(1, 2), 0, True, 90), ev(0.3, 2, -1), ev(10, 1), ev(20, 1), ev(30, 1, 0, True, 120), ev(40, F(1, 2))]
    events, ok = mp.split_voices(events, F(3))
    assert ok and [e["voice"] for e in events] == [1, 2, 1, 1, 2, 1]


def test_whole_rest_fills_any_bar_and_wrong_bars_are_reported():
    events, ok = mp.split_voices([ev(0, 4, 0, True, bar_rest=True)], F(3, 2))
    assert ok and events[0]["dur"] == F(3, 2)
    events, ok = mp.split_voices([ev(0, 1), ev(10, 1)], F(3))
    assert not ok and [e["beat"] for e in events] == [1, 2]


# ---- accidentals and tunings

def test_accidental_names_keep_unknown_code_points():
    assert mp.accidental_name(0xE262) == "sharp"
    assert mp.accidental_name(0xE274) == "sharp-arrow-up"
    assert mp.accidental_name(0xE275) == "sharp-arrow-down"
    assert mp.accidental_name(0xE2C5) == "U+E2C5"
    assert "E2C5" in mp.accidental_suffix(0xE2C5)


def test_plain_step_table():
    edo31 = mp.Notation(31, dict(zip("CDEFGAB", (0, 5, 10, 13, 18, 23, 28))), {0xE262: 2, 0xE260: -2, 0xE282: 1})
    assert edo31.step("C", 0) == (0, "")
    assert edo31.step("A", 4, (0xE262,)) == (4 * 31 + 25, "")
    assert edo31.step("E", 3, (0xE282,)) == (3 * 31 + 11, "")
    step, problem = edo31.step("E", 3, (0xE2C5,))
    assert step is None and "not in the table" in problem


def test_weigel_16_puts_every_third_spelling_on_a_step():
    n = mp.WEIGEL_16
    sharp, up, down, sharp_up, sharp_down, half_flat, half_sharp = 0xE262, 0xE272, 0xE273, 0xE274, 0xE275, 0xE280, 0xE282
    # the four notes 16 and 12 equal steps share, 4 steps (300 cents) apart
    assert [n.step(*x)[0] for x in (("D", 4), ("F", 4), ("G", 4, (sharp,)), ("B", 4))] == [67, 71, 75, 79]
    # one octave upwards from B3 in single steps, as the piece spells them
    scale = [("B", 3), ("C", 4, (down,)), ("C", 4, (half_sharp,)), ("C", 4, (sharp_up,)), ("D", 4),
             ("D", 4, (sharp_down,)), ("E", 4, (half_flat,)), ("E", 4, (up,)), ("F", 4),
             ("F", 4, (sharp_down,)), ("G", 4, (half_flat,)), ("G", 4, (up,)), ("G", 4, (sharp,)),
             ("A", 4, (down,)), ("A", 4, (half_sharp,)), ("A", 4, (sharp_up,)), ("B", 4)]
    steps = [n.step(*x) for x in scale]
    assert [s for s, _ in steps] == list(range(63, 80)) and not any(problem for _, problem in steps)
    # enharmonic spellings found in the piece
    assert n.step("C", 4, (0xE263,)) == n.step("D", 4)                    # C double sharp
    assert n.step("B", 3, (0xE270,)) == n.step("A", 3, (sharp_up,))       # B flat with arrow up
    assert n.step("B", 3, (0xE281,)) == n.step("A", 3, (half_sharp,))     # B sesquiflat
    assert n.step("F", 4, (0xE283,)) == n.step("G", 4, (half_flat,))      # F sesquisharp
    assert n.step("B", 4, (sharp_down,)) == n.step("C", 5, (down,))
    # a spelling between two steps is reported, with the nearest step
    step, problem = n.step("C", 4)
    assert step == 64 and "not a whole step" in problem
    assert n.step("C", 6, (sharp_down,))[1]


def test_notation_from_cents_for_quarter_tones():
    n = mp.notation_from_cents(24, {0xE262: 100, 0xE282: 50})
    assert n.step("A", 4) == (4 * 24 + 18, "")
    assert n.step("A", 4, (0xE282,)) == (4 * 24 + 19, "")


def test_key_signature_is_the_run_of_accidentals_after_the_clef():
    assert mp.key_signature_run(50.0, [61.0, 66.0, 71.0, 120.0], 4.0) == (61.0, 71.0)
    assert mp.key_signature_run(50.0, [90.0, 120.0], 4.0) == (0.0, -1.0)      # accidentals of notes
    assert mp.key_signature_run(50.0, [], 4.0) == (0.0, -1.0)


def test_heading():
    h = mp.parse_heading("Some Piece (A. Composer) 16-TET - transcribed by B. Scribe")
    assert h == {"title": "Some Piece", "composer": "A. Composer", "transcriber": "B. Scribe",
                 "tuning": "16-TET", "edo": 16}
    assert mp.parse_heading("Just a Title") == {"title": "Just a Title"}


# ---- layout and the whole reader on a made-up page

def test_staves_and_systems_from_lines():
    hlines = [(y, 50.0, 300.0) for y in LINES] + [(y + 40, 50.0, 300.0) for y in LINES]
    hlines += [(120.0, 88.0, 97.0), (200.0, 50.0, 300.0)]          # a ledger line, a stray long line
    staves = mp.find_staves(hlines)
    assert [s.top for s in staves] == [100.0, 140.0] and staves[0].space == 4.0
    assert staves[0].distance(98.0) == 2.0 and staves[0].distance(110.0) == 0.0
    assert [len(s) for s in mp.group_systems(staves, [(50.0, 100.0, 156.0)])] == [2]
    assert [len(s) for s in mp.group_systems(staves, [(50.0, 100.0, 116.0), (50.0, 140.0, 156.0)])] == [1, 1]


def synthetic_page() -> mp.PageData:
    """One staff, 3/4, key signature F sharp. Bar 1: half note E4, two beamed eighths F4
    (sharp by the key) and G4. Bar 2: quarter rest, dotted quarter B4 with an arrow-up
    natural (stem down), eighth B4 with a flag (the accidental still holds)."""
    w, size = 5.2, 20.0
    g = mp.Glyph
    page = mp.PageData()
    page.hlines = [(y, 50.0, 300.0) for y in LINES]
    page.vlines = [(50.0, 100.0, 116.0), (180.0, 100.0, 116.0), (300.0, 100.0, 116.0)]      # bar lines
    page.glyphs = [
        g(0xE050, 53.0, 112.0, size, 10.0),                                   # treble clef
        g(0xE262, 64.0, 100.0, size, 4.0),                                    # key signature: F sharp
        g(0xE083, 75.0, 104.0, size, 7.0), g(0xE084, 75.0, 112.0, size, 7.0),   # 3/4
        g(0xE0A3, 90.0, 116.0, size, w),                                      # half note E4
        g(0xE0A4, 120.0, 114.0, size, w), g(0xE0A4, 140.0, 112.0, size, w),   # F4, G4
        g(0xE4E5, 190.0, 108.0, size, 5.0),                                   # quarter rest
        g(0xE272, 208.0, 108.0, size, 4.0), g(0xE0A4, 215.0, 108.0, size, w), g(0xE1E7, 222.5, 106.0, size, 2.0),
        g(0xE0A4, 250.0, 108.0, size, w), g(0xE240, 255.2, 94.0, size, 5.0),  # eighth with a flag
    ]
    page.vlines += [(95.2, 102.0, 115.5), (125.2, 100.0, 113.5), (145.2, 98.0, 111.5),      # stems up
                    (215.0, 108.8, 122.0), (255.2, 94.0, 107.5)]                             # down, up
    page.quads = [[(125.0, 101.5), (125.0, 100.0), (145.4, 98.0), (145.4, 99.5)]]          # the beam
    return page


def test_reader_on_a_made_up_page():
    quarter_tones = mp.Notation(24, dict(zip("CDEFGAB", (0, 4, 8, 10, 14, 18, 22))), {0xE262: 2, 0xE272: 1})
    reader = mp.ScoreReader(quarter_tones)
    reader.add_page(synthetic_page())
    score = reader.result(title="made up")
    assert [b["n"] for b in score["bars"]] == [1, 2]
    assert all(b["time"] == "3/4" and b["adds_up"] for b in score["bars"])
    assert score["uncertain"] == []
    first, second = (b["staves"]["upper"] for b in score["bars"])
    assert [(e["beat"], e["dur"]) for e in first] == [(1, 2), (3, 0.5), (3.5, 0.5)]
    assert [[(n["name"], n["step"]) for n in e["notes"]] for e in first] == [
        [("E4", 104)], [("F#4", 108)], [("G4", 110)]]
    assert first[1]["notes"][0]["accidental"] == "sharp" and "printed" not in first[1]["notes"][0]
    assert [(e["beat"], e["dur"], e.get("rest", False)) for e in second] == [(1, 1, True), (2, 1.5, False), (3.5, 0.5, False)]
    assert [n["name"] for e in second for n in e["notes"]] == ["B^4", "B^4"]
    assert [n["step"] for e in second for n in e["notes"]] == [119, 119]
    assert second[1]["notes"][0].get("printed") and not second[2]["notes"][0].get("printed")
    assert score["counts"][0]["noteheads"] == score["counts"][0]["read_noteheads"] == 5
    assert score["counts"][0]["accidentals"] == score["counts"][0]["read_accidentals"] == 2
    assert mp.summary(score)["bars_not_adding_up"] == []


def test_reader_reports_what_does_not_fit():
    page = synthetic_page()
    page.glyphs = [x for x in page.glyphs if x.cp != 0xE1E7]          # the dot is gone: bar 2 is short
    reader = mp.ScoreReader(mp.Notation(12, dict(zip("CDEFGAB", (0, 2, 4, 5, 7, 9, 11))), {0xE262: 1}))
    reader.add_page(page)
    score = reader.result()
    assert [b["adds_up"] for b in score["bars"]] == [True, False]
    what = " | ".join(u["what"] for u in score["uncertain"])
    assert "do not fill the bar" in what and "natural-arrow-up is not in the table" in what
    assert score["bars"][1]["staves"]["upper"][1]["notes"][0]["step"] is None


# ---- the real score, if it is on this machine

@pytest.mark.skipif(not REAL_PDF.exists(), reason="the PDF is private reference material")
def test_real_pdf():
    pytest.importorskip("pymupdf")
    score = mp.read_pdf(REAL_PDF)
    bars = score["bars"]
    assert len(bars) == 117
    assert score["tuning"]["edo"] == 16
    assert sum(b["adds_up"] for b in bars) >= 0.95 * len(bars)
    for b in bars:                      # the stored flag is what the pure check says
        fits = all(mp.bar_adds_up(ev, tuple(map(int, b["time"].split("/")))) for ev in b["staves"].values())
        assert fits == b["adds_up"]
    assert score["checks"]["printed_bar_numbers_matching"] == score["checks"]["printed_bar_numbers"] > 20
    for c in score["counts"]:           # every notehead and accidental of the PDF is in the output
        assert c["noteheads"] == c["read_noteheads"] and c["accidentals"] == c["read_accidentals"]
        assert c["rests"] == c["read_rests"]
    notes = [n for b in bars for ev in b["staves"].values() for e in ev for n in e["notes"]]
    off = [u for u in score["uncertain"] if "not a whole step" in u["what"]]
    assert len(notes) > 1000 and len(off) <= 0.01 * len(notes)
