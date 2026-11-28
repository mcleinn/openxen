"""Playing along with a composition of the library, and judging the rhythm of what was played.

Two ways to keep time (`mode`):
- "click": a click runs at a share of the piece's tempo and the player follows it. A note's error
  is played - due - the player's offset (`rhythm calibrate`), as in `rhythm.py`.
- "follow": no click. The player sets the tempo, the accompaniment waits for them, and the
  judgement is made against the player's own tempo (a straight line through each bar's notes): it
  speaks of evenness and proportions, not of absolute time.

How it works, and where each rule comes from, is in reference/research/rhythm-judgement.md:
- `plan` lays the chosen bars out as notes with their times; grace notes and the later strokes of
  a written-out trill are marked and never judged (no tool or paper times ornaments strictly).
- `align` matches played notes to written ones by dynamic programming over score onsets (what is
  due at one moment is one set, in any order: parangonar, Bloch & Dannenberg 1985) with a cost for
  a missing and for an extra note (Dannenberg 1984; Nakamura et al. 2017). Time only breaks ties.
- `judge` turns the matched notes into words. A chord's time is the mean of its notes
  (partitura's performance codec). Bands and wording are those of `rhythm.py`.
- `Follower` is a pointer with look-ahead that says where the player is while they play; it only
  steers the accompaniment and the end of a take in follow mode (PianoBooster's "follow you").
- `run` is the tool: it sounds click and accompaniment, collects the key presses and calls the rest.
"""

from __future__ import annotations

import heapq
import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from . import rhythm as R
from . import trills

HAND = {"upper": "right hand", "lower": "left hand"}
MISS = EXTRA = 1.0          # cost of a written note not played, of a played note not written
ORNAMENT = 0.05             # the same for a grace note or a trill stroke: nearly free
TIME_WEIGHT = 0.9           # most a matched note costs for lying far from its time: always below MISS
TEMPO_OFF = 0.08            # a bar counts as faster or slower from this share (tempo changes are heard from about 6 %)
TREND = 0.10                # speeding up or slowing down over the take counts from this share
HELD_FROM = 1.0             # notes written this long (quarter notes) or longer are checked for being held
HELD_SHARE = 0.5            # let go before this share of the length: "let go early"
FOLLOW_PAUSE_S = 6.0        # follow mode ends when the player has started and then kept quiet this long
FIRST_NOTE_S = 20.0         # and when nothing at all was played for this long
LOOK_AHEAD = 3              # how many moments ahead the follower looks for a note that does not fit here


@dataclass
class Note:
    """One written note of the player's part."""
    q: float                # quarter notes from the start of the first bar
    at: float               # seconds from there at the target tempo
    bar: int
    beat: float             # quarter notes into its bar
    hand: str               # upper | lower
    pitch: int
    quarters: float         # written length
    kind: str = "note"      # note | grace | trill (a later stroke of a written-out trill)
    trill: bool = False     # the print has a trill sign on it
    absorb: frozenset = frozenset()     # the notes of the trill it belongs to
    played: float | None = None         # when it was struck
    let_go: float | None = None


@dataclass
class Bar:
    n: int
    q: float
    at: float
    quarters: float
    seconds: float
    bpm: float
    time: str


@dataclass
class Group:
    """What is due at one moment, both hands together."""
    q: float
    at: float
    bar: int
    beat: float
    notes: list[Note] = field(default_factory=list)

    @property
    def judged(self) -> bool:
        return any(n.kind == "note" for n in self.notes)

    @property
    def absorb(self) -> frozenset:
        return frozenset().union(*(n.absorb for n in self.notes))


@dataclass
class Played:
    t: float
    pitch: int
    off: float | None = None


@dataclass
class Onset:
    """One hand's notes at one moment, as judged: struck at `t` (the mean of its notes)."""
    at: float
    q: float
    bar: int
    beat: float
    hand: str
    t: float | None
    spread: float
    due: float | None = None

    @property
    def error(self) -> float | None:
        return None if self.t is None or self.due is None else self.t - self.due


# --- the score as notes in time ---

def beats_in(time_signature: str, quarters: float) -> list[float]:
    """Where the click falls in a bar, in quarter notes from its start: every beat of the
    metre; in 6/8, 9/8 and 12/8 every dotted quarter."""
    try:
        count, unit = (int(x) for x in time_signature.split("/"))
    except ValueError:
        count, unit = 4, 4
    step = 4.0 / unit
    if unit >= 8 and count >= 6 and count % 3 == 0:
        step *= 3
    out, at = [], 0.0
    while at < quarters - 1e-6:
        out.append(round(at, 4))
        at += step
    return out


def plan(bars: list[dict], part: str, bpm_of: Callable[[int], float], pitch_of: Callable[[int], int],
         playable: Callable[[int], bool]) -> tuple[list[Note], list[Bar], list[int]]:
    """The chosen bars as notes of the player's part with their times, the bars, and the pitches
    that have no key (left out)."""
    notes: list[Note] = []
    rows: list[Bar] = []
    left_out: list[int] = []
    q0 = at0 = 0.0
    for bar in bars:
        bpm = bpm_of(bar["n"])
        quarter = 60.0 / bpm
        marks = {(m["staff"], round(m["beat"], 3), m["step"]): m["mark"] for m in bar.get("marks", [])}
        for staff, events in bar["staves"].items():
            if part not in (staff, "both"):
                continue
            for beat, dur, steps in events:
                for step in steps:
                    pitch = pitch_of(step)
                    if not playable(pitch):
                        left_out.append(pitch)
                        continue
                    mark = marks.get((staff, round(beat, 3), step))
                    notes.append(Note(q0 + beat, at0 + beat * quarter, bar["n"], beat, staff, pitch, dur,
                                      kind="grace" if mark == "grace" else "note", trill=mark == "trill"))
        rows.append(Bar(bar["n"], q0, at0, bar["length"], bar["length"] * quarter, bpm, bar["time"]))
        q0 += bar["length"]
        at0 += bar["length"] * quarter
    _mark_trills(notes)
    return notes, rows, left_out


def _mark_trills(notes: list[Note]) -> None:
    """The file holds trills and tremolos written out stroke by stroke. Which notes are such
    strokes is decided by `trills.find_runs`, the rule `library get` uses to hand a trill out as
    one step: after a trill sign, or two sides taking turns fast for a beat or more. The first
    stroke is judged like any note; the later ones are ornaments."""
    for hand in HAND:
        moments: list[list[Note]] = []
        for n in sorted((n for n in notes if n.hand == hand), key=lambda n: n.q):
            if moments and n.q - moments[-1][0].q <= 0.01:
                moments[-1].append(n)
            else:
                moments.append([n])
        events = [trills.Event(moment[0].q, max(n.quarters for n in moment), tuple(n.pitch for n in moment if n.kind != "grace"),
                               tuple(n.pitch for n in moment if n.trill), tuple(n.pitch for n in moment if n.kind == "grace"))
                  for moment in moments]
        at = {round(moment[0].q, 4): moment for moment in moments}
        for run in trills.find_runs(events):
            pool = frozenset(run.main) | frozenset(run.other)
            for k, (when, struck) in enumerate(run.strokes):
                for n in at.get(when, []):
                    if n.pitch in struck and n.kind != "grace":
                        n.absorb = pool
                        if k:
                            n.kind = "trill"


def groups_of(notes: list[Note]) -> list[Group]:
    """The notes by moment. A note both hands have at one moment is asked for once."""
    out: list[Group] = []
    for n in sorted(notes, key=lambda n: (n.q, n.kind != "note", n.hand, n.pitch)):
        if out and n.q - out[-1].q <= 0.01:
            if all(m.pitch != n.pitch for m in out[-1].notes):
                out[-1].notes.append(n)
        else:
            out.append(Group(n.q, n.at, n.bar, n.beat, [n]))
    return out


# --- matching what was played to what is written ---

def align(groups: list[Group], played: list[Played], due: list[float] | None = None,
          reach: list[float] | None = None) -> list[tuple[Played, int, bool]]:
    """Give every played note (in time order) to a written note of its pitch or call it extra, so
    that the fewest notes are missing or extra; the order of the moments is kept, the order inside
    a chord is free. `due`: when each moment is expected (seconds); a match costs a little for
    lying far from it (all of it at `reach` seconds), which decides between notes of one pitch.
    Sets `played` and `let_go` on the notes; returns the extra notes as (note, index of the moment
    they came before or in, whether a trill there absorbs them)."""
    for g in groups:
        for n in g.notes:
            n.played = n.let_go = None
    count_g, count_p = len(groups), len(played)
    inf = float("inf")
    cost = [[inf] * (count_p + 1) for _ in range(count_g + 1)]
    back: list[list[tuple[int, int] | None]] = [[None] * (count_p + 1) for _ in range(count_g + 1)]
    cost[0][0] = 0.0
    soaks = [g.absorb for g in groups]
    for i in range(count_g + 1):
        row = cost[i]
        soak = (soaks[i - 1] if i else frozenset()) | (soaks[i] if i < count_g else frozenset())
        g = groups[i] if i < count_g else None
        for j in range(count_p + 1):
            c = row[j]
            if c == inf:
                continue
            if j < count_p:                     # a played note that belongs to no moment
                step = c + (ORNAMENT if played[j].pitch in soak else EXTRA)
                if step < row[j + 1]:
                    row[j + 1] = step
                    back[i][j + 1] = (i, j)
            if g is None:
                continue
            want = {n.pitch: (MISS if n.kind == "note" else ORNAMENT) for n in g.notes}
            run = c + sum(want.values())
            first: float | None = None
            k = 0
            longest = len(g.notes) + 2
            while True:                         # this moment takes the next k played notes
                if run < cost[i + 1][j + k]:
                    cost[i + 1][j + k] = run
                    back[i + 1][j + k] = (i, j)
                if k == longest or j + k == count_p:
                    break
                p = played[j + k]
                k += 1
                if p.pitch in want:
                    run -= want.pop(p.pitch)
                    if due is not None:
                        run += TIME_WEIGHT * min(1.0, abs(p.t - due[i]) / (reach[i] if reach else 1.0))
                    if first is None:
                        first = p.t
                    else:
                        run += 0.05 * min(1.0, p.t - first)     # a chord's notes lie together
                else:
                    run += ORNAMENT if p.pitch in soaks[i] else EXTRA
    extras: list[tuple[Played, int, bool]] = []
    i, j = count_g, count_p
    while (i, j) != (0, 0):
        pi, pj = back[i][j]
        if pi == i:                             # a lone extra note
            p = played[pj]
            soak = (soaks[i - 1] if i else frozenset()) | (soaks[i] if i < count_g else frozenset())
            extras.append((p, i, p.pitch in soak))
        else:
            open_notes = {n.pitch: n for n in groups[pi].notes}
            for p in played[pj:j]:
                n = open_notes.pop(p.pitch, None)
                if n is not None:
                    n.played, n.let_go = p.t, p.off
                else:
                    extras.append((p, pi, p.pitch in soaks[pi]))
        i, j = pi, pj
    extras.sort(key=lambda e: e[0].t)
    return extras


class Follower:
    """Where the player is, note by note, while they play: the furthest moment reached. A note
    counts for the moment the player is in or one of the next few (so a skipped or wrong note does
    not stop it); anything else leaves the place unchanged."""

    def __init__(self, groups: list[Group], look: int = LOOK_AHEAD):
        self.groups = groups
        self.look = look
        self.at = -1
        self._hit: list[set[int]] = [set() for _ in groups]
        self._told: set[int] = set()
        self.last = max((i for i, g in enumerate(groups) if g.judged), default=-1)

    @property
    def done(self) -> bool:
        return self.at >= self.last

    def feed(self, pitch: int) -> int | None:
        """A key press. Returns the index of the moment it is the first judged note of, else None."""
        ahead = 0
        for i in range(max(self.at, 0), len(self.groups)):
            g = self.groups[i]
            if i > self.at and g.judged:
                ahead += 1
                if ahead > self.look:
                    break
            note = next((n for n in g.notes if n.pitch == pitch), None)
            if note is None or pitch in self._hit[i]:
                continue
            self._hit[i].add(pitch)
            self.at = max(self.at, i)
            if note.kind == "note" and i not in self._told:
                self._told.add(i)
                return i
            return None
        return None


# --- judging ---

def _fit(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Least squares line y = slope * x + intercept, None if x does not vary."""
    if len(points) < 2:
        return None
    mx = statistics.fmean(x for x, _ in points)
    my = statistics.fmean(y for _, y in points)
    spread = sum((x - mx) ** 2 for x, _ in points)
    if spread < 1e-9:
        return None
    slope = sum((x - mx) * (y - my) for x, y in points) / spread
    return slope, my - slope * mx


def _steady_line(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    """A line that single stray points do not move: the median of the slopes between pairs."""
    stride = max(1, len(points) // 40)
    slopes = [(y2 - y1) / (x2 - x1) for a, (x1, y1) in enumerate(points) for (x2, y2) in points[a + 1::stride] if x2 - x1 > 1e-6]
    if not slopes:
        return None
    slope = statistics.median(slopes)
    return slope, statistics.median(y - slope * x for x, y in points)


def _onsets(groups: list[Group]) -> list[Onset]:
    out = []
    for g in groups:
        for hand in HAND:
            times = [n.played for n in g.notes if n.hand == hand and n.kind == "note"]
            if not times:
                continue
            got = [t for t in times if t is not None]
            out.append(Onset(g.at, g.q, g.bar, g.beat, hand, statistics.fmean(got) if got else None, max(got) - min(got) if got else 0.0))
    return out


def _anchors(onsets: list[Onset]) -> list[tuple[float, float]]:
    """(due at the target tempo, played) per moment, the hands' times averaged."""
    by_at: dict[float, list[float]] = {}
    for o in onsets:
        if o.t is not None:
            by_at.setdefault(o.at, []).append(o.t)
    return [(at, statistics.fmean(ts)) for at, ts in sorted(by_at.items())]


def take_out_stops(groups: list[Group], played: list[Played]) -> list[tuple[int, float, float]]:
    """Follow mode: where the player stopped (a gap at least a second longer than the notes ask for,
    and more than twice as long), the stop is taken out of all times (the matched notes' and the
    played notes'), so that it is reported as a stop and not as a slow bar. Returns (bar, beat,
    seconds) per stop."""
    points = [(g, statistics.fmean(n.played for n in g.notes if n.kind == "note" and n.played is not None))
              for g in groups if any(n.kind == "note" and n.played is not None for n in g.notes)]
    paces = [(tb - ta) / (gb.at - ga.at) for (ga, ta), (gb, tb) in zip(points, points[1:]) if gb.at - ga.at > 1e-6]
    if len(paces) < 2:
        return []
    pace = statistics.median(paces)             # seconds played per second written, from note to note: a few stops do not move it
    cuts: list[tuple[float, float]] = []        # (from this time on, take away this much)
    stops = []
    for (ga, ta), (gb, tb) in zip(points, points[1:]):
        expected = (gb.at - ga.at) * pace
        excess = (tb - ta) - expected
        if excess > max(1.0, expected):
            cuts.append((tb - 1e-6, excess))
            stops.append((gb.bar, gb.beat, excess))

    def moved(t: float | None) -> float | None:
        return None if t is None else t - sum(amount for start, amount in cuts if t >= start)

    for g in groups:
        for n in g.notes:
            n.played, n.let_go = moved(n.played), moved(n.let_go)
    for p in played:
        p.t, p.off = moved(p.t), moved(p.off)
    return stops


def _bars_text(numbers: list[int]) -> str:
    numbers = sorted(set(numbers))
    return ("bar " if len(numbers) == 1 else "bars ") + ", ".join(map(str, numbers[:8])) + (" ..." if len(numbers) > 8 else "")


def _place(bar: int, beat: float) -> str:
    return f"bar {bar} beat {round(beat + 1, 2):g}"


def _figure(share: float) -> str:
    """A name for two successive distances of which the first takes this share."""
    for value, name in ((0.75, "dotted rhythm (long-short)"), (0.25, "short-long rhythm"), (2 / 3, "long-short rhythm (two to one)"),
                        (1 / 3, "short-long rhythm (one to two)")):
        if abs(share - value) < 0.03:
            return name
    return "even notes" if abs(share - 0.5) < 0.03 else "uneven rhythm"


def judge(groups: list[Group], rows: list[Bar], extras: list[tuple[Played, int, bool]], mode: str, level: str,
          label: Callable[[int], str], chord_window: float = 0.12, calibrated: bool = True,
          stops: list[tuple[int, float, float]] | None = None) -> dict:
    """What to tell the tutor about a take whose notes are matched (`align`). Times of the notes:
    seconds from the start of the first bar (click mode) or from anywhere (follow mode)."""
    bands = R.BANDS[level]
    onsets = _onsets(groups)
    anchors = _anchors(onsets)
    bar_of = {row.n: row for row in rows}
    out: dict = {}

    # notes: right, missing, wrong (a missing and an extra note at one place), extra
    judged = [n for g in groups for n in g.notes if n.kind == "note"]
    ornaments = [n for g in groups for n in g.notes if n.kind != "note"]
    free = [(p, i) for p, i, absorbed in extras if not absorbed]
    where: list[tuple[float, str]] = []
    wrong = 0
    weak_bars: list[int] = []
    for i, g in enumerate(groups):
        for n in g.notes:
            if n.kind != "note" or n.played is not None:
                continue
            weak_bars.append(n.bar)
            near = [e for e in free if e[1] in (i, i + 1)]
            if near:
                p = near[0][0]
                free.remove(near[0])
                wrong += 1
                where.append((n.q, f"{_place(n.bar, n.beat)}: {label(p.pitch)} for {label(n.pitch)}"))
            else:
                where.append((n.q, f"{_place(n.bar, n.beat)}: {label(n.pitch)} missing"))
    for p, i in free:                   # named by the nearer of the two moments it fell between
        around = [(abs(p.t - statistics.fmean(n.played for n in g.notes if n.played is not None)), k) for k, g in enumerate(groups)
                  if k in (i - 1, i) and any(n.played is not None for n in g.notes)]
        g = groups[min(around)[1] if around else min(i, len(groups) - 1)]
        where.append((g.q - 0.001, f"extra {label(p.pitch)} near {_place(g.bar, g.beat)}"))
    right = sum(n.played is not None for n in judged)
    out["notes"] = {"written": len(judged), "right": right, "missing": len(judged) - right - wrong, "wrong": wrong, "extra": len(free)}
    if where:
        where.sort()
        out["notes"]["where"] = [text for _, text in where[:6]] + ([f"and {len(where) - 6} more"] if len(where) > 6 else [])
    if ornaments:
        done = sum(n.played is not None for n in ornaments)
        out["ornaments"] = (f"{done} of {len(ornaments)} grace notes and trill strokes were played; they are not judged for time, "
                            f"and leaving them out is not counted as missing")
    if len(anchors) < 3:
        out["timing"] = "too few right notes to judge the time"
        out["practise_next"] = ("Too little of it was played to speak about rhythm. Take the notes first, without time pressure "
                                "(library get and run_exercise for these bars), then come back.")
        return out

    # the time each moment is compared with
    whole = _steady_line(anchors)
    if mode == "click":
        for o in onsets:
            o.due = o.at
    else:
        lines: dict[int, tuple[float, float] | None] = {}
        for row in rows:
            near = [(at, t) for at, t in anchors if row.at - row.seconds / 2 - 1e-6 <= at <= row.at + row.seconds * 1.5 + 1e-6]
            lines[row.n] = (_fit(near) if len(near) >= 4 else None) or whole
        for o in onsets:
            line = lines.get(o.bar) or whole
            o.due = line[0] * o.at + line[1] if line else None
    timed = [o for o in onsets if o.error is not None]
    errors = [o.error for o in timed]
    counts = R.spread_over_bands(errors, level)
    mean_ms = counts.pop("mean_ms", 0)
    spread_ms = counts.pop("spread_ms", 0)
    out["timing"] = {k: v for k, v in counts.items() if v}
    out["timing"]["bands_ms"] = dict(zip(R.GRADES, bands))

    # tempo: over the take and bar by bar
    ratios: dict[int, float] = {}       # the bar's tempo as a share of the target tempo
    gains: dict[int, float] = {}        # click mode: milliseconds the player fell behind (+) or got ahead (-) within the bar
    for n, row in enumerate(rows):
        inside = [(at, t) for at, t in anchors if row.at - 1e-6 <= at < row.at + row.seconds - 1e-6]
        if mode == "follow":
            inside += [(at, t) for at, t in anchors if at >= row.at + row.seconds - 1e-6][:1]
        if len(inside) < 3 or inside[-1][0] - inside[0][0] < 0.4 * row.seconds:
            continue
        line = _fit(inside)
        if line and line[0] > 0.05:
            ratios[row.n] = 1.0 / line[0]
            gains[row.n] = (line[0] - 1.0) * row.seconds * 1000
    trend = None                        # "rushing" | "dragging" over the whole take
    tempo_bars: dict[int, str] = {}
    one_tempo = len({row.bpm for row in rows}) == 1
    if mode == "click":
        drift = R.drift_ms([o.at for o in timed], errors) if len(timed) >= 6 else 0.0
        # steady = the errors grow along a line; one bar that ran away does not make a line
        along = statistics.correlation([o.at for o in timed], errors) ** 2 if len(timed) >= 6 and len(set(errors)) > 1 else 0.0
        if abs(drift) > bands[0] and along >= 0.6:
            trend = "dragging" if drift > 0 else "rushing"
            share = abs((1.0 / whole[0] if whole else 1.0) - 1.0) * 100
            out["tempo_played"] = (f"{trend} steadily: by the end about {abs(drift):.0f} ms {'behind' if drift > 0 else 'ahead of'} where the take "
                                   f"began against the click (about {share:.0f} % {'slower' if drift > 0 else 'faster'} than the click)")
        else:
            for n, gain in gains.items():
                if abs(gain) > bands[0]:
                    tempo_bars[n] = (f"{'dragged' if gain > 0 else 'rushed'}: {'fell' if gain > 0 else 'got'} about {abs(gain):.0f} ms "
                                     f"{'behind' if gain > 0 else 'ahead'} within the bar")
            out["tempo_played"] = "kept the click's tempo" + (f", except in {_bars_text(list(tempo_bars))}" if tempo_bars else "")
    else:
        own = 1.0 / whole[0] if whole and whole[0] > 0.05 else 1.0
        if one_tempo:
            out["tempo_played"] = (f"about {rows[0].bpm * own:.0f} quarter notes per minute; the target was {rows[0].bpm:.0f} "
                                   f"({own * 100:.0f} % of it)")
        else:
            out["tempo_played"] = f"about {own * 100:.0f} % of the target tempo"
        numbers = sorted(ratios)
        if len(numbers) >= 3:
            line = _fit([(bar_of[n].at, ratios[n]) for n in numbers])
            change = line[0] * (bar_of[numbers[-1]].at - bar_of[numbers[0]].at) / own if line else 0.0
            steps = [ratios[b] - ratios[a] for a, b in zip(numbers, numbers[1:])]
            if abs(change) > TREND and sum((s > 0) == (change > 0) for s in steps) >= 0.6 * len(steps):
                trend = "rushing" if change > 0 else "dragging"
                first, last = ratios[numbers[0]], ratios[numbers[-1]]
                figures = (f"from about {rows[0].bpm * first:.0f} to {rows[0].bpm * last:.0f} quarter notes per minute" if one_tempo
                           else f"from about {first * 100:.0f} % to {last * 100:.0f} % of the target tempo")
                out["tempo_played"] += f"; {'sped up' if change > 0 else 'slowed down'} steadily ({trend}): {figures}"
        if trend is None and len(numbers) >= 2:
            middle = statistics.median(ratios.values())
            for n in numbers:
                share = ratios[n] / middle - 1.0
                if abs(share) > TEMPO_OFF:
                    tempo_bars[n] = f"{'rushed' if share > 0 else 'dragged'}: about {abs(share) * 100:.0f} % {'faster' if share > 0 else 'slower'} than the other bars"
        if stops:
            out["stops"] = [f"before {_place(bar, beat)}: about {seconds:.0f} s" for bar, beat, seconds in stops[:5]]

    # how the take sat as a whole
    side = R.lean(mean_ms, level)
    if mode == "click":
        if side == "on it":
            out["sits"] = f"on it (mean {mean_ms:+d} ms, spread {spread_ms} ms)"
        else:
            constant = trend is None and not tempo_bars and spread_ms <= bands[0]
            out["sits"] = (f"{side} by about {abs(mean_ms)} ms on average (spread {spread_ms} ms)"
                           + ("; evenly so in every bar: a constant " + ("lead" if side == "early" else "lag")
                              + ", not " + ("rushing" if side == "early" else "dragging") if constant else ""))
            if constant and not calibrated:
                out["not_calibrated"] = ("The player's offset has not been measured, so this may be the equipment's delay and not the player: "
                                         "run rhythm action calibrate once and repeat.")
    else:
        out["evenness"] = (("even" if spread_ms <= bands[0] else "fairly even" if spread_ms <= bands[1] else "uneven")
                           + f": the notes lie {spread_ms} ms (spread) around the player's own tempo")

    # bar by bar and hand by hand
    hands = [h for h in HAND if any(o.hand == h for o in onsets)]
    bars: dict[str, str] = {}
    for row in rows:
        said: list[tuple[str, str, float | None, str]] = []      # hand, early / late / on it / not played, milliseconds, what is missing
        for hand in hands:
            mine = [o for o in onsets if o.bar == row.n and o.hand == hand]
            if not mine:
                continue
            got = [o.error for o in mine if o.error is not None]
            if not got:
                said.append((hand, "not played", None, ""))
                continue
            ms = statistics.fmean(got) * 1000
            said.append((hand, R.lean(ms, level), ms, f", {len(mine) - len(got)} of {len(mine)} places not played" if len(got) < len(mine) else ""))
        if not said:
            continue

        def word(lean: str, ms: float | None, missing: str) -> str:
            return (lean if lean in ("on it", "not played") else f"{lean} (about {abs(ms):.0f} ms)") + missing

        if len(said) == 2 and said[0][1] == said[1][1] and not said[0][3] and not said[1][3]:
            text = "both hands " + word(said[0][1], None if said[0][2] is None else (said[0][2] + said[1][2]) / 2, "")
        elif len(hands) > 1:
            text = "; ".join(f"{HAND[hand]} {word(lean, ms, missing)}" for hand, lean, ms, missing in said)
        else:
            text = word(*said[0][1:])
        if row.n in tempo_bars:
            text += "; " + tempo_bars[row.n]
        bars[str(row.n)] = text
    out["by_bar"] = bars

    # the hands against each other
    if len(hands) == 2:
        upper = {o.at: o.t for o in onsets if o.hand == "upper" and o.t is not None}
        pairs = [(o.bar, o.t - upper[o.at]) for o in onsets if o.hand == "lower" and o.t is not None and o.at in upper]
        if len(pairs) >= 3:
            apart = statistics.fmean(d for _, d in pairs) * 1000
            off = [bar for bar, d in pairs if abs(d) * 1000 > bands[0]]
            if abs(apart) > bands[0] or len(off) > len(pairs) / 2:
                out["hands"] = (f"not together: the left hand comes about {abs(apart):.0f} ms {'after' if apart > 0 else 'before'} the right "
                                f"where both strike ({len(off)} of {len(pairs)} places, {_bars_text(off)})") if abs(apart) > bands[0] / 2 else \
                               f"not together, now one hand first and now the other ({len(off)} of {len(pairs)} places, {_bars_text(off)})"
            else:
                out["hands"] = f"together ({len(pairs)} places where both strike, the left on average {apart:+.0f} ms against the right)"
        else:
            sides = {h: [o.error for o in timed if o.hand == h] for h in hands}
            if all(len(v) >= 4 for v in sides.values()):
                apart = (statistics.fmean(sides["lower"]) - statistics.fmean(sides["upper"])) * 1000
                out["hands"] = (f"the left hand lies about {abs(apart):.0f} ms {'after' if apart > 0 else 'before'} the right against the beat"
                                if abs(apart) > bands[0] else "together against the beat (they rarely strike at the same moment here)")
    broken = [o.bar for o in onsets if o.spread > chord_window]
    if broken:
        out["chords"] = f"{len(broken)} chord{'s' if len(broken) != 1 else ''} not struck together (notes more than {chord_window * 1000:.0f} ms apart): {_bars_text(broken)}"

    # proportions: three successive notes of one hand, the share of the first distance
    figures: dict[tuple[int, str], tuple[bool, str]] = {}     # one finding per bar and hand, a figure that starts on a beat first
    for hand in hands:
        mine = [o for o in onsets if o.hand == hand]
        for a, b, c in zip(mine, mine[1:], mine[2:]):
            if None in (a.t, b.t, c.t) or c.q - a.q > 2.5 or c.t - a.t <= 0:
                continue
            written = (b.at - a.at) / (c.at - a.at)
            was = (b.t - a.t) / (c.t - a.t)
            if abs(was - written) * (c.t - a.t) * 1000 <= bands[0] or abs(was - written) < 0.06:
                continue
            if abs(written - 0.5) >= 0.1 and abs(was - 0.5) < abs(was - written):
                text = f"the {_figure(written)} was played even"
            elif abs(written - 0.5) < 0.03 and abs(was - 0.5) > 0.1 and a.bar == c.bar and b.bar not in tempo_bars:
                text = f"the even notes were played uneven ({'long-short' if was > 0.5 else 'short-long'})"
            elif abs(written - 0.5) >= 0.1 and abs(was - written) > 0.1 and (was - 0.5) * (written - 0.5) > 0:
                text = f"the {_figure(written)} was overdone (the short note too short)"
            else:
                continue
            off_beat = abs(a.beat - round(a.beat)) > 0.01
            if (b.bar, hand) not in figures or (figures[(b.bar, hand)][0] and not off_beat):
                figures[(b.bar, hand)] = (off_beat, text)
    if figures:
        listed = sorted(figures.items())
        out["rhythms"] = [f"bar {bar}, {HAND[hand]}: {text}" for (bar, hand), (_, text) in listed[:5]] + ([f"and {len(listed) - 5} more"] if len(listed) > 5 else [])

    # held notes
    own_rate = whole[0] if whole and mode == "follow" and whole[0] > 0.05 else 1.0
    long_notes = [n for n in judged if n.played is not None and n.quarters >= HELD_FROM]
    short = [n for n in long_notes if n.let_go is not None and n.let_go - n.played < HELD_SHARE * n.quarters * 60.0 / bar_of[n.bar].bpm * own_rate]
    if short:
        out["held"] = (f"{len(short)} of {len(long_notes)} long notes were let go before half their length: {_bars_text([n.bar for n in short])} "
                       f"(e.g. {label(short[0].pitch)} in {_place(short[0].bar, short[0].beat)})")

    out["_facts"] = {"trend": trend, "constant": mode == "click" and side != "on it" and trend is None and not tempo_bars and spread_ms <= bands[0],
                     "side": side if mode == "click" else "on it", "weak_bars": sorted(set(weak_bars)),
                     "missed_share": 1 - right / max(1, len(judged)), "off_share": (counts["near"] + counts["off"]) / max(1, len(errors)),
                     "tempo_bars": sorted(tempo_bars), "figure_bars": sorted({bar for bar, _ in figures}),
                     "hands_apart": str(out.get("hands", "")).startswith(("not together", "the left hand lies"))}
    return out


def advice(facts: dict, mode: str, slower: str, faster: str, calibrated: bool) -> str:
    """One or two sentences on what to practise next, the most important first."""
    say = []
    if facts["missed_share"] > 0.25:
        say.append(f"The notes are not safe yet ({_bars_text(facts['weak_bars'])}): take those bars without time pressure first "
                   f"(library get and run_exercise), then play along again, {slower}.")
    if facts["trend"] == "rushing":
        say.append("The tempo runs away: repeat it and let the player wait for each beat; counting aloud helps."
                   if mode == "follow" else "The player runs ahead of the click: repeat at the same tempo and listen for the click before each beat.")
    elif facts["trend"] == "dragging":
        say.append("The tempo sinks: let the player choose a tempo they can keep to the end and count aloud." if mode == "follow"
                   else f"The player falls behind the click: repeat {slower} until it holds.")
    if facts["figure_bars"]:
        say.append(f"Take the rhythm of {_bars_text(facts['figure_bars'])} alone: clap or tap it (rhythm action play with it as an own "
                   f"pattern), then play it again.")
    if facts["tempo_bars"] and not facts["trend"]:
        say.append(f"Repeat {_bars_text(facts['tempo_bars'])} with the bar before, so that the tempo goes through.")
    if facts["hands_apart"]:
        say.append("The hands do not strike together: each hand once alone, then both slowly, listening for one sound where both strike.")
    if facts["off_share"] > 0.4 and facts["missed_share"] <= 0.25 and not facts["constant"] and not say:
        say.append(f"Many notes lie far from their time: repeat {slower}.")
    if facts["side"] != "on it" and not facts["trend"] and not say:
        say.append("The notes are even but sit " + facts["side"] + (": measure the player's offset first (rhythm action calibrate)."
                   if not calibrated else ": let the player aim a little " + ("later" if facts["side"] == "early" else "earlier") + "."))
    if not say:
        say.append(f"This held: go on {faster}, or to the next bars." if mode == "click" else
                   "Even and in proportion: now with the click (mode click) at about the tempo just played.")
    return " ".join(say[:2])


# --- the tool ---

class _Sounds(threading.Thread):
    """Sounds things at their times on its own thread, so that listening for keys is never held up."""

    def __init__(self):
        super().__init__(name="tutor-playalong", daemon=True)
        self._heap: list[tuple[float, int, Callable[[], None]]] = []
        self._cond = threading.Condition()
        self._over = False
        self._count = 0

    def at(self, when: float, what: Callable[[], None]) -> None:
        with self._cond:
            self._count += 1
            heapq.heappush(self._heap, (when, self._count, what))
            self._cond.notify()

    def end(self) -> None:
        with self._cond:
            self._over = True
            self._cond.notify()

    def run(self) -> None:
        while True:
            with self._cond:
                while not self._over and (not self._heap or self._heap[0][0] > time.monotonic()):
                    self._cond.wait(None if not self._heap else max(0.0, self._heap[0][0] - time.monotonic()))
                if self._over:
                    return
                _, _, what = heapq.heappop(self._heap)
            try:
                what()
            except Exception:       # a keyboard that is away for a moment must not end the take
                pass


def run(tutor, id: str | None, from_bar: int, to_bar: int | None, part: str, mode: str, speed: float, tempo_bpm: float | None,
        nearest: bool, count_in: int, click: bool, accompany: bool, level: str, pause_s: float, progress=None) -> dict:
    """The play_along tool (see `Tutor.play_along`)."""
    from .session import CHORD_WINDOW_S, MAX_BLOCK_S, TutorError
    from .theory import tuning_for

    mode = (mode or "click").strip().lower()
    if mode not in ("click", "follow"):
        raise TutorError("mode must be click (the player follows a click) or follow (no click, the player sets the tempo)")
    if level not in R.BANDS:
        raise TutorError(f"level must be one of: {', '.join(R.BANDS)}")
    if part not in ("upper", "lower", "both"):
        raise TutorError("part must be upper (right hand), lower (left hand) or both")
    if not 0.1 <= speed <= 2:
        raise TutorError("speed must be between 0.1 (a tenth of the tempo) and 2")
    tutor._need_player("play_along")
    piece = tutor.music.piece(id) if id else None
    if piece is None:
        raise TutorError("give the id of a piece (library search tradition=composition lists them)")
    if not piece.get("score"):
        raise TutorError("play_along is for compositions in two staves (tradition composition); for other pieces use run_exercise, "
                         "and rhythm for their rhythm alone")
    kb = tutor.keyboard
    t = kb.tuning
    bars = piece["score"]
    if piece["tuning"] != t.edo and not nearest:
        raise TutorError(f"this piece is written in {piece['tuning']} notes per octave and the keyboard is in {t.edo}. Switch with tuning to "
                         f"{piece['tuning']}, or ask again with nearest=true to play it on the nearest notes here (an approximation).")
    to_bar = len(bars) if to_bar is None else to_bar
    if not 1 <= from_bar <= to_bar <= len(bars):
        raise TutorError(f"from_bar and to_bar must lie between 1 and {len(bars)}, from_bar first")
    written = tuning_for(piece["tuning"]) if piece["tuning"] != t.edo else None

    def here(step: int) -> int:
        return t.retuned_from(written, step)[0] if written else step

    # the same transposition as the bars handed out by library get for this part
    every = [here(s) for bar in bars for staff, events in bar["staves"].items() if part in (staff, "both") for _, _, steps in events for s in steps]
    shift = tutor._fit_shift(every)[0]
    tempi = sorted(piece.get("tempi") or [])

    def bpm_of(n: int) -> float:
        marked = [bpm for bar, bpm in tempi if bar <= n]
        bpm = float(tempo_bpm) if tempo_bpm else (marked[-1] if marked else 60.0) * speed
        if not 10 <= bpm <= 400:
            raise TutorError(f"that gives {bpm:.0f} quarter notes per minute in bar {n}; choose a speed or tempo_bpm between 10 and 400")
        return bpm

    count_in = max(0, min(int(count_in), 2)) if mode == "click" else 0
    chosen = bars[from_bar - 1:to_bar]
    lead_bar = chosen[0]
    lead_quarter = 60.0 / bpm_of(lead_bar["n"])
    lead_clicks = [(c * lead_bar["length"] + b) * lead_quarter for c in range(count_in) for b in beats_in(lead_bar["time"], lead_bar["length"])]
    lead = count_in * lead_bar["length"] * lead_quarter
    cut = None
    if mode == "click":             # what does not fit into one call is left for the next
        fits, total = 0, lead + 1.5
        for bar in chosen:
            total += bar["length"] * 60.0 / bpm_of(bar["n"])
            if total > MAX_BLOCK_S:
                break
            fits += 1
        if fits == 0:
            raise TutorError(f"bar {from_bar} alone takes longer than the {MAX_BLOCK_S:.0f} s of one call at this tempo; raise the speed or leave out the count-in")
        if fits < len(chosen):
            cut = chosen[fits]["n"]
            chosen = chosen[:fits]
    notes, rows, left_out = plan(chosen, part, bpm_of, lambda step: here(step) + shift, lambda pitch: bool(kb.keys_for_pitch(pitch)))
    groups = groups_of(notes)
    if not any(g.judged for g in groups):
        raise TutorError("there is nothing to play in these bars for this part on this keyboard")
    total = rows[-1].at + rows[-1].seconds

    # the other hand, played by the server
    other = {"upper": "lower", "lower": "upper"}.get(part) if accompany else None
    backing: dict[float, list] = {}
    if other:
        at = 0.0
        for bar in chosen:
            quarter = 60.0 / bpm_of(bar["n"])
            for beat, dur, steps in bar["staves"].get(other, []):
                for step in steps:
                    pitch = here(step) + shift
                    if not kb.keys_for_pitch(pitch):
                        pitch = next((pitch + k * t.edo for k in (-1, 1, -2, 2, -3, 3) if kb.keys_for_pitch(pitch + k * t.edo)), None)
                        if pitch is None:
                            continue
                    key = kb.keys_for_pitch(pitch)[0]
                    backing.setdefault(round(at + beat * quarter, 4), []).append(((key.board, key.key), 64, max(30, int(dur * quarter * 950))))
            at += bar["length"] * quarter
    moments = sorted(backing.items())

    told: dict = {"piece": piece["title"], "bars": f"{rows[0].n}-{rows[-1].n}" if len(rows) > 1 else str(rows[0].n), "part": part, "mode": mode,
                  "level": level}
    target = (f"{rows[0].bpm:.0f} quarter notes per minute" if len({r.bpm for r in rows}) == 1
              else f"{min(r.bpm for r in rows):.0f} to {max(r.bpm for r in rows):.0f} quarter notes per minute")
    told["tempo"] = target + ("" if tempo_bpm or speed == 1 else f" ({speed:g} of the piece's tempo)") + (" as the target" if mode == "follow" else "")
    if shift:
        told["moved"] = f"the whole piece {tutor._shift_words(shift)} to fit the keyboard" + ("" if part == "both" else " (for this hand alone)")
    if written:
        told["approximated"] = f"written for {piece['tuning']} notes per octave, played on the nearest notes of {t.edo}"
    if left_out:
        told["left_out"] = [t.label(p) for p in sorted(set(left_out))]
    if other:
        told["accompanied"] = f"the {HAND[other]} was played by the keyboard" + (", waiting for the player" if mode == "follow" else "")

    sounds = _Sounds()
    sounding: set = set()

    def strike(chord: list) -> None:
        tutor.client.notes(on=chord)
        sounding.update(addr for addr, _, _ in chord)

    tutor._begin()
    q = tutor.pump.subscribe()
    presses: list[Played] = []
    down: dict[str, Played] = {}
    outcome = "finished"
    reached = -1                    # follow mode: the furthest moment the player got to
    origin = 0.0
    try:
        if tutor.pump.error:
            raise TutorError(tutor.pump.error)
        began = time.monotonic()
        if mode == "click":
            zero = began + 0.4
            origin = zero + lead
            for n, at in enumerate(lead_clicks):
                sounds.at(zero + at, lambda accent=(n == 0): tutor._click(accent))
            if click:
                for row, bar in zip(rows, chosen):
                    for beat in beats_in(bar["time"], bar["length"]):
                        sounds.at(origin + row.at + beat * 60.0 / row.bpm, lambda accent=(beat == 0): tutor._click(accent))
            for at, chord in moments:
                sounds.at(origin + at, lambda chord=chord: strike(chord))
            sounds.start()
            end = origin + total + min(0.6, 60.0 / rows[-1].bpm)
            shown = 0
            while True:
                ev = tutor._events_until(q, end)
                if ev is None:
                    outcome = "stopped" if tutor._cancel.is_set() else "finished"
                    break
                now = time.monotonic()
                while progress and shown < len(rows) and now >= origin + rows[shown].at:
                    shown += 1
                    progress(shown, len(rows), f"bar {rows[shown - 1].n}")
                if ev is False:
                    continue
                if ev.on:
                    down[ev.key] = Played(ev.t, ev.pitch)
                    presses.append(down[ev.key])
                elif ev.key in down:
                    down.pop(ev.key).off = ev.t
            if outcome == "stopped":
                reached_bar = next((row.n for row in reversed(rows) if time.monotonic() >= origin + row.at), rows[0].n)
                rows_played = [row for row in rows if row.n <= reached_bar]
                keep = {row.n for row in rows_played}
                groups = [g for g in groups if g.bar in keep]
                rows = rows_played or rows[:1]
        else:
            follower = Follower(groups)
            judged_at = [g.at for g in groups if g.judged]
            sent = 0
            for at, chord in moments:           # what the other hand has before the player's first note
                if at >= judged_at[0] - 1e-6:
                    break
                sounds.at(began + 0.5 + at, lambda chord=chord: strike(chord))
                sent += 1
            sounds.start()
            pause_s = max(0.0, float(pause_s))
            rate = 1.0                          # seconds played per second written, as heard so far
            before: tuple[float, float] | None = None
            last_activity = began
            end = None
            bar_shown = None
            while True:
                ev = tutor._events_until(q, min(began + MAX_BLOCK_S, end) if end else began + MAX_BLOCK_S)
                now = time.monotonic()
                if ev is None:
                    outcome = "stopped" if tutor._cancel.is_set() else "finished" if end and now >= end else "time limit"
                    break
                if ev is False:
                    if end is None and not presses and now - began >= FIRST_NOTE_S:
                        outcome = "nothing played"
                        break
                    if end is None and presses and not down and pause_s and now - last_activity >= pause_s:
                        outcome = "player paused"
                        break
                    continue
                last_activity = ev.t
                if not ev.on:
                    if ev.key in down:
                        down.pop(ev.key).off = ev.t
                    continue
                down[ev.key] = Played(ev.t, ev.pitch)
                presses.append(down[ev.key])
                i = follower.feed(ev.pitch)
                reached = follower.at
                if i is None:
                    continue
                g = groups[i]
                if before and g.at - before[0] > 1e-6:
                    rate = 0.5 * rate + 0.5 * min(3.0, max(0.33, (ev.t - before[1]) / (g.at - before[0])))
                before = (g.at, ev.t)
                upto = next((at for at in judged_at if at > g.at + 1e-6), float("inf"))
                while sent < len(moments) and moments[sent][0] < g.at - 1e-6:
                    sent += 1                   # the player is past these
                while sent < len(moments) and moments[sent][0] < upto - 1e-6:
                    sounds.at(ev.t + (moments[sent][0] - g.at) * rate, lambda chord=moments[sent][1]: strike(chord))
                    sent += 1
                if progress and g.bar != bar_shown:
                    bar_shown = g.bar
                    progress(g.bar - rows[0].n + 1, len(rows), f"bar {g.bar}")
                if follower.done and end is None:
                    end = now + 0.6             # for the rest of a last chord
    finally:
        sounds.end()
        tutor.pump.unsubscribe(q)
        if sounding and outcome != "finished":
            try:
                tutor.client.notes(off=list(sounding))
            except Exception:
                pass
        tutor._activity.release()
        tutor._told_until_now()         # what was played here is judged in the result

    # judging
    offset = (tutor.player.offset_ms or 0.0) / 1000 if mode == "click" else 0.0
    quarter = 60.0 / rows[0].bpm
    if mode == "click":
        base = origin + offset
        played = [Played(p.t - base, p.pitch, None if p.off is None else p.off - base) for p in presses if p.t - base > -min(quarter, 0.5)]
    else:
        base = presses[0].t if presses else 0.0
        played = [Played(p.t - base, p.pitch, None if p.off is None else p.off - base) for p in presses]
        if outcome != "finished" and reached >= 0:      # what the player did not get to is not missing
            last_bar = groups[reached].bar
            groups = [g for g in groups if g.bar <= last_bar]
            rows = [row for row in rows if row.n <= last_bar]
    played.sort(key=lambda p: p.t)
    stops: list = []
    if mode == "click":
        extras = align(groups, played, [g.at for g in groups], [max(1.0, 2 * 60.0 / r.bpm) for g in groups for r in rows if r.n == g.bar])
    else:
        extras = align(groups, played)                  # by the order of the notes alone
        stops = take_out_stops(groups, played)
        line = _steady_line(_anchors(_onsets(groups)))
        if line and line[0] > 0.05:                     # again, now knowing roughly when each note was due
            extras = align(groups, played, [line[0] * g.at + line[1] for g in groups], [max(1.5, 3 * quarter * line[0])] * len(groups))
    calibrated = tutor.player.offset_ms is not None
    result = judge(groups, rows, extras, mode, level, t.label, CHORD_WINDOW_S, calibrated, stops)
    facts = result.pop("_facts", None)
    if facts:
        if tempo_bpm:
            slower, faster = f"slower (tempo_bpm {rows[0].bpm * 0.8:.0f})", f"faster (tempo_bpm {rows[0].bpm * 1.15:.0f})"
        else:
            slower = f"slower (speed {max(0.1, round(speed * 0.8, 2)):g})"
            faster = f"faster (speed {min(2.0, round(speed + 0.15, 2)):g})" if speed < 1 else "at this tempo with fewer clicks to lean on (click=false)"
        result["practise_next"] = advice(facts, mode, slower, faster, calibrated)
    out = {**told, "outcome": outcome, **result}
    next_bar = cut if cut and outcome == "finished" else rows[-1].n if outcome not in ("finished", "nothing played") else None
    if next_bar:
        out["continue_with"] = (f"play_along with from_bar={next_bar}" + (f" and to_bar={to_bar}" if to_bar > next_bar else "")
                                + (": the bars after did not fit into this call" if cut and outcome == "finished" else ": the take ended in that bar"))
    out["what_now"] = ("Tell the player in plain words how the time was, the one or two things that matter most, then what to do next. "
                       "Early and late are against the " + ("click" if mode == "click" else "player's own even tempo")
                       + "; do not read figures out beyond one or two.")
    return out
