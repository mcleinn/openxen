"""Which hand plays which note: music given as one stream of notes, arranged for two hands.

    hands = assign_hands([(onset, end, pitch), ...], per_octave=24, middle=96)     # 0 = right hand, 1 = left hand

The input is any polyphonic music as notes with onset, end and pitch: no staves, no voices,
no instruments. Pitch is a number in any equal division (`per_octave` of them make an octave:
1200 for cents, 12 for semitones, 24 for quarter-tones), so the tuning does not matter. Times
are meant in seconds; quarter notes work too and then mean a tempo of 60 to the minute.

Method. No free library does this (looked for on 2026-11-27): `partitura` has the voice
separation of Chew & Wu (voices, not hands; whole-number MIDI pitches), `music21` has no
separation at all, `pianoplayer` fingers hands that are already separate, and the hand
separation of Nakamura, Ono & Sagayama is C++ outside pip. So this is the simplest published
approach, written out as costs:

  * E. Nakamura, N. Ono, S. Sagayama, "Merged-output HMM for piano fingering of both hands"
    (ISMIR 2014): each hand is a chain of its own notes, the two chains are merged into the one
    stream that is heard, and the most likely division is found with the Viterbi algorithm. A
    hand prefers small distances from where it is, and the right hand lies above the left.
    Here the probabilities are costs, the search is the same (a trellis over the moments at
    which notes begin, each moment's notes cut at one pitch into a left and a right part).
  * E. Chew, X. Wu, "Separating voices in contrapuntal music" (CMMR 2004): a line goes on by
    pitch proximity and lines do not cross. Both are terms of the cost below.
  * The sizes: how far a hand reaches is taken from this project's fingering model
    (`tutor.fingering`, thumb to little finger in Balliauw et al. 2017: relaxed, comfortable,
    practical; the same three weights). Their unit is 1/14 octave on a piano. A piano's reach in
    pitch is only a stand-in here: on the hexagonal keyboard the reach depends on the layout
    (an octave may be nearer than a fifth), which this tuning-independent model cannot know.

What is weighed, per moment and hand (`HandModel` holds the numbers):

  1. the notes struck together lie within the hand's reach, at most five of them;
  2. notes still held in the hand count too, but less (`held`): a pedal may hold them;
  3. the hand stays where it has just played (`memory`): leaving that place costs, at most
     `move_cap`, and a note is nearer to the hand whose recent notes surround it (`w_near`), which
     is what keeps a line in its hand when it dips below the accompaniment or climbs above;
  4. the right hand above the left: no sounding note of the left above one of the right
     (`w_cross`), the hands' places in this order (`w_order`); crossing happens when all else
     is worse;
  5. a hand that rests joins only when it saves more than `w_enter` (it helps with a chord
     that is too wide, it does not take single notes out of the other hand's line);
     a note that begins where a note of one hand ends, a step away from it, goes on with that
     hand (`w_line`): this is what lets a melody pass through the accompaniment's register;
  6. as a tie-break only, the right hand above middle C and the left below (`w_register`).

A note keeps the hand it was struck with until it ends. The same input gives the same output.
Limits: the notes struck at one moment are cut at one pitch, so two lines that cross at the
very moment both strike come out uncrossed; and the model knows pitch and time only, no slurs,
beams or dynamics, which is why a printed staff, where there is one, goes first (`fixed`).

`playability` then says what two hands cannot do however the notes are divided: moments at
which more is struck at once than two hands reach.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..fingering import _SPANS_UNITS, W_COMF, W_PRAC, W_REL

UNITS_PER_OCTAVE = 14.0          # the unit of the span tables: 1/14 octave (a piano key's width)
RIGHT, LEFT = 0, 1
FINGERS = 5


@dataclass(frozen=True)
class HandModel:
    """The numbers of the cost. Distances in units of 1/14 octave, times in seconds. The weights were
    set on Wyschnegradsky's Preludes 1-10 (bars hidden a quarter at a time, the rest left on their
    printed staves: 90 % of the hidden notes come back on their staff) and checked on Nos. 13-24 (87 %)."""
    size: str = "medium"         # which column of the span tables (thumb to little finger): practical reach 16 units, a ninth
    held: float = 0.5            # share of the reach cost for notes held from before (a pedal may hold them)
    memory: float = 2.0          # for so long the hand lies where it played
    half_life: float = 0.5       # the hand's place: its notes weighed by age
    w_move: float = 0.25         # leaving the place, as a share of the reach cost ...
    move_cap: float = 6.0        # ... and at most this (fingering.MOVE_CAP for legato)
    w_near: float = 1.0          # per unit between a note and the hand's place
    w_cross: float = 4.0         # per unit a sounding left-hand note lies above a right-hand one
    w_order: float = 1.0         # per unit the right hand's notes lie below the left hand's place
    w_enter: float = 6.0         # a hand that rested for `rest` seconds starts to play
    rest: float = 1.0
    w_line: float = 16.0         # a note a step away from one that just ended in the other hand (it goes on with that line)
    line_step: float = 2.4       # what counts as a step for that: up to a whole tone
    w_fingers: float = 20.0      # per note beyond five at once
    w_register: float = 0.02     # per unit on the other side of middle C (tie-break)
    beam: int = 48               # states kept per moment

    def spans(self) -> tuple[float, float, float]:
        """Thumb to little finger: relaxed, comfortable, practical (units)."""
        _, _, _, relaxed, comfortable, practical = _SPANS_UNITS[self.size][(1, 5)]
        return float(relaxed), float(comfortable), float(practical)

    def reach(self, span: float) -> float:
        """What a stretch of `span` units costs: the three ranges and weights of the fingering model."""
        relaxed, comfortable, practical = self.spans()
        return W_REL * max(0.0, span - relaxed) + W_COMF * max(0.0, span - comfortable) + W_PRAC * max(0.0, span - practical)


DEFAULT = HandModel()


def _moments(notes, per_octave: float) -> list[tuple[float, list[tuple[int, float, float]]]]:
    """The notes by onset: [(time, [(index, end, pitch in units), ... from the lowest up])]."""
    scale = UNITS_PER_OCTAVE / float(per_octave)
    by_onset: dict[float, list[tuple[int, float, float]]] = {}
    for i, (onset, end, pitch) in enumerate(notes):
        by_onset.setdefault(float(onset), []).append((i, float(end), float(pitch) * scale))
    return [(t, sorted(group, key=lambda n: (n[2], n[1], n[0]))) for t, group in sorted(by_onset.items())]


def _span(pitches) -> float:
    return max(pitches) - min(pitches) if pitches else 0.0


class _Cost:
    def __init__(self, model: HandModel, middle: float) -> None:
        self.m = model
        self.middle = middle

    def prune(self, hand: tuple, t: float) -> tuple:
        """What is remembered of a hand at time t: notes (onset, end, pitch) that sound or were struck
        within `memory`; else the last ones it struck (where it was)."""
        kept = tuple(n for n in hand if n[1] > t - 1e-6 or n[0] > t - self.m.memory)
        if not kept and hand:
            kept = tuple(n for n in hand if n[0] == hand[-1][0])
        return kept[-8:]

    def place(self, hand: tuple, t: float) -> float | None:
        if not hand:
            return None
        total = weight = 0.0
        for onset, _, pitch in hand:
            w = 0.5 ** ((t - onset) / self.m.half_life)
            total, weight = total + w * pitch, weight + w
        return total / weight if weight > 1e-12 else hand[-1][2]

    def take(self, side: int, hand: tuple, group: list[float], t: float, other: tuple) -> float:
        """Cost of `side` striking `group` (pitches) at t, `hand` and `other` being what the two hands did before."""
        m = self.m
        struck = m.reach(_span(group))
        cost = struck + m.w_fingers * max(0, len(group) - FINGERS)
        sounding = [p for _, end, p in hand if end > t]
        if sounding:
            cost += m.held * max(0.0, m.reach(_span(sounding + group)) - struck)
        window = [p for onset, _, p in hand if onset > t - m.memory]
        if window:
            cost += min(m.move_cap, m.w_move * max(0.0, m.reach(_span(window + group)) - max(m.reach(_span(window)), struck)))
        place = self.place(hand, t)
        if place is not None:
            cost += m.w_near * sum(abs(p - place) for p in group)
        if not sounding and not any(onset > t - m.rest for onset, _, _ in hand):
            cost += m.w_enter
        theirs = [p for _, end, p in other if abs(end - t) < 1e-6]                   # notes of the other hand that end just now
        if theirs and m.w_line:
            mine = [p for _, end, p in hand if abs(end - t) < 1e-6]
            for p in group:
                step = min(abs(p - q) for q in theirs)
                if step <= m.line_step and all(abs(p - q) > step for q in mine):
                    cost += m.w_line
        if any(end > t or onset > t - m.memory for onset, end, _ in other):          # the other hand is there
            there = self.place(other, t)
            mean = sum(group) / len(group)
            cost += m.w_order * max(0.0, there - mean if side == RIGHT else mean - there)
        if side == RIGHT:
            cost += m.w_register * sum(max(0.0, self.middle - p) for p in group)
        else:
            cost += m.w_register * sum(max(0.0, p - self.middle) for p in group)
        return cost

    def crossing(self, left: tuple, right: tuple, t: float) -> float:
        low = [p for _, end, p in left if end > t]
        high = [p for _, end, p in right if end > t]
        return self.m.w_cross * max(0.0, max(low) - min(high)) if low and high else 0.0


def assign_hands(notes, per_octave: float = 1200.0, middle: float | None = None, model: HandModel = DEFAULT, fixed=None) -> list[int]:
    """0 (right hand, upper staff) or 1 (left hand, lower staff) for every note of `notes`, a sequence
    of (onset, end, pitch) in any order. `per_octave`: how many pitch units make an octave; `middle`:
    the pitch of middle C (default: four octaves above pitch 0, as in steps counted from C0).
    `fixed`: per note 0, 1 or None; a note whose hand is known (it is printed on that staff) keeps
    it, and only the others are chosen, so that they go on with the lines around them."""
    notes = list(notes)
    if not notes:
        return []
    known = list(fixed) if fixed is not None else [None] * len(notes)
    if len(known) != len(notes):
        raise ValueError("fixed must name a hand or None for every note")
    scale = UNITS_PER_OCTAVE / float(per_octave)
    cost = _Cost(model, (4.0 * per_octave if middle is None else float(middle)) * scale)
    moments = _moments(notes, per_octave)
    # state: (left hand's notes, right hand's notes) -> (cost so far, link to the choices made)
    states: dict[tuple, tuple[float, tuple | None]] = {((), ()): (0.0, None)}
    for t, group in moments:
        free = [n for n in group if known[n[0]] is None]
        given = {side: [n for n in group if known[n[0]] == side] for side in (LEFT, RIGHT)}
        found: dict[tuple, tuple[float, tuple | None]] = {}
        for (left, right), (so_far, link) in states.items():
            left, right = cost.prune(left, t), cost.prune(right, t)
            for cut in range(len(free) + 1):                     # the lowest `cut` free notes to the left hand
                low = sorted(given[LEFT] + free[:cut], key=lambda n: n[2])
                high = sorted(given[RIGHT] + free[cut:], key=lambda n: n[2])
                c = so_far
                new_left, new_right = left, right
                if low:
                    c += cost.take(LEFT, left, [p for _, _, p in low], t, right)
                    new_left = left + tuple((t, end, p) for _, end, p in low)
                if high:
                    c += cost.take(RIGHT, right, [p for _, _, p in high], t, left)
                    new_right = right + tuple((t, end, p) for _, end, p in high)
                c += cost.crossing(new_left, new_right, t)
                key = (new_left, new_right)
                if key not in found or c < found[key][0]:
                    found[key] = (c, (cut, link))
        states = dict(sorted(found.items(), key=lambda item: (item[1][0], item[0]))[:model.beam])
    link = min(states.items(), key=lambda item: (item[1][0], item[0]))[1][1]
    cuts: list[int] = []
    while link is not None:
        cuts.append(link[0])
        link = link[1]
    cuts.reverse()
    out = [RIGHT if side is None else int(side) for side in known]
    for (t, group), cut in zip(moments, cuts):
        for i, _, _ in [n for n in group if known[n[0]] is None][:cut]:
            out[i] = LEFT
    return out


def playability(notes, hands, per_octave: float = 1200.0, model: HandModel = DEFAULT) -> dict:
    """What a division asks of the player, counted over the moments at which notes begin:

    `moments`       how many there are;
    `max_sounding`  most notes sounding at once (held ones included);
    `max_struck`    most notes struck at once;
    `over_span`     times of the moments at which the notes one hand strikes together exceed its
                    practical reach or five fingers (the chord has to be broken or thinned);
    `held_over`     times at which a hand's struck notes fit, but not together with the notes it still
                    holds (pedal, or let go);
    `crossed`       how often a sounding left-hand note lies above a right-hand one;
    `unplayable`    times at which the notes struck at once fit no two hands, however they are divided.

    The reach is the practical thumb-to-little-finger span of `model` on a piano (see the module text:
    a stand-in for the real keyboard)."""
    notes, hands = list(notes), list(hands)
    _, _, practical = model.spans()
    practical += 1e-9
    sounding: list[tuple[float, float, int]] = []                 # (end, pitch, hand)
    out = {"moments": 0, "max_sounding": 0, "max_struck": 0, "over_span": [], "held_over": [], "crossed": 0, "unplayable": []}
    for t, group in _moments(notes, per_octave):
        sounding = [s for s in sounding if s[0] > t]
        out["moments"] += 1
        out["max_struck"] = max(out["max_struck"], len(group))
        pitches = [p for _, _, p in group]
        if not any(_span(pitches[:cut]) <= practical and _span(pitches[cut:]) <= practical and cut <= FINGERS and len(group) - cut <= FINGERS
                   for cut in range(len(group) + 1)):
            out["unplayable"].append(t)
        over = held_over = False
        for side in (RIGHT, LEFT):
            struck = [p for i, _, p in group if hands[i] == side]
            held = [p for _, p, h in sounding if h == side]
            if struck and (_span(struck) > practical or len(struck) > FINGERS):
                over = True
            elif struck and held and (_span(struck + held) > practical or len(struck) + len(held) > FINGERS):
                held_over = True
        if over:
            out["over_span"].append(t)
        elif held_over:
            out["held_over"].append(t)
        sounding += [(end, p, hands[i]) for i, end, p in group]
        out["max_sounding"] = max(out["max_sounding"], len(sounding))
        low = [p for _, p, h in sounding if h == LEFT]
        high = [p for _, p, h in sounding if h == RIGHT]
        out["crossed"] += bool(low and high and max(low) > min(high))
    return out
