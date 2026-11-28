"""Exercise engine: decides, key press by key press, whether the player has done what a
step asks, and what to show them. Pure logic with no clock, no keyboard and no network: it
is fed events and answers with actions, so every rule here is covered by tests.

Rules (wait mode, the piece waits for the player):
- A step asks for a set of notes: one note (melody) or several held together (chord), in
  any order. By default any key that sounds the right note counts; `exact_keys` insists on
  the keys that were shown.
- The step is done at the moment all its notes are held together and at least one of them
  was pressed since the step began (so the notes a previous chord shares may stay down).
- A press that is not part of the step is a wrong note. More than `max_extra` wrong keys
  held at once keep the step from completing; lifting them completes it.
- Keys still held from the step before are ignored until released.
- An attempt ends when the player lets go of everything pressed in it without finishing.
- Hints: the keys to press are shown at once, after a delay or a failed attempt, or never.
- A trill step (two notes or two chords taking turns) is judged by its effect, never by a
  count of strokes (`trills.judge`): the two sides alternate at least `trills.MIN_CHANGES`
  times, every note of both is struck, it starts on the main side if the step says so, no
  other key is pressed, it is not too lumpy, and, where the written time is known, it lasts
  at least half of it. It is judged when the player stops (nothing new for a moment); a
  failed try counts as an attempt and the step waits on. A trill under which other steps
  enter (`goes_on`) is done as soon as it is going, and its notes are then neither wanted
  nor wrong in the steps marked `under`; what is struck there still counts for its report.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import trills


@dataclass(frozen=True)
class Press:
    """A key going down (`on`) or up, at `t` seconds."""
    t: float
    key: str        # key id
    pitch: int
    on: bool
    velocity: int = 0


@dataclass(frozen=True)
class Step:
    label: str                      # what the player is asked for: "C major", "E4"
    pitches: tuple[int, ...]        # the notes that must sound
    keys: tuple[str, ...] = ()      # keys shown as the hint (and required with exact_keys)
    exact_keys: bool = False
    # A trill or tremolo: its two sides (the one it starts on first). `pitches` are then only
    # the notes struck together with its start (often none).
    trill: tuple[tuple[int, ...], tuple[int, ...]] | None = None
    start_on_main: bool = True      # the first stroke must be on the first side
    seconds: float | None = None    # how long it is written to last, where a tempo is known
    goes_on: bool = False           # other steps enter while it continues
    under: tuple[int, ...] = ()     # notes of a trill that goes on under this step


@dataclass
class StepResult:
    label: str
    status: str = "not reached"     # ok | timed out | stopped | not reached
    seconds: float = 0.0
    attempts: int = 0
    wrong: list[int] = field(default_factory=list)      # pitches of wrong presses, in order
    missing: list[int] = field(default_factory=list)    # pitches not held when time ran out
    hint_shown: bool = False
    trill: dict | None = None       # a trill step: the facts of `trills.judge` for the last try


# Actions for whoever drives the lights. All refer to key ids.
@dataclass(frozen=True)
class ShowHint:
    step: int
    keys: tuple[str, ...]


@dataclass(frozen=True)
class Mark:
    key: str
    correct: bool


@dataclass(frozen=True)
class Unmark:
    key: str


@dataclass(frozen=True)
class StepDone:
    step: int


@dataclass(frozen=True)
class Finished:
    pass


class Exercise:
    def __init__(self, steps: list[Step], hints: str = "always", hint_delay_s: float = 4.0, max_extra: int = 0):
        if hints not in ("always", "after_delay", "never"):
            raise ValueError("hints must be 'always', 'after_delay' or 'never'")
        if not steps:
            raise ValueError("an exercise needs at least one step")
        self.steps = steps
        self.hints = hints
        self.hint_delay_s = hint_delay_s
        self.max_extra = max_extra
        self.results = [StepResult(s.label) for s in steps]
        self.index = 0
        self.finished = False
        self.presses = 0            # key presses judged
        self.wrong_presses = 0
        self._held: dict[str, int] = {}     # key id -> pitch, keys down now
        self._fresh: set[str] = set()       # of those, pressed during the current step
        self._attempt_open = False
        self._step_started = 0.0
        self._hint_out = False
        self._take = trills.Take()          # what is being struck of the trill step now
        self._takes: dict[int, trills.Take] = {}    # step index -> the take it was accepted with
        self._going: int | None = None      # a trill that goes on under the current steps

    # --- driving ---

    def start(self, t: float, held: dict[str, int] | None = None) -> list:
        """Begin at time `t`; `held`: keys already down (ignored until released)."""
        self._held = dict(held or {})
        return self._enter(0, t)

    def start_at(self, index: int, t: float, held: dict[str, int] | None = None) -> list:
        """Begin at a later step (to continue after a time limit)."""
        if not 0 <= index < len(self.steps):
            raise ValueError(f"step {index + 1} does not exist; the exercise has {len(self.steps)} steps")
        self._held = dict(held or {})
        return self._enter(index, t)

    def _enter(self, index: int, t: float) -> list:
        self.index = index
        self._fresh = set()
        self._attempt_open = False
        self._step_started = t
        self._hint_out = False
        self._take = trills.Take()
        if self._going is not None and not self.steps[index].under:
            self._going = None
        return self._maybe_hint(t)

    def _maybe_hint(self, t: float, failed: bool = False) -> list:
        if self._hint_out or self.finished or self.hints == "never":
            return []
        if self.hints == "always" or failed or t - self._step_started >= self.hint_delay_s:
            self._hint_out = True
            self.results[self.index].hint_shown = True
            return [ShowHint(self.index, self.steps[self.index].keys)]
        return []

    def tick(self, t: float) -> list:
        """Call regularly; shows a delayed hint when its time has come, and judges a trill
        once the player has stopped."""
        if self.finished:
            return []
        step = self.steps[self.index]
        if step.trill and self._take.last is not None and t - self._take.last >= self._take.idle_s():
            return self._trill_over(t)
        return self._maybe_hint(t)

    # --- a trill step ---

    def _judge(self, index: int, take: trills.Take, final: bool) -> dict:
        step = self.steps[index]
        return trills.judge(take, step.trill[0], step.trill[1], start_on_main=step.start_on_main, seconds=step.seconds,
                            with_notes=step.pitches, allowed_wrong=self.max_extra, final=final)

    def trill_facts(self, index: int) -> dict | None:
        """The judgement of a trill step, with everything struck of it up to now (a trill that
        went on under later steps is judged as a whole)."""
        if index in self._takes:
            return self._judge(index, self._takes[index], True)
        return self.results[index].trill

    def _feed_trill(self, ev: Press) -> list:
        step, result = self.steps[self.index], self.results[self.index]
        if not ev.on:
            self._held.pop(ev.key, None)
            return [Unmark(ev.key)]
        self._held[ev.key] = ev.pitch
        self._attempt_open = True
        self.presses += 1
        take = self._take
        take.last = ev.t
        if ev.pitch in step.trill[0] or ev.pitch in step.trill[1]:
            take.strokes.append((ev.t, ev.pitch, ev.velocity))
        elif ev.pitch in step.pitches:
            take.with_notes.add(ev.pitch)
        else:
            take.wrong += 1
            self.wrong_presses += 1
            result.wrong.append(ev.pitch)
            return [Mark(ev.key, False)]
        actions: list = [Mark(ev.key, True)]
        if step.goes_on and self._judge(self.index, take, False)["ok"]:
            actions += self._trill_done(ev.t)
        return actions

    def _trill_over(self, t: float) -> list:
        """The player has stopped: is what they played the trill?"""
        result = self.results[self.index]
        facts = self._judge(self.index, self._take, True)
        if facts["ok"]:
            return self._trill_done(t)
        result.trill = facts
        result.attempts += 1
        self._take = trills.Take()
        self._attempt_open = False
        return self._maybe_hint(t, failed=True)

    def _trill_done(self, t: float) -> list:
        index, result = self.index, self.results[self.index]
        self._takes[index] = self._take
        result.trill = self._judge(index, self._take, not self.steps[index].goes_on)
        going = index if self.steps[index].goes_on else None
        actions = self._done(t)
        self._going = going if not self.finished and self.steps[self.index].under else None
        return actions

    def _wanted(self, step: Step, key: str, pitch: int) -> bool:
        return key in step.keys if step.exact_keys else pitch in step.pitches

    def _covered(self, step: Step) -> bool:
        if step.exact_keys:
            return all(k in self._held for k in step.keys)
        return set(step.pitches) <= set(self._held.values())

    def feed(self, ev: Press) -> list:
        if self.finished:
            return []
        step, result = self.steps[self.index], self.results[self.index]
        if step.trill:
            return self._feed_trill(ev)
        actions: list = []
        if ev.on and ev.pitch in step.under and not self._wanted(step, ev.key, ev.pitch):
            self._held[ev.key] = ev.pitch       # the trill going on underneath: not wanted here, not wrong
            if self._going is not None:
                self._takes[self._going].strokes.append((ev.t, ev.pitch, ev.velocity))
            return [Mark(ev.key, True)]
        if ev.on:
            self._held[ev.key] = ev.pitch
            self._fresh.add(ev.key)
            self._attempt_open = True
            self.presses += 1
            good = self._wanted(step, ev.key, ev.pitch)
            actions.append(Mark(ev.key, good))
            if not good:
                self.wrong_presses += 1
                result.wrong.append(ev.pitch)
            return actions + self._check_done(ev.t)
        # key up
        self._held.pop(ev.key, None)
        actions.append(Unmark(ev.key))
        if ev.key in self._fresh:
            self._fresh.discard(ev.key)
            done = self._check_done(ev.t)   # lifting a wrong finger can complete the chord
            if done:
                return actions + done
            if self._attempt_open and not self._fresh:
                self._attempt_open = False
                result.attempts += 1        # let go without finishing
                actions += self._maybe_hint(ev.t, failed=True)
        return actions

    def _check_done(self, t: float) -> list:
        """Step done? All its notes are down, at least one of them pressed during this
        step, and no more than `max_extra` wrong keys are down with them."""
        step = self.steps[self.index]
        fresh_good = [k for k in self._fresh if self._wanted(step, k, self._held[k])]
        extras = len(self._fresh) - len(fresh_good)
        if not fresh_good or not self._covered(step) or extras > self.max_extra:
            return []
        return self._done(t)

    def _done(self, t: float) -> list:
        result = self.results[self.index]
        result.status = "ok"
        result.seconds = round(t - self._step_started, 2)
        result.attempts += 1
        actions: list = [StepDone(self.index)]
        if self.index + 1 < len(self.steps):
            actions += self._enter(self.index + 1, t)
        else:
            self.finished = True
            actions.append(Finished())
        return actions

    def stop(self, t: float, reason: str = "timed out") -> None:
        """End early. The current step gets `reason`, later ones stay 'not reached'."""
        if self.finished:
            return
        step, result = self.steps[self.index], self.results[self.index]
        result.status = reason
        result.seconds = round(t - self._step_started, 2)
        if self._attempt_open:
            result.attempts += 1
        held = set(self._held.values())
        result.missing = [p for p in step.pitches if p not in held]
        if step.trill:
            if self._take.last is not None:
                result.trill = self._judge(self.index, self._take, True)
            both = sorted(set(step.trill[0]) | set(step.trill[1]))
            result.missing = (result.trill["missing"] + result.trill["missing_with"]) if result.trill else both + list(step.pitches)
        self.finished = True

    # --- summary ---

    @property
    def completed(self) -> int:
        return sum(r.status == "ok" for r in self.results)

    @property
    def first_try(self) -> int:
        return sum(r.status == "ok" and r.attempts == 1 and not r.wrong for r in self.results)

    @property
    def accuracy(self) -> int:
        """Share of key presses that were right, in percent (100 if nothing was pressed)."""
        return round(100 * (self.presses - self.wrong_presses) / self.presses) if self.presses else 100
