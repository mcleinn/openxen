"""The outline of a jazz tune (host/tutor/outline_jazz.py) on small made-up tunes: the form from the
source's labels, repeats and endings; labels that stand one section off; an unlabelled tune sectioned
from its chords; a transposed section and a sequence; the blues; key areas; a lead sheet with repeat
signs and endings; changes and lead sheet of one tune linked; the tutor's tools by section; and, if
the library is built, the forms of well-known standards."""
from __future__ import annotations

import io
import json
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))

from tutor import library as lib  # noqa: E402
from tutor import library_build as build  # noqa: E402
from tutor import outline_jazz  # noqa: E402
from tutor.sample import sample_setup  # noqa: E402
from tutor.session import Tutor, TutorError  # noqa: E402
from tutor.xt import FakeXentool  # noqa: E402

A = "C6|Am7|Dm7|G7|Em7|A7|Dm7"                  # seven bars, the eighth is the ending
A8 = A + "|G7"
BRIDGE = "E7|E7|A7|A7|D7|D7|G7|G7"              # two bars, three times more, each a fourth higher
BLUES = "F7|Bb7|F7|F7|Bb7|Bb7|F7|D7|Gm7|C7|F7|C7"


def tune(title: str, sections: list[dict], key: str | None = "C", **more) -> dict:
    return {"Title": title, "Composer": "Some One", "Rhythm": "Medium Swing", "TimeSignature": "4/4",
            **({"Key": key} if key else {}), "Sections": sections, **more}


def section(chords: str, label: str | None = None, repeats: int = 0, endings: list[str] | None = None) -> dict:
    out: dict = {"MainSegment": {"Chords": chords}}
    if label:
        out["Label"] = label
    if repeats:
        out["Repeats"] = repeats
    if endings:
        out["Endings"] = [{"Chords": e} for e in endings]
    return out


def outlines(tmp_path: Path, tunes: list[dict]) -> dict[str, dict]:
    path = tmp_path / "JazzStandards.json"
    path.write_text(json.dumps(tunes), encoding="utf-8")
    return {piece["title"]: piece["outline"] for piece in build.jazz_changes(path)}


def shape(made: dict) -> list:
    return [(s["label"], s["bars"]) for s in made["sections"]]


def test_labels_repeats_and_endings_give_the_form_and_the_bars(tmp_path):
    made = outlines(tmp_path, [
        tune("Endings", [section(A, "A", endings=["G7", "C6"]), section(BRIDGE, "B"), section(A + "|C6", "A")]),
        tune("Repeat", [section(A8, "A", repeats=1), section(BRIDGE, "B"), section("F6|Fm6|C6|A7|Dm7|G7|C6|C6", "C")]),
        tune("With Intro", [section("C6|G7|C6|G7", "i"), section(A8, "A", repeats=1), section("C6|C6", None)]),
    ])
    one = made["Endings"]
    assert one["letters"] == "source" and one["form"] == "AABA" and one["bars"] == 32 and outline_jazz.form_words(one) == "32 bars, AABA"
    assert shape(one) == [("A", [1, 8]), ("A", [9, 16]), ("B", [17, 24]), ("A", [25, 32])]
    assert one["sections"][1]["like"] == {"of": 1, "kind": "ending", "differs": [8, 8]}       # the same but for bar 8 of it
    assert one["sections"][3]["like"] == {"of": 2, "kind": "same"} and "like" not in one["sections"][2]
    assert one["sections"][2]["sequence"] == "a sequence: bars 1-2 of it, then three times more, each a fourth higher"
    assert one["sections"][0]["keys"] == ["C major"]             # its last chord, G7, comes home in the bar after it
    assert "turnaround" not in one                               # the form ends at home: no turnaround
    said = outline_jazz.overview(one)
    assert said["form"] == "32 bars, AABA" and said["sections"][1] == "2. A, bars 9-16: as section 1, another ending (bar 16)"
    assert said["sections"][2].startswith("3. B (the bridge), bars 17-24: a sequence") and said["sections"][3] == "4. A, bars 25-32: as section 2"
    assert said["practice_order"][0] == "1. A (bars 1-8; 24 of the 32 bars): roots, shells, guide tones."
    assert said["practice_order"][1].startswith("2. The bridge (bars 17-24)") and "suggestion" in said["made"] and "source's labels" in said["made"]
    assert len(json.dumps(said)) < 900
    two = made["Repeat"]
    assert two["form"] == "AABC" and shape(two)[1] == ("A", [9, 16]) and two["sections"][1]["like"]["kind"] == "same"
    assert "turnaround" not in two and two["sections"][3]["keys"] == ["C major"]
    # an intro is not part of the chorus; a short last section without a label is the coda, and said to be named here
    three = made["With Intro"]
    assert [s["label"] for s in three["sections"]] == ["intro", "A", "A", "coda"] and three["form"] == "AA" and three["bars"] == 22
    assert outline_jazz.form_words(three) == "16 bars, AA, with a 4-bar intro and a 2-bar coda" and three["letters"] == "source and computed"
    assert three["sections"][3]["computed"] and "named here" in outline_jazz.overview(three)["sections"][3]
    assert any("can wait" in step for step in three["practice_order"])


def test_labels_one_section_off_are_put_right(tmp_path):
    """The defect of the standards file: every label one section early (B A -) or late (- A B)."""
    made = outlines(tmp_path, [
        tune("Early", [section(A, "B", endings=["G7", "C6"]), section(BRIDGE, "A"), section(A + "|C6", None)]),
        tune("Late", [section(A, None, endings=["G7", "C6"]), section(BRIDGE, "A"), section(A + "|C6", "B")]),
        tune("Honest", [section(A8, "A"), section(BRIDGE, "B")]),
    ])
    for name in ("Early", "Late"):
        assert made[name]["form"] == "AABA" and made[name]["letters"].startswith("source, moved"), name
        assert "moved one section" in made[name]["made"]
    assert made["Late"]["sections"][3]["computed"]               # the label that fell off the end is found from the chords
    assert made["Honest"]["letters"] == "source" and made["Honest"]["form"] == "AB"


def test_a_tune_without_labels_is_sectioned_from_its_chords(tmp_path):
    made = outlines(tmp_path, [
        tune("Unlabelled", [section("|".join([A8, A + "|C6", BRIDGE, A + "|C6"]))]),
        tune("Short", [section("Cm7|Cm7|Fm7|Fm7|Dm7b5|G7|Cm7|Cm7|Ebm7|Ab7|Dbmaj7|Dbmaj7|Dm7b5|G7|Cm7|Dm7b5,G7")], key="Cmin"),
    ])
    one = made["Unlabelled"]
    assert one["letters"] == "computed" and one["form"] == "AABA" and shape(one)[2] == ("B", [17, 24])
    assert one["sections"][1]["like"]["kind"] == "ending" and all(s.get("computed") for s in one["sections"])
    assert "no section letters" in one["made"] and "not a published form" in one["made"]
    two = made["Short"]
    assert two["form"] == "AB" and two["bars"] == 16 and two["sections"][0]["keys"] == ["C minor"]
    assert two["sections"][1]["keys"] == ["Db major", "C minor"] and two["turnaround"] == "bar 16 (Dm7b5 G7) leads back to bar 1"


def test_a_transposed_section_is_reported_with_its_interval(tmp_path):
    moved = "F6|Dm7|Gm7|C7|Am7|D7|Gm7|C7"           # A a fourth higher
    made = outlines(tmp_path, [
        tune("Fourth Up", [section(A8, "A"), section(moved, "B"), section(A8, "A")]),
        tune("Half Step", [section("Dm7|Dm7|Dm7|Dm7", "A", repeats=1), section("Ebm7|Ebm7|Ebm7|Ebm7", "B"), section("Dm7|Dm7|Dm7|Dm7", "A")], key="Dmin"),
    ])
    one = made["Fourth Up"]
    assert one["sections"][1]["like"] == {"of": 1, "kind": "transposed", "shift": 5}
    said = outline_jazz.overview(one)
    assert said["sections"][1] == "2. B (the bridge), bars 9-16: section 1 a fourth higher"
    assert "2. The bridge (bars 9-16): section 1 a fourth higher, the same shapes moved." in said["practice_order"]
    two = made["Half Step"]
    assert two["form"] == "AABA" and two["sections"][2]["like"] == {"of": 1, "kind": "transposed", "shift": 1}
    assert two["sections"][2]["keys"] == ["stays on Ebm7"] and "like" in two["sections"][1] and two["sections"][1]["like"]["kind"] == "same"
    assert outline_jazz.interval_words(7) == "a fourth lower" and outline_jazz.interval_words(11) == "a half step lower"
    # the comparison itself: chord kinds must stay, the roots move together
    same, other = outline_jazz.tokens([["Dm7"], ["G7"], ["Cmaj7"], ["C6"]]), outline_jazz.tokens([["Em7"], ["A7"], ["Dmaj7"], ["D6"]])
    assert outline_jazz.compare(same, other) == {"kind": "transposed", "shift": 2, "share": 1.0}
    assert outline_jazz.compare(same, outline_jazz.tokens([["Em7"], ["A7"], ["Dm7"], ["Dm7"]]))["kind"] != "transposed"


def test_a_blues_is_recognised_by_its_chords(tmp_path):
    made = outlines(tmp_path, [
        tune("Riff", [section(BLUES)], key="F"),
        tune("Riff Twice", [section(BLUES.rsplit("|", 1)[0], "A", endings=["C7", "F7"])], key="F"),
        tune("Minor Riff", [section("Cm7|Cm7|Cm7|Cm7|Fm7|Fm7|Cm7|Cm7|Ab7|G7|Cm7|G7", "A")], key=None),
        tune("Twelve Bars", [section("Cmaj7|Cmaj7|Dm7|G7|Em7|A7|Dm7|G7|Cmaj7|A7|Dm7|G7", "A")]),
        tune("Slow Riff", [section("|".join(bar for chord in BLUES.split("|") for bar in (chord, chord)))], key="F"),
    ])
    assert made["Riff"]["blues"] == 12 and outline_jazz.form_words(made["Riff"]) == "12-bar blues"
    assert len(made["Riff"]["sections"]) == 1 and "read from the chords" in made["Riff"]["made"]         # a blues is not cut into eights
    assert made["Riff"]["practice_order"][0].startswith("1. Three lines of four bars")
    assert outline_jazz.form_words(made["Riff Twice"]) == "12-bar blues, 2 choruses written out (24 bars)"
    assert made["Minor Riff"]["blues"] == 12                      # home is the first chord where the source names no key
    assert "blues" not in made["Twelve Bars"] and outline_jazz.form_words(made["Twelve Bars"]) == "12 bars, A"
    assert made["Slow Riff"]["blues"] == 24 and outline_jazz.form_words(made["Slow Riff"]) == "24-bar blues"


# --- lead sheets ---

SCALE = ["C", "D", "E", "F", "G", "A", "B"]
A_TUNE = [[0, 2, 4, 2], [1, 3, 5, 3], [4, 2, 0, 2], [1, 1, 1, 1], [0, 2, 4, 2], [1, 3, 5, 3], [4, 3, 2, 1], [0, 0, 0, 0]]
B_TUNE = [[6, 5, 4, 5], [6, 5, 4, 5], [5, 4, 3, 4], [5, 4, 3, 4], [4, 3, 2, 3], [4, 3, 2, 3], [3, 2, 1, 2], [1, 1, 1, 1]]
A_CHORDS = ["C", "A", "D", "G", "E", "A", "D", "G"]
KINDS = {"C": "major-sixth", "A": "minor-seventh", "D": "minor-seventh", "G": "dominant", "E": "minor-seventh"}


def measure(n: int, degrees: list[int], chord: str | None, kind: str | None = None, left: str = "", right: str = "", octave: int = 4) -> str:
    first = ('<attributes><divisions>1</divisions><key><fifths>0</fifths><mode>major</mode></key>'
             '<time><beats>4</beats><beat-type>4</beat-type></time></attributes>') if n == 1 else ""
    harmony = f"<harmony><root><root-step>{chord}</root-step></root><kind>{kind or KINDS[chord]}</kind></harmony>" if chord else ""
    notes = "".join(f"<note><pitch><step>{SCALE[d % 7]}</step><octave>{octave + d // 7}</octave></pitch><duration>1</duration><voice>1</voice></note>"
                    for d in degrees)
    return f'<measure number="{n}">{left}{first}{harmony}{notes}{right}</measure>'


def sheet(title: str, measures: list[str], composer: str = "Some One") -> str:
    return (f'<?xml version="1.0"?><score-partwise><movement-title>{title}</movement-title><identification>'
            f'<creator type="composer">{composer}</creator></identification><part id="P1">{"".join(measures)}</part></score-partwise>')


def volta(number: int, kind: str) -> str:
    return f'<ending number="{number}" type="{kind}"/>'


def little_song() -> str:
    """|: A, seven bars, first ending :| second ending | B, eight bars, a double bar | A again."""
    bars = [measure(k + 1, A_TUNE[k], A_CHORDS[k], left='<barline location="left"><repeat direction="forward"/></barline>' if k == 0 else "")
            for k in range(7)]
    bars.append(measure(8, [1, 1, 1, 1], "G", left=f'<barline location="left">{volta(1, "start")}</barline>',
                        right=f'<barline location="right">{volta(1, "stop")}<repeat direction="backward"/></barline>'))
    bars.append(measure(9, [0, 0, 0, 0], "C", left=f'<barline location="left">{volta(2, "start")}</barline>',
                        right=f'<barline location="right">{volta(2, "discontinue")}</barline>'))
    chords = ["E", "E", "A", "A", "D", "D", "G", "G"]
    bars += [measure(10 + k, B_TUNE[k], chords[k], "dominant",
                     right='<barline location="right"><bar-style>light-light</bar-style></barline>' if k == 7 else "") for k in range(8)]
    bars += [measure(18 + k, A_TUNE[k], A_CHORDS[k] if k < 7 else "C") for k in range(8)]
    return sheet("Little Song", bars)


def test_a_lead_sheet_with_repeat_signs_and_endings():
    piece = build.leadsheet(little_song().encode())
    made = piece["outline"]
    assert made["letters"] == "print and computed" and made["form"] == "AABA" and made["bars"] == 32 and "twice" not in made
    assert shape(made) == [("A", [1, 8]), ("A", [9, 16]), ("B", [17, 24]), ("A", [25, 32])]
    # the second A is the first seven printed bars again and the second ending
    assert [s["written"] for s in made["sections"]] == [[[1, 8]], [[1, 7], [9, 9]], [[10, 17]], [[18, 25]]]
    assert made["sections"][1]["like"] == {"of": 1, "kind": "varied"} and made["sections"][3]["like"]["of"] == 1
    assert made["sections"][2]["notes"] == [[36, 67]] and made["sections"][1]["notes"] == [[0, 27], [32, 35]]
    assert made["sections"][2]["chords"] == [[9, 16]] and made["sections"][0]["keys"] == ["C major"]
    said = outline_jazz.overview(made)
    assert said["sections"][1].startswith("2. A, bars 9-16 (printed 1-7, 9): the melody of section 1, varied")
    assert said["sections"][2].startswith("3. B (the bridge), bars 17-24") and "repeat signs, endings, double bars" in said["made"]
    assert "computed from melody and chords" in said["made"] and said["practice_order"][0] == "1. A (bars 1-8; 24 of the 32 bars): phrase by phrase."
    assert outline_jazz.unfold([{}, {"ending": [1], "backward": True}, {"ending": [2]}, {}]) == [0, 1, 0, 2, 3]


def test_a_lead_sheet_without_marks_a_transposed_strain_and_a_whole_form_printed_twice():
    # no marks at all: A A B A found from the melody, the last A with another ending
    bars = [measure(k + 1, (A_TUNE + A_TUNE + B_TUNE + A_TUNE[:6] + [[4, 4, 4, 4], [0, 0, 0, 0]])[k], None) for k in range(32)]
    made = build.leadsheet(sheet("Plain", bars).encode())["outline"]
    assert made["letters"] == "computed" and made["form"] == "AABA" and "marks no sections" in made["made"]
    assert made["sections"][1]["like"] == {"of": 1, "kind": "same"} and made["sections"][3]["like"] == {"of": 1, "kind": "varied"}
    assert "chords" in made["sections"][0] and made["sections"][0]["chords"] == [] and "keys" not in made["sections"][0]
    # the second strain is the first a fourth higher
    higher = [[d + 4 for d in row] for row in A_TUNE]           # C D E F G A -> G A B C D E: the same steps
    made = build.leadsheet(sheet("Moved", [measure(k + 1, (A_TUNE + higher)[k], None) for k in range(16)]).encode())["outline"]
    assert made["form"] == "AB" and made["sections"][1]["like"] == {"of": 1, "kind": "transposed", "shift": 7}
    assert outline_jazz.overview(made)["sections"][1] == "2. B, bars 9-16: the melody of section 1 a fifth higher"
    # a pickup bar is not counted, and the whole tune under one repeat sign is given once
    pickup = '<measure number="0" implicit="yes"><attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>' \
             '<note><pitch><step>G</step><octave>3</octave></pitch><duration>1</duration><voice>1</voice></note></measure>'
    body = [measure(k + 2, (A_TUNE + B_TUNE)[k], None, right='<barline location="right"><repeat direction="backward"/></barline>' if k == 15 else "")
            for k in range(16)]
    made = build.leadsheet(sheet("Upbeat", [pickup] + body).encode())["outline"]
    assert made["form"] == "AB" and made["bars"] == 16 and made["twice"] and "comes twice in the print" in made["made"]
    assert made["sections"][0]["written"] == [[0, 8]] and made["sections"][0]["notes"][0][0] == 0


# --- the library and the tutor ---

JAZZ = [
    tune("Little Song", [section(A, "A", endings=["G7", "C6"]), section(BRIDGE, "B"), section(A + "|C6", "A")]),
    tune("Short Bridge", [section("Dm7|G7|Cmaj7|Cmaj7", "A", repeats=1), section("Gm7|C7", "B"), section("Dm7|G7|Cmaj7|Cmaj7", "A")]),
    tune("Riff", [section(BLUES)], key="F"),
    tune("Other Song", [section(A8, "A"), section(BRIDGE, "B")], Composer="Another Person"),
]


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("jazzsrc")
    (root / "jazz").mkdir()
    (root / "jazz" / "JazzStandards.json").write_text(json.dumps(JAZZ), encoding="utf-8")
    with zipfile.ZipFile(root / "jazz" / "OpenEWLD.zip", "w") as z:
        for name, xml in (("Little_Song", little_song()),
                          ("Other_Song", sheet("Other Song", [measure(k + 1, (A_TUNE + B_TUNE)[k], None) for k in range(16)], "Somebody Else"))):
            inner = io.BytesIO()
            with zipfile.ZipFile(inner, "w") as mxl:
                mxl.writestr(f"{name}.xml", xml)
            z.writestr(f"OpenEWLD-master/dataset/x/{name}/{name}.mxl", inner.getvalue())
    out = tmp_path_factory.mktemp("jazzlib")
    assert build.build(root, out) == {"jazz": 4, "jazz-melodies": 2}
    return out


def test_changes_and_lead_sheet_of_one_tune_are_linked(built):
    library = lib.Library(built)
    changes, melody = library.piece("jazz/little-song"), library.piece("jazz/melody-little-song")
    assert changes["outline"]["same_tune"] == {"id": "jazz/melody-little-song", "what": "the lead sheet with the melody", "form": "32 bars, AABA",
                                               "agrees": "agree", "says": "the same form"}
    assert melody["outline"]["same_tune"]["id"] == "jazz/little-song" and melody["outline"]["same_tune"]["what"] == "the chord changes"
    # the same title by another composer is not the same tune
    assert "same_tune" not in library.piece("jazz/other-song")["outline"] and "same_tune" not in library.piece("jazz/melody-other-song")["outline"]
    # forms that differ are said to differ, not made to fit
    a, b = changes["outline"], library.piece("jazz/melody-other-song")["outline"]
    assert outline_jazz.agreement(a, b)[0] == "differ"
    sixteen = {"form": "AB", "eights": "ABAC", "sections": [{"label": "A", "length": 16}, {"label": "B", "length": 16}]}
    eight = {"form": "ABAC", "sections": [{"label": x, "length": 8} for x in "ABAC"]}
    assert outline_jazz.agreement(sixteen, eight)[0] == "agree in units"
    # the index carries the form, and search finds by it
    assert {e["id"]: e.get("structure") for e in library.index} == {
        "jazz/little-song": "AABA", "jazz/short-bridge": "AABA", "jazz/riff": "12-bar blues", "jazz/other-song": "AB",
        "jazz/melody-little-song": "AABA", "jazz/melody-other-song": "AB"}
    assert [e["id"] for e in library.search(tradition="jazz", form="blues")] == ["jazz/riff"]
    assert {e["id"] for e in library.search(form="AABA")} == {"jazz/little-song", "jazz/short-bridge", "jazz/melody-little-song"}
    assert {e["id"] for e in library.search(form="AB")} == {"jazz/other-song", "jazz/melody-other-song"}          # letters are the whole form
    assert [e["id"] for e in library.search(bars=12)] == ["jazz/riff"] and len(library.search(form="swing")) == 4      # the style still searches
    assert {e["id"] for e in library.search(bars=32)} == {"jazz/little-song", "jazz/melody-little-song"}        # the lead sheet as played


def test_the_tutor_gives_the_form_and_a_tune_by_section(built):
    t = Tutor(FakeXentool(sample_setup(31, (0, 1, 2, 3, 4))), library=lib.Library(built))
    try:
        head = t.library("get", id="jazz/little-song")
        assert head["outline"]["form"] == "32 bars, AABA" and len(head["outline"]["sections"]) == 4 and "steps" not in head
        assert head["outline"]["same_tune"].startswith("the lead sheet with the melody: jazz/melody-little-song (32 bars, AABA)")
        assert "section = a letter" in head["note"] and len(json.dumps(head["outline"])) < 1000
        # the bridge by name, by letter and by number, with the options the jazz path has
        bridge = t.library("get", id="jazz/little-song", section="bridge", voicing="shell")
        assert [s["label"] for s in bridge["steps"]] == ["E7", "E7", "A7", "A7", "D7", "D7", "G7", "G7"] and bridge["voicing"] == "shell"
        assert bridge["section"] == "3 (B), bars 17-24" and bridge["of"] == "4 sections; 32 bars, AABA" and len(bridge["steps"][0]["notes"]) == 3
        assert "Next: section 4." in bridge["note"] and "improvise with id and section" in bridge["note"]
        assert t.library("get", id="jazz/little-song", section="B", voicing="root")["steps"] == t.library("get", id="jazz/little-song", section=3, voicing="root")["steps"]
        first, second = (t.library("get", id="jazz/little-song", section=name) for name in ("A", "A2"))
        assert first["section"] == "1 (A), bars 1-8" and first["comes_again"] == "bars 9-16 (another ending), bars 25-32"
        assert second["section"] == "2 (A), bars 9-16" and second["steps"][-1]["label"] == "C6" and first["steps"][-1]["label"] == "G7"
        assert t.library("get", id="jazz/little-song", section=4)["note"].count("This is the last section.") == 1
        # sections by phrase number still work as before
        assert t.library("get", id="jazz/little-song", phrase=3)["section"] == 3
        with pytest.raises(TutorError, match="there is no section 'C'. Sections: 1 \\(A, bars 1-8\\)"):
            t.library("get", id="jazz/little-song", section="C")
        # a blues by its changes gets the harmonic seventh, like one by its title
        assert "harmonic seventh" in t.library("get", id="jazz/riff", section=1)["sevenths"]
        assert t.library("get", id="jazz/riff")["outline"]["form"] == "12-bar blues"
        # the lead sheet: the melody of a section, or its chords
        sheet_head = t.library("get", id="jazz/melody-little-song")
        assert sheet_head["outline"]["form"] == "32 bars, AABA" and sheet_head["phrase_count"] > 0 and "section = a letter" in sheet_head["note"]
        tune_b = t.library("get", id="jazz/melody-little-song", section="bridge")
        assert tune_b["part"] == "melody" and len(tune_b["steps"]) == 32 and tune_b["steps"][0]["note"].startswith("B4")
        again = t.library("get", id="jazz/melody-little-song", section="A2")
        assert len(again["steps"]) == 32 and again["steps"][-1]["note"].startswith("C4") and again["comes_again"] == "bars 1-8, bars 25-32"
        chords = t.library("get", id="jazz/melody-little-song", section="bridge", part="changes", voicing="root")
        assert [s["label"] for s in chords["steps"]] == ["E7", "E7", "A7", "A7", "D7", "D7", "G7", "G7"]
        found = t.library("search", tradition="jazz", form="AABA", bars=32)
        assert found["matches"] == 2 and found["pieces"][0]["structure"] == "AABA"
    finally:
        t.pump.stop()


def test_improvise_on_a_section_of_a_tune(built):
    fake = FakeXentool(sample_setup(31, (0, 1, 2, 3, 4)))
    t = Tutor(fake, library=lib.Library(built))
    try:
        kb = t.keyboard

        def player():
            time.sleep(0.3 + 2 * 0.25)                   # the count-in: two beats at 240
            for name in ("G4", "C4"):                    # on Gm7, then on C7
                key = kb.keys_for_pitch(t._pitch(name)[0])[0]
                fake.press(key.board, key.key)
                time.sleep(0.1)
                fake.release(key.board, key.key)
                time.sleep(0.9)

        threading.Thread(target=player, daemon=True).start()
        began = time.monotonic()
        out = t.improvise(id="jazz/short-bridge", section="bridge", choruses=2, tempo_bpm=240, count_in=2, rule="chord_tone_first", voicing="shell")
        assert 4.3 < time.monotonic() - began < 5.8                               # two beats, then twice two bars of four beats at 240
        assert out["played_on"] == "Short Bridge, section 3 (B), bars 9-10, 2 times" and out["chords"] == 4
        assert [c["chord"] for c in out["per_chord"]] == ["Gm7", "C7", "Gm7", "C7"] and out["per_chord"][0]["first_note"].endswith("root")
        assert out["rule_met"] == "2 of 2 chords started on a chord tone" and len(fake.sounded) == 4 * 3
        whole = t._tune_changes("jazz/short-bridge", None, "root")
        assert whole[1] == "Short Bridge, the whole form (14 bars)" and len(whole[0]) == 14
        with pytest.raises(TutorError, match="either changes or id"):
            t.improvise([{"notes": ["C4"], "beats": 4}], id="jazz/short-bridge")
        with pytest.raises(TutorError, match="there is no tune 'jazz/nothing'"):
            t.improvise(id="jazz/nothing")
        with pytest.raises(TutorError, match="there is no section 'Q'"):
            t.improvise(id="jazz/short-bridge", section="Q")
        with pytest.raises(TutorError, match="changes is empty"):
            t.improvise()
    finally:
        t.pump.stop()


# --- the real library ---

def test_forms_of_well_known_standards_in_the_real_library():
    """Bar counts and forms as players know them; the letters are the source's unless noted."""
    library = lib.Library()
    if not any(e["id"] == "jazz/autumn-leaves" for e in library.index):
        pytest.skip("the library is not built")
    if "outline" not in library.piece("jazz/autumn-leaves"):
        pytest.skip("the library was built before jazz tunes had outlines")

    def made(piece_id: str) -> dict:
        return library.piece(piece_id)["outline"]

    known = {"jazz/autumn-leaves": (32, "AABC", "source"), "jazz/oleo": (32, "AABA", "source"), "jazz/anthropology": (32, "AABA", "source"),
             "jazz/so-what": (32, "AABA", "source"), "jazz/impressions": (32, "AABA", "source"), "jazz/misty": (32, "AABA", "source"),
             "jazz/all-of-me": (32, "ABAC", "source"), "jazz/how-high-the-moon": (32, "ABAC", "source"),
             "jazz/song-for-my-father": (24, "AAB", "source"), "jazz/alone-together": (44, "AABA", "source"),
             "jazz/my-funny-valentine": (36, "AABC", "source"),
             # the labels stand one section early in the file and are moved
             "jazz/body-and-soul": (32, "AABA", "source, moved"), "jazz/satin-doll": (32, "AABA", "source, moved"),
             "jazz/all-the-things-you-are": (36, "ABCD", "source, moved"), "jazz/on-green-dolphin-street": (32, "ABAC", "source, moved"),
             "jazz/girl-from-ipanema-the": (40, "AABA", "source, moved"), "jazz/confirmation": (32, "AABA", "source, moved"),
             # no labels in the source: computed
             "jazz/blue-bossa": (16, "AB", "computed"), "jazz/summertime": (16, "AB", "computed"), "jazz/lady-bird": (16, "AB", "computed")}
    for piece_id, (bars, form, letters) in known.items():
        o = made(piece_id)
        assert (o["bars"], o["form"], o["letters"]) == (bars, form, letters), piece_id
    for piece_id in ("jazz/billie-s-bounce", "jazz/now-s-the-time", "jazz/blue-monk", "jazz/straight-no-chaser", "jazz/mr-p-c", "jazz/tenor-madness"):
        assert made(piece_id)["blues"] == 12 and made(piece_id)["bars"] == 12, piece_id
    assert made("jazz/all-blues")["blues"] == 24 and made("jazz/freddie-freeloader")["blues"] == 12
    assert "blues" not in made("jazz/solar") and "blues" not in made("jazz/giant-steps")
    # what repeats: the bridge of rhythm changes is a sequence, the bridge of So What is the A a half step up
    assert made("jazz/oleo")["sections"][2]["sequence"] == "a sequence: bars 1-2 of it, then three times more, each a fourth higher"
    assert made("jazz/so-what")["sections"][2]["like"] == {"of": 1, "kind": "transposed", "shift": 1}
    assert made("jazz/body-and-soul")["sections"][2]["keys"] == ["D major"] and made("jazz/body-and-soul")["sections"][0]["keys"] == ["Db major"] and made("jazz/autumn-leaves")["sections"][0]["keys"] == ["Bb major", "G minor"]
    # every tune has an outline that names how it was made, and the tutor's view of a standard stays small
    sizes = []
    for entry in library.index:
        if entry["tradition"] == "jazz":
            piece = library.piece(entry["id"])
            assert piece["outline"]["made"] and piece["outline"]["sections"], entry["id"]
            assert piece["outline"]["bars"] == piece["outline"]["sections"][-1]["bars"][1], entry["id"]
            if not piece["notes"]:
                assert piece["outline"]["bars"] == piece["bars"], entry["id"]
                sizes.append(len(json.dumps(outline_jazz.overview(piece["outline"]))))
    assert sorted(sizes)[len(sizes) // 2] < 700
    # a standard and its lead sheet name each other
    assert made("jazz/blue-moon")["same_tune"]["id"] == "jazz/melody-blue-moon" and made("jazz/melody-blue-moon")["same_tune"]["id"] == "jazz/blue-moon"
