"""Harmony from the tuning itself (host/tutor/voiceleading.py, host/tutor/xen_progressions.py
and the harmony tool's actions neighbours, path and xen): distances against hand-computed
cases in 12, 31 and 53 notes per octave, the ranking, progressions built from neighbours,
the curated wiki data, and that every chord given out has keys and names no internals."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
from tutor import voiceleading as vl  # noqa: E402
from tutor import xen_progressions as xen  # noqa: E402
from tutor.library import Library  # noqa: E402
from tutor.sample import sample_setup  # noqa: E402
from tutor.session import Tutor, TutorError  # noqa: E402
from tutor.theory import CHORDS, TheoryError, tuning_for  # noqa: E402
from tutor.wiki import Wiki  # noqa: E402
from tutor.xt import FakeXentool  # noqa: E402

INTERNALS = re.compile(r"\b(board|boards|module index|chan|channel|edo|lattice|midi|hid|usb|address|doubled)\b", re.I)
TUNINGS = (12, 19, 22, 24, 29, 31, 41, 53, 56)      # what the keyboard is played in


def find(found, root, quality):
    return next(n for n in found if (n.root, n.quality) == (root, quality))


def everything(edo, root, quality, **kw):
    return vl.neighbours(tuning_for(edo), root, quality, limit=9999, max_cents=1200, ranking="nearest", **kw)


# --- distances ---

def test_distance_the_short_way_round():
    assert vl.displacement(0, 7, 12) == -5 and vl.displacement(7, 0, 12) == 5
    assert vl.displacement(52, 1, 53) == 2 and vl.displacement(1, 52, 53) == -2
    assert vl.displacement(0, 6, 12) == 6          # half an octave counts as up


def test_voices_are_assigned_at_the_least_total_cost():
    # A diminished (A C Eb) to D major (D F# A). Taking the closest pair first (Eb to D, one
    # semitone) leaves C to F#, a tritone: 7 in all. The best way is C to D and Eb to F#: 5.
    moves = vl.assign((9, 0, 3), (2, 6, 9), 12)
    assert [(m.source, m.target, m.steps) for m in moves] == [(9, 9, 0), (0, 2, 2), (3, 6, 3)]
    assert sum(abs(m.steps) for m in moves) == 5
    # the same with two voices only
    assert sum(abs(m.steps) for m in vl.assign((0, 3), (2, 6), 12)) == 5
    # C D to D E: both voices up a whole tone, or D held and C up a major third. Equally far; the held note wins.
    assert [(m.source, m.target, m.steps) for m in vl.assign((0, 2), (2, 4), 12)] == [(0, 4, 4), (2, 2, 0)]


def test_chords_of_different_size_split_and_merge_voices():
    # C major to C dominant seventh in 12: one voice splits, G also goes to Bb (or C falls to Bb)
    up = vl.assign((0, 4, 7), (0, 4, 7, 10), 12)
    assert len(up) == 4 and sum(abs(m.steps) for m in up) == 2 and {m.target for m in up} == {0, 4, 7, 10}
    down = vl.assign((0, 4, 7, 10), (0, 4, 7), 12)
    assert len(down) == 4 and sum(abs(m.steps) for m in down) == 2 and {m.source for m in down} == {0, 4, 7, 10}


def test_twelve_tone_neighbours_are_the_textbook_ones():
    found = everything(12, 0, "major")
    a_minor = find(found, 9, "minor")
    assert (a_minor.steps, a_minor.cents, a_minor.stays, a_minor.group) == (2, 200.0, 2, "one_voice")
    assert [(m.source, m.target, m.steps) for m in a_minor.moves if m.steps] == [(7, 9, 2)]      # G to A, a whole tone
    assert "whole tone" in a_minor.kind and "root falls a minor third" in a_minor.kind
    e_minor = find(found, 4, "minor")
    assert (e_minor.steps, e_minor.stays) == (1, 2) and [(m.source, m.target) for m in e_minor.moves if m.steps] == [(0, 11)]
    c_minor = find(found, 0, "minor")
    assert (c_minor.steps, c_minor.group, c_minor.kind) == (1, "quality", "same root, the third changes: major to minor")
    assert find(found, 0, "sus4").kind == "same root, the third moves to the fourth: major to sus4"
    assert find(found, 0, "diminished").kind == "same root, the third and the fifth change: major to diminished"
    f_major = find(found, 5, "major")
    assert (f_major.steps, f_major.stays) == (3, 1) and "root falls a fifth" in f_major.kind
    # the three nearest moves that keep two notes: to E minor, A minor, and the diminished chord on C#
    one_voice = [(n.root, n.quality) for n in vl.neighbours(tuning_for(12), 0, "major", limit=10) if n.group == "one_voice"]
    assert one_voice[:2] == [(4, "minor"), (9, "minor")]


def test_53_has_neighbours_a_piano_lacks():
    t = tuning_for(53)
    assert vl.chord_notes(t, 0, "major") == (0, 17, 31)
    found = everything(53, 0, "major")
    neutral, supermajor, minor, subminor = (find(found, 0, q) for q in ("neutral", "supermajor", "minor", "subminor"))
    assert [(m.source, m.target, m.steps) for m in neutral.moves if m.steps] == [(17, 15, -2)]
    assert neutral.cents == 45.3 and neutral.stays == 2 and neutral.kind == "same root, the third changes: major to neutral"
    assert [m.steps for m in supermajor.moves if m.steps] == [2]
    assert [m.steps for m in minor.moves if m.steps] == [-3] and [m.steps for m in subminor.moves if m.steps] == [-5]
    # the relative minor that shares two notes is on vA (39), the mediant on vE (17) ...
    relative = find(found, 39, "minor")
    assert relative.notes == (39, 0, 17) and relative.stays == 2 and [(m.source, m.target, m.steps) for m in relative.moves if m.steps] == [(31, 39, 8)]
    assert "small whole tone (181 cents)" in relative.kind
    assert find(found, 17, "minor").stays == 2
    # ... while A minor on the plain A (40) shares nothing: two voices a comma up, one a whole tone
    plain = find(found, 40, "minor")
    assert plain.stays == 0 and sorted(m.steps for m in plain.moves) == [1, 1, 9] and plain.cents == 249.1
    # the same chord a comma higher
    shifted = find(found, 1, "major")
    assert shifted.group == "shift" and shifted.steps == 3 and "the same chord a comma higher" in shifted.kind
    assert find(found, 2, "major").kind.endswith("a planing shift")
    # the default list shows all of these kinds within ten entries
    ten = [(n.root, n.quality) for n in vl.neighbours(t, 0, "major", limit=10)]
    for wanted in ((0, "supermajor"), (0, "neutral"), (0, "minor"), (17, "minor"), (39, "minor"), (1, "major"), (52, "major")):
        assert wanted in ten, wanted
    assert (40, "minor") not in [(n.root, n.quality) for n in vl.neighbours(t, 0, "major", limit=999)]     # beyond 240 cents


def test_31_neighbours_and_the_harmonic_seventh():
    found = everything(31, 0, "major")
    neutral = find(found, 0, "neutral")
    assert [(m.source, m.target, m.steps) for m in neutral.moves if m.steps] == [(10, 9, -1)] and neutral.cents == 38.7
    assert find(found, 23, "minor").steps == 5 and find(found, 23, "minor").cents == 193.5      # A minor: G to A, no comma here
    sevenths = everything(31, 0, "harmonic7")
    ordinary = find(sevenths, 0, "dominant7")
    assert [(m.source, m.target, m.steps) for m in ordinary.moves if m.steps] == [(25, 26, 1)]
    assert ordinary.kind == "same root, the seventh changes: harmonic7 to dominant7"
    assert vl.neighbours(tuning_for(31), 0, "harmonic7", limit=1)[0] == ordinary
    assert all(len(n.notes) == 4 for n in sevenths)
    # resolutions to triads by least movement: the seventh rises to the root, or two voices move to E minor
    triads = vl.neighbours(tuning_for(31), 0, "harmonic7", sizes="triads", max_cents=400, ranking="nearest", limit=3)
    assert (triads[0].root, triads[0].quality, triads[0].steps) == (0, "major", 6)
    assert "the seventh moves to the root" in triads[0].kind
    assert {(n.root, n.quality) for n in triads[1:]} == {(10, "minor"), (10, "diminished")}
    both = vl.neighbours(tuning_for(31), 0, "harmonic7", sizes="any", limit=40)
    assert {len(n.notes) for n in both} == {3, 4}


@pytest.mark.parametrize("edo", [12, 31, 53])
def test_common_notes_are_counted_and_kept(edo):
    t = tuning_for(edo)
    for quality in ("major", "minor", "diminished", "dominant7", *(q for q in ("neutral", "harmonic7") if t.has(q))):
        source = set(vl.chord_notes(t, 3, quality))
        found = everything(edo, 3, quality)
        assert found == sorted(found, key=lambda n: n.steps)
        for n in found:
            assert set(n.notes) != source                                  # never the same notes under another name
            assert n.stays == len(source & set(n.notes))
            assert sum(1 for m in n.moves if not m.steps) == n.stays        # every common note is held
            assert n.steps == sum(abs(m.steps) for m in n.moves) and n.cents == round(1200 * n.steps / edo, 1)
            assert {m.source for m in n.moves} == source and {m.target for m in n.moves} == set(n.notes)
            assert all((m.source + m.steps) % edo == m.target for m in n.moves)


def test_one_name_per_set_of_notes():
    found = everything(12, 0, "major")
    augmented = find(found, 0, "augmented")
    assert set(augmented.also) == {(4, "augmented"), (8, "augmented")}
    assert not [n for n in found if n.quality == "augmented" and n.root in (4, 8)]
    assert find(found, 0, "sus4").also == ((5, "sus2"),)
    sixths = everything(12, 0, "major6")
    assert not [n for n in sixths if (n.root, n.quality) == (9, "minor7")]      # the same four notes


def test_selection_and_ranking():
    t = tuning_for(53)
    assert all(n.root == 0 for n in vl.neighbours(t, 0, "major", roots="same", limit=99))
    assert all(n.root != 0 for n in vl.neighbours(t, 0, "major", roots="other", limit=99))
    assert all(n.cents <= 70 for n in vl.neighbours(t, 0, "major", max_cents=70, limit=99))
    assert {n.quality for n in vl.neighbours(t, 0, "major", max_cents=70, roots="same", limit=99)} == {"supermajor", "neutral", "minor", "augmented"}
    nearest = vl.neighbours(t, 0, "major", ranking="nearest", limit=30)
    assert [n.steps for n in nearest] == sorted(n.steps for n in nearest)
    varied = vl.neighbours(t, 0, "major", limit=10)
    assert [n.group for n in varied] == list(vl.TURNS)
    assert [n.quality for n in varied if n.group == "one_voice"] == ["minor", "diminished", "minor"]    # vE minor before the nearer diminished chord
    assert vl.neighbours(t, 0, "major", limit=10) == varied                 # the same every time
    assert vl.neighbours(t, 9, "major", limit=10)[1].root == 26            # and the same from every root, moved along
    for bad in ({"roots": "all"}, {"sizes": "big"}, {"ranking": "best"}):
        with pytest.raises(TheoryError):
            vl.neighbours(t, 0, "major", **bad)
    with pytest.raises(TheoryError, match="no neutral chord"):
        vl.neighbours(tuning_for(12), 0, "neutral")


def test_small_steps_are_named_after_the_tuning():
    assert vl.step_names(tuning_for(12)) == {1: "a semitone", 2: "a whole tone"}
    assert vl.step_names(tuning_for(31)) == {1: "a diesis", 2: "a chromatic semitone", 3: "a diatonic semitone", 5: "a whole tone"}
    fifty_three = vl.step_names(tuning_for(53))
    assert (fifty_three[1], fifty_three[2], fifty_three[3], fifty_three[5], fifty_three[8], fifty_three[9]) == (
        "a comma", "a diesis", "a chromatic semitone", "a diatonic semitone", "a small whole tone", "a whole tone")
    assert vl.step_names(tuning_for(24))[1] == "a quarter tone" and vl.step_names(tuning_for(22))[1] == "a comma"
    assert vl.step_words(tuning_for(53), 1) == "1 step up, a comma (23 cents)"
    assert vl.step_words(tuning_for(31), -1) == "1 step down, a diesis (39 cents)"
    assert vl.step_words(tuning_for(31), 4).startswith("4 steps up") and "155 cents" in vl.step_words(tuning_for(31), 4)
    assert vl.root_words(tuning_for(53), 22) == "the root falls a fifth (rises a fourth)"
    assert vl.root_words(tuning_for(53), -1) == "the root falls a comma" and vl.root_words(tuning_for(53), 0) == "the root stays"


def test_a_given_move_is_described_however_far():
    far = vl.move(tuning_for(12), 0, "major", 6, "major")       # C E G to F# A# C#: a semitone, a whole tone and a minor third
    assert far.steps == 1 + 2 + 3 and far.stays == 0 and far.kind.startswith("no note stays, all voices move")
    same = vl.move(tuning_for(12), 0, "major6", 9, "minor7")
    assert same.steps == 0 and same.kind == "the same notes under another name"


def test_a_voicing_follows_the_voices():
    t = tuning_for(53)
    relative = find(everything(53, 0, "major"), 39, "minor")
    assert vl.voiced([212, 229, 243], relative.moves, 53) == [212, 229, 251]       # C4 vE4 G4 -> C4 vE4 vA4: two keys stay
    mediant = find(everything(53, 0, "major"), 17, "minor")
    assert vl.voiced([212, 229, 243], mediant.moves, 53) == [207, 229, 243]        # the C falls to vB3
    assert t.name(207) == "vB3"


# --- progressions ---

@pytest.mark.parametrize("edo,kw", [(53, {}), (31, {}), (12, {}), (53, {"length": 7, "max_cents": 70}), (31, {"length": 4, "max_cents": 120}),
                                    (53, {"seed": 5, "max_cents": 150}), (53, {"sizes": "any", "seed": 2})])
def test_a_path_comes_home_within_its_limits(edo, kw):
    t = tuning_for(edo)
    moves = vl.path(t, 0, "major", **kw)
    length, reach = kw.get("length", 5), kw.get("max_cents", vl.DEFAULT_MAX_CENTS)
    assert len(moves) == length - 1
    assert (moves[-1].root, moves[-1].quality) == (0, "major")
    assert all(n.cents <= reach for n in moves)
    chords = [frozenset(vl.chord_notes(t, 0, "major"))] + [frozenset(n.notes) for n in moves[:-1]]
    assert len(set(chords)) == len(chords)                                       # no chord twice
    # every move starts where the one before ended
    here = set(vl.chord_notes(t, 0, "major"))
    for n in moves:
        assert {m.source for m in n.moves} == here
        here = set(n.notes)
    assert vl.path(t, 0, "major", **kw) == moves                                 # the same for the same arguments


def test_path_variety_and_constraints():
    t = tuning_for(53)
    ways = {tuple((n.root, n.quality) for n in vl.path(t, 0, "major", seed=s)) for s in range(6)}
    assert len(ways) >= 3
    there_and_back = vl.path(t, 0, "major", via="xen")
    assert any(CHORDS[n.quality].get("xen") for n in there_and_back[:-1])
    assert any(n.quality == "neutral" for n in vl.path(t, 0, "major", via="neutral")[:-1])
    assert all(n.root == 0 for n in vl.path(t, 0, "major", roots="same"))
    elsewhere = vl.path(t, 0, "major", end=(39, "minor"), length=4)
    assert (elsewhere[-1].root, elsewhere[-1].quality) == (39, "minor") and len(elsewhere) == 3
    with pytest.raises(TheoryError, match="no chords of that size beyond"):
        vl.path(tuning_for(12), 0, "major", via="xen")
    with pytest.raises(TheoryError, match="no progression of 5 chords within 20 cents"):
        vl.path(t, 0, "major", max_cents=20)
    with pytest.raises(TheoryError, match="length"):
        vl.path(t, 0, "major", length=2)
    with pytest.raises(TheoryError, match="sizes='any'"):
        vl.path(t, 0, "major", end=(0, "harmonic7"))


# --- what microtonal musicians wrote ---

def test_the_curated_entries_are_well_formed():
    ids = [e["id"] for e in xen.ENTRIES]
    assert len(set(ids)) == len(ids) and len(ids) >= 35
    for e in xen.ENTRIES:
        assert set(e) <= {"id", "name", "kind", "tunings", "also", "chords", "shows", "source"}, e["id"]
        assert e["kind"] in ("progression", "vocabulary", "idea")
        assert e["tunings"] and set(e["tunings"]) | set(e.get("also", ())) <= set(TUNINGS), e["id"]
        assert not set(e["tunings"]) & set(e.get("also", ()))
        assert len(e["source"]) == 2 and all(e["source"]) and 40 < len(e["shows"]) < 700 and e["name"]
        assert e["chords"] or e["kind"] == "idea", e["id"]
        if e["kind"] == "progression":
            assert len(e["chords"]) >= 2
        in_steps = any("/" not in part for chord in e["chords"] for field in chord.split("|")[1:] for part in field.split())
        if in_steps:
            assert len(e["tunings"]) == 1 and not e.get("also"), f"{e['id']}: step counts hold in one tuning only"
        assert not INTERNALS.search(json.dumps({k: e[k] for k in ("id", "name", "shows", "chords")})), e["id"]
        for edo in (*e["tunings"], *e.get("also", ())):
            t = tuning_for(edo)
            for name, root, tones in xen.resolve(e, edo):
                assert name and 0 <= root < edo
                assert list(tones) == sorted(set(tones)) and 0 < tones[0] and tones[-1] < edo, (e["id"], edo, name)
                assert len(tones) >= 1
            assert e in xen.for_tuning(edo)
            assert t.edo == edo
    assert xen.for_tuning(56) == [] and xen.MISSING
    assert len(xen.for_tuning(41)) >= 14 and len(xen.for_tuning(22)) >= 7 and len(xen.for_tuning(53)) >= 12
    assert xen.entry("kite-gu-pump")["id"] == "kite-gu-pump" and xen.entry("gu-pump")["id"] == "kite-gu-pump"
    with pytest.raises(xen.ProgressionError):
        xen.entry("no such thing")
    with pytest.raises(xen.ProgressionError, match="written for 22"):
        xen.resolve(xen.entry("porcupine-pump-22"), 31)


def test_entries_resolve_to_the_chords_their_sources_give():
    # 41 notes per octave: Iv = 0-13-24, the harmonic seventh at 33; six, two, five are fifths apart
    pump = xen.resolve(xen.entry("kite-gu-pump"), 41)
    assert [(root, tones) for _, root, tones in pump] == [(0, (13, 24)), (31, (11, 24)), (7, (11, 24)), (24, (13, 24, 33)), (0, (13, 24))]
    assert [root for _, root, _ in xen.resolve(xen.entry("kite-gu-pump"), 53)] == [0, 40, 9, 31, 0]
    # I Will: the root goes from the low sixth to the plain second by a fourth that is one step wide
    i_will = [root for _, root, _ in xen.resolve(xen.entry("kite-i-will"), 41)]
    assert (i_will[2] - i_will[1]) % 41 == 17 + 1
    assert [name for name, _, _ in xen.resolve(xen.entry("kite-two-five-one-strong"), 41)] == ["II^m7", "V^7", "IvM7"]
    assert xen.resolve(xen.entry("kite-two-five-one-strong"), 41)[1] == ("V^7", 24, (15, 24, 35))
    # the porcupine pump: three equal root moves in 22, unequal ones (6, 5, 6) in 41, as its page says
    def falls(entry_id, edo):
        roots = [root for _, root, _ in xen.resolve(xen.entry(entry_id), edo)][::2]
        return [(a - b) % edo for a, b in zip(roots, roots[1:])]
    assert falls("porcupine-pump-22", 22) == [3, 3, 3] and falls("kite-porcupine-pump", 41) == [6, 5, 6]
    assert xen.resolve(xen.entry("superpyth-quartal"), 22) == [("Csus4", 0, (9, 13)), ("E Orwell diminished", 8, (5, 10)), ("Fsus4", 9, (9, 13)), ("G supermajor", 13, (8, 13))]
    assert xen.resolve(xen.entry("superpyth-tetrads"), 22)[0][1:] == (9, (5, 13, 18))
    # the turnaround closes where four fifths make a major third
    for edo, roots in ((12, [0, 9, 2, 7, 0]), (19, [0, 14, 3, 11, 0]), (31, [0, 23, 5, 18, 0])):
        assert [root for _, root, _ in xen.resolve(xen.entry("meantone-turnaround"), edo)] == roots
    # three major thirds down: back a small step above the start
    assert [xen.resolve(xen.entry("thirds-cycle"), edo)[-1][1] for edo in (19, 31, 41, 53)] == [1, 1, 2, 2]
    assert [tones for _, _, tones in xen.resolve(xen.entry("garibaldi-thirds"), 53)] == [(18, 31), (17, 31), (19, 31), (13, 31), (14, 31), (12, 31)]
    assert xen.resolve(xen.entry("31-augmented-sixth"), 31) == [("bVI with augmented sixth", 21, (10, 18, 25))]     # = a harmonic seventh chord


def test_sources_exist_in_the_wiki_copy_if_installed():
    wiki = Wiki()
    if not wiki.available:
        pytest.skip("build/tutor-wiki/pages.json not built")
    for e in xen.ENTRIES:
        page, section = e["source"]
        assert wiki.section(page, section), f"{e['id']}: no section '{section}' on page '{page}'"


# --- the tool ---

def tutor_for(edo: int) -> Tutor:
    return Tutor(FakeXentool(sample_setup(edo, (0, 1, 2, 3, 4))))


def has_keys(t: Tutor, step: dict) -> bool:
    kb = t.keyboard
    return all(kb.tuning.parse(n)[0] in kb._by_pitch for n in [*step["notes"], *([step["root"]] if step.get("root") else [])])


def numbers(step: dict) -> list[int]:
    return [int(n.split("(")[1].rstrip(")")) for n in step["notes"]]


def test_neighbours_tool_in_53():
    t = tutor_for(53)
    try:
        out = t.harmony("neighbours", chord="C major", limit=10)
        assert out["from"] == {"notes": ["C4 (0)", "vE4 (17)", "G4 (31)"], "label": "C major", "root": "C4 (0)", "beats": 4}
        by_label = {n["label"]: n for n in out["neighbours"]}
        assert {"C supermajor", "C neutral", "C minor", "vE minor", "vA minor", "^C major", "vC major"} <= set(by_label)
        neutral = by_label["C neutral"]
        assert neutral["notes"] == ["C4 (0)", "^^Eb4 (15)", "G4 (31)"] and neutral["stays"] == 2 and neutral["total_cents"] == 45
        assert neutral["moves"] == ["vE4 (17) to ^^Eb4 (15): 2 steps down, a diesis (45 cents)"]
        assert neutral["not_on_a_piano"].startswith("18:22:27")
        # the voicing follows the voices: C and vE stay on their keys, G goes up to vA
        relative = by_label["vA minor"]
        assert relative["notes"] == ["C4 (0)", "vE4 (17)", "vA4 (39)"] and relative["root"] == "vA4 (39)"
        assert relative["moves"] == ["G4 (31) to vA4 (39): 8 steps up, a small whole tone (181 cents)"]
        assert by_label["vE minor"]["notes"] == ["vB3 (48)", "vE4 (17)", "G4 (31)"]
        assert "a comma higher" in by_label["^C major"]["kind"] and numbers(by_label["^C major"]) == [1, 18, 32]
        assert out["small_steps"]["1 step"] == "a comma (23 cents)"
        for n in out["neighbours"]:
            assert has_keys(t, n) and set(n) >= {"notes", "label", "root", "beats", "kind", "stays", "moves"}
        # an entry is a chord step: the other tools take it as it is
        fingered = t.fingering([out["from"], relative])
        assert len(fingered["steps"]) == 2
        # one given move: A minor on the plain A is further away than on vA
        plain = t.harmony("neighbours", chord="C major", to="A minor")["move"]
        assert plain["label"] == "A minor" and plain["stays"] == 0 and plain["total_cents"] == 249 and len(plain["moves"]) == 3
        # other roots, qualities a piano lacks, chord symbols, note numbers
        assert t.harmony("neighbours", chord="vE neutral", limit=3)["from"]["label"] == "vE neutral"
        assert t.harmony("neighbours", chord="Dm7", limit=3)["from"]["label"] == "D minor7"
        assert numbers(t.harmony("neighbours", chord="17 subminor", limit=3)["from"]) == [17, 29, 48]
        sevenths = t.harmony("neighbours", chord="Bb harmonic7", limit=16, sizes="any", max_cents=400, roots="same")
        assert {len(n["notes"]) for n in sevenths["neighbours"]} == {3, 4}
        assert all(n["root"].startswith("C") for n in t.harmony("neighbours", chord="C major", roots="same")["neighbours"])
        assert INTERNALS.search(json.dumps([out, plain, sevenths], ensure_ascii=False)) is None
        for bad in ({"chord": None}, {"chord": "H major"}, {"chord": "C wobbly"}, {"chord": "C major", "roots": "x"}, {"chord": "C major", "max_cents": 5}):
            with pytest.raises((TutorError, TheoryError)):
                t.harmony("neighbours", **bad)
    finally:
        t.pump.stop()


@pytest.mark.parametrize("edo", [12, 31, 53])
def test_every_chord_given_out_has_keys(edo):
    t = tutor_for(edo)
    try:
        tuning = t.keyboard.tuning
        qualities = ["major", "minor", "dominant7"] + [q for q in ("neutral", "subminor", "harmonic7") if tuning.has(q)]
        said = []
        for root in ("C", "F#", "vE" if edo != 12 else "E"):
            for quality in qualities:
                out = t.harmony("neighbours", chord=f"{root} {quality}", limit=8)
                said.append(out)
                assert has_keys(t, out["from"])
                for n in out["neighbours"]:
                    assert has_keys(t, n), (root, quality, n["label"])
                    assert len(n["notes"]) == len(set(n["notes"])) == len(out["from"]["notes"])
                    # the label names the chord that sounds
                    pcs = {x % edo for x in numbers(n)}
                    name, quality_said = n["label"].split(" ", 1)
                    assert pcs == set(vl.chord_notes(tuning, tuning.parse(name)[0] % edo, quality_said))
        assert INTERNALS.search(json.dumps(said, ensure_ascii=False)) is None
    finally:
        t.pump.stop()


def test_path_tool():
    for edo in (53, 31):
        t = tutor_for(edo)
        try:
            out = t.harmony("path", chord="C major", via="xen")
            steps = out["steps"]
            assert len(steps) == 5 and steps[0]["label"] == steps[-1]["label"] == "C major"
            assert sorted(numbers(steps[0])) == sorted(numbers(steps[-1]))                  # home again, on the same notes
            assert out["progression"] == " - ".join(s["label"] for s in steps)
            assert len({s["label"] for s in steps[:-1]}) == 4
            assert any("not_on_a_piano" in s for s in steps[1:-1])
            assert all(s["total_cents"] <= 240 for s in steps[1:]) and all(has_keys(t, s) for s in steps)
            assert all(s["moves"] and s["kind"] for s in steps[1:]) and "moves" not in steps[0]
            assert t.harmony("path", chord="C major", via="xen") == out
            assert t.harmony("path", chord="C major", seed=4, max_cents=150)["progression"] != out["progression"]
            tight = t.harmony("path", chord="D minor", length=6, max_cents=120, seed=1)
            assert len(tight["steps"]) == 6 and all(s["total_cents"] <= 120 for s in tight["steps"][1:]) and tight["steps"][-1]["label"] == "D minor"
            away = t.harmony("path", chord="C major", to="F major", length=4)
            assert away["steps"][-1]["label"] == "F major" and all(has_keys(t, s) for s in away["steps"])
            # the steps go to the other tools as they are
            assert len(t.fingering(steps)["steps"]) == 5
            played = t.demo([{k: v for k, v in s.items() if k != "beats"} for s in steps], tempo_bpm=240, beats_per_step=0.2)
            assert played and INTERNALS.search(json.dumps([out, tight, away, played], ensure_ascii=False)) is None
            with pytest.raises(TheoryError, match="max_cents"):
                t.harmony("path", chord="C major", max_cents=30)
        finally:
            t.pump.stop()


@pytest.mark.parametrize("edo", [22, 31, 41, 53])
def test_xen_tool_lists_and_plays_the_wiki_entries(edo):
    t = tutor_for(edo)
    try:
        listed = t.harmony("xen")
        names = [e["name"] for e in listed["entries"]]
        assert names == [e["id"] for e in xen.for_tuning(edo)] and listed["not_found_in_the_wiki_copy"]
        said = [listed]
        for e in xen.for_tuning(edo):
            out = t.harmony("xen", name=e["id"], key="D" if e["chords"] and edo != 22 else "C")
            said.append(out)
            assert out["shows"] == e["shows"] and e["source"][0] in out["source"] and e["source"][1] in out["source"]
            assert ("written_for" in out) == (edo not in e["tunings"])
            if not e["chords"]:
                assert "steps" not in out
                continue
            assert "no_keys_for" not in out and len(out["steps"]) == len(e["chords"])
            for step, (label, root, tones) in zip(out["steps"], xen.resolve(e, edo)):
                assert has_keys(t, step) and step["label"] == label and step["beats"] == 4
                tonic = numbers({"notes": [out["home_note"]]})[0]
                assert [(x - numbers(step)[0]) % edo for x in numbers(step)[1:]] == [s % edo for s in tones]
                assert numbers(step)[0] == (tonic + root) % edo
            assert t.fingering(out["steps"][:2])["steps"]
        assert INTERNALS.search(json.dumps(said, ensure_ascii=False)) is None
        with pytest.raises(TutorError, match="lists the entries"):
            t.harmony("xen", name="nothing like it")
    finally:
        t.pump.stop()


def test_xen_tool_in_particular():
    t = tutor_for(53)
    try:
        pump = t.harmony("xen", name="kite-gu-pump", key="C")
        assert [s["label"] for s in pump["steps"]] == ["Iv", "VI^m", "II^m", "Vv7", "Iv"]
        assert [s["tutor_calls_it"] for s in pump["steps"]] == ["C major", "A minor", "D minor", "G harmonic7", "C major"]
        assert pump["steps"][1]["notes"] == ["A3 (40)", "^C4 (1)", "E4 (18)"]              # the plain A: C and E one step higher than in the chord before
        assert pump["written_for"].startswith("41 notes per octave") and "Kite Guitar" in pump["source"]
        triads = t.harmony("xen", name="53-triads")
        assert [numbers(s) for s in triads["steps"]] == [[0, 12, 31], [0, 14, 31], [0, 15, 31], [0, 16, 31], [0, 17, 31], [0, 19, 31]]
        assert "tutor_calls_it" not in triads["steps"][3] and triads["steps"][2]["tutor_calls_it"] == "C neutral"     # the higher neutral third is the wiki's alone
        with pytest.raises(TutorError, match="written for 22"):
            t.harmony("xen", name="porcupine-pump-22")
    finally:
        t.pump.stop()
    empty = tutor_for(56)
    try:
        assert empty.harmony("xen")["entries"] == [] and "neighbours" in empty.harmony("xen")["note"]
        assert empty.harmony("neighbours", chord="C major", limit=4)["neighbours"]
    finally:
        empty.pump.stop()


def test_new_actions_need_no_statistics_and_are_announced(tmp_path):
    t = Tutor(FakeXentool(sample_setup(31, (0, 1, 2, 3, 4))), library=Library(tmp_path))
    try:
        with pytest.raises(TutorError, match="statistics are not installed"):
            t.harmony("next", chord="Dm7")              # the repertoire counts are missing here ...
        assert t.harmony("neighbours", chord="C major")["neighbours"]       # ... the tuning's own harmony is not
        told = t.harmony("tuning")
        assert "neighbours" in told["harmony_of_this_tuning"] and told["small_steps"]["1 step"] == "a diesis (39 cents)"
    finally:
        t.pump.stop()
