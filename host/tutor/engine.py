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
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Press:
    """A key going down (`on`) or up, at `t` seconds."""
    t: float
    key: str        # key id
    pitch: int
    on: bool


@dataclass(frozen=True)
class Step:
    label: str                      # what the player is asked for: "C major", "E4"
    pitches: tuple[int, ...]        # the notes that must sound
    keys: tuple[str, ...] = ()      # keys shown as the hint (and required with exact_keys)
    exact_keys: bool = False


@dataclass
class StepResult:
    label: str
    status: str = "not reached"     # ok | timed out | stopped | not reached
    seconds: float = 0.0
    attempts: int = 0
    wrong: list[int] = field(default_factory=list)      # pitches of wrong presses, in order
    missing: list[int] = field(default_factory=list)    # pitches not held when time ran out
    hint_shown: bool = False


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
        """Call regularly; shows a delayed hint when its time has come."""
        return self._maybe_hint(t)

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
        actions: list = []
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
        step, result = self.steps[self.index], self.results[self.index]
        fresh_good = [k for k in self._fresh if self._wanted(step, k, self._held[k])]
        extras = len(self._fresh) - len(fresh_good)
        if not fresh_good or not self._covered(step) or extras > self.max_extra:
            return []
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
