"""Which finger on which key: an ergonomic cost model on the real key positions.

No fingering method has been published for hexagonal keyboards in Bosanquet layouts
(search of 2026-11-26: Lumatone's material, Bosanquet 1876, the Fokker organ literature).
This model is therefore assembled from what does exist and carries over:

  * Finger-pair distances and rule weights from piano fingering research: Parncutt, Sloboda,
    Clarke, Raekallio, Desain (1997), in the hand-size tables of Balliauw, Herremans,
    Palhazi Cuervo, Sörensen (2017), converted from keys to millimetres (their unit is
    1/14 octave = 11.8 mm). "Relaxed", "comfortable" and "practical" ranges per finger pair;
    1 point per unit outside relaxed, 2 more outside comfortable, 10 more outside practical;
    doubled inside a chord.
  * From the Jankó keyboard and the chromatic button accordion, which have fingering schools:
    the thumb plays nearer to the player than the fingers; among several keys for a note take
    the one that keeps the wrist straight and the hand still; move the hand rather than cross.
    Here this follows from a resting posture of the hand (where each fingertip lies when the
    hand is relaxed) instead of the piano's black-key rules.
  * A phrase is fingered as a whole (trellis search, Al Kasimi, Nichols, Raphael 2007): the
    fingering of a chord depends on what comes before and after; a note held over stays on
    its finger (Nakamura, Saito, Yoshii 2020).

Fingering is not set in stone: two pianists agree on 60-80 % of the notes of a piece
(Nakamura et al.). So this module returns several ranked fingerings with the reasons for
their cost, and a legato / detached switch, never one "correct" answer.

Assumed, not measured (no published data): the resting posture `REST_MM` and the free range
of each finger towards and away from the palm. They are meant to be replaced by a
calibration of the player's own hand.

Everything is in millimetres in the player's frame: x to the player's right, y away from
the player. Fingers are numbered 1 (thumb) to 5 (little finger). The left hand is the right
hand mirrored.
"""

from __future__ import annotations

import functools
import itertools
import math
from dataclasses import dataclass

UNIT_MM = 165.0 / 14.0      # the distance unit of the piano tables: 1/14 octave
FINGER_NAMES = {1: "thumb", 2: "index finger", 3: "middle finger", 4: "ring finger", 5: "little finger"}

# Balliauw et al. 2017, right hand, in units; per finger pair (lower, higher finger number):
# MinPrac, MinComf, MinRel, MaxRel, MaxComf, MaxPrac. Distance = position of the higher
# finger minus position of the lower one, along the line of the fingers (negative: crossed).
_SPANS_UNITS = {
    "small": {
        (1, 2): (-7, -5, 1, 3, 8, 10), (1, 3): (-6, -4, 3, 6, 10, 12), (1, 4): (-4, -2, 5, 8, 11, 13),
        (1, 5): (-2, 0, 7, 10, 12, 14), (2, 3): (1, 1, 1, 2, 4, 6), (2, 4): (1, 1, 3, 4, 6, 8),
        (2, 5): (2, 2, 5, 6, 8, 10), (3, 4): (1, 1, 1, 2, 2, 4), (3, 5): (1, 1, 3, 4, 6, 8), (4, 5): (1, 1, 1, 2, 4, 6),
    },
    "medium": {
        (1, 2): (-8, -6, 1, 5, 8, 10), (1, 3): (-7, -5, 3, 9, 12, 14), (1, 4): (-5, -3, 5, 11, 13, 15),
        (1, 5): (-2, 0, 7, 12, 14, 16), (2, 3): (1, 1, 1, 2, 5, 7), (2, 4): (1, 1, 3, 4, 6, 8),
        (2, 5): (2, 2, 5, 6, 10, 12), (3, 4): (1, 1, 1, 2, 2, 4), (3, 5): (1, 1, 3, 4, 6, 8), (4, 5): (1, 1, 1, 2, 4, 6),
    },
    "large": {
        (1, 2): (-10, -8, 1, 6, 9, 11), (1, 3): (-8, -6, 3, 9, 13, 15), (1, 4): (-6, -4, 5, 11, 14, 16),
        (1, 5): (-2, 0, 7, 12, 16, 18), (2, 3): (1, 1, 1, 2, 5, 7), (2, 4): (1, 1, 3, 4, 6, 8),
        (2, 5): (2, 2, 5, 6, 10, 12), (3, 4): (1, 1, 1, 2, 2, 4), (3, 5): (1, 1, 3, 4, 6, 8), (4, 5): (1, 1, 1, 2, 4, 6),
    },
}
# Where the fingertips of a relaxed, slightly curved right hand lie, relative to the middle
# fingertip (assumption; x after pianoplayer's hand model at its medium size).
REST_MM = {1: (-57.0, -50.0), 2: (-23.0, -5.0), 3: (0.0, 0.0), 4: (23.0, -5.0), 5: (46.0, -22.0)}
_REST_SCALE = {"small": 0.9, "medium": 1.0, "large": 1.1}

W_REL, W_COMF, W_PRAC = 1.0, 2.0, 10.0      # per unit outside each range (Balliauw rules 1, 2, 13)
W_CHORD = 2.0                               # pair rules count double inside a chord (rule 14)
W_REACH = 1.5                               # per unit a finger reaches or curls beyond its free range
W_WEAK = {4: 0.5, 5: 0.25}                  # ring and little finger (Parncutt rule 6, reduced)
W_TURN = 0.4                                # per 10 degrees the hand is turned beyond TURN_FREE
TURN_FREE = 10.0
TURNS = (0.0, -10.0, 10.0, -20.0, 20.0, -30.0, 30.0)    # the straight hand first: it wins ties
W_SUBSTITUTE = {True: 2.0, False: 0.5}      # a note both steps share changes finger
SAME_FINGER = {True: 3.0, False: 1.5}       # one finger plays two different keys in a row (legato / detached)
MOVE_CAP = {True: 6.0, False: 2.0}          # a change of hand position costs at most this per key
W_TURN_CHANGE = 0.3                         # per 10 degrees the hand turns between two steps
W_SHIFT = {True: 0.5, False: 0.3}           # per unit the whole hand moves between two steps
BOOK_BONUS = 25.0                           # the player's own fingering of a shape is preferred by this much in a phrase
SPAN_TO_PRACTICAL = 0.9                     # practical limit of a finger pair = this share of the widest stretch measured
REST_WIDTH_MM = (60.0, 240.0)               # a plausible resting hand, thumb to little finger
PRACTICAL = 10.0                            # from this effort on, something is outside the practical range


class FingeringError(ValueError):
    pass


@dataclass(frozen=True)
class Hand:
    """One player's hand (as a right hand)."""
    size: str
    spans: tuple[tuple[tuple[int, int], tuple[float, ...]], ...]    # finger pair -> six distances, mm
    rest: tuple[tuple[int, tuple[float, float]], ...]               # finger -> resting fingertip, mm
    extend_free: float = 8.0     # a finger reaches this much further from the palm at no cost
    curl_free: float = 25.0      # and curls in this much
    extend_max: float = 22.0
    curl_max: float = 50.0

    def span(self, i: int, j: int) -> tuple[float, ...]:
        return dict(self.spans)[(i, j)]

    def rest_of(self, f: int) -> tuple[float, float]:
        return dict(self.rest)[f]


def default_hand(size: str = "medium") -> Hand:
    size = size.strip().lower()
    if size not in _SPANS_UNITS:
        raise FingeringError(f"hand size must be one of: {', '.join(_SPANS_UNITS)}")
    spans = tuple((pair, tuple(v * UNIT_MM for v in values)) for pair, values in _SPANS_UNITS[size].items())
    s = _REST_SCALE[size]
    return Hand(size, spans, tuple((f, (x * s, y * s)) for f, (x, y) in REST_MM.items()))


def customise(hand: Hand, rest: dict[int, tuple[float, float]] | None = None, thumb_factor: float = 1.0, finger_factor: float = 1.0) -> Hand:
    """A measured hand: the resting fingertips replaced, the stretches scaled. `thumb_factor`
    scales the distances of the thumb pairs (also how far the thumb passes under),
    `finger_factor` the widest distances between two fingers."""
    spans = []
    for (i, j), values in hand.spans:
        if i == 1:
            spans.append(((i, j), tuple(v * thumb_factor if (n >= 3 or v < 0) else v for n, v in enumerate(values))))
        else:
            spans.append(((i, j), tuple(v * finger_factor if n >= 3 else v for n, v in enumerate(values))))
    new_rest = hand.rest if rest is None else tuple((f, (float(rest[f][0]), float(rest[f][1]))) for f in (1, 2, 3, 4, 5))
    return Hand("measured" if (rest or thumb_factor != 1.0 or finger_factor != 1.0) else hand.size, tuple(spans), new_rest,
                hand.extend_free, hand.curl_free, hand.extend_max, hand.curl_max)


def rest_from_handprint(points: list[tuple[float, float]], side: str = "right") -> dict[int, tuple[float, float]]:
    """The resting posture from five keys the player's relaxed hand lies on: fingers from
    thumb to little finger in the order the keys lie across the hand; positions relative
    to the middle finger, as a right hand."""
    side = side.strip().lower()
    if side not in ("left", "right"):
        raise FingeringError(f"hand must be 'left' or 'right', not '{side}'")
    if len(points) != 5:
        raise FingeringError(f"a handprint needs five keys, one under each finger; {len(points)} are held")
    sign = -1.0 if side == "left" else 1.0
    ordered = sorted(((sign * x, y) for x, y in points), key=lambda p: (p[0], p[1]))
    width = ordered[4][0] - ordered[0][0]
    if not REST_WIDTH_MM[0] <= width <= REST_WIDTH_MM[1]:
        raise FingeringError(f"these five keys are {width:.0f} mm apart from thumb to little finger, which is not a resting hand; "
                             f"let the hand lie relaxed with one finger on each key")
    mx, my = ordered[2]
    return {f: (round(x - mx, 1), round(y - my, 1)) for f, (x, y) in zip((1, 2, 3, 4, 5), ordered)}


@dataclass(frozen=True)
class Fingering:
    fingers: tuple[int, ...]            # one per key, in the order the keys were given
    effort: float                       # 0 = lies under the relaxed hand
    reasons: tuple[str, ...]            # what the effort comes from, largest first
    turn: float = 0.0                   # degrees the hand is turned anticlockwise
    own: bool = False                   # the player's own fingering, from their book

    @property
    def feel(self) -> str:
        if self.effort < 1.5:
            return "easy"
        if self.effort < 5:
            return "comfortable"
        if self.effort < PRACTICAL:
            return "a stretch"
        return "hardly playable with one hand"

    @property
    def text(self) -> str:
        return "-".join(str(f) for f in self.fingers)


def _range_cost(value: float, low_rel: float, high_rel: float, low_comf: float, high_comf: float,
                low_prac: float, high_prac: float) -> float:
    """Points for a distance outside the relaxed / comfortable / practical range, per unit."""
    def outside(lo: float, hi: float) -> float:
        return max(0.0, lo - value, value - hi) / UNIT_MM
    return W_REL * outside(low_rel, high_rel) + W_COMF * outside(low_comf, high_comf) + W_PRAC * outside(low_prac, high_prac)


THUMB_BELOW_MM = 20.0        # a thumb this much nearer to the player than a finger may lie under the hand


def _pair(hand_spans: dict, i: int, j: int, dx: float, dy: float = 0.0) -> tuple[float, str]:
    """Cost and description for fingers i < j whose tips are dx apart along the finger line
    (dy: how much further from the player finger j lies than finger i)."""
    mnp, mnc, mnr, mxr, mxc, mxp = hand_spans[(i, j)]
    if i == 1 and dy >= THUMB_BELOW_MM:
        # On a keyfield with rows the thumb plays on the nearer rows, under the hand, as on
        # the Janko keyboard; the piano's "thumb passed under" is the normal position here.
        mnr = mnc
    cost = _range_cost(dx, mnr, mxr, mnc, mxc, mnp, mxp)
    if cost <= 0:
        return 0.0, ""
    a, b = FINGER_NAMES[i], FINGER_NAMES[j]
    if dx > mxr:
        return cost, f"{a} and {b} are stretched apart" + (" beyond their practical limit" if dx > mxp else "")
    if dx < 0 and i != 1:
        return cost, f"{a} and {b} are crossed"
    if dx < 0:
        return cost, f"thumb passes under the {b}"
    return cost, f"{a} and {b} are cramped together"


def _reach(hand: Hand, dev: float) -> float:
    """Cost of a fingertip `dev` mm further from the palm (negative: nearer) than at rest."""
    return W_REACH * max(0.0, dev - hand.extend_free, -dev - hand.curl_free) / UNIT_MM \
        + W_PRAC * max(0.0, dev - hand.extend_max, -dev - hand.curl_max) / UNIT_MM


def _evaluate(hand: Hand, pts: tuple[tuple[float, float], ...], fingers: tuple[int, ...], chord: bool = True) -> Fingering:
    spans, rest = dict(hand.spans), dict(hand.rest)
    best: tuple[float, list[tuple[float, str]], float] | None = None
    for turn in TURNS:
        c, s = math.cos(math.radians(turn)), math.sin(math.radians(turn))
        local = [(x * c + y * s, -x * s + y * c) for x, y in pts]      # in the hand's own frame
        parts: list[tuple[float, str]] = []
        for (a, fa), (b, fb) in itertools.combinations(sorted(zip(range(len(fingers)), fingers), key=lambda t: t[1]), 2):
            cost, why = _pair(spans, fa, fb, local[b][0] - local[a][0], local[b][1] - local[a][1])
            if cost:
                parts.append((cost * (W_CHORD if chord else 1.0), why))
        # the palm sits where the fingers have least to reach or curl
        offsets = [local[n][1] - rest[f][1] for n, f in enumerate(fingers)]
        candidates = {o + d for o in offsets for d in (-hand.extend_free, 0.0, hand.curl_free)}
        palm = min(candidates, key=lambda y0: sum(_reach(hand, o - y0) for o in offsets))
        for n, f in enumerate(fingers):
            dev = offsets[n] - palm
            cost = _reach(hand, dev)
            if cost:
                parts.append((cost, f"{FINGER_NAMES[f]} {'reaches far up' if dev > 0 else 'has to curl in far'}"))
        for f in fingers:
            if f in W_WEAK and len(fingers) > 1:
                parts.append((W_WEAK[f], ""))
        over = abs(turn) - TURN_FREE
        if over > 0:
            parts.append((W_TURN * over / 10.0, f"hand turned {abs(turn):.0f} degrees {'anticlockwise' if turn > 0 else 'clockwise'}"))
        total = sum(p[0] for p in parts)
        if best is None or total < best[0] - 1e-9:
            best = (total, parts, turn)
    total, parts, turn = best
    reasons = tuple(why for cost, why in sorted(parts, key=lambda p: -p[0]) if why and cost >= 0.4)
    return Fingering(fingers, round(total, 2), reasons[:3], turn)


@functools.lru_cache(maxsize=4096)
def _ranked(hand: Hand, shape: tuple[tuple[float, float], ...]) -> tuple[Fingering, ...]:
    n = len(shape)
    found = [_evaluate(hand, shape, fingers) for fingers in itertools.permutations(range(1, 6), n)]
    found.sort(key=lambda f: (f.effort, f.fingers))
    return tuple(found)


def _as_right(points: list[tuple[float, float]], side: str) -> tuple[tuple[float, float], ...]:
    """Points relative to the first one, mirrored for the left hand, rounded for the cache."""
    side = side.strip().lower()
    if side not in ("left", "right"):
        raise FingeringError(f"hand must be 'left' or 'right', not '{side}'")
    x0, y0 = points[0]
    sign = -1.0 if side == "left" else 1.0
    return tuple((round(sign * (x - x0), 1), round(y - y0, 1)) for x, y in points)


def fingerings(hand: Hand, points: list[tuple[float, float]], side: str = "right", limit: int = 3) -> list[Fingering]:
    """The best ways to put fingers on these keys (played together), easiest first.
    Empty for more than five keys: that takes two hands."""
    if not 1 <= len(points) <= 5:
        return []
    return list(_ranked(hand, _as_right(points, side))[:limit])


def own_fingering(hand: Hand, points: list[tuple[float, float]], fingers: tuple[int, ...], side: str = "right") -> Fingering:
    """A fingering the player chose, judged by the model (to say how it feels) and marked as theirs."""
    fingers = tuple(int(f) for f in fingers)
    if len(fingers) != len(points) or len(set(fingers)) != len(fingers) or not set(fingers) <= {1, 2, 3, 4, 5}:
        raise FingeringError(f"give one finger per key, each 1 (thumb) to 5 (little finger) and none twice: "
                             f"{len(points)} keys, fingers {list(fingers)}")
    f = _evaluate(hand, _as_right(points, side), fingers)
    return Fingering(f.fingers, f.effort, f.reasons, f.turn, own=True)


def with_own(ranked: list[Fingering], own: Fingering | None) -> list[Fingering]:
    """The player's fingering first, the computed ones after it."""
    if own is None:
        return ranked
    return [own] + [f for f in ranked if f.fingers != own.fingers]


# --- a trill: two keys in quick alternation ---
#
# The research file (reference/research/fingering.md) has nothing on trills, so the pairs
# come from keyboard teaching: C. P. E. Bach, Versuch ueber die wahre Art das Clavier zu
# spielen I (1753), chapter 2.3 "On trills", par. 10: "at least two good trills in each
# hand: in the right with the second and third finger, and with the third and fourth
# finger; in the left with the thumb and second finger, and with the second and third
# finger" (versuch.cpebach.org). Tuerk's Klavierschule (1789) likewise starts the trill
# with 2 and 3. Those pairs cost nothing here. The points for the other pairs are this
# project's choice (neighbouring fingers before pairs that skip one, the thumb with the
# middle finger as pianists also use it, pairs with the little finger last); the weak
# ring and little finger are counted by W_WEAK as everywhere. On top comes what the two
# keys ask of the hand: the same distance costs as for any two keys, not doubled (the
# fingers strike in turn, not together).
TRILL_PAIRS = {
    "right": {(2, 3): 0.0, (3, 4): 0.0, (1, 3): 0.5, (1, 2): 0.75, (2, 4): 1.0, (3, 5): 1.5, (4, 5): 2.0, (1, 4): 2.0, (2, 5): 2.5, (1, 5): 3.0},
    "left": {(1, 2): 0.0, (2, 3): 0.0, (1, 3): 0.5, (3, 4): 0.75, (2, 4): 1.0, (3, 5): 1.5, (4, 5): 2.0, (1, 4): 2.0, (2, 5): 2.5, (1, 5): 3.0},
}
TRILL_SOURCE = "C. P. E. Bach, Versuch (1753) I, 2.3, par. 10: right hand 2-3 and 3-4, left hand 1-2 and 2-3"


def trill_fingerings(hand: Hand, points: list[tuple[float, float]], side: str = "right", limit: int = 3) -> list[Fingering]:
    """Finger pairs for a trill between two keys, best first: what the pair is worth for
    trilling (TRILL_PAIRS) plus what the positions of the two keys ask of the hand."""
    side = side.strip().lower()
    if len(points) != 2:
        raise FingeringError("a trill fingering is for two keys")
    shape = _as_right(points, side)
    found = []
    for fingers in itertools.permutations(range(1, 6), 2):
        f = _evaluate(hand, shape, fingers, chord=False)
        pair = TRILL_PAIRS[side][tuple(sorted(fingers))]
        reasons = (("a pair Bach names for trills",) if pair == 0 else ()) + f.reasons
        found.append(Fingering(fingers, round(f.effort + pair, 2), reasons[:3], f.turn))
    found.sort(key=lambda f: (f.effort, f.fingers))
    return found[:limit]


# --- a phrase: steps one after another ---

@dataclass(frozen=True)
class Option:
    """One way to play a step: the keys (id, x, y) it uses."""
    keys: tuple[tuple[str, float, float], ...]


@dataclass(frozen=True)
class Planned:
    option: int                 # index into the step's options
    fingering: Fingering
    alternatives: tuple[Fingering, ...]     # other fingerings of the same keys, by themselves
    notes: tuple[str, ...]      # what the context contributed ("keeps the middle finger on the shared key")


def _palm(hand: Hand, keys, f: Fingering, sign: float) -> tuple[float, float]:
    """Where the hand is for this fingering: the point under the resting middle fingertip."""
    rest = dict(hand.rest)
    c, s = math.cos(math.radians(f.turn)), math.sin(math.radians(f.turn))
    xs = [sign * k[1] - (rest[n][0] * c - rest[n][1] * s) for k, n in zip(keys, f.fingers)]
    ys = [k[2] - (rest[n][0] * s + rest[n][1] * c) for k, n in zip(keys, f.fingers)]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _transition(hand: Hand, legato: bool, a_keys, a: Fingering, b_keys, b: Fingering, sign: float) -> tuple[float, tuple[str, ...]]:
    spans = dict(hand.spans)
    turn = math.radians(b.turn)
    c, s = math.cos(turn), math.sin(turn)
    prev = {k[0]: (f, k) for k, f in zip(a_keys, a.fingers)}
    cost, notes = 0.0, []
    melodic = len(a_keys) == 1 and len(b_keys) == 1
    for key, f in zip(b_keys, b.fingers):
        if key[0] in prev:
            if prev[key[0]][0] == f:
                notes.append(f"keeps the {FINGER_NAMES[f]} on the note both share")
            else:
                cost += W_SUBSTITUTE[legato]
                notes.append(f"changes finger on the held key ({FINGER_NAMES[prev[key[0]][0]]} to {FINGER_NAMES[f]})")
            continue
        moves = []
        # Finger-to-finger distances bind while the hand stays where it is: within a melody,
        # or between a chord and a single note. Between two chords the hand moves as a whole.
        for pf, pk in (prev.values() if min(len(a_keys), len(b_keys)) == 1 else ()):
            if pf == f:
                # a melody cannot be joined with one finger; a chord is lifted as a whole anyway
                moves.append(SAME_FINGER[legato] if melodic else 0.0)
                continue
            i, j = (pf, f) if pf < f else (f, pf)
            (xi, yi), (xj, yj) = ((pk[1], pk[2]), (key[1], key[2])) if pf < f else ((key[1], key[2]), (pk[1], pk[2]))
            dx = sign * (xj - xi) * c + (yj - yi) * s
            dy = -sign * (xj - xi) * s + (yj - yi) * c
            moves.append(min(_pair(spans, i, j, dx, dy)[0], MOVE_CAP[legato]))
        if moves:
            cost += sum(moves) / len(moves)
    cost += W_TURN_CHANGE * abs(b.turn - a.turn) / 10.0
    (ax, ay), (bx, by) = _palm(hand, a_keys, a, sign), _palm(hand, b_keys, b, sign)
    cost += W_SHIFT[legato] * math.hypot(bx - ax, by - ay) / UNIT_MM
    return cost, tuple(dict.fromkeys(notes))


def plan(hand: Hand, steps: list[list[Option]], side: str = "right", legato: bool = True, per_option: int = 4,
         prefer=None) -> list[Planned | None]:
    """Finger a phrase as a whole: for every step one of its options and a fingering, such
    that the sum of each step's own effort and the moves between steps is smallest.
    A step whose options all need more than five fingers gets None."""
    sign = -1.0 if side.strip().lower() == "left" else 1.0
    states: list[list[tuple[int, Fingering, tuple[Fingering, ...]]]] = []
    for options in steps:
        here = []
        for n, opt in enumerate(options):
            pts = [(x, y) for _, x, y in opt.keys]
            ranked = fingerings(hand, pts, side, max(per_option, 5 if len(opt.keys) == 1 else 0))
            chosen = prefer(pts) if prefer and ranked else None     # the player's own fingering of this shape
            if chosen:
                ranked = with_own(ranked, own_fingering(hand, pts, chosen, side))
            here.extend((n, f, tuple(r for r in ranked if r is not f)) for f in ranked)
        states.append(here)
    out: list[Planned | None] = [None] * len(steps)
    # runs of fingerable steps; a step for two hands breaks the phrase
    start = 0
    while start < len(steps):
        if not states[start]:
            start += 1
            continue
        end = start
        while end + 1 < len(steps) and states[end + 1]:
            end += 1
        def cost(f: Fingering) -> float:
            return f.effort - (BOOK_BONUS if f.own else 0.0)

        best = [[(cost(s[1]), -1, ()) for s in states[start]]]
        for t in range(start + 1, end + 1):
            row = []
            for n, f, _ in states[t]:
                cands = []
                for p, (pn, pf, _) in enumerate(states[t - 1]):
                    move, notes = _transition(hand, legato, steps[t - 1][pn].keys, pf, steps[t][n].keys, f, sign)
                    cands.append((best[-1][p][0] + move + cost(f), p, notes))
                row.append(min(cands, key=lambda c: c[0]))
            best.append(row)
        at = min(range(len(best[-1])), key=lambda i: best[-1][i][0])
        for t in range(end, start - 1, -1):
            n, f, alts = states[t][at]
            total, back, notes = best[t - start][at]
            out[t] = Planned(n, f, alts, notes)
            at = back
        start = end + 1
    return out
