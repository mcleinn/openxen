"""The fingering model (host/tutor/fingering.py): the published numbers it is built on, and
the behaviour that follows from them on a keyfield with rows. Only principles the sources
support are asserted; which of several good fingerings a player prefers is theirs to say."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
from tutor import fingering as F  # noqa: E402
from tutor.board import Keyboard  # noqa: E402
from tutor.sample import sample_setup  # noqa: E402

HAND = F.default_hand()
KEY = 19.2      # mm between neighbouring keys


def best(points, side="right"):
    return F.fingerings(HAND, points, side, 1)[0]


def test_tables_are_the_published_ones():
    """Balliauw et al. 2017, medium hand, in their unit of 1/14 octave (Parncutt's 165 mm octave)."""
    assert F.UNIT_MM == pytest.approx(165 / 14)
    units = lambda pair: tuple(round(v / F.UNIT_MM) for v in HAND.span(*pair))     # noqa: E731
    assert units((1, 5)) == (-2, 0, 7, 12, 14, 16)
    assert units((1, 2)) == (-8, -6, 1, 5, 8, 10)
    assert units((3, 4)) == (1, 1, 1, 2, 2, 4)
    # hand sizes differ where the paper says they do: thumb spans
    small, large = F.default_hand("small"), F.default_hand("large")
    assert small.span(1, 5)[5] < HAND.span(1, 5)[5] < large.span(1, 5)[5]
    assert small.span(3, 4) == large.span(3, 4)
    # their practical thumb-to-little-finger limit is about 0.9 of the span measured on pianists
    # (Boyle et al. 2015: mean 210 mm)
    assert 0.85 < HAND.span(1, 5)[5] / 210 < 0.95
    with pytest.raises(F.FingeringError):
        F.default_hand("huge")


def test_the_resting_hand_costs_nothing():
    rest = [HAND.rest_of(f) for f in (1, 2, 3, 4, 5)]
    f = best(rest)
    assert f.fingers == (1, 2, 3, 4, 5) and f.feel == "easy"
    assert f.effort == pytest.approx(sum(F.W_WEAK.values()))     # only the weak-finger points
    assert not f.reasons


def test_fingers_do_not_cross_and_the_left_hand_is_the_mirror():
    row = [(0.0, 0.0), (KEY, 0.0), (2 * KEY, 0.0)]
    right, left = best(row), best(row, "left")
    assert list(right.fingers) == sorted(right.fingers)
    assert list(left.fingers) == sorted(left.fingers, reverse=True)
    mirrored = [(-x, y) for x, y in row]
    assert [f.fingers for f in F.fingerings(HAND, row, "left")] == [f.fingers for f in F.fingerings(HAND, mirrored, "right")]
    # a crossed fingering of the same keys is much worse and says why
    crossed = F._evaluate(HAND, tuple(row), (3, 2, 4))
    assert crossed.effort > right.effort + 5 and any("crossed" in r for r in crossed.reasons)
    with pytest.raises(F.FingeringError):
        F.fingerings(HAND, row, "both")


def test_the_thumb_plays_nearer_to_the_player_than_the_fingers():
    """Janko's rule; here it follows from where the relaxed thumb lies."""
    near_left = [(0.0, 0.0), (2 * KEY, 2.5 * KEY)]      # first key: left and nearer to the player
    assert best(near_left).fingers[0] == 1
    # a thumb on the far key while a finger takes the near one is a strain
    wrong = F._evaluate(HAND, tuple(near_left), (2, 1))
    assert wrong.effort > best(near_left).effort + 3
    # the thumb may lie under the hand, between the fingers, on a nearer row
    under = [(0.0, 0.0), (2 * KEY, -1.75 * KEY), (3.5 * KEY, -0.9 * KEY)]
    assert best(under).fingers[1] == 1 and best(under).feel == "easy"


def test_reach_is_judged_and_two_hands_are_two_hands():
    assert best([(0.0, 0.0), (6 * KEY, 0.0)]).feel in ("easy", "comfortable")       # about an octave on a piano
    wide = best([(0.0, 0.0), (14 * KEY, 0.0)])
    assert wide.feel == "hardly playable with one hand" and any("practical limit" in r for r in wide.reasons)
    assert F.fingerings(HAND, [(i * KEY, 0.0) for i in range(6)]) == []
    # a larger hand finds the same wide chord easier
    span = [(0.0, 0.0), (10 * KEY, 0.0)]
    assert F.fingerings(F.default_hand("large"), span)[0].effort < F.fingerings(F.default_hand("small"), span)[0].effort


def test_several_fingerings_are_offered_easiest_first():
    triad = [(0.0, 0.0), (2 * KEY, 0.0), (3.5 * KEY, 0.9 * KEY)]
    ranked = F.fingerings(HAND, triad, limit=4)
    assert len(ranked) == 4 and len({f.fingers for f in ranked}) == 4
    assert [f.effort for f in ranked] == sorted(f.effort for f in ranked)
    assert ranked[0].text.count("-") == 2


@pytest.fixture(scope="module")
def kb():
    return Keyboard(sample_setup(53, (0, 1, 2, 3, 4)))


def options(kb, pitches, near=None, limit=3):
    return [F.Option(tuple((k.id, *kb.position_mm(k)) for k in s.keys)) for s in kb.shapes(pitches, near, limit)]


def test_the_same_shape_gets_the_same_fingers_on_every_root(kb):
    t = kb.tuning
    texts = set()
    for root in ("C4", "F4", "G4", "Bb3"):
        shape = kb.shapes(list(t.chord(t.parse(root)[0], "major").pitches), limit=1)[0]
        texts.add(tuple(f.text for f in F.fingerings(HAND, [kb.position_mm(k) for k in shape.keys])))
    assert len(texts) == 1
    # and a progression in root position keeps one fingering throughout
    steps = [options(kb, list(t.chord(t.parse(r)[0], "major").pitches)) for r in ("C4", "F4", "G4", "C4")]
    assert len({p.fingering.text for p in F.plan(HAND, steps)}) == 1


def test_a_melody_is_fingered_as_a_whole(kb):
    t = kb.tuning
    pitches = [p for p, _ in t.scale(t.parse("C4")[0], "major")] + [t.parse("C5")[0]]
    steps, prev = [], None
    for p in pitches:
        keys = kb.keys_for_pitch(p, prev)[:3]
        prev = keys[0]
        steps.append([F.Option(((k.id, *kb.position_mm(k)),)) for k in keys])
    for legato in (True, False):
        fingers = [p.fingering.fingers[0] for p in F.plan(HAND, steps, "right", legato)]
        # stepping along the row no finger plays twice running; at most the last step, where
        # the octave key lies on another row, is taken with the same finger
        assert all(a != b for a, b in zip(fingers[:-1], fingers[1:-1])), f"a finger plays two notes in a row: {fingers}"
        assert len(set(fingers)) >= 3
    # five neighbouring keys in a row lie under five fingers
    row = [[F.Option((("r%d" % i, i * KEY, 0.0),))] for i in range(5)]
    assert [p.fingering.fingers[0] for p in F.plan(HAND, row)] == [1, 2, 3, 4, 5]
    assert [p.fingering.fingers[0] for p in F.plan(HAND, row, "left")] == [5, 4, 3, 2, 1]


def test_context_changes_the_fingering_of_a_step():
    """Two notes, then two notes sharing one key: by itself each pair takes the same two
    fingers, in the phrase the shared key keeps its finger."""
    a, b, c = ("a", 0.0, 0.0), ("b", KEY, 0.0), ("c", 2 * KEY, 0.0)
    alone = F.fingerings(HAND, [(KEY, 0.0), (2 * KEY, 0.0)], limit=1)[0]
    first, second = F.plan(HAND, [[F.Option((a, b))], [F.Option((b, c))]])
    assert first.fingering.fingers[1] == second.fingering.fingers[0], "the shared key keeps its finger"
    assert second.fingering.fingers != alone.fingers or first.fingering.fingers != alone.fingers
    assert any("keeps" in n for n in second.notes)
    assert alone in (second.fingering, *second.alternatives)        # the other reading is still offered


def test_a_step_for_two_hands_breaks_the_phrase_without_breaking_the_plan():
    one = [F.Option((("a", 0.0, 0.0),))]
    six = [F.Option(tuple(("s%d" % i, i * KEY, 0.0) for i in range(6)))]
    planned = F.plan(HAND, [one, six, one])
    assert planned[1] is None and planned[0] is not None and planned[2] is not None
