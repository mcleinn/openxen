"""Tutor exercise engine (host/tutor/engine.py): the rules by which a step counts as played.
Scripted key presses in, verdicts and light actions out; no keyboard, no clock."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
from tutor.engine import Exercise, Finished, Mark, Press, ShowHint, Step, StepDone, Unmark  # noqa: E402

# A tiny keyboard for the scripts: key id -> pitch. "c2" is a second key sounding C.
PITCH = {"c": 60, "c2": 60, "d": 62, "e": 64, "f": 65, "g": 67, "a": 69}
C_MAJOR = Step("C major", (60, 64, 67), ("c", "e", "g"))
F_MAJOR = Step("F major", (65, 69, 72 - 12), ("f", "a", "c"))


def down(t: float, key: str) -> Press:
    return Press(t, key, PITCH[key], True)


def up(t: float, key: str) -> Press:
    return Press(t, key, PITCH[key], False)


def play(ex: Exercise, *events: Press) -> list:
    out = []
    for ev in events:
        out += ex.feed(ev)
    return out


def test_chord_played_correctly_in_any_order():
    ex = Exercise([C_MAJOR])
    assert ex.start(0.0) == [ShowHint(0, ("c", "e", "g"))]
    actions = play(ex, down(1.0, "g"), down(1.05, "c"), down(1.1, "e"))
    assert actions == [Mark("g", True), Mark("c", True), Mark("e", True), StepDone(0), Finished()]
    r = ex.results[0]
    assert (r.status, r.seconds, r.attempts, r.wrong) == ("ok", 1.1, 1, [])
    assert ex.finished and ex.completed == 1 and ex.first_try == 1 and ex.accuracy == 100
    assert ex.feed(down(2.0, "d")) == []        # nothing more after the end


def test_chord_needs_all_notes_held_together():
    ex = Exercise([C_MAJOR])
    ex.start(0.0)
    # played one after the other, letting go in between: never all three down
    actions = play(ex, down(1, "c"), up(1.2, "c"), down(1.3, "e"), up(1.5, "e"), down(1.6, "g"), up(1.8, "g"))
    assert StepDone(0) not in actions and not ex.finished
    assert ex.results[0].attempts == 3
    play(ex, down(2, "c"), down(2, "e"), down(2.1, "g"))
    assert ex.results[0].status == "ok" and ex.results[0].attempts == 4
    assert ex.first_try == 0


def test_wrong_note_is_reported_and_blocks_until_released():
    ex = Exercise([C_MAJOR])
    ex.start(0.0)
    actions = play(ex, down(1, "c"), down(1, "f"), down(1.1, "e"), down(1.2, "g"))
    assert Mark("f", False) in actions
    assert not ex.finished, "a wrong key held with the chord does not pass"
    # lifting the wrong finger leaves the chord: done, without pressing anything again
    actions = play(ex, up(2, "f"))
    assert actions == [Unmark("f"), StepDone(0), Finished()]
    r = ex.results[0]
    assert r.status == "ok" and r.wrong == [65] and r.attempts == 1 and r.seconds == 2.0
    assert ex.accuracy == 75    # 3 of 4 presses were right
    assert ex.first_try == 0    # a wrong note is not "right first time"


def test_max_extra_tolerates_a_slip():
    ex = Exercise([C_MAJOR], max_extra=1)
    ex.start(0.0)
    play(ex, down(1, "d"), down(1, "c"), down(1, "e"), down(1.1, "g"))
    assert ex.results[0].status == "ok" and ex.results[0].wrong == [62]


def test_any_key_with_the_right_note_counts_unless_exact():
    ex = Exercise([C_MAJOR])
    ex.start(0.0)
    play(ex, down(1, "c2"), down(1, "e"), down(1, "g"))
    assert ex.results[0].status == "ok"
    exact = Exercise([Step("C major", (60, 64, 67), ("c", "e", "g"), exact_keys=True)])
    exact.start(0.0)
    actions = play(exact, down(1, "c2"), down(1, "e"), down(1, "g"))
    assert Mark("c2", False) in actions and not exact.finished
    play(exact, up(2, "c2"), down(2.1, "c"))
    assert exact.results[0].status == "ok" and exact.results[0].wrong == [60]


def test_progression_shared_note_may_stay_down():
    ex = Exercise([C_MAJOR, F_MAJOR])
    ex.start(0.0)
    actions = play(ex, down(1, "c"), down(1, "e"), down(1, "g"))
    assert actions[-2:] == [StepDone(0), ShowHint(1, ("f", "a", "c"))]
    # keep C, move the other two fingers: E and G still down do not count against F major
    actions = play(ex, up(2, "e"), up(2, "g"), down(2.5, "f"), down(2.6, "a"))
    assert actions[-2:] == [StepDone(1), Finished()]
    assert [r.status for r in ex.results] == ["ok", "ok"]
    assert ex.results[1].seconds == 1.6 and ex.results[1].wrong == []


def test_holding_the_old_chord_does_not_complete_the_next_step():
    ex = Exercise([C_MAJOR, C_MAJOR])
    ex.start(0.0)
    play(ex, down(1, "c"), down(1, "e"), down(1, "g"))
    assert ex.index == 1 and not ex.finished
    # still holding all three: the repeat needs a new press
    play(ex, up(2, "e"), down(2.2, "e"))
    assert ex.finished


def test_keys_held_before_the_start_are_ignored():
    ex = Exercise([Step("D", (62,), ("d",))])
    ex.start(0.0, held={"f": 65})
    play(ex, down(1, "d"))
    assert ex.results[0].status == "ok" and ex.results[0].wrong == []


def test_melody_in_order():
    steps = [Step(n.upper(), (PITCH[n],), (n,)) for n in ("c", "d", "e", "c")]
    ex = Exercise(steps)
    ex.start(0.0)
    actions = play(ex, down(1, "c"), up(1.3, "c"), down(1.5, "e"), up(1.7, "e"), down(2, "d"), down(2.5, "e"), down(3, "c"))
    assert Mark("e", False) in actions      # E before D is out of order
    assert [r.status for r in ex.results] == ["ok"] * 4
    assert ex.results[1].wrong == [64] and ex.results[1].attempts == 2
    assert ex.first_try == 3 and ex.finished
    assert [a for a in actions if isinstance(a, StepDone)] == [StepDone(0), StepDone(1), StepDone(2), StepDone(3)]


def test_hints_modes():
    never = Exercise([C_MAJOR], hints="never")
    assert never.start(0.0) == [] and never.tick(99) == []
    assert not never.results[0].hint_shown

    delayed = Exercise([C_MAJOR, F_MAJOR], hints="after_delay", hint_delay_s=4)
    assert delayed.start(0.0) == []
    assert delayed.tick(3.9) == []
    assert delayed.tick(4.0) == [ShowHint(0, ("c", "e", "g"))]
    assert delayed.tick(5.0) == []          # shown once
    play(delayed, down(6, "c"), down(6, "e"), down(6, "g"), up(7, "c"), up(7, "e"), up(7, "g"))
    assert delayed.results[0].hint_shown
    # second step: a failed try brings the hint before the delay is over
    actions = play(delayed, down(8, "d"), up(8.5, "d"))
    assert actions[-1] == ShowHint(1, ("f", "a", "c"))
    assert delayed.results[1].wrong == [62] and delayed.results[1].attempts == 1

    with pytest.raises(ValueError, match="hints must be"):
        Exercise([C_MAJOR], hints="sometimes")
    with pytest.raises(ValueError, match="at least one step"):
        Exercise([])


def test_time_limit_reports_what_was_missing():
    ex = Exercise([C_MAJOR, F_MAJOR])
    ex.start(0.0)
    play(ex, down(1, "c"), down(1, "e"))
    ex.stop(30.0, "timed out")
    assert ex.finished
    r0, r1 = ex.results
    assert (r0.status, r0.seconds, r0.missing, r0.attempts) == ("timed out", 30.0, [67], 1)
    assert r1.status == "not reached"
    assert ex.completed == 0


def test_continue_from_a_later_step():
    ex = Exercise([C_MAJOR, F_MAJOR])
    assert ex.start_at(1, 10.0) == [ShowHint(1, ("f", "a", "c"))]
    play(ex, down(11, "f"), down(11, "a"), down(11.2, "c"))
    assert [r.status for r in ex.results] == ["not reached", "ok"]
    assert ex.results[1].seconds == 1.2 and ex.finished
    with pytest.raises(ValueError, match="does not exist"):
        Exercise([C_MAJOR]).start_at(3, 0.0)
