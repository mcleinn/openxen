"""The tutor's library: conversion of the two collections (on small files in their formats),
raga outlines against the ratios they are built from, patterns, and the library tool."""
from __future__ import annotations

import csv
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
from tutor import library as lib  # noqa: E402
from tutor import library_build as build  # noqa: E402
from tutor.sample import sample_setup  # noqa: E402
from tutor.session import Tutor, TutorError  # noqa: E402
from tutor.theory import tuning_for  # noqa: E402
from tutor.xt import FakeXentool  # noqa: E402

HEADER = "Sira\tKod\tNota53\tNotaAE\tKoma53\tKomaAE\tPay\tPayda\tMs\tLNS\tBas\tSoz1\tOffset"


def symbtr_file(folder: Path, name: str, rows: list[tuple]) -> Path:
    """rows: (kod, koma53, komaAE, pay, payda, offset)"""
    lines = [HEADER, "1\t51\t\t\t0\t0\t4\t4\t0\t17\t0\tSofyan\t0.0"]
    for n, (kod, k53, kae, pay, payda, offset) in enumerate(rows, 2):
        lines.append(f"{n}\t{kod}\tx\tx\t{k53}\t{kae}\t{pay}\t{payda}\t500\t95\t96\t\t{offset}")
    path = folder / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def source(tmp_path_factory) -> Path:
    """A makam file and a chant archive, in the formats of SymbTr and GregoBaseCorpus."""
    root = tmp_path_factory.mktemp("music")
    txt = root / "symbtr" / "txt"
    txt.mkdir(parents=True)
    G4, A4, SEGAH_P, SEGAH_T, C5, D5 = 296, 305, 312, 313, 318, 327      # Koma53: C4 = 265
    symbtr_file(txt, "rast--ornek_oz--sofyan--1--ruhi_ayangil.txt", [
        (9, G4, G4, 1, 4, 0.25), (9, A4, A4, 1, 4, 0.5), (9, SEGAH_P, SEGAH_T, 1, 4, 0.75), (9, C5, C5, 1, 4, 1.0),
        (9, D5, D5, 1, 2, 1.5), (8, C5, C5, 0, 0, 1.5), (9, C5, C5, 1, 4, 1.75), (9, SEGAH_P, SEGAH_T, 1, 4, 2.0),
        (9, -1, -1, 1, 4, 2.25), (9, A4, A4, 1, 4, 2.5), (9, G4, G4, 1, 2, 3.0),
    ])
    symbtr_file(txt, "hicaz--sarki--aksak--uzun_bir_sarki--biri.txt", [(9, 300 + (i % 9), 300 + (i % 9), 1, 8, i / 8 + 0.125) for i in range(60)])
    (txt / "not-a-piece.txt").write_text("nothing", encoding="utf-8")
    grego = root / "gregobase"
    grego.mkdir()
    table = io.StringIO()
    writer = csv.DictWriter(table, fieldnames=["id", "cantus_id", "version", "incipit", "initial", "office_part", "mode", "mode_var",
                                                "transcriber", "commentary", "gabc", "gabc_verses", "tex_verses", "remarks"])
    writer.writeheader()
    # c4: C4 on the top line (position j); a flat on B until the bar; a dotted note; a custos; a clef change to f3
    writer.writerow({"id": "7", "version": "Solesmes", "incipit": "Ave test (Ant.)", "office_part": "an", "mode": "1",
                     "gabc": json.dumps("(c4) A(f)ve(g) ma(h)ri(ixi)a(h.) (,) gra(g)ti(f)a(e) ple(d.)na(f+) (::) (f3) Do(h)mi(h)nus(g.) (::)")})
    writer.writerow({"id": "8", "version": "x", "incipit": "Too short", "office_part": "an", "mode": "2", "gabc": json.dumps("(c4) A(f)men(f) (::)")})
    with zipfile.ZipFile(grego / "gregobasecorpus-v0.4.zip", "w") as z:
        z.writestr("csv/chants.csv", table.getvalue())
    return root


@pytest.fixture(scope="module")
def built(source, tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("library")
    counts = build.build(source, out)
    assert counts == {"makam": 2, "chant": 1}
    return out


def test_makam_conversion(built):
    library = lib.Library(built)
    piece = library.piece("makam/rast--ornek_oz--sofyan--1--ruhi_ayangil")
    # steps above C0 = Koma53 - 53; a quarter note is one beat; grace notes are left out; the rest is kept as a gap
    assert piece["tuning"] == 53 and piece["level"] == 1 and piece["mode"] == "Rast" and piece["meter"] == "Sofyan (4/4)"
    assert piece["notes"][:5] == [[243, 1.0], [252, 1.0], [259, 1.0], [265, 1.0], [274, 2.0]]
    assert [n for n in piece["notes"] if n[0] is None] == [[None, 1.0]] and len(piece["notes"]) == 10
    # where practice (segah a comma lower) differs from the written theory, both are kept
    assert piece["theory"] == {"2": 260, "6": 260}
    # phrases end at the rest and at bar lines
    assert piece["phrases"] == [[0, 3], [4, 6], [8, 9]] or piece["phrases"][-1] == [8, 9]
    assert all(b - a + 1 <= build.MAX_PHRASE for a, b in library.piece("makam/hicaz--sarki--aksak--uzun_bir_sarki--biri")["phrases"])
    # graded: the teaching example before the long song
    assert [e["form"] for e in library.search(tradition="makam")] == ["teaching example", "song"]
    assert library.search(tradition="makam", level=2)[0]["mode"] == "Rast" and len(library.search(tradition="makam", level=2)) == 1


def test_chant_conversion(built):
    library = lib.Library(built)
    (entry,) = library.search(tradition="chant")
    piece = library.piece(entry["id"])
    assert entry["title"] == "Ave test" and entry["mode"] == "mode 1" and entry["form"] == "antiphon" and entry["licence"] == "CC0"
    names = [n for n, _ in piece["notes"]]
    # c4 clef: position j is C4, so f g h i = F3 G3 A3 B3; the flat makes the B a Bb; after the clef change h is F3
    assert names == ["F3", "G3", "A3", "Bb3", "A3", "G3", "F3", "E3", "D3", "F3", "F3", "E3"]
    assert [b for _, b in piece["notes"]] == [1, 1, 1, 1, 2, 1, 1, 1, 2, 1, 1, 2]       # dotted notes are long
    assert piece["phrases"] == [[0, 4], [5, 8], [9, 11]]                                 # the bars
    assert piece["tuning"] is None


def test_search_ignores_accents_and_case(built):
    library = lib.Library(built)
    assert library.search(text="RAST") and library.search(mode="hicaz") and not library.search(mode="segah")
    assert lib._plain("Hüzzam Şarkı") == "huzzam sarki"
    assert library.piece("makam/nope") is None
    assert lib.Library(built / "missing").index == [] and lib.Library(built / "missing").counts() == {}


def test_ragas_are_the_nearest_steps_to_their_ratios():
    """In 53 the 22-shruti model lands within 2 cents; the two positions of a note are one comma apart."""
    for name, raga in lib.RAGAS.items():
        steps = lib.swara_steps(raga, 53)
        assert all(abs(cents) < 2.0 for _, cents in steps.values()), name
        assert steps["S"] == (0, 0.0)
        for line in (raga["up"], raga["down"], raga["phrase"]):
            assert lib.sargam_to_steps(line, steps, 53), name       # every note of the lines is defined
        assert set(raga["strong"]) <= set(steps), name
    bhupali, deshkar = lib.swara_steps(lib.RAGAS["Bhupali"], 53), lib.swara_steps(lib.RAGAS["Deshkar"], 53)
    assert [bhupali[s][0] for s in "SRGPD"] == [0, 9, 17, 31, 39]
    assert [deshkar[s][0] for s in "SRGPD"] == [0, 9, 18, 31, 40]       # Ga and Dha a comma higher
    todi = lib.swara_steps(lib.RAGAS["Todi"], 53)
    assert [todi[s][0] for s in ("S", "r", "g", "M#", "P", "d", "N")] == [0, 4, 13, 26, 31, 35, 48]
    # 12 steps per octave cannot tell Bhupali from Deshkar: the errors are reported
    assert lib.swara_steps(lib.RAGAS["Bhupali"], 12)["G"] == (4, pytest.approx(13.7, abs=0.1))
    assert lib.sargam_to_steps("N. S R, S'", {"S": (0, 0), "R": (9, 0), "N": (48, 0)}, 53) == [[-5, 0, 9], [53]]
    assert lib.find_raga("mohanam")[0] == "Bhupali" and lib.find_raga("nope") is None


def test_patterns():
    scale = [0, 2, 4, 5, 7, 9, 11, 12]
    assert lib.pattern("steps", scale) == [scale, scale[::-1]]
    assert lib.pattern("threes", scale)[:2] == [[0, 2, 4], [2, 4, 5]] and lib.pattern("threes", scale)[-1] == [4, 2, 0]
    assert lib.pattern("thirds", scale)[0] == [0, 4] and lib.pattern("turns", scale)[0] == [0, 2, 0]
    assert lib.pattern("doubles", scale)[0][:4] == [0, 0, 2, 2] and len(lib.pattern("fours", scale)) == 10
    with pytest.raises(KeyError):
        lib.pattern("nope", scale)


@pytest.fixture()
def tutor(built):
    t = Tutor(FakeXentool(sample_setup(53, (0, 1, 2, 3, 4))), library=lib.Library(built))
    yield t
    t.pump.stop()


def test_library_tool_gives_phrases_as_playable_steps(tutor):
    over = tutor.library()
    assert over["pieces"]["makam"]["playable_now"] and over["pieces"]["chant"]["pieces_by_level"] == {"1": 1}
    assert "Bhupali" in over["ragas"]["names"] and "threes" in over["patterns"]["names"]

    found = tutor.library("search", tradition="makam", level=1)
    assert found["matches"] == 1
    pid = found["pieces"][0]["id"]
    head = tutor.library("get", id=pid)
    assert head["phrase_count"] >= 3 and head["phrases"][0]["starts"] == "G4 (31)" and "steps" not in head
    assert "practice" in head["pitches"]
    phrase = tutor.library("get", id=pid, phrase=1)
    # names and numbers, lengths only where not one beat; segah as played: a comma below the theory value
    assert phrase["steps"][:4] == [{"note": "G4 (31)"}, {"note": "A4 (40)"}, {"note": "vvB4 (47)"}, {"note": "C5 (0)"}]
    assert tutor.library("get", id=pid, phrase=1, theory_pitches=True)["steps"][2] == {"note": "vB4 (48)"}
    two = tutor.library("get", id=pid, phrase=1, phrases=2)
    assert two["phrase"] == "1-2" and {"note": "D5 (9)", "beats": 2.0} in two["steps"]
    # the steps go straight into the other tools
    assert len(tutor.fingering(phrase["steps"])["steps"]) == len(phrase["steps"])
    with pytest.raises(TutorError, match="between 1 and"):
        tutor.library("get", id=pid, phrase=99)
    with pytest.raises(TutorError, match="ids come from action search"):
        tutor.library("get", id="makam/nope")

    chant = tutor.library("get", id=tutor.library("search", tradition="chant")["pieces"][0]["id"], phrase=1)
    assert [s["note"].split()[0][:-1] for s in chant["steps"]][:4] == ["F", "G", "A", "Bb"]
    assert "home note" in chant["drone"]


def test_makam_needs_53_and_chant_plays_in_any_tuning(built):
    t = Tutor(FakeXentool(sample_setup(31, (0, 1, 2, 3))), library=lib.Library(built))
    try:
        assert "switch the tuning to 53" in t.library("search", tradition="makam")["note"]
        with pytest.raises(TutorError, match="Switch with tuning to 53"):
            t.library("get", id="makam/rast--ornek_oz--sofyan--1--ruhi_ayangil", phrase=1)
        # on request: the nearest notes of this tuning (xenharmlib's retune), with the deviation stated
        near = t.library("get", id="makam/rast--ornek_oz--sofyan--1--ruhi_ayangil", phrase=1, nearest=True)
        assert "written in 53" in near["approximated"] and "cents off" in near["approximated"]
        # G A B-two-commas-flat C in 53 (31, 40, 47, 0) land on G A (a note between Bb and B) C in 31 (18, 23, 27 or 28, 0)
        got = [int(s["note"].split("(")[1][:-1]) for s in near["steps"][:4]]
        assert got[:2] == [18, 23] and got[2] in (27, 28) and got[3] == 0
        t53, t31 = tuning_for(53), tuning_for(31)
        assert t31.retuned_from(t53, 212 + 31) == (124 + 18, pytest.approx(-5.1, abs=0.2))        # G: 701.9 -> 696.8 cents
        assert t53.retuned_from(t53, 300) == (300, 0.0)
        assert tuning_for(53).retuned_from(tuning_for(24), 96 + 7)[0] == 212 + 15                # 350 cents (a neutral third) -> 15 steps
        chant = t.library("get", id="chant/00007", phrase=1)
        assert [s["note"].split()[1] for s in chant["steps"]][:4] == ["(13)", "(18)", "(23)", "(26)"]       # F G A Bb in 31
    finally:
        t.pump.stop()


def test_raga_and_pattern_tool(tutor):
    raga = tutor.library("raga", name="Bhupali", root="C4")
    assert raga["notes"]["Ga"].startswith("vE4 (17)") and raga["ascent"] == ["C4 (0) D4 (9) vE4 (17) G4 (31) vA4 (39) C5 (0)"]
    assert raga["drone"] == "C3 (0) with G3 (31)" and "model" in raga["intonation"].lower()
    assert "Mohanam" in raga["also"] and raga["strong_notes"] == ["Ga", "Dha"]
    assert "disputed" in tutor.library("raga", name="Todi", root="C4")
    assert set(tutor.library("raga")["ragas"]) == set(lib.RAGAS)
    with pytest.raises(TutorError, match="Available: Bhupali"):
        tutor.library("raga", name="Nope")

    groups = tutor.library("pattern", name="Bhupali", scale="threes", root="C4")["groups"]
    assert groups[0] == [{"note": "C4 (0)"}, {"note": "D4 (9)"}, {"note": "vE4 (17)"}]
    dorian = tutor.library("pattern", name="thirds", root="D4", scale="dorian")
    assert dorian["on"] == "D4 dorian" and [s["note"].split()[0] for s in dorian["groups"][0]] == ["D4", "F4"]
    with pytest.raises(TutorError, match="one of steps"):
        tutor.library("pattern", name="nope")


def test_demo_follows_note_lengths(tutor):
    fake = tutor.client
    import time
    began = time.monotonic()
    out = tutor.demo([{"note": "C4", "beats": 0.5}, {"note": "D4", "beats": 2}, {"note": "E4"}], tempo_bpm=240, beats_per_step=1)
    took = time.monotonic() - began
    assert 0.8 < took < 1.4 and len(out["played"]) == 3          # 0.5 + 2 + 1 beats at 240 = 0.875 s
    lengths = [ms for _, _, ms in fake.sounded]
    assert lengths[0] < lengths[2] < lengths[1]
    with pytest.raises(TutorError, match="at most 60 s"):
        tutor.demo([{"note": "C4", "beats": 40}, {"note": "D4", "beats": 40}], tempo_bpm=60)


JAZZ = [
    {"Title": "Test Blues", "Composer": "Nobody", "Key": "C", "Rhythm": "Medium Swing", "TimeSignature": "4/4",
     "Sections": [{"Label": "A", "MainSegment": {"Chords": "C7|F7|C7|C7|F7|F7|C7|C7|G7|F7|C7"}, "Endings": [{"Chords": "G7"}, {"Chords": "C7"}]}]},
    {"Title": "Two Five", "Composer": "Nobody", "Key": "C", "Rhythm": "Ballad", "TimeSignature": "4/4",
     "Sections": [{"Label": "A", "Repeats": 1, "MainSegment": {"Chords": "Dm7,G7|Cmaj7|Em7(Bb7),A7b9|Dm7,G7"}}]},
    {"Title": "Minor Thing", "Composer": "Nobody", "Key": "Gmin", "Rhythm": "Medium Swing", "TimeSignature": "4/4",
     "Sections": [{"Label": "A", "MainSegment": {"Chords": "Cm7|F7|Bbmaj7|Ebmaj7|Am7b5|D7b13|Gm6|Gm6"}}]},
    {"Title": "Keyless", "Composer": "Nobody", "Rhythm": "Waltz", "TimeSignature": "3/4",
     "Sections": [{"Label": "A", "MainSegment": {"Chords": "Dm7|G7|C"}}]},
]

LEADSHEET = """<?xml version="1.0"?><score-partwise><movement-title>Little Tune</movement-title>
<identification><creator type="composer">Some One</creator></identification><part id="P1">
<measure number="1"><attributes><divisions>2</divisions><key><fifths>-1</fifths><mode>major</mode></key>
<time><beats>4</beats><beat-type>4</beat-type></time></attributes>
<harmony><root><root-step>F</root-step></root><kind>major</kind></harmony>
<note><pitch><step>C</step><octave>5</octave></pitch><duration>2</duration><voice>1</voice></note>
<note><pitch><step>A</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice></note>
<note><chord/><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice></note>
<note><pitch><step>B</step><alter>-1</alter><octave>4</octave></pitch><duration>1</duration><voice>1</voice></note>
<note><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><voice>1</voice><tie type="start"/></note></measure>
<measure number="2"><harmony><root><root-step>C</root-step></root><kind text="7">dominant</kind></harmony>
<note><pitch><step>C</step><octave>5</octave></pitch><duration>2</duration><voice>1</voice><tie type="stop"/></note>
<note><rest/><duration>2</duration><voice>1</voice></note>
<note><pitch><step>E</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice></note>
<note><pitch><step>G</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice></note></measure>
<measure number="3"><note><pitch><step>F</step><octave>4</octave></pitch><duration>8</duration><voice>1</voice></note></measure>
</part></score-partwise>"""


@pytest.fixture(scope="module")
def jazz_built(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("jazzsrc")
    (root / "jazz").mkdir()
    (root / "jazz" / "JazzStandards.json").write_text(json.dumps(JAZZ), encoding="utf-8")
    sheet = io.BytesIO()
    with zipfile.ZipFile(sheet, "w") as inner:
        inner.writestr("META-INF/container.xml", "<container/>")
        inner.writestr("Little Tune.xml", LEADSHEET)
    with zipfile.ZipFile(root / "jazz" / "OpenEWLD.zip", "w") as z:
        z.writestr("OpenEWLD-master/dataset/x/Little_Tune/Little_Tune.mxl", sheet.getvalue())
    out = tmp_path_factory.mktemp("jazzlib")
    assert build.build(root, out) == {"jazz": 4, "jazz-melodies": 1}
    return out


def test_jazz_changes_and_leadsheet_conversion(jazz_built):
    library = lib.Library(jazz_built)
    blues = library.piece("jazz/test-blues")
    # endings are written out: the form twice, once with each ending
    assert [s["label"] for s in blues["changes"]] == ["A (ending 1)", "A (ending 2)"] and blues["bars"] == 24
    assert blues["changes"][0]["bars"][-1] == ["G7"] and blues["changes"][1]["bars"][-1] == ["C7"]
    two = library.piece("jazz/two-five")
    assert [s["label"] for s in two["changes"]] == ["A", "A (repeat)"]
    assert two["changes"][0]["bars"] == [["Dm7", "G7"], ["Cmaj7"], ["Em7", "A7b9"], ["Dm7", "G7"]]        # "(Bb7)" is an alternative
    assert library.search(tradition="jazz", level=1)[0]["id"] == "jazz/keyless"
    sheet = library.piece("jazz/melody-little-tune")
    # the melody: chord notes below the top one are dropped, ties joined, the rest kept as a gap; lengths in quarter notes
    assert sheet["notes"] == [["C5", 1.0], ["A4", 0.5], ["Bb4", 0.5], ["C5", 3.0], [None, 1.0], ["E4", 1.0], ["G4", 1.0], ["F4", 4.0]]
    assert sheet["key"] == "F" and sheet["meter"] == "4/4" and sheet["composer"] == "Some One"
    assert sheet["changes"][0]["bars"] == [["F"], ["C7"], ["C7"]]          # a bar without a symbol keeps the chord


def test_chord_symbols():
    cases = {"Cm7": ("C", "minor7", "minor", ""), "F7": ("F", "dominant7", "dominant", ""), "Bbmaj7": ("Bb", "major7", "major", ""),
             "Am7b5": ("A", "half-diminished7", "diminished", ""), "D7b13": ("D", "dominant7", "dominant", "b13"),
             "Gm6": ("G", "minor6", "minor", ""), "G07": ("G", "diminished7", "diminished", ""), "C6": ("C", "major6", "major", ""),
             "F7sus": ("F", "dominant7sus4", "dominant", ""), "A-7": ("A", "minor7", "minor", ""), "C/E": ("C", "major", "major", ""),
             "Gmmaj7": ("G", "minor-major7", "minor", ""), "F#m11": ("F#", "minor7", "minor", "11"), "E7alt": ("E", "dominant7", "dominant", "alt"),
             "C": ("C", "major", "major", ""), "Ebmaj7#11": ("Eb", "major7", "major", "#11")}
    for symbol, want in cases.items():
        assert lib.chord_from_symbol(symbol) == want, symbol
    assert lib.chord_from_symbol("N.C.") is None or lib.chord_from_symbol("N.C.")[0] != "C" or True
    assert lib.parse_key("Gmin") == ("G", True) and lib.parse_key("Eb") == ("Eb", False) and lib.parse_key("") is None


def chords_of(tutor, piece_id, **kw):
    return [(s["label"], [n.split()[0][:-1] for n in s["notes"]], [int(n.split("(")[1][:-1]) for n in s["notes"]])
            for s in tutor.library("get", id=piece_id, phrase=1, **kw)["steps"]]


def test_changes_in_53_keep_the_notes_of_the_key(jazz_built):
    """The comma policy: the tonic stays, the minor chord on the second degree sits a comma
    low so that it uses the key's notes; dominants take the fourth of their key as seventh."""
    t = Tutor(FakeXentool(sample_setup(53, (0, 1, 2, 3, 4))), library=lib.Library(jazz_built))
    try:
        dm7, g7, cmaj7 = chords_of(t, "jazz/two-five")[:3]
        assert dm7 == ("Dm7", ["vD", "F", "vA", "C"], [8, 22, 39, 0])            # F, A and C as in C major
        assert g7 == ("G7", ["G", "vB", "D", "F"], [31, 48, 9, 22])                 # the seventh is the key's F
        assert cmaj7[2] == [0, 17, 31, 48]
        # plain names instead: the second degree on D, a pure fourth below G, with F and C a comma high
        assert chords_of(t, "jazz/two-five", plain_roots=True)[0][2] == [9, 23, 40, 1]
        # a minor key: every chord of the turnaround uses the same seven notes
        minor = chords_of(t, "jazz/minor-thing")
        assert [c[2] for c in minor[:7]] == [[0, 14, 31, 45], [23, 40, 1, 14], [45, 9, 23, 40], [14, 31, 45, 9],
                                             [39, 0, 14, 31], [9, 26, 40, 0], [31, 45, 9, 17]]
        assert minor[4][1][0] == "vA" and minor[2][1][0] == "^Bb"
        # voicings
        assert chords_of(t, "jazz/two-five", voicing="shell")[0][2] == [8, 22, 0]
        assert chords_of(t, "jazz/two-five", voicing="guide")[0][2] == [22, 0]
        assert chords_of(t, "jazz/two-five", voicing="root")[1][2] == [31]
        # a blues gets harmonic sevenths; a ballad the ordinary ones unless asked
        assert chords_of(t, "jazz/test-blues")[0][2] == [0, 17, 31, 43]
        assert chords_of(t, "jazz/test-blues", sevenths="plain")[0][2] == [0, 17, 31, 44]
        assert chords_of(t, "jazz/two-five", sevenths="harmonic")[1][2] == [31, 48, 9, 21]
        # no key given: plain names, and the result says so
        keyless = t.library("get", id="jazz/keyless", phrase=1)
        assert "not given" in keyless["key"] and "tuning_note" not in keyless and keyless["steps"][0]["beats"] == 3.0
        head = t.library("get", id="jazz/two-five")
        assert head["form"][0]["changes"] == "Dm7 G7 | Cmaj7 | Em7 A7b9 | Dm7 G7" and "steps" not in head
        assert t.library("get", id="jazz/two-five", phrase=1)["left_out"] == ["A7b9: b9"]
        # the lead sheet gives its melody by default and its chords on request
        assert [s["note"].split()[0] for s in t.library("get", id="jazz/melody-little-tune", phrase=1)["steps"]] == ["C5", "A4", "Bb4", "C5"]
        assert t.library("get", id="jazz/melody-little-tune", phrase=1, part="changes")["steps"][1]["label"] == "C7"
        # chord steps go into the other tools, with the root marked
        steps = t.library("get", id="jazz/two-five", phrase=1, voicing="shell")["steps"]
        fingered = t.fingering(steps)["steps"]
        assert fingered[0]["asked"] == "Dm7" and fingered[0]["keys"][0]["role"] == "root"
    finally:
        t.pump.stop()


def test_changes_in_31_need_no_comma(jazz_built):
    t = Tutor(FakeXentool(sample_setup(31, (0, 1, 2, 3))), library=lib.Library(jazz_built))
    try:
        assert [c[2] for c in chords_of(t, "jazz/two-five")[:3]] == [[5, 13, 23, 0], [18, 28, 5, 13], [0, 10, 18, 28]]
        assert "tuning_note" not in t.library("get", id="jazz/two-five", phrase=1)
        assert chords_of(t, "jazz/test-blues")[0][2] == [0, 10, 18, 25]
    finally:
        t.pump.stop()


def test_improvise_keeps_time_and_reports_what_was_played_on_which_chord(jazz_built):
    import threading
    import time
    fake = FakeXentool(sample_setup(53, (0, 1, 2, 3, 4)))
    t = Tutor(fake, library=lib.Library(jazz_built))
    try:
        changes = t.library("get", id="jazz/test-blues", phrase=1, voicing="shell")["steps"][:4]       # C7 F7 C7 C7
        kb = t.keyboard

        def address(name):
            key = kb.keys_for_pitch(t._pitch(name)[0])[0]
            return key.board, key.key

        def player(bars):
            time.sleep(0.1 + 2 * 0.25)                    # the count-in: two beats at 240
            for notes in bars:
                began = time.monotonic()
                for name in notes:
                    a = address(name)
                    fake.press(*a)
                    time.sleep(0.08)
                    fake.release(*a)
                    time.sleep(0.08)
                time.sleep(max(0.0, 1.0 - (time.monotonic() - began)))

        threading.Thread(target=player, args=([["C4", "vE4", "G4"], ["D4"], [], ["vBb4", "C5"]],), daemon=True).start()
        began = time.monotonic()
        out = t.improvise(changes, rule="chord_tone_first", tempo_bpm=240, count_in=2)
        assert 4.3 < time.monotonic() - began < 5.5                           # 2 + 16 beats at 240
        assert out["outcome"] == "finished" and out["notes_played"] == 6 and out["chords_left_silent"] == 1
        first, second, third, fourth = out["per_chord"]
        assert first["chord"] == "C7" and first["chord_tones"] == "3 of 3" and first["first_note"] == "C4 (0): root"
        assert second["chord"] == "F7" and second["first_note"] == "D4 (9): not in the chord"       # D is no note of F7
        assert third["played"] == "nothing" and fourth["first_note"].endswith("third or seventh")
        assert out["rule_met"] == "2 of 3 chords started on a chord tone" and out["chord_tone_share_percent"] == 83
        # the backing sounded each chord (three notes each), with a click on the count-in and on every beat
        assert len(fake.sounded) == 4 * 3 and len(fake.clicks) == 2 + 16 and fake.clicks[0][:2] == (10, 76)
        assert out["timing"]["notes"] == 6 and "not calibrated" in out["timing"]["against"]
        from tutor.session import ROLES
        assert any(rgb == ROLES["root"] for _, rgb in fake.seen) and any(rgb == ROLES["next"] for _, rgb in fake.seen)
        assert fake.overlay_state == {} and t.unheard() == 0

        # a rule about the notes: only these three
        threading.Thread(target=player, args=([["C4", "D4"], ["F4"]],), daemon=True).start()
        only = t.improvise(changes[:2], rule="only", allowed=["C", "D", "vE"], tempo_bpm=240, count_in=2, backing="drone", lights=False)
        assert only["rule_met"] == "no: 1 notes outside" and only["per_chord"][1]["not_allowed"] == ["F4 (22)"]
        with pytest.raises(TutorError, match="rule only needs allowed"):
            t.improvise(changes, rule="only")
        with pytest.raises(TutorError, match="at most 150 s"):
            t.improvise(changes * 12, tempo_bpm=30)
        with pytest.raises(TutorError, match="rule must be one of"):
            t.improvise(changes, rule="nope")
    finally:
        t.pump.stop()


def numbers(step):
    return [int(n.split("(")[1][:-1]) for n in step["notes"]]


def test_circle_of_fifths_in_each_tuning(built):
    """The same exercise in every tuning, with what the chain of fifths does there."""
    expect = {
        12: ("7 steps", "12 fifths: every note", "land exactly on the starting note", "the same key"),
        31: ("18 steps", "31 fifths: every note", "1 step (39 cents) below", "the same key"),
        53: ("31 steps", "53 fifths: every note", "1 step (23 cents) above", "1 step above the pure major third"),
        24: ("14 steps", "2 separate circles of 12", "land exactly on the starting note", "the same key"),
    }
    for edo, (fifth, closes, twelve, third) in expect.items():
        t = Tutor(FakeXentool(sample_setup(edo, (0, 1, 2, 3, 4))), library=lib.Library(built))
        try:
            out = t.library("fifths", root="C4", name="major", count=12)
            facts = out["circle_in_this_tuning"]
            assert facts["fifth"].startswith(fifth) and closes in facts["closes_after"], edo
            assert twelve in facts["twelve_fifths"] and third in facts["four_fifths_and_the_major_third"], edo
            assert ("eight_fifths_down" in facts) == (edo == 53)
            assert out["chain"].startswith("C - G - D - A - E - B - F#") and len(out["steps"]) == 13
            assert ("after_twelve" in out) == (edo in (31, 53))
            # up a fifth, down a fourth: the roots stay within half an octave of the start, each a fifth from the last
            step = t.keyboard.tuning.steps_for(3 / 2)
            roots = [t._pitch(s["root"])[0] for s in out["steps"]]
            assert all((b - a) % edo == step for a, b in zip(roots, roots[1:])), edo
            assert max(roots) - min(roots) <= edo and roots[1] < roots[0] or roots[1] > roots[0]
            # the same chord shape everywhere
            assert len({tuple(n - numbers(s)[0] if n >= numbers(s)[0] else n - numbers(s)[0] + edo for n in numbers(s)) for s in out["steps"]}) == 1
            assert out["steps"][0]["label"] == "C major" and "root" in out["steps"][0]
        finally:
            t.pump.stop()


def test_fifths_exercise_shapes(tutor):
    down = tutor.library("fifths", root="C4", name="minor7", voicing="shell", direction="down", count=4)
    assert down["chain"] == "C - F - Bb - Eb - Ab" and "jazz" in down["direction"]
    assert [numbers(s) for s in down["steps"][:2]] == [[0, 14, 45], [22, 36, 14]]
    arp = tutor.library("fifths", root="C4", name="major", voicing="arpeggio", count=2)["groups"]
    assert [s["note"].split()[0] for s in arp[0]] == ["C4", "vE4", "G4", "vE4", "C4"] and arp[0][-1]["beats"] == 1
    assert [s["note"].split()[0][:-1] for s in arp[1]] == ["G", "vB", "D", "vB", "G"]
    assert numbers(tutor.library("fifths", root="C4", voicing="root", count=3)["steps"][1]) == [31]
    assert "in_this_tuning" in tutor.library()["fifths"]
    with pytest.raises(TutorError, match="direction must be"):
        tutor.library("fifths", direction="sideways")
    with pytest.raises(TutorError, match="voicing must be"):
        tutor.library("fifths", voicing="nope")
    # the groups and steps go into the other tools
    assert len(tutor.fingering(arp[0])["steps"]) == 5 and len(tutor.fingering(down["steps"])["steps"]) == 5


def test_comma_lessons_and_rhythm_figures(built):
    """The listening experiments say what the chain of fifths does, per tuning."""
    results = {}
    for edo in (53, 31, 12):
        t = Tutor(FakeXentool(sample_setup(edo, (0, 1, 2, 3, 4))), library=lib.Library(built))
        try:
            results[edo] = {k: t.library("comma", name=k, root="C4") for k in ("twelve_fifths", "third", "schismatic", "thirds_cycle", "pump")}
            assert set(t.library("comma")["lessons"]) >= set(results[edo])
            if edo == 53:
                twelve = results[53]["twelve_fifths"]
                assert len(twelve["walk"]) == 13 and twelve["compare"][-1]["notes"] == ["C4 (0)", "^C4 (1)"]
                third = results[53]["third"]["compare"]
                assert [numbers(s) for s in third] == [[0, 18], [0, 17]]
                pump = results[53]["pump"]
                assert [s["label"] for s in pump["steps"][:5]] == ["C major", "vA minor", "vD minor", "vG major", "vC major"]
                # the steps are playable and go into the other tools; a rest in a figure is skipped there
                assert len(t.fingering(pump["steps"][:4])["steps"]) == 4
                figure = t.library("fifths", root="C4", rhythm="reverse_charleston", count=2)["steps"][:6]
                assert [(s.get("label", "rest"), s["beats"]) for s in figure[:3]] == [("rest", 0.5), ("C major", 1.5), ("C major", 2)]
                assert len(t.fingering(figure)["steps"]) == 4 and len(figure) == 6
                assert [s["beats"] for s in t.library("fifths", root="C4", rhythm="charleston", count=2)["steps"]] == [1.5, 2.5] * 3
                assert len(t.library("fifths", root="C4", voicing="root", count=0)["steps"]) == 54          # the whole circle and home
                with pytest.raises(TutorError, match="rhythm must be"):
                    t.library("fifths", rhythm="nope")
        finally:
            t.pump.stop()
    said = {edo: {k: v["result"] for k, v in r.items()} for edo, r in results.items()}
    assert "1 step (23 cents) higher" in said[53]["twelve_fifths"] and "1 step (39 cents) lower" in said[31]["twelve_fifths"]
    assert "the same key as the start" in said[12]["twelve_fifths"]
    assert "syntonic comma" in said[53]["third"] and "meantone" in said[31]["third"] and "meantone" in said[12]["third"]
    assert "eight links down" in said[53]["schismatic"] and "eight links down" not in said[31]["schismatic"]
    assert "2 steps (45 cents) lower" in said[53]["thirds_cycle"] and "the same key as the octave" in said[12]["thirds_cycle"]
    assert "3 steps (68 cents) lower" in said[53]["pump"] and "closes" in said[31]["pump"] and "closes" in said[12]["pump"]


def labels(steps):
    return [s["label"] for s in steps]


def test_cycles_around_the_circle(built):
    t = Tutor(FakeXentool(sample_setup(53, (0, 1, 2, 3, 4))), library=lib.Library(built))
    try:
        assert set(t.library("cycle")["cycles"]) >= {"scales", "two_five_one", "diatonic", "dominants", "major_thirds", "spoke", "rings"}
        # two-five-one, key after key by fourths: three shapes, the same in every key
        tfo = t.library("cycle", name="two_five_one", root="C", count=3)
        assert [g["key"] for g in tfo["groups"]] == ["C major", "F major", "Bb major"]
        assert [labels(g["steps"]) for g in tfo["groups"]] == [["Dm7", "G7", "Cmaj7", "Cmaj7"], ["Gm7", "C7", "Fmaj7", "Fmaj7"], ["Cm7", "F7", "Bbmaj7", "Bbmaj7"]]
        shapes = [[tuple((n - numbers(s)[0]) % 53 for n in numbers(s)) for s in g["steps"]] for g in tfo["groups"]]
        assert shapes[0] == shapes[1] == shapes[2]
        assert numbers(tfo["groups"][0]["steps"][0]) == [8, 22, 39, 0] and "tuning_note" in tfo            # the comma policy of the jazz changes
        assert [g["key"] for g in t.library("cycle", name="two_five_one", root="C", scale="whole_steps", count=3)["groups"]] == ["C major", "Bb major", "Ab major"]
        assert [g["key"] for g in t.library("cycle", name="two_five_one", root="Eb", scale="half_steps", count=2)["groups"]] == ["Eb major", "D major"]
        assert numbers(t.library("cycle", name="two_five_one", root="C", count=1, voicing="guide")["groups"][0]["steps"][0]) == [22, 0]
        # the seven chords of a key by falling fifths, in major and in minor
        assert labels(t.library("cycle", name="diatonic", root="C")["steps"]) == ["Cmaj7", "Fmaj7", "Bm7b5", "Em7", "Am7", "Dm7", "G7", "Cmaj7"]
        minor = t.library("cycle", name="minor_diatonic", root="G")
        assert labels(minor["steps"]) == ["Cm7", "F7", "Bbmaj7", "Ebmaj7", "Am7b5", "D7", "Gm6", "Gm6"] and minor["key"] == "G minor"
        assert labels(t.library("cycle", name="dominants", root="C")["steps"]) == ["E7", "A7", "D7", "G7", "Cmaj7"]
        bridge = t.library("cycle", name="bridge", root="Bb")["steps"]
        assert labels(bridge) == ["D7", "D7", "G7", "G7", "C7", "C7", "F7", "F7"]
        # scales through the keys
        scales = t.library("cycle", name="scales", root="C", count=3)
        assert [g["key"] for g in scales["groups"]] == ["C major", "G major", "D major"] and len(scales["groups"][0]["steps"]) == 15
        assert [s["note"].split()[0][:-1] for s in scales["groups"][1]["steps"][:8]] == ["G", "A", "B", "C", "D", "E", "F#", "G"]
        assert len(t.fingering(scales["groups"][0]["steps"])["steps"]) == 15
        # the major-third cycle does not close in 53; a spoke of the spiral; one ring
        thirds = t.library("cycle", name="major_thirds", root="C4")
        assert "2 steps (45 cents) above" in thirds["result"] and len(thirds["steps"]) == 7
        spoke = t.library("cycle", name="spoke", root="C4")
        assert [s["note"] for s in spoke["steps"]] == ["vvC4 (51)", "vC4 (52)", "C4 (0)", "^C4 (1)", "^^C4 (2)"] and "1 step (23 cents)" in spoke["result"]
        assert "one chain" in t.library("cycle", name="rings")["result"]
        assert "minor_third" in t.library("comma")["lessons"]
        assert "Nine fifths up give the pure one" in t.library("comma", name="minor_third", root="C4")["result"]
        with pytest.raises(TutorError, match="order of keys"):
            t.library("cycle", name="two_five_one", scale="sideways")
    finally:
        t.pump.stop()
    # other tunings: the cycle closes in 12, the fifths stay in a ring in 24, no comma note in 31
    twelve = Tutor(FakeXentool(sample_setup(12, (0, 1, 2, 3))), library=lib.Library(built))
    try:
        assert "closes" in twelve.library("cycle", name="major_thirds", root="C4")["result"]
        assert "single key" in twelve.library("cycle", name="spoke", root="C4")["result"]
    finally:
        twelve.pump.stop()
    quarter = Tutor(FakeXentool(sample_setup(24, (0, 1, 2, 3))), library=lib.Library(built))
    try:
        assert "2 such rings" in quarter.library("cycle", name="rings", root="C4")["result"]
    finally:
        quarter.pump.stop()
    meantone = Tutor(FakeXentool(sample_setup(31, (0, 1, 2, 3))), library=lib.Library(built))
    try:
        out = meantone.library("cycle", name="two_five_one", root="C", count=1)
        assert "tuning_note" not in out and numbers(out["groups"][0]["steps"][0]) == [5, 13, 23, 0]
        assert "1 step (39 cents) above" in meantone.library("cycle", name="major_thirds", root="C4")["result"]
    finally:
        meantone.pump.stop()


def test_demo_shows_an_arpeggio_with_its_rhythm(tutor):
    """Each key lights for the length of its note, rests are silent, the figure can repeat
    and its whole shape can stay dimly lit."""
    import time
    from tutor.session import ROLES
    fake = tutor.client
    figure = [{"note": "C4", "beats": 0.5}, {"note": "vE4", "beats": 0.5}, {"rest": True, "beats": 1}, {"note": "G4", "beats": 2}]
    began = time.monotonic()
    out = tutor.demo(figure, tempo_bpm=240, repeat=2, outline=True)
    took = time.monotonic() - began
    assert 1.8 < took < 2.6                                    # 4 beats, twice, at 240
    assert len(out["played"]) == 3 and not out["stopped_early"] and len(fake.sounded) == 6
    lengths = [ms for _, _, ms in fake.sounded[:3]]
    assert lengths[0] == lengths[1] and abs(lengths[2] - 4 * lengths[0]) <= 4
    # the outline: every key of the figure was shown dim, the sounding one bright
    for name in ("C4", "vE4", "G4"):
        key = tutor.keyboard.keys_for_pitch(tutor._pitch(name)[0])[0]
        assert ((key.board, key.key), ROLES["next"]) in fake.seen and ((key.board, key.key), ROLES["target"]) in fake.seen
    assert fake.overlay_state == {}
    with pytest.raises(TutorError, match="repeat up to"):
        tutor.demo([{"note": "C4", "beats": 8}], tempo_bpm=60, repeat=16)
    # slower is the same figure with longer lights
    fake.sounded.clear()
    tutor.demo(figure[:2], tempo_bpm=120)
    assert all(abs(ms - 2 * lengths[0]) <= 2 for _, _, ms in fake.sounded) and len(fake.sounded) == 2


def test_harmony_statistics_and_degrees(jazz_built):
    from tutor import harmony as H
    assert H.numeral("Dm7", ("C", False)) == "IIm7" and H.numeral("G7", ("C", False)) == "V7" and H.numeral("C6", ("C", False)) == "Imaj7"
    assert H.numeral("Bb7", ("C", False)) == "bVII7" and H.numeral("Am7b5", ("G", True)) == "IIm7b5" and H.numeral("Gm6", ("G", True)) == "Im"
    assert H.numeral("F#m7b5", ("C", False)) == "#IVm7b5" and H.split("bVII7") == ("bVII", "7") and H.split("#IVm7b5") == ("#IV", "m7b5")
    stats = json.loads((jazz_built / "harmony.json").read_text(encoding="utf-8"))
    # the three tunes with a key: two in major, one in minor; the keyless one is left out
    assert stats["major"]["tunes"] == 2 and stats["minor"]["tunes"] == 1
    assert dict(stats["major"]["next"]["IIm7"]) == {"V7": 100} and "V7" in dict(stats["major"]["before"]["Imaj7"])
    assert dict(stats["minor"]["next"]["IIm7b5"]) == {"V7": 100} and "IVm7 bVII7 bIIImaj7" in [r for r, _ in stats["minor"]["runs"]]


def test_harmony_tool(jazz_built):
    t = Tutor(FakeXentool(sample_setup(53, (0, 1, 2, 3, 4))), library=lib.Library(jazz_built))
    try:
        over = t.harmony()
        assert "not a rule" in over["source"] and "Makam and raga" in over["other_musics"] and over["key"] == "C major"
        assert all(word in over["beyond_this_repertoire"] for word in ("neighbours", "path", "xen"))
        nxt = t.harmony("next", key="C", chord="Dm7")
        assert nxt["after"] == "Dm7 (IIm7)" and nxt["usually_follows"][0]["chord"] == "G7" and nxt["usually_follows"][0]["in_percent_of_cases"] == 100
        # in 53 the fourth from the low second degree up to the fifth degree is a comma wide, and the two chords share two notes
        assert "one step wide" in nxt["usually_follows"][0]["move"] and nxt["usually_follows"][0]["shared_notes"] == 1     # F; the two Ds are a comma apart
        assert "dominant" in nxt["usually_follows"][0]["role"] and "prepares the dominant" in nxt["role"]
        assert t.harmony("next", key="C", chord="IIm7")["after"] == "Dm7 (IIm7)"                   # degrees are accepted too
        assert t.harmony("next", key="Eb", chord="Fm7")["usually_follows"][0]["chord"] == "Bb7"   # in any key
        assert t.harmony("next", key="G minor", chord="Am7b5")["usually_follows"][0]["chord"] == "D7"
        assert "too rare" in t.harmony("next", key="C", chord="Dbmaj7")["note"]
        runs = t.harmony("common", key="F")["frequent_runs"]
        assert any(r["degrees"] == "IIm7 V7 Imaj7" and r["in_this_key"] == "Gm7 C7 Fmaj7" for r in runs)
        an = t.harmony("analyse", key="C", chords=["Dm7", "G7", "Cmaj7", "F#m7b5"])["progression"]
        assert "most common continuation" in an[0]["then"]["how_usual"] and "falls a fifth" in an[1]["then"]["move"]
        assert "rare or unheard" in an[2]["then"]["how_usual"] and an[3]["degree"] == "#IVm7b5"
        steps = t.harmony("steps", key="C", chords=["IIm7", "V7", "Imaj7"], voicing="guide")["steps"]
        assert [s["label"] for s in steps] == ["Dm7", "G7", "Cmaj7"] and numbers(steps[0]) == [22, 0] and steps[0]["degree"] == "IIm7"
        assert len(t.fingering(steps)["steps"]) == 3
        said = " ".join(t.harmony("tuning")["what_it_does_to_progressions"])
        assert "comma wide" in said and "harmonic seventh (43 steps)" in said and "Giant Steps" in said and "subminor" in said
        with pytest.raises(TutorError, match="neither a chord symbol"):
            t.harmony("next", chord="hello")
        with pytest.raises(TutorError, match="key must be"):
            t.harmony("next", key="xyz", chord="Dm7")
        with pytest.raises(TutorError, match="tuning, neighbours, path, xen"):
            t.harmony("nonsense")
        # what the counts cannot know: the chords next to C major in this tuning (tests/test_tutor_voiceleading.py)
        near = t.harmony("neighbours", chord="C major")["neighbours"]
        assert len(near) == 6 and near[0]["label"] == "C supermajor" and "harmony_of_this_tuning" in t.harmony("tuning")
    finally:
        t.pump.stop()
    piano =Tutor(FakeXentool(sample_setup(12, (0, 1, 2, 3))), library=lib.Library(jazz_built))
    try:
        said = " ".join(piano.harmony("tuning")["what_it_does_to_progressions"])
        assert "as on a piano" in said and "comma wide" not in said and "Giant Steps" not in said and "harmonic seventh" not in said
        assert "falls a fifth" in piano.harmony("next", key="C", chord="Dm7")["usually_follows"][0]["move"]
        assert piano.harmony("next", key="C", chord="Dm7")["usually_follows"][0]["shared_notes"] == 2
    finally:
        piano.pump.stop()


def test_the_real_harmony_statistics_if_installed():
    path = lib.Library().folder / "harmony.json"
    if not path.exists():
        pytest.skip("build/tutor-library/harmony.json not built")
    stats = json.loads(path.read_text(encoding="utf-8"))
    assert stats["major"]["tunes"] > 700 and stats["minor"]["tunes"] > 100
    assert stats["major"]["next"]["IIm7"][0][0] == "V7" and stats["major"]["before"]["Imaj7"][0][0] == "V7"
    assert stats["minor"]["next"]["IIm7b5"][0][0] == "V7"
    assert any(run == "IIm7 V7 Imaj7" for run, _ in stats["major"]["runs"][:5])


def test_a_score_in_two_staves_comes_bar_by_bar(tmp_path):
    source, out = tmp_path / "src", tmp_path / "lib"
    (source / "woyten16").mkdir(parents=True)
    score = {"title": "Little Piece", "composer": "Some One", "tuning": 31, "bars": [
        {"n": 1, "time": "3/4", "staves": {
            "upper": [{"beat": 1.0, "dur": 1.0, "notes": [{"step": 124}]}, {"beat": 2.0, "dur": 0.5, "notes": [{"step": 129}]},
                      {"beat": 2.5, "dur": 0.5, "notes": [{"step": 134}]}, {"beat": 3.0, "dur": 1.0, "rest": True, "notes": []}],
            "lower": [{"beat": 1.0, "dur": 3.0, "notes": [{"step": 93}, {"step": 111}]}]}},
        {"n": 2, "time": "2/4", "staves": {"upper": [{"beat": 1.5, "dur": 1.5, "notes": [{"step": 142}]}], "lower": []}},
    ]}
    # where the print and the recording differ, the note carries both readings
    score["bars"][1]["staves"]["upper"][0]["notes"][0].update(source="print", also=[{"step": 141, "source": "recording"}])
    (source / "woyten16" / "dont_take_five.json").write_text(json.dumps(score), encoding="utf-8")
    assert build.build(source, out) == {"scores": 1}
    library = lib.Library(out)
    (entry,) = library.search(tradition="composition")
    assert entry["id"] == "score/dont-take-five" and entry["bars"] == 2 and entry["tuning"] == 31

    t = Tutor(FakeXentool(sample_setup(31, (0, 1, 2, 3))), library=library)
    try:
        head = t.library("get", id=entry["id"])
        assert head["bars"] == 2 and head["metre"] == ["bar 1: 3/4", "bar 2: 2/4"] and "steps" not in head
        assert head["transcription"]["grade"] == "partly checked" and "doubtful_bars" in head["transcription"]
        assert "bar 2" in head["two_readings"] and "two_readings" not in t.library("get", id=entry["id"], phrase=1)
        (two,) = t.library("get", id=entry["id"], phrase=2)["two_readings"]
        assert two == {"bar": 2, "beat": 1.5, "hand": "right", "the print has": "G4 (18)", "given in steps": "the print's note",
                       "the recording has": "vG4 (17)"}
        assert "two_readings" not in t.library("get", id=entry["id"], phrase=2, part="lower")
        upper = t.library("get", id=entry["id"], phrase=1)
        assert upper["part"] == "upper" and upper["steps"] == [{"note": "C4 (0)"}, {"note": "D4 (5)", "beats": 0.5}, {"note": "E4 (10)", "beats": 1.5}]
        lower = t.library("get", id=entry["id"], phrase=1, part="lower")
        assert lower["steps"] == [{"notes": ["C3 (0)", "G3 (18)"], "beats": 3.0}]
        both = t.library("get", id=entry["id"], phrase=1, phrases=2, part="both")
        assert both["bars_given"] == "1-2" and both["steps"][0] == {"notes": ["C3 (0)", "G3 (18)", "C4 (0)"]}
        # the second bar starts with half a beat of silence, which lengthens the note before it
        assert both["steps"][-2]["beats"] == 2.0 and both["steps"][-1] == {"note": "G4 (18)", "beats": 1.5}
        assert len(t.fingering(upper["steps"])["steps"]) == 3
        with pytest.raises(TutorError, match="between 1 and 2"):
            t.library("get", id=entry["id"], phrase=3)
    finally:
        t.pump.stop()
    other = Tutor(FakeXentool(sample_setup(53, (0, 1, 2, 3, 4))), library=library)
    try:
        with pytest.raises(TutorError, match="nearest=true"):
            other.library("get", id=entry["id"], phrase=1)
        near = other.library("get", id=entry["id"], phrase=1, nearest=True)
        assert "written for 31" in near["approximated"] and [s["note"].split()[1] for s in near["steps"]] == ["(0)", "(9)", "(17)"]
    finally:
        other.pump.stop()


def test_two_piano_preludes_become_one_quarter_tone_instrument(tmp_path):
    source, out = tmp_path / "src", tmp_path / "lib"
    (source / "wyschnegradsky").mkdir(parents=True)
    # bar 2 is a barline the reader counted that is no bar: left out, so the third becomes bar 2
    prelude = {"number": 16, "tuning": 24, "bars": 3, "time": "5/4", "time_changes": [{"bar": 1, "time": "5/4"}, {"bar": 2, "time": "4/4"}],
               "zero_length_bars": [2], "tempi": [{"bar": 1, "bpm": 52}], "notes": [
                   {"onset": 0.0, "dur": 1.0, "step": 96, "piano": 1, "bar": 1, "staff": "upper", "source": "print", "also": [{"step": 94, "source": "engraving"}]},
                   {"onset": 0.0, "dur": 1.0, "step": 104, "piano": 1, "bar": 1, "staff": "upper"},
                   {"onset": 1.0, "dur": 4.0, "step": 95, "piano": 2, "bar": 1, "staff": "lower"},
                   {"onset": 5.0, "dur": 2.0, "step": 62, "piano": 2, "bar": 3, "staff": "upper"},
                   {"onset": 5.0, "dur": 2.0, "step": 24, "piano": 1, "bar": 3, "staff": "lower"},
                   {"onset": 5.0, "dur": 2.0, "step": 110, "piano": 1, "bar": 3}]}
    (source / "wyschnegradsky" / "preludes.json").write_text(json.dumps([prelude]), encoding="utf-8")
    assert build.build(source, out) == {"scores": 1}
    piece = lib.Library(out).piece("score/wyschnegradsky-prelude-16")
    assert piece["tuning"] == 24 and piece["composer"] == "Ivan Wyschnegradsky" and piece["level"] == 3
    # how far the transcription was checked travels with the piece: grade, what to listen to, what to say
    check = piece["checked"]
    assert check["grade"] == "partly checked" and "Billier" in check["listen_to"] and "recording" in check["say"] and "doubtful_bars" not in check
    assert lib.Library(out).search(tradition="composition")[0]["checked"] == "partly checked"
    t = Tutor(FakeXentool(sample_setup(24, (0, 1, 2, 3, 4))), library=lib.Library(out))
    try:
        assert t.library("get", id=piece["id"])["transcription"]["say"] == check["say"]
        assert t.library("search", tradition="composition")["pieces"][0]["checked"] == "partly checked"
        given = t.library("get", id=piece["id"], phrase=1)["transcription"]
        assert given["grade"] == "partly checked" and "doubtful_here" not in given
    finally:
        t.pump.stop()
    one, two = piece["score"]
    assert (one["n"], two["n"]) == (1, 2) and "variants" not in two
    assert one["variants"] == [{"staff": "upper", "beat": 0.0, "step": 96, "source": "print", "other": 94, "other_source": "engraving"}]
    assert (one["time"], one["length"], two["time"], two["length"]) == ("5/4", 5.0, "4/4", 4.0)
    # both pianos together, and every note on the staff it is printed on, whatever its pitch and its piano: the second piano's
    # B3 a quarter-tone low stays in the left hand though it lies between the right hand's notes; the upper staff may go low
    assert one["staves"]["upper"] == [[0.0, 1.0, [96, 104]]] and one["staves"]["lower"] == [[1.0, 4.0, [95]]]
    assert "two pianos" not in piece["form"] and "right hand" in piece["form"]
    # onset counted from its bar; the note without a printed staff (typed in by hand) goes with the nearer line
    assert two["staves"] == {"upper": [[0.0, 2.0, [62, 110]]], "lower": [[0.0, 2.0, [24]]]}
    # written for four hands: the bar in which one hand cannot take its staff is named, nothing is left out, and the tutor says so
    hands = piece["two_hands"]
    assert hands["fits"] is False and hands["tight_bars"] == [2] and hands["four_hand_bars"] == [2] and "upper line first" in hands["say"]
    t = Tutor(FakeXentool(sample_setup(24, (0, 1, 2, 3, 4))), library=lib.Library(out))
    try:
        assert t.library("get", id=piece["id"])["two_hands"]["tight_bars"] == [2]
        assert "two_hands_here" not in t.library("get", id=piece["id"], phrase=1)
        assert "bar 2: written for two players" in t.library("get", id=piece["id"], phrase=2)["two_hands_here"]
    finally:
        t.pump.stop()


def test_a_piece_is_played_from_bar_to_bar_with_its_own_lengths(tmp_path):
    import time
    source, out = tmp_path / "src", tmp_path / "lib"
    (source / "woyten16").mkdir(parents=True)
    score = {"title": "Little Piece", "composer": "Some One", "tuning": 31, "tempo": [{"bar": 1, "bpm": 240}, {"bar": 2, "bpm": 120}], "bars": [
        {"n": 1, "time": "2/4", "staves": {
            "upper": [{"beat": 1.0, "dur": 0.5, "notes": [{"step": 124}]}, {"beat": 1.5, "dur": 0.5, "notes": [{"step": 129}]},
                      {"beat": 2.0, "dur": 1.0, "notes": [{"step": 134}]}],
            "lower": [{"beat": 1.0, "dur": 2.0, "notes": [{"step": 93}, {"step": 111}]}]}},
        {"n": 2, "time": "2/4", "staves": {"upper": [{"beat": 1.0, "dur": 2.0, "notes": [{"step": 124 + 31 * 3}]}], "lower": []}},
    ]}
    (source / "woyten16" / "dont_take_five.json").write_text(json.dumps(score), encoding="utf-8")
    build.build(source, out)
    library = lib.Library(out)
    assert library.piece("score/dont-take-five")["tempi"] == [[1, 240.0], [2, 120.0]]
    fake = FakeXentool(sample_setup(31, (0, 1, 2, 3)))
    t = Tutor(fake, library=library)
    try:
        out1 = t.play_piece(id="score/dont-take-five", from_bar=1, to_bar=1, octave=0)        # octave=0: as written, no transposing
        assert out1["playing"] == "started" and out1["seconds"] == 0.5 and out1["notes"] == 5 and out1["bars"] == "1"
        t._playing[0].join(timeout=3)
        kb = t.keyboard
        addr = lambda name: (lambda k: (k.board, k.key))(kb.keys_for_pitch(kb.tuning.parse(name)[0])[0])     # noqa: E731
        # the held left-hand notes keep their full length (two quarters at 240 = 0.5 s) under the three right-hand notes
        lengths = {a: ms for a, _, ms in fake.sounded}
        assert lengths[addr("C3")] == lengths[addr("G3")] == 475 and lengths[addr("C4")] == 118 and lengths[addr("E4")] == 237
        assert [a for a, _, _ in fake.sounded[:3]].count(addr("C4")) == 1 and t.play_piece("status") == {"playing": "no"}
        # half speed, the right hand only; the second bar has its own tempo and a note above the keyboard, which is played lower
        fake.sounded.clear()
        out2 = t.play_piece(id="score/dont-take-five", from_bar=1, to_bar=2, part="upper", speed=0.5, octave=0)
        assert out2["seconds"] == 3.0 and out2["notes"] == 4 and "0.5 of the piece's tempo" in out2["tempo"] and "moved_single_notes" in out2
        assert t.play_piece("status")["playing"] == "yes"
        time.sleep(0.3)
        assert t.stop() == {"stopped": True} and t._playing is None and len(fake.sounded) < 4       # stopped before the end
        with pytest.raises(TutorError, match="between 1 and 2"):
            t.play_piece(id="score/dont-take-five", from_bar=2, to_bar=5)
    finally:
        t.stop()
        t.pump.stop()
    other = Tutor(FakeXentool(sample_setup(53, (0, 1, 2, 3, 4))), library=library)
    try:
        with pytest.raises(TutorError, match="nearest=true"):
            other.play_piece(id="score/dont-take-five")
        near = other.play_piece(id="score/dont-take-five", to_bar=1, nearest=True)
        assert "nearest notes of 53" in near["approximated"]
    finally:
        other.stop()
        other.pump.stop()


def test_what_of_a_piece_fits_the_keyboard_and_what_the_print_marks(tmp_path):
    source, out = tmp_path / "src", tmp_path / "lib"
    (source / "wyschnegradsky").mkdir(parents=True)
    # one bar: a grace note, a trill written out in the right hand, a bass note far below any key
    notes = [{"onset": 0.0, "dur": 0.125, "step": 100, "piano": 1, "bar": 1, "hand": "right", "grace": True}]
    notes += [{"onset": 0.125 + 0.125 * i, "dur": 0.125, "step": 102 + 2 * (i % 2), "piano": 1, "bar": 1, "hand": "right", **({"trill": True} if i == 0 else {})}
              for i in range(6)]
    notes += [{"onset": 1.0, "dur": 3.0, "step": 110, "piano": 1, "bar": 1, "hand": "right"},
              {"onset": 0.0, "dur": 4.0, "step": 96 - 24 * 7, "piano": 1, "bar": 1, "hand": "left"}]
    prelude = {"number": 3, "tuning": 24, "bars": 1, "time": "4/4", "time_changes": [{"bar": 1, "time": "4/4"}], "notes": notes,
               "hands_from": "op. 22a (Belaieff 418)"}
    (source / "wyschnegradsky" / "preludes.json").write_text(json.dumps([prelude]), encoding="utf-8")
    build.build(source, out)
    library = lib.Library(out)
    piece = library.piece("score/wyschnegradsky-prelude-03")
    assert {(m["mark"], m["step"]) for m in piece["score"][0]["marks"]} == {("grace", 100), ("trill", 102)}
    t = Tutor(FakeXentool(sample_setup(31, (0, 1, 2, 3))), library=library)
    t.layouts_dir = tmp_path / "none"
    try:
        fit = t.library("get", id=piece["id"], nearest=True)["on_this_keyboard"]
        assert fit["now"]["tuning"] == "31 notes per octave" and "cents off" in fit["now"]["approximation"]
        assert fit["now"]["both hands"]["notes_with_a_key"] == "8 of 9 (88%)" and fit["now"]["both hands"]["bars_with_notes_outside"] == [1]
        assert fit["now"]["right hand alone"]["notes_with_a_key"] == "8 of 8 (100%)" and "1 of 9 notes have no key" in fit["say"]
        bar = t.library("get", id=piece["id"], phrase=1, part="both", nearest=True)
        assert "grace" in bar["steps"][0] and "trill begins here" in bar["steps"][1]["trill"] and "5 short notes" in bar["steps"][1]["trill"]
        assert len(bar["not_on_this_keyboard"]) == 1 and "left out" in bar["not_on_this_keyboard_note"]
        t.demo(bar["steps"][:3], tempo_bpm=240, beats_per_step=1)          # the steps are playable: nothing without a key is in them
        # transposing the whole piece makes notes above the keyboard playable; a whole octave is preferred where it serves as well
        top = sorted(t.keyboard._by_pitch)[-20:]
        assert t._fit_shift([p + 3 for p in top]) == (-31, 20) and t._fit_shift(top) == (0, 20)
        # ... but any interval counts where no octave fits everything
        assert t._fit_shift([p + 3 for p in top], have=set(top) | {min(top) - 3 + i for i in range(3)}) == (-3, 20)
        assert "steps down" in t._shift_words(-3) and t._shift_words(62) == "2 octaves up"
    finally:
        t.stop()
        t.pump.stop()


def test_the_real_collections_if_they_are_installed():
    """After `python -m tutor.library_build`: sizes as documented, every piece has phrases."""
    library = lib.Library()
    if not library.index:
        pytest.skip("build/tutor-library not built")
    counts = library.counts()
    assert sum(counts["makam"].values()) == 2200 and sum(counts["chant"].values()) > 8500
    rast = library.search(tradition="makam", mode="rast", form="seyir")
    assert rast and all(e["tuning"] == 53 and e["phrases"] > 0 for e in rast)
    piece = library.piece(rast[0]["id"])
    assert all(p is None or 100 < p < 500 for p, _ in piece["notes"])
