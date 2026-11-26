"""The rhythm library: conversion of the researched reference (on a small made-up one), how
tabla bols are sounded, a cycle played with its own strokes on a drum that only records what
it is sent, what the player taps, and the drone for a raga."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
from tutor import library as lib  # noqa: E402
from tutor import percussion  # noqa: E402
from tutor import rhythm as R  # noqa: E402
from tutor import rhythm_build as B  # noqa: E402
from tutor.osc import Sender  # noqa: E402
from tutor.sample import sample_setup  # noqa: E402
from tutor.session import Tutor, TutorError  # noqa: E402
from tutor.xt import FakeXentool  # noqa: E402

CLASSES = {"_source": "CompMusic", "KI": ["KA", "KAT", "KE", "KI", "KII"], "GE": ["GA", "GHE", "GE"], "TA": ["TA", "TI", "RA"],
           "NA": ["N", "NA", "TAA", "TU"], "DIN": ["DI", "DIN"], "KDA": ["KDA", "KRA"], "DHA": ["DHA"], "DHIN": ["DHIN"], "TIN": ["TIN"]}
TALA = {
    "_about": {"generated": "test"},
    "hindustani": [
        {"name": "Testtal", "aliases": ["Tt", "Test Taal"], "matras": 4, "vibhag": [2, 2], "tali_khali": ["X", "0"],
         "theka": ["Dha", "DhaGe", ["-", "Dhin"], "TiRaKiTa"],
         "variants": [{"name": "plain", "theka": ["Dha", "Tin", "Na", "Kat"], "source": "s1"},
                      {"name": "prose", "theka": "see elsewhere", "source": "s2"},
                      {"name": "three sections", "vibhag": [1, 1, 2], "tali_khali": ["X", "2", "3"], "theka": "same bols", "source": "s3"}],
         "sources": ["a", "b"], "agreement": "Two sources agree. CONFLICT: a third has Na on matra 2."},
        {"name": "Wavetal", "aliases": [], "matras": 3, "vibhag": [1, 2], "tali_khali": ["0", "2"], "theka": ["Tin", "Din", "Kra"],
         "variants": [], "sources": ["a"], "agreement": "NO AGREEMENT: every source differs."},
    ],
    "carnatic": [
        {"name": "chatusra jati triputa tala", "popular_name": "adi", "angas": ["L", "D", "D"], "laghu_beats": 4, "aksharas": 8,
         "kriya": ["clap", "finger:little", "finger:ring", "finger:middle", "clap", "wave", "clap", "wave"], "kriya_derived": False,
         "kriya_note": "stated", "common": True, "sources": ["k"]},
        {"name": "sankeerna chapu", "popular_name": "sankeerna chapu", "angas": "4+5 beats (one source)", "aksharas": 9, "kriya": None,
         "kriya_note": "none found", "common": False, "sources": ["k"]},
    ],
    "gati": [{"name": "tisra", "per_beat": 3, "syllables": {"x": "ta ki ta"}, "sources": []}],
    "solkattu_lessons": [
        {"name": "lesson 1", "tala": "adi", "gati": "chatusra", "syllables": ["THA", ",", "THI", "NA", "(THA)"],
         "strokes": ["Tha", None, "Thi", None, "Tha"], "speeds": "three speeds", "sources": ["l"]},
        {"name": "lesson in words", "tala": "adi", "gati": "chatusra", "syllables": ["tha ka doom doom"], "strokes": None, "speeds": "-", "sources": []},
    ],
    "syllable_to_stroke": {"nam / na": {"stroke": "Num"}, "ka": {"stroke": "context-dependent"}, "ki": {"stroke": "Thi"}},
    "usul": [
        {"name": "aksak", "symbtr_name": "aksak", "display": "Aksak", "pulses": 9, "unit": 8, "grouping": [2, 2, 2, 3],
         "strokes": [{"at": 0, "stroke": "dum", "dur": 2}, {"at": 2, "stroke": "te", "dur": 1}, {"at": 3, "stroke": "ke", "dur": 1},
                     {"at": 4, "stroke": "dum", "dur": 2}, {"at": 6, "stroke": "tek", "dur": 2}, {"at": 8, "stroke": "tek", "dur": 1}],
         "sources": ["t"], "confidence": "confirmed by two independent sources", "notes": ""},
        {"name": "ciftetest", "symbtr_name": "ciftetest", "display": "Çifte Test", "pulses": 4, "unit": 4, "grouping": [2, 2],
         "strokes": [{"at": 0, "stroke": None, "dur": 2}, {"at": 2, "stroke": "tek", "dur": 1.5}, {"at": 3.5, "stroke": "hek", "dur": 0.5}],
         "sources": ["m"], "confidence": "conflicting: one source says four strokes, another three", "notes": ""},
    ],
    "tabla_bol_timbre_classes": CLASSES,
}


@pytest.fixture()
def library(tmp_path):
    (tmp_path / "tala.json").write_text(json.dumps(TALA), encoding="utf-8")
    data = B.build(tmp_path / "tala.json", tmp_path / "out")
    assert R.load(tmp_path / "out" / "rhythm.json") == 7
    yield data
    R.load()


def test_conversion_of_a_small_reference(library):
    p = library["patterns"]
    assert library["counts"] == {"hindustani theka": 2, "carnatic tala": 2, "carnatic lesson": 1, "makam usul": 2}
    t = p["testtal"]
    # a matra with several bols is split evenly; "-" is a rest and takes its share
    assert [(s["at"], s["stroke"], s["dur"]) for s in t["strokes"]] == [
        (0, "Dha", 1), (1, "Dha", 0.5), (1.5, "Ge", 0.5), (2.5, "Dhin", 0.5), (3, "Ti", 0.25), (3.25, "Ra", 0.25), (3.5, "Ki", 0.25), (3.75, "Ta", 0.25)]
    assert t["strokes"][0]["loud"] > t["strokes"][1]["loud"] > t["strokes"][2]["loud"]
    assert (t["pulses"], t["beats"], t["onsets"], t["accents"]) == (4, 4, [0, 1, 2, 3], [0]) and t["tradition"] == "hindustani"
    assert [(s["at"], s["length"], s["mark"], s["gesture"]) for s in t["sections"]] == [(0, 2, "X", "clap"), (2, 2, "0", "wave")]
    assert t["what"] == "4 matras, 2+2: clap on 1, wave on 3"
    # sourced by two, with a marked conflict: kept, and the mark with it
    assert t["confidence"] == "confirmed by two or more sources" and "third has Na" in t["conflict"] and t["sources"] == ["a", "b"]
    plain, prose, three = t["variants"]
    assert [s["stroke"] for s in plain["strokes"]] == ["Dha", "Tin", "Na", "Kat"] and "strokes" not in prose and "not written bol by bol" in prose["note"]
    assert three["accents"] == [0, 1, 2] and len(three["strokes"]) == 8
    w = p["wavetal"]
    assert w["confidence"] == "conflicting" and w["accents"] == [1] and w["what"] == "3 matras, 1+2: it begins with a wave; clap on 2"

    adi = p["chatusra_jati_triputa_tala"]
    assert adi["aliases"] == ["adi"] and adi["accents"] == [0, 4, 6] and adi["gestures"][1] == "little finger" and adi["strokes"] == []
    assert [s["name"] for s in adi["sections"]] == ["laghu", "drutam", "drutam"] and adi["confidence"] == "stated by a source"
    chapu = p["sankeerna_chapu"]
    assert [s["length"] for s in chapu["sections"]] == [4, 5] and "gestures" not in chapu and "no source gives the hand gestures" in chapu["what"]

    lesson = p["lesson_1"]
    # the syllable in brackets lands on the first beat of the next round; "na" has a stroke by the syllable table
    assert lesson["pulses"] == 4 and [(s["at"], s["stroke"], s["say"]) for s in lesson["strokes"]] == [(0, "Tha", "Tha"), (2, "Thi", "Thi"), (3, "Num", "Na")]
    assert lesson["ending"]["stroke"] == "Tha" and lesson["onsets"] == [0, 2, 3]
    assert [entry["name"] for entry in library["lessons_without_strokes"]] == ["lesson in words"]
    assert library["syllable_strokes"] == {"nam": "Num", "na": "Num", "ki": "Thi"}

    aksak = p["aksak"]
    assert [(s["at"], s["stroke"], s["dur"]) for s in aksak["strokes"]][:3] == [(0, "dum", 2), (2, "te", 1), (3, "ke", 1)]
    assert aksak["onsets"] == [0, 2, 3, 4, 6, 8] and aksak["accents"] == [0, 2, 4, 6] and aksak["confidence"] == "confirmed by two independent sources"
    cifte = p["ciftetest"]
    assert cifte["confidence"] == "conflicting" and "another three" in cifte["conflict"] and cifte["unnamed_strokes"]
    assert [s["at"] for s in cifte["strokes"]] == [0, 2, 3.5] and cifte["strokes"][0]["stroke"] is None

    # found by any of its names, accents and brackets aside; a sourced cycle comes before a built-in one of the same name
    assert R.find("Tt")[0] == "testtal" and R.find("test-taal")[0] == "testtal" and R.find("Çifte Test (4/4)")[0] == "ciftetest"
    assert R.find("Adi")[0] == "chatusra_jati_triputa_tala" and R.find("tresillo")[1] is R.PATTERNS["tresillo"] and R.find("nope") is None
    assert "testtal" in R.close_names("testal")


def test_every_bol_has_a_sound(library):
    bols = {s["stroke"] for c in library["patterns"].values() if c["tradition"] == "hindustani"
            for group in [c["strokes"]] + [v.get("strokes", []) for v in c["variants"]] for s in group}
    assert bols == {"Dha", "Ge", "Dhin", "Ti", "Ra", "Ki", "Ta", "Tin", "Na", "Kat", "Din", "Kra"}
    table, silent = percussion.tabla_bols(bols, CLASSES)
    assert not silent and set(table) == bols == set(library["tabla_bols"]) and library["silent_bols"] == []
    assert all(set(how["samples"]) <= set(percussion.TABLA_SAMPLES) for how in table.values())
    assert table["Dha"] == {"samples": ["dha"], "how": "recorded"}
    # no recording of its own: both drums together, and that is said to be this project's choice
    assert table["Dhin"]["samples"] == ["ge", "tin"] and table["Dhin"]["how"] == "composed" and "this project's choice" in table["Dhin"]["note"]
    assert table["Kat"]["samples"] == ["ka"] and table["Kat"]["how"] == "same timbre class" and table["Ra"]["samples"] == ["ta"]
    assert table["Din"]["how"] == table["Kra"]["how"] == "stand-in" and table["Ki"]["samples"] == ["ka"]
    assert percussion.tabla_bol("Tu", CLASSES)["samples"] == ["tun"] and percussion.tabla_bol("Dhaa", CLASSES)["samples"] == ["dha"]
    assert percussion.tabla_bol("Xyz", CLASSES) is None
    # the kit's table for the patch: lower-case bols, the samples as symbols
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host" / "synth"))
    import tabla_kit
    kit = {"strokes": {"ge": {"samples": ["ge_rr1.wav"], "gain_db": 17.1}, "ki": {"alias_of": "ka"}}, "composites": {"dha": {"samples": ["dha_rr1.wav"], "gain_db": 15.35}}}
    samples = tabla_kit.samples_of(kit)
    assert samples == {"ge": (17.1, ["ge_rr1.wav"]), "dha": (15.35, ["dha_rr1.wav"])}
    bol_table, _ = tabla_kit.bol_table(TALA)
    text = tabla_kit.kit_scd(samples, bol_table)
    assert 'ge: [17.1, ["ge_rr1.wav"]]' in text and "dhin: [\\ge, \\tin]" in text and "kat: [\\ka]" in text
    assert all(bol.lower() in text for bol in set(percussion.USUL_ON_TABLA.values()) | set(percussion.GENERIC["tabla"]))


class Drum(Sender):
    """A drum that keeps the time of every stroke."""

    def __init__(self):
        super().__init__("127.0.0.1", 9)        # the discard port: nothing listens, nothing fails
        self.at: list[float] = []

    def send(self, address, *args):
        self.at.append(time.monotonic())
        super().send(address, *args)


def test_a_theka_on_the_tabla_and_what_is_tapped(library):
    fake = FakeXentool(sample_setup(53, (0,)))
    tabla = Drum()
    tutor = Tutor(fake, tabla=tabla)
    try:
        # demo with sound auto: the count-in as clicks, then the theka's own bols in order at their places
        out = tutor.rhythm("demo", pattern="Tt", tempo_bpm=200, cycles=2)
        assert out["demonstrated"] == "testtal" and out["sound"] == "tabla" and len(fake.clicks) == 4
        bols = ["Dha", "Dha", "Ge", "Dhin", "Ti", "Ra", "Ki", "Ta"]
        assert [m[:2] for m in tabla.sent] == [("/tabla/stroke", b) for b in bols] * 2
        beat = 60 / 200
        places = [0, 1, 1.5, 2.5, 3, 3.25, 3.5, 3.75]
        due = [(c * 4 + p) * beat for c in range(2) for p in places]
        assert [t - tabla.at[0] for t in tabla.at] == pytest.approx(due, abs=0.04)
        assert tabla.sent[0][2] > tabla.sent[1][2]                      # the first beat is the loudest
        # the result says how well it is sourced and what the sound is made of
        assert out["confidence"] == "confirmed by two or more sources" and "third has Na" in out["sources_disagree"]
        assert "Dhin" in out["sound_note"] and "this project's choice" in out["sound_note"]

        # play: the theka is the pulse (no clicks after the count-in); the player taps every matra, or the claps, or the strokes
        fake.clicks.clear()
        tabla.sent.clear()
        played = tutor.rhythm("play", pattern="testtal", tempo_bpm=200, cycles=1)
        assert played["due"] == 4 and played["tapped"] == "every beat" and len(fake.clicks) == 4 and len(tabla.sent) == 8
        assert tutor.rhythm("play", pattern="testtal", tempo_bpm=200, cycles=2, tap="claps")["due"] == 2
        assert tutor.rhythm("play", pattern="testtal", tempo_bpm=200, cycles=1, tap="strokes")["due"] == 8
        with pytest.raises(TutorError, match="tap must be"):
            tutor.rhythm("play", pattern="testtal", tap="feet")
        # a variant, by its number among those that can be played
        tabla.sent.clear()
        assert tutor.rhythm("demo", pattern="testtal", tempo_bpm=200, cycles=1, variant=1)["variant"] == "plain"
        assert [m[1] for m in tabla.sent] == ["Dha", "Tin", "Na", "Kat"]
        with pytest.raises(TutorError, match="2 variant"):
            tutor.rhythm("demo", pattern="testtal", variant=5)

        # an usul on the tabla is a stand-in and says so; a stroke the source does not name is a click
        fake.clicks.clear()
        tabla.sent.clear()
        usul = tutor.rhythm("demo", pattern="ciftetest", tempo_bpm=200, cycles=1)
        assert [m[1] for m in tabla.sent] == ["Na", "Dha"] and len(fake.clicks) == 4 + 1
        assert "stand-in" in usul["sound_note"] and usul["confidence"] == "conflicting" and "unnamed_strokes" in usul
        tabla.sent.clear()
        tutor.rhythm("demo", pattern="aksak", tempo_bpm=200, cycles=1)
        assert [m[1] for m in tabla.sent] == ["Ge", "Te", "Ke", "Ge", "Na", "Na"]
        # a built-in pattern on the tabla, and a Carnatic tala (no strokes of its own, no mridangam here: clicks)
        tabla.sent.clear()
        tutor.rhythm("demo", pattern="tresillo", tempo_bpm=200, cycles=1, sound="tabla")
        assert [m[1] for m in tabla.sent] == ["Dha", "Te", "Na"]
        assert tutor.rhythm("demo", pattern="adi", tempo_bpm=200, cycles=1)["sound"] == "click"
    finally:
        tutor.pump.stop()


def test_tap_places():
    tala = {"pulses": 16, "beats": 16, "onsets": list(range(16)), "accents": [0, 4, 12], "strokes": [{"at": 0}, {"at": 1.5}, {"at": 1.5}]}
    assert R.tap_onsets(tala, None) == list(range(16)) and R.tap_onsets(tala, "beats") == list(range(16))
    assert R.tap_onsets(tala, "claps") == [0, 4, 12] and R.tap_onsets(tala, "strokes") == [0, 1.5]
    clave = R.PATTERNS["son_clave_3_2"]
    assert R.tap_onsets(clave, "beats") == [0, 4, 8, 12] and R.tap_onsets(clave, "claps") == [0]
    with pytest.raises(ValueError, match="no strokes"):
        R.tap_onsets(clave, "strokes")
    assert R.targets({**tala, "onsets": R.tap_onsets(tala, "claps")}, 1, 10.0, 0.5) == [10.0, 12.0, 16.0]


def test_without_a_drum_auto_is_the_click_and_a_lesson_goes_to_the_mridangam(library):
    plain = Tutor(FakeXentool(sample_setup(53, (0,))))
    try:
        out = plain.rhythm("demo", pattern="testtal", tempo_bpm=200, cycles=1)
        # every stroke of the theka as a click, after the count-in
        assert out["sound"] == "click" and len(plain.client.clicks) == 4 + 8 and "no tabla is set up" in out["sound_note"]
        with pytest.raises(TutorError, match="no tabla is set up"):
            plain.rhythm("demo", pattern="testtal", sound="tabla")
        listed = plain.rhythm()
        assert listed["sounds"] == ["click"] and "tresillo" in listed["patterns"]
        cycles = listed["cycles"]
        assert cycles["hindustani_talas"]["count"] == 2 and cycles["hindustani_talas"]["conflicting"] == "wavetal 3"
        assert cycles["usul"]["confirmed by two independent sources"] == "aksak 9" and cycles["mridangam_lessons"]["count"] == 1
        detail = plain.rhythm("patterns", pattern="Test Taal")
        assert detail["pattern"] == "testtal" and detail["matras"] == 4 and detail["also_called"] == ["Tt", "Test Taal"]
        assert detail["sections"] == ["matras 1-2, clap (sam): Dha DhaGe", "matras 3-4, wave (khali): -Dhin TiRaKiTa"]
        assert "third has Na" in detail["sources_disagree"] and detail["sources"] == ["a", "b"] and detail["sound"]["auto"] == "click"
        assert [v.get("variant") for v in detail["variants"]] == [1, None, 2] and detail["variants"][0]["sections"][0].endswith("Dha Tin")
        adi = plain.rhythm("patterns", pattern="adi")
        assert adi["sections"][0] == "beats 1-4 (laghu): clap, little finger, ring finger, middle finger" and adi["beats"] == 8
        assert plain.rhythm("patterns", pattern="aksak")["sections"][0] == "pulses 1-2: dum(2)"
        assert plain.rhythm("patterns", pattern="tresillo")["taps_per_cycle"] == 3
    finally:
        plain.pump.stop()
    drum = Drum()
    tutor = Tutor(FakeXentool(sample_setup(53, (0,))), mridangam=drum)
    try:
        out = tutor.rhythm("demo", pattern="lesson 1", tempo_bpm=200, cycles=2)
        # the lesson's strokes, twice, and the closing stroke on the first beat after
        assert out["sound"] == "mridangam" and [m[:2] for m in drum.sent] == [("/mridangam/stroke", s) for s in ["Tha", "Thi", "Num"] * 2 + ["Tha"]]
        assert drum.at[-1] - drum.at[0] == pytest.approx(8 * 60 / 200, abs=0.04)
        # a tala has no strokes of its own: claps deep, the other beats light, and the result says whose idea that is
        drum.sent.clear()
        adi = tutor.rhythm("demo", pattern="adi", tempo_bpm=200, cycles=1)
        assert [m[1] for m in drum.sent] == ["Thom", "Thi", "Thi", "Thi", "Thom", "Thi", "Thom", "Thi"] and "this project's choice" in adi["sound_note"]
        # a theka has no strokes for the mridangam: auto would not choose it, and asked for, it marks the beats the same way
        assert tutor.rhythm("demo", pattern="testtal", tempo_bpm=200, cycles=1)["sound"] == "click"
    finally:
        tutor.pump.stop()


def test_the_drone_for_a_raga():
    # the rule: Pa if the raga has it, else the plain Ma, else Dha, Ni or Ga (the sources disagree); a raga's own entry wins
    assert lib.drone_tuning(lib.RAGAS["Bhupali"])["tuning"] == "Pa-Sa-Sa-Sa"
    bageshri = lib.drone_tuning(lib.RAGAS["Bageshri"])
    assert bageshri["tuning"] == "Ma-Sa-Sa-Sa" and "Toss Levy" in bageshri["rule"]
    assert lib.drone_tuning({"notes": {"g": "6/5", "M": "4/3", "d": "8/5", "n": "9/5"}})["first"] == "M"
    marwa = lib.drone_tuning({"notes": {"r": "16/15", "G": "5/4", "M#": "45/32", "D": "5/3", "N": "15/8"}})
    assert marwa["tuning"] == "Dha-Sa-Sa-Sa" and "Ni or Ga" in marwa["sources_disagree"] and "never the raised Ma" in marwa["rule"]
    assert lib.drone_tuning({"notes": {"r": "16/15", "M#": "45/32"}})["tuning"] == "Sa-Sa-Sa-Sa"

    fake = FakeXentool(sample_setup(31, (0, 1, 2, 3)))
    tutor = Tutor(fake)
    try:
        raga = tutor.library("raga", name="Bhupali", root="C4")["tanpura"]
        assert raga["tuning"] == "Pa-Sa-Sa-Sa" and raga["strings"] == ["G3 (18)", "C4 (0)", "C4 (0)", "C3 (0)"] and "Pa" in raga["rule"]
        assert tutor.library("raga", name="Bageshri", root="C4")["tanpura"]["strings"][0] == "F3 (13)"
        assert tutor.drone()["drone"] == "silent"

        out = tutor.drone("start", raga="Bhupali", root="C4", pace_s=0.3)
        assert out["drone"] == "sounding" and out["strings"] == raga["strings"] and out["tuning"] == "Pa-Sa-Sa-Sa"
        kb = tutor.keyboard
        order = [(k.board, k.key) for k in (kb.keys_for_pitch(kb.tuning.parse(n)[0])[0] for n in ("G3", "C4", "C4", "C3"))]
        long = int(0.3 * 4 * 1150)

        def struck():
            return [addr for addr, _, ms in fake.sounded if ms == long]

        time.sleep(1.0)
        first = struck()
        # one string after the other in the tanpura's order, each ringing until its next turn
        assert 3 <= len(first) <= 5 and first == (order * 2)[:len(first)]
        assert tutor.drone("status")["drone"] == "sounding"
        # a demonstration and a rhythm take run over it; it goes on striking
        tutor.demo([{"note": "E4"}, {"note": "G4"}], tempo_bpm=240, beats_per_step=1)
        tutor.rhythm("demo", pattern="tresillo", tempo_bpm=200, cycles=1)
        after = struck()
        assert len(after) >= len(first) + 4 and after == (order * 9)[:len(after)] and tutor._drone[0].is_alive()
        # another drone replaces it: own notes, an octave down
        own = tutor.drone("start", notes=["C4", "G4"], octave=-1, pace_s=0.4)
        assert own["strings"] == ["C3 (0)", "G3 (18)"]
        thread = tutor._drone[0]
        # stop ends it: the strings are let go and nothing is struck any more
        assert tutor.stop() == {"stopped": True} and not thread.is_alive() and tutor._drone is None
        assert set(order) <= set(fake.released)
        count = len(fake.sounded)
        time.sleep(0.6)
        assert len(fake.sounded) == count and tutor.drone("status")["drone"] == "silent"
        assert tutor.drone("stop") == {"drone": "none was sounding"}
        with pytest.raises(TutorError, match="no raga"):
            tutor.drone("start", raga="Nope")
    finally:
        tutor.stop()


def test_the_drone_has_its_own_instrument_where_one_is_set_up():
    fake = FakeXentool(sample_setup(31, (0, 1, 2, 3)))
    tanpura = Sender("127.0.0.1", 9)
    tutor = Tutor(fake, tanpura=tanpura)
    try:
        out = tutor.drone("start", raga="Bhupali", root="C4", pace_s=1.5, loudness=64)
        assert out["sound"] == "tanpura" and out["strings"] == ["G3 (18)", "C4 (0)", "C4 (0)", "C3 (0)"]
        address, pace, loud, *hz = tanpura.sent[-1]
        assert address == "/tanpura/start" and pace == 1.5 and loud == pytest.approx(64 / 127)
        c4 = 16.351597831287414 * 16
        assert hz == pytest.approx([c4 * 2 ** (18 / 31) / 2, c4, c4, c4 / 2])
        # nothing goes through the keyboard's own sound, so no key the player presses can cut a string
        assert fake.sounded == [] and tutor.drone("status")["drone"] == "sounding"
        # notes the keyboard has no key for are fine: the drone does not need keys
        low = tutor.drone("start", notes=["C4", "G4"], octave=-4)
        assert low["strings"] == ["C0 (0)", "G0 (18)"] and tanpura.sent[-1][0] == "/tanpura/start"
        assert tutor.stop() == {"stopped": True} and tanpura.sent[-1] == ("/tanpura/stop",)
        assert tutor.drone("status")["drone"] == "silent" and tutor.drone("stop") == {"drone": "none was sounding"}
    finally:
        tutor.stop()
        tutor.pump.stop()


def test_the_built_library_if_it_is_there():
    if not R.LIBRARY_FILE.exists():
        pytest.skip("rhythm library not built (python -m tutor.rhythm_build)")
    data = json.loads(R.LIBRARY_FILE.read_text(encoding="utf-8"))
    R.load()
    p = data["patterns"]
    kinds = data["counts"]
    assert kinds["hindustani theka"] == 22 and kinds["carnatic tala"] == 40 and kinds["makam usul"] == 36 and kinds["carnatic lesson"] >= 6
    assert len(data["gati"]) == 5 and len(data["lessons_without_strokes"]) + kinds["carnatic lesson"] == 27
    teental = p["teental"]
    assert teental["pulses"] == 16 and [s["stroke"] for s in teental["strokes"]][:4] == ["Dha", "Dhin", "Dhin", "Dha"] and teental["accents"] == [0, 4, 12]
    assert R.find("teental")[1]["strokes"] and R.find("Tintal")[0] == "teental"            # the sourced one, not the built-in fallback
    for name in ("jhaptal", "rupak", "dadra", "keherwa"):
        assert R.find(name)[1].get("tradition") == "hindustani", name
        assert R.find(name)[1]["beats"] == R.PATTERNS[name]["beats"], name
    for key, cycle in p.items():
        assert cycle["tradition"] in ("hindustani", "carnatic", "makam") and cycle["confidence"] and cycle["sources"] is not None, key
        assert cycle["beats"] == cycle["pulses"] and all(0 <= o < cycle["pulses"] for o in cycle["onsets"]), key
        assert all(0 <= s["at"] < cycle["pulses"] and s["dur"] > 0 for s in cycle["strokes"]), key
        if cycle["tradition"] == "hindustani":
            assert sum(s["length"] for s in cycle["sections"]) == cycle["pulses"], key
            assert all(s["stroke"] in data["tabla_bols"] for s in cycle["strokes"]), key            # every bol of every theka has a sound
        if cycle["kind"] == "usul" and cycle["strokes"]:
            assert sum(s["dur"] for s in cycle["strokes"]) == pytest.approx(cycle["pulses"]), key   # the strokes fill the cycle
    usul = [c for c in p.values() if c["kind"] == "usul"]
    assert sum(c["confidence"] == "conflicting" for c in usul) == 3 and sum(not c["strokes"] for c in usul) == 2
    assert all(c.get("conflict") for c in p.values() if c["confidence"] == "conflicting")
    # the usul named in the `meter` of the library's makam pieces are found by that name
    for meter, key in (("Düyek (8/8)", "duyek"), ("Aksaksemâî (10/8)", "aksaksemai"), ("K. Curcuna (10/8)", "kapali_curcuna"),
                       ("Devr-i Kebîr (28/4)", "devrikebir"), ("Yürüksemâî II (6/8)", "yuruksemai_ii"), ("Türkaksağı (5/8)", "turkaksagi")):
        assert R.find(meter)[0] == key, meter
    assert R.find("adi")[1]["pulses"] == 8 and R.find("misra chapu")[1]["pulses"] == 7
