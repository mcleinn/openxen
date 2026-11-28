"""Trills and tremolos: found in a score that holds them written out, judged by their effect,
and laid out as strokes for a demonstration. Pure functions, no keyboard and no clock.

What a trill is, and the reading used here (sources in docs/tutor.md, "Trills and tremolos"):
- A trill is a rapid alternation between two adjacent notes, a semitone or a tone apart
  (E. Taylor, The AB Guide to Music Theory I, p. 92). A tremolo between two notes or two
  chords is the same thing at any interval; it is measured when the rate is written and
  unmeasured when it is to be as fast as it goes ("Tremolo", Wikipedia, after Forsyth,
  Orchestration). How many times the notes alternate is not part of the text: it "can vary
  according to the length of the notated note" ("Trill (music)", Wikipedia).
- Which note begins changed with the period: on the upper note in the Baroque and Classical
  era, on the main note in music after Mozart (same article). Wyschnegradsky's preludes are
  of 1934, so the plain modern reading is used: the trill begins on the main (written)
  note unless a grace note before it says otherwise, alternates with the note the source
  gives, and is unmeasured.

This project's own choices, not taken from a source: the numbers below (what counts as a
written-out tremolo without a sign, how few changes make a trill, the bands for "even").
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from . import rhythm as R

EPS = 1e-3
FIRST_GAP = 0.34        # a trill sign's second stroke follows within this many quarter notes
FAST_GAP = 0.125        # without a sign: strokes a thirty-second note apart or closer ...
MIN_STROKES = 6         # ... at least this many of them ...
MIN_QUARTERS = 1.0      # ... for a beat or more, the two sides taking turns
ALTERNATING = 0.8       # share of strokes that change side
LONG = 3.0              # a note of the trill this many strokes long ends it: its closing note

MIN_CHANGES = 3         # from one key to the other at least this often: below that it is no trill
EVEN = (0.15, 0.30, 0.60)       # spread of the distances between strokes, as a share of their mean: even, fairly even, uneven; beyond: lumpy
LIMP = 1.4              # one direction this much slower than the other: the trill limps
SHORT = 0.5             # shorter than this share of the written time: too short
SLOW, FAST = 4.0, 8.0   # strokes per second: below slow, from fast on fast
WEAKER = 0.8            # one note struck this much softer than the other on average
END_S = (0.6, 1.5)      # the player has stopped: nothing new for this long (at least, at most)
DEMO_STROKE = 0.125     # a demonstrated trill without a written rate: thirty-second notes (eight to a beat)
DEMO_MAX_RATE = 12.0    # strokes per second the keyboard's sound still tells apart


# --- finding written-out trills and tremolos ---

@dataclass(frozen=True)
class Event:
    """What one hand has at one moment (quarter notes from the first bar looked at)."""
    at: float
    dur: float                          # of the longest note there
    pitches: tuple[int, ...]            # without grace notes
    marked: tuple[int, ...] = ()        # of those, the notes under the print's trill sign
    grace: tuple[int, ...] = ()         # grace notes at this moment: never strokes


@dataclass
class Run:
    """One trill or tremolo as the file holds it."""
    start: float
    end: float
    main: tuple[int, ...]               # the side it starts on (a note or a chord)
    other: tuple[int, ...]
    strokes: list[tuple[float, tuple[int, ...]]]    # when, and which of its notes
    gap: float                          # the usual distance between strokes
    marked: bool                        # the print has a trill sign
    lead_in: tuple[int, ...] = ()       # grace notes just before it
    ending: tuple[int, ...] = ()        # grace notes among its last strokes: a written-out ending

    @property
    def quarters(self) -> float:
        return round(self.end - self.start, 4)

    def has(self, at: float, pitch: int) -> bool:
        return any(abs(at - when) < EPS and pitch in notes for when, notes in self.strokes)


def _grow(events: list[Event], i: int, main: tuple[int, ...], other: tuple[int, ...]) -> tuple[list[tuple[int, tuple[int, ...]]], float | None, int]:
    """The strokes from event i on: (index, notes of the trill there), where a long closing
    note cuts it off, and how many other notes came between the strokes. A stroke follows
    the one before within twice the shortest distance so far (one stroke may be missing,
    another note may come between); a note of the trill that stands alone and lasts LONG
    strokes or more is not a stroke but what the trill ends on. It also ends at the next
    trill sign, and where the same side returns with another note in between (that is
    another figure: this side taking turns with something else)."""
    pool = set(main) | set(other)
    found = [(i, tuple(p for p in events[i].pitches if p in pool))]
    gaps: list[float] = []
    last = events[i].at
    closed = None
    foreign = between = 0
    for j in range(i + 1, len(events)):
        e = events[j]
        d = e.at - last
        if d > (2 * min(gaps) if gaps else FIRST_GAP) + EPS or e.marked:
            break
        own = tuple(p for p in e.pitches if p in pool)
        if not own:
            between += bool(e.pitches)
            continue
        if len(own) == len(e.pitches) and e.dur >= LONG * (min(gaps) if gaps else d) - EPS:
            closed = e.at
            break
        if between and bool(set(own) & set(main)) == bool(set(found[-1][1]) & set(main)):
            break
        foreign += between
        between = 0
        found.append((j, own))
        gaps.append(d)
        last = e.at
    return found, closed, foreign


def _run(events: list[Event], found: list[tuple[int, tuple[int, ...]]], closed: float | None, main, other, marked: bool, limit: float | None) -> Run:
    times = [events[j].at for j, _ in found]
    gaps = [b - a for a, b in zip(times, times[1:])]
    gap = statistics.median(gaps) if gaps else FIRST_GAP
    end = closed if closed is not None else times[-1] + (gaps[-1] if gaps else gap)
    if limit is not None:
        end = min(end, limit)
    start = times[0]
    lead_in = tuple(p for e in events if start - 0.5 - EPS <= e.at < start - EPS for p in e.grace)
    ending = tuple(p for e in events if end - 3 * gap - EPS <= e.at < end + EPS and e.at > start + EPS for p in e.grace)
    return Run(round(start, 4), round(end, 4), tuple(main), tuple(other), [(round(events[j].at, 4), own) for j, own in found],
               round(gap, 4), marked, lead_in, ending)


def find_runs(events: list[Event], limit: float | None = None) -> list[Run]:
    """The trills and tremolos among one hand's events (in time order). `limit`: where the
    bars looked at end.

    With a trill sign: the main side is what stands under the sign, the other side the notes
    of the next moment (within FIRST_GAP) that are not under it. Without a sign: two moments
    with no note in common, a thirty-second note apart or closer, neither long, that then take turns
    for at least MIN_STROKES strokes and MIN_QUARTERS. Either way the run ends where no
    stroke follows within twice the shortest distance, at a long closing note, at the next
    trill sign, or where one side starts taking turns with another note; grace notes are
    never strokes."""
    events = sorted(events, key=lambda e: e.at)
    runs: list[Run] = []
    taken: set[int] = set()

    def keep(run: Run, found) -> None:
        runs.append(run)
        taken.update(range(found[0][0], found[-1][0] + 1))

    for i, e in enumerate(events):
        if not e.marked or i in taken:
            continue
        following = next((x for x in events[i + 1:] if x.pitches), None)
        if following is None or following.at - e.at > FIRST_GAP + EPS:
            continue
        other = tuple(p for p in following.pitches if p not in e.marked)
        if not other:
            continue
        found, closed, _ = _grow(events, i, e.marked, other)
        if len(found) >= 2:
            keep(_run(events, found, closed, e.marked, other, True, limit), found)
    i = 0
    while i + 1 < len(events):
        a, b = events[i], events[i + 1]
        g = b.at - a.at
        if (i in taken or i + 1 in taken or not a.pitches or not b.pitches or set(a.pitches) & set(b.pitches) or g > FAST_GAP + EPS
                or a.dur >= LONG * g - EPS or b.dur >= LONG * g - EPS):
            i += 1
            continue
        found, closed, foreign = _grow(events, i, a.pitches, b.pitches)
        if any(j in taken for j, _ in found):
            i += 1
            continue
        pool = set(a.pitches) | set(b.pitches)
        gap = statistics.median([events[y].at - events[x].at for (x, _), (y, _) in zip(found, found[1:])]) if len(found) > 1 else g
        k = i - 1               # the first strokes may stand in a chord with other notes: look back
        while k >= 0 and k not in taken:
            e = events[k]
            if events[found[0][0]].at - e.at > 2 * gap + EPS:
                break
            own = tuple(p for p in e.pitches if p in pool)
            if own:         # a whole side of it, and not a long note of its own
                if set(own) not in (set(a.pitches), set(b.pitches)) or (len(own) == len(e.pitches) and e.dur >= LONG * gap - EPS):
                    break
                found.insert(0, (k, own))
            k -= 1
        sides = [bool(set(own) & set(a.pitches)) for _, own in found]
        changes = sum(x != y for x, y in zip(sides, sides[1:]))
        main, other = (a.pitches, b.pitches) if sides[0] else (b.pitches, a.pitches)
        run = _run(events, found, closed, main, other, False, limit)
        if (len(found) >= MIN_STROKES and run.quarters >= MIN_QUARTERS - EPS and run.gap <= FAST_GAP + EPS
                and changes >= ALTERNATING * (len(found) - 1) and foreign <= len(found) / 3):
            keep(run, found)
            i = found[-1][0] + 1
        else:
            i += 1
    return sorted(runs, key=lambda r: r.start)


def kind_of(main: tuple[int, ...], other: tuple[int, ...], whole_tone: int) -> str:
    """"trill" for two single notes up to a whole tone apart, "tremolo" for anything wider or for chords."""
    if len(main) == 1 and len(other) == 1 and abs(main[0] - other[0]) <= whole_tone + 1:
        return "trill"
    return "tremolo"


def beats_words(beats: float) -> str:
    """`1.5` -> "a beat and a half"."""
    whole, half = int(beats), abs(beats - int(beats) - 0.5) < 0.01
    names = {1: "a beat", 2: "two beats", 3: "three beats", 4: "four beats", 5: "five beats", 6: "six beats", 8: "eight beats"}
    if abs(beats - whole) < 0.01 and whole in names:
        return names[whole]
    if half and whole == 0:
        return "half a beat"
    if half and whole in names:
        return f"{names[whole]} and a half"
    return f"{beats:g} beats"


# --- what a demonstration plays ---

def demo_rate(stroke_beats: float | None, tempo_bpm: float, rate: float | None = None) -> float:
    """Strokes per second: `rate` if asked for; else the written rate of the step at this tempo
    (thirty-second notes where none is written), so a low tempo shows the trill slowly; never
    faster than the sound tells apart."""
    if rate:
        return max(1.0, min(float(rate), 16.0))
    return max(1.0, min((tempo_bpm / 60.0) / (stroke_beats or DEMO_STROKE), DEMO_MAX_RATE))


def schedule(seconds: float, rate: float) -> list[tuple[float, int]]:
    """An even alternation filling `seconds`: (time from its start, side 0 = main or 1 = other),
    beginning on the main note; at least four strokes."""
    count = max(4, int(seconds * rate + 0.5))
    return [(k / rate, k % 2) for k in range(count)]


# --- judging what was played ---

@dataclass
class Take:
    """What the player struck while a trill step was asked for."""
    strokes: list[tuple[float, int, int]] = field(default_factory=list)     # time, pitch, velocity: notes of the trill
    wrong: int = 0                      # other keys pressed
    with_notes: set = field(default_factory=set)        # notes to strike with its start that were struck
    last: float | None = None           # the last press of any kind

    def idle_s(self) -> float:
        """How long nothing new must come before the player is taken to have stopped."""
        times = [t for t, _, _ in self.strokes]
        gaps = [b - a for a, b in zip(times, times[1:])]
        return max(END_S[0], min(END_S[1], 3 * statistics.median(gaps))) if gaps else END_S[0]


def judge(take: Take, main: tuple[int, ...], other: tuple[int, ...], *, start_on_main: bool = True, seconds: float | None = None,
          with_notes: tuple[int, ...] = (), allowed_wrong: int = 0, final: bool = True) -> dict:
    """A trill by its effect: did the two sides take turns, were both there, did it start on
    the right one, how fast, how even, how long. Never a count of strokes against the score.
    `final` False: asked while it is still going on (only what can be said by then).
    Returns facts; `ok` and, if not, `why`; pitches are turned into names by the caller."""
    a, b = set(main), set(other)
    # a side of several notes is struck as a chord: its notes within a short time are one stroke
    groups: list[tuple[float, int, list[int]]] = []        # time, side, velocities
    for t, pitch, velocity in take.strokes:
        side = 0 if pitch in a else 1
        if groups and groups[-1][1] == side and len((main, other)[side]) > 1 and t - groups[-1][0] <= 0.06:
            groups[-1][2].append(velocity)
        else:
            groups.append((t, side, [velocity]))
    times = [t for t, _, _ in groups]
    sides = [s for _, s, _ in groups]
    changes = sum(x != y for x, y in zip(sides, sides[1:]))
    struck = {p for _, p, _ in take.strokes}
    facts: dict = {"strokes": len(groups), "changes": changes, "missing": sorted((a | b) - struck),
                   "missing_with": sorted(set(with_notes) - take.with_notes), "wrong": take.wrong,
                   "started_on": None if not sides else "main" if sides[0] == 0 else "other"}
    gaps = [y - x for x, y in zip(times, times[1:])]
    if gaps:
        mean = statistics.fmean(gaps)
        facts["lasted_s"] = round(times[-1] - times[0] + mean, 2)
        facts["per_second"] = round(1.0 / mean, 1) if mean > 0 else 0.0
        facts["speed"] = "slow" if facts["per_second"] < SLOW else "fast" if facts["per_second"] >= FAST else "at a moderate speed"
    if len(gaps) >= 3:
        mean = statistics.fmean(gaps)
        spread = statistics.pstdev(gaps) / mean if mean > 0 else 0.0
        facts["spread_ms"] = round(statistics.pstdev(gaps) * 1000)
        facts["evenness"] = "even" if spread <= EVEN[0] else "fairly even" if spread <= EVEN[1] else "uneven" if spread <= EVEN[2] else "lumpy"
        # limping: the way from one side to the other takes longer than the way back
        to_other = [g for g, s in zip(gaps, sides) if s == 0]
        to_main = [g for g, s in zip(gaps, sides) if s == 1]
        if to_other and to_main:
            x, y = statistics.fmean(to_other), statistics.fmean(to_main)
            if max(x, y) >= LIMP * min(x, y):
                facts["limps"] = "main" if x > y else "other"       # the side it lingers on
        # getting faster or slower: the same measure rhythm.py uses for drift, on the distances
        drift = R.drift_ms(times[1:], gaps)
        if abs(drift) / 1000.0 > 0.3 * mean:
            facts["trend"] = "dragging" if drift > 0 else "rushing"
    loud = [[v for _, s, vs in groups if s == side for v in vs if v] for side in (0, 1)]
    if all(len(x) >= 2 for x in loud):
        x, y = statistics.fmean(loud[0]), statistics.fmean(loud[1])
        if min(x, y) < WEAKER * max(x, y):
            facts["weaker"] = "main" if x < y else "other"
    if seconds and "lasted_s" in facts:
        share = facts["lasted_s"] / seconds
        facts["written_s"] = round(seconds, 2)
        facts["length"] = ("much shorter than written" if share < SHORT else "shorter than written" if share < 0.75
                           else "about as long as written" if share <= 1.5 else "longer than written")
    why = None
    if take.wrong > allowed_wrong:
        why = "other keys were pressed"
    elif not groups:
        why = "none of the two was played"
    elif changes == 0:
        why = "one side only: no alternation"
    elif facts["missing"]:
        why = "a note of it was never struck"
    elif start_on_main and facts["started_on"] != "main":
        why = "it started on the other note"
    elif changes < MIN_CHANGES:
        why = f"too few changes: {changes}, a trill needs at least {MIN_CHANGES}"
    elif facts["missing_with"]:
        why = "a note that is struck with its start is missing"
    elif final and facts.get("evenness") == "lumpy":
        why = "too lumpy to be a trill yet: slower, and evenly"
    elif final and facts.get("length") == "much shorter than written":
        why = "much shorter than written"
    facts["ok"] = why is None
    if why:
        facts["why"] = why
    return facts


def words(facts: dict, main: str, other: str) -> str:
    """The judgement in plain words, with the names of the two sides."""
    name = {"main": main, "other": other}
    if not facts.get("strokes"):
        return "nothing of the trill was played" + ("; other keys were pressed" if facts.get("wrong") else "")
    parts = []
    if not facts["ok"]:
        parts.append("not yet a trill: " + facts["why"])
    if "per_second" in facts:
        parts.append(f"{facts['speed']} (about {facts['per_second']:g} strokes a second for {facts['lasted_s']:g} s)")
    if facts.get("length"):
        parts.append(f"{facts['length']} (about {facts['written_s']:g} s at this tempo)")
    if facts.get("evenness"):
        parts.append(facts["evenness"])
    if facts.get("limps"):
        parts.append(f"it limps: it lingers on {name[facts['limps']]}")
    if facts.get("trend"):
        parts.append("rushing (getting faster)" if facts["trend"] == "rushing" else "dragging (getting slower)")
    if facts.get("weaker"):
        parts.append(f"{name[facts['weaker']]} is the weaker note")
    if facts["started_on"] == "other":
        parts.append(f"started on {other}")
    return "; ".join(parts) if parts else f"{facts['changes']} changes"
