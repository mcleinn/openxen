"""Which chords lie next to a chord in a tuning: found by moving the voices as little as
possible, not by looking up what a repertoire does.

The statistics in `harmony.py` come from 12-tone lead sheets and can only say what follows
what there. This module needs no repertoire. It takes every chord the tuning offers (every
quality of `theory.CHORDS` the tuning has, on every note), measures how far the voices of a
given chord have to move to reach it, and returns the closest ones. That finds what a piano
does not have: in 53 notes per octave, the chords next to C major are C neutral and C
supermajor (the third moves two steps), C major a comma higher (every voice moves one
step), and the relative minor exactly where it shares two notes (on vA, not on A).

How far: chords are sets of notes regardless of octave. Each voice of the first chord goes
to a note of the second so that every note of both chords is used and the sum of the
distances is as small as it can be (when the chords differ in size, one voice splits or two
merge). Distances are counted in steps of the tuning and reported in cents as well.

`neighbours` ranks, `path` chains neighbours into a short progression, `voiced` carries a
voicing along a move so that held notes stay on the same keys. Everything is in steps above
C (0 .. steps per octave - 1); `session.py` turns that into note names and keys.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import permutations, product

from .theory import CHORDS, TheoryError, Tuning, tuning_for

SIZES = ("same", "triads", "sevenths", "any")
ROOTS = ("any", "same", "other")
DEFAULT_MAX_CENTS = 240.0   # a whole tone and a little: C major to A minor is inside in every tuning
_DEGREE_WORDS = {1: "root", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh"}
_COUNT = {1: "one", 2: "two", 3: "three", 4: "four"}
# The kinds of move: another quality on the same root; one voice moves and the rest stay;
# the same chord slid along; some notes stay and several move; nothing stays.
GROUPS = ("quality", "one_voice", "shift", "held", "free")
# The order in which the kinds take turns in the varied ranking: the moves that keep most
# of the chord get most of the places.
TURNS = ("quality", "one_voice", "shift", "quality", "one_voice", "held", "quality", "one_voice", "shift", "free")
RESTLESS_FACTOR = 2.0


class VoiceLeadingError(TheoryError):
    """A request that cannot be answered; the message says what to change."""


@dataclass(frozen=True)
class Move:
    source: int     # the note a voice leaves (steps above C)
    target: int     # the note it reaches
    steps: int      # how far, signed; 0 = the note is held


@dataclass(frozen=True)
class Neighbour:
    root: int                       # steps above C
    quality: str
    notes: tuple[int, ...]          # root first, then the chord's tones in order
    moves: tuple[Move, ...]         # one per voice (more when a voice splits)
    stays: int                      # notes the two chords share
    steps: int                      # total movement in steps of the tuning
    cents: float                    # the same in cents
    root_steps: int                 # how the root moves, signed, the short way round
    group: str                      # one of GROUPS
    kind: str                       # the move in words
    also: tuple[tuple[int, str], ...] = ()      # other names of the same notes: (root, quality)


# --- distances and the best assignment of voices ---

def displacement(a: int, b: int, edo: int) -> int:
    """From note a to note b the short way round, signed; half an octave counts as up."""
    d = (b - a) % edo
    return d - edo if d > edo / 2 else d


def assign(source: tuple[int, ...], target: tuple[int, ...], edo: int) -> tuple[Move, ...]:
    """The cheapest way to lead the voices of `source` to `target`: every note of both is
    used, the total distance is minimal; among equally cheap ways the one that holds the
    most notes, then the one with the smallest largest move. One Move per source voice, in
    the order of `source` (a voice that splits appears once per note it goes to)."""
    n, m = len(source), len(target)
    if not n or not m:
        raise VoiceLeadingError("a chord needs at least one note")
    if n == m:
        ways = ([(i, p[i]) for i in range(n)] for p in permutations(range(m)))
    elif n > m:     # two voices merge
        ways = ([(i, f[i]) for i in range(n)] for f in product(range(m), repeat=n) if len(set(f)) == m)
    else:           # a voice splits
        ways = (sorted((f[j], j) for j in range(m)) for f in product(range(n), repeat=m) if len(set(f)) == n)
    best = None
    for way in ways:
        ds = [displacement(source[i], target[j], edo) for i, j in way]
        sizes = [abs(d) for d in ds]
        key = (sum(sizes), sum(1 for s in sizes if s), max(sizes))
        if best is None or key < best[0]:
            best = (key, way, ds)
    _, way, ds = best
    return tuple(Move(source[i], target[j], d) for (i, j), d in zip(way, ds))


# --- the tuning's chords ---

def chord_notes(tuning: Tuning, root: int, quality: str) -> tuple[int, ...]:
    """Root and tones of a chord as steps above C, root first."""
    return tuple((root + s) % tuning.edo for s in (0,) + tuning.tone_steps(quality))


def _pool(tuning: Tuning, sizes: str, quality: str) -> tuple[str, ...]:
    """The chord qualities a search looks at."""
    if sizes not in SIZES:
        raise VoiceLeadingError(f"sizes must be one of: {', '.join(SIZES)}")
    own = len(CHORDS[quality]["tones"])
    want = {"same": (own,), "triads": (2,), "sevenths": (3,), "any": (2, 3)}[sizes]
    return tuple(q for q in tuning.qualities() if len(CHORDS[q]["tones"]) in want)


@lru_cache(maxsize=None)
def _table(edo: int, quality: str, pool: tuple[str, ...]) -> tuple[Neighbour, ...]:
    """Every chord of `pool` as a neighbour of `quality` on C, nearest first. The same table
    serves every root, moved along (nothing in it depends on where the chord sits). Chords
    with the same notes under two names (C sus2 and G sus4; C major sixth and A minor
    seventh) appear once, and the chord's own notes under another name not at all."""
    tuning = tuning_for(edo)
    source = chord_notes(tuning, 0, quality)
    order = {q: i for i, q in enumerate(CHORDS)}
    by_notes: dict[frozenset, list[tuple[int, str]]] = {}
    for q in pool:
        for root in range(edo):
            by_notes.setdefault(frozenset(chord_notes(tuning, root, q)), []).append((root, q))
    out = []
    for notes, names in by_notes.items():
        if notes == frozenset(source):
            continue
        # the name on the same root if there is one, then the plainer quality
        names.sort(key=lambda rq: (rq[0] != 0, order[rq[1]], rq[0]))
        root, q = names[0]
        target = chord_notes(tuning, root, q)
        moves = assign(source, target, edo)
        steps = sum(abs(mv.steps) for mv in moves)
        stays = len(notes & set(source))
        group, kind = _classify(tuning, 0, quality, root, q, moves, stays)
        out.append(Neighbour(root, q, target, moves, stays, steps, round(tuning.cents_of(steps), 1), displacement(0, root, edo),
                             group, kind, tuple(names[1:])))
    out.sort(key=lambda n: (n.steps, n.root != 0, order[n.quality], n.root))
    return tuple(out)


def _moved(n: Neighbour, by: int, edo: int) -> Neighbour:
    """A neighbour from the table, seen from a chord `by` steps above C."""
    if not by:
        return n
    return replace(n, root=(n.root + by) % edo, notes=tuple((x + by) % edo for x in n.notes),
                   moves=tuple(Move((mv.source + by) % edo, (mv.target + by) % edo, mv.steps) for mv in n.moves),
                   also=tuple(((r + by) % edo, q) for r, q in n.also))


# --- words ---

def step_names(tuning: Tuning) -> dict[int, str]:
    """What the small distances of this tuning are called: number of steps -> name. Sizes
    follow from the tuning's pure fifth and thirds, so 'a comma' is one step in 53 and does
    not exist in 31, where one step is a diesis."""
    edo = tuning.edo
    fifth, major3, minor3 = tuning.steps_for(3 / 2), tuning.steps_for(5 / 4), tuning.steps_for(6 / 5)
    comma = 4 * fifth - 2 * edo - major3        # four fifths against the pure major third
    chromatic = major3 - minor3                 # major against minor third
    diatonic = edo - fifth - major3             # fourth against major third (E to F)
    diesis = edo - 3 * major3                   # three major thirds against the octave
    whole = 2 * fifth - edo
    names: dict[int, str] = {}

    def put(steps: int, name: str) -> None:
        if steps > 0 and steps not in names:
            names[steps] = name

    put(comma, "a comma")
    if chromatic == diatonic:
        put(chromatic, "a semitone")
    if not comma and not diesis and chromatic == 2:
        put(1, "a quarter tone")
    put(chromatic, "a chromatic semitone")
    put(diatonic, "a diatonic semitone")
    put(diesis, "a diesis")
    put(3 * edo - 5 * fifth, "a small semitone (limma)")
    if comma > 0:
        put(whole - comma, "a small whole tone")
    put(whole, "a whole tone")
    return names


def step_words(tuning: Tuning, steps: int, direction: bool = True) -> str:
    """`1 step up, a comma (23 cents)`: a distance in steps of the tuning, its name if it
    has one, and cents."""
    n = abs(steps)
    if n == 0:
        return "stays"
    text = f"{n} step{'' if n == 1 else 's'}"
    if direction:
        text += " up" if steps > 0 else " down"
    name = step_names(tuning).get(n)
    if not name:
        words = tuning.words(tuning.interval(n))
        name = f"a{'n' if words[:1] in 'aeiou' else ''} {words}" if " " in words else None
    return f"{text}{', ' + name if name else ''} ({tuning.cents_of(n):.0f} cents)"


def root_words(tuning: Tuning, steps: int) -> str:
    """How a root moves, in words that hold in any tuning."""
    edo = tuning.edo
    if steps % edo == 0:
        return "the root stays"
    up = steps % edo
    fifth = tuning.steps_for(3 / 2)
    if up == edo - fifth:
        return "the root falls a fifth (rises a fourth)"
    if up == fifth:
        return "the root rises a fifth (falls a fourth)"
    short = displacement(0, up, edo)
    n = abs(short)
    name = step_names(tuning).get(n)
    if not name:
        words = tuning.words(tuning.interval(n))
        name = f"a{'n' if words[:1] in 'aeiou' else ''} {words}" if " " in words else f"{n} steps"
    return f"the root {'rises' if short > 0 else 'falls'} {name}"


def _degree_of(tuning: Tuning, root: int, quality: str, note: int) -> int | None:
    degrees = (1,) + tuple(d for _, d in CHORDS[quality]["tones"])
    for n, d in zip(chord_notes(tuning, root, quality), degrees):
        if n == note:
            return d
    return None


def _classify(tuning: Tuning, root: int, quality: str, to_root: int, to_quality: str, moves: tuple[Move, ...], stays: int) -> tuple[str, str]:
    """(group, words) for one move between two chords."""
    edo = tuning.edo
    moving = [mv for mv in moves if mv.steps]
    names = step_names(tuning)
    comma = next((n for n, name in names.items() if name == "a comma"), 0)
    if to_root == root:
        changes, others = [], []
        for mv in moving:
            a, b = _degree_of(tuning, root, quality, mv.source), _degree_of(tuning, root, to_quality, mv.target)
            if a == b or b is None:
                changes.append(f"the {_DEGREE_WORDS.get(a, 'note')}")
            else:
                others.append(f"the {_DEGREE_WORDS.get(a, 'note')} moves to the {_DEGREE_WORDS[b]}")
        changes = list(dict.fromkeys(changes))
        parts = ([" and ".join(changes) + (" change" if len(changes) > 1 else " changes")] if changes else []) + list(dict.fromkeys(others))
        return "quality", f"same root, {', '.join(parts)}: {quality} to {to_quality}"
    sizes = {mv.steps for mv in moves}
    if to_quality == quality and len(sizes) == 1:
        d = moves[0].steps
        tail = "the same chord a comma " + ("higher" if d > 0 else "lower") if abs(d) == comma else "a planing shift"
        return "shift", f"all voices slide {step_words(tuning, d)}: {tail}"
    root_text = root_words(tuning, displacement(root, to_root, edo))
    held = f"{_COUNT.get(stays, stays)} note{'' if stays == 1 else 's'} stay{'s' if stays == 1 else ''}"
    if len(moving) == 1 and stays:
        d = moving[0].steps
        tail = ": a comma shift" if abs(d) == comma else ""
        return "one_voice", f"{held}, one voice moves {step_words(tuning, d)}{tail}; {root_text}"
    if stays:
        return "held", f"{held}, {_COUNT.get(len(moving), len(moving))} voices move; {root_text}"
    if len({mv.steps > 0 for mv in moving}) == 1:
        return "free", f"no note stays, all voices move {'up' if moving[0].steps > 0 else 'down'}; {root_text}"
    return "free", f"no note stays, the voices move in contrary motion; {root_text}"


# --- neighbours ---

def _check(tuning: Tuning, quality: str) -> str:
    quality = tuning.quality_key(quality)
    if not tuning.has(quality):
        raise VoiceLeadingError(f"{tuning.edo} steps per octave has no {quality} chord of its own. Available: {', '.join(tuning.qualities())}.")
    return quality


def _candidates(tuning: Tuning, root: int, quality: str, pool: tuple[str, ...], max_cents: float, roots: str) -> list[Neighbour]:
    """All chords within reach, nearest first."""
    if roots not in ROOTS:
        raise VoiceLeadingError(f"roots must be one of: {', '.join(ROOTS)}")
    edo = tuning.edo
    reach = max_cents * edo / 1200.0 + 1e-9
    out = []
    for n in _table(edo, quality, pool):
        if n.steps > reach:
            break
        if (roots == "same" and n.root) or (roots == "other" and not n.root):
            continue
        out.append(_moved(n, root, edo))
    return out


def _restless(quality: str) -> bool:
    """No pure fifth above the root: diminished and augmented chords, which pass rather than rest."""
    return ("P5",) not in [parts for parts, _ in CHORDS[quality]["tones"]]


def _take_turns(found: list[Neighbour], quality: str) -> list[Neighbour]:
    """The varied ranking. Within each kind of move the nearest comes first, a restless
    chord (diminished, augmented) counting as RESTLESS_FACTOR times as far unless the
    starting chord is restless too. The kinds then take turns in the order of TURNS: so
    a list of ten shows changed thirds, the chords that share two notes, a comma shift
    and one or two of the stranger moves, not ten near-copies."""
    calm = not _restless(quality)
    queues = {g: sorted((n for n in found if n.group == g),
                        key=lambda n: (n.steps * RESTLESS_FACTOR, 1) if calm and _restless(n.quality) else (n.steps, 0)) for g in GROUPS}
    out = []
    while any(queues.values()):
        for g in TURNS:
            if queues[g]:
                out.append(queues[g].pop(0))
    return out


def neighbours(tuning: Tuning, root: int, quality: str, *, limit: int = 8, max_cents: float = DEFAULT_MAX_CENTS,
               roots: str = "any", sizes: str = "same", ranking: str = "varied") -> list[Neighbour]:
    """The chords closest to `quality` on `root` (steps above C).

    max_cents: the most all voices together may move. roots: "any", "same" (only other
    qualities on this root) or "other" (the root must change). sizes: "same" (triads for a
    triad, seventh chords for a seventh chord), "triads", "sevenths" or "any". ranking:
    "varied" lets the kinds of move take turns (see `_take_turns`),"nearest" is by distance alone.
    A chord that has the same notes as the given one is never returned."""
    quality = _check(tuning, quality)
    if ranking not in ("varied", "nearest"):
        raise VoiceLeadingError("ranking must be 'varied' or 'nearest'")
    found = _candidates(tuning, root % tuning.edo, quality, _pool(tuning, sizes, quality), max_cents, roots)
    if ranking == "varied":
        found = _take_turns(found, quality)
    return found[:max(1, limit)]


def move(tuning: Tuning, root: int, quality: str, to_root: int, to_quality: str) -> Neighbour:
    """One given move, described like a neighbour (however far it is)."""
    quality, to_quality = _check(tuning, quality), _check(tuning, to_quality)
    edo = tuning.edo
    source, target = chord_notes(tuning, root % edo, quality), chord_notes(tuning, to_root % edo, to_quality)
    moves = assign(source, target, edo)
    stays = len(set(source) & set(target))
    steps = sum(abs(mv.steps) for mv in moves)
    if set(source) == set(target):
        group, kind = "same", "the same notes under another name"
    else:
        group, kind = _classify(tuning, root % edo, quality, to_root % edo, to_quality, moves, stays)
    return Neighbour(to_root % edo, to_quality, target, moves, stays, steps, round(tuning.cents_of(steps), 1),
                     displacement(root % edo, to_root % edo, edo), group, kind)


# --- progressions ---

def path(tuning: Tuning, root: int, quality: str, *, length: int = 5, end: tuple[int, str] | None = None,
         max_cents: float = DEFAULT_MAX_CENTS, via: str | None = None, seed: int = 0, roots: str = "any",
         sizes: str = "same") -> list[Neighbour]:
    """A progression of `length` chords from `quality` on `root` to `end` (default: back to
    the start), each step moving the voices by at most `max_cents` in total, no chord twice.
    Returns the moves: length - 1 neighbours, the last one being `end`.

    via: a quality that must occur on the way, or "xen" for any quality a piano does not
    have. seed 0 takes the closest chord that still gets home in time at every step; other
    seeds choose among the close ones, the same way for the same seed."""
    quality = _check(tuning, quality)
    edo = tuning.edo
    root %= edo
    if not 3 <= length <= 12:
        raise VoiceLeadingError("length (the number of chords, start and end included) must be 3 to 12")
    pool = _pool(tuning, sizes, quality)
    goal = (root, quality) if end is None else (end[0] % edo, _check(tuning, end[1]))
    if goal[1] not in pool:
        raise VoiceLeadingError(f"the last chord ({goal[1]}) is not among the chords searched (sizes='{sizes}'); use sizes='any'")
    if via is not None and via != "xen":
        via = _check(tuning, via)
        if via not in pool:
            raise VoiceLeadingError(f"{via} is not among the chords searched (sizes='{sizes}'); use sizes='any'")
    if via == "xen" and not any(CHORDS[q].get("xen") for q in pool):
        raise VoiceLeadingError("this tuning has no chords of that size beyond the twelve-tone ones; try sizes='any' or another tuning")

    def wanted(q: str) -> bool:
        return via is None or q == via or (via == "xen" and bool(CHORDS[q].get("xen")))

    def near(r: int, q: str) -> list[Neighbour]:
        return _candidates(tuning, r, q, pool, max_cents, roots)

    def key(r: int, q: str) -> frozenset:
        return frozenset(chord_notes(tuning, r, q))

    # how many moves each chord is from the goal (the relation is the same in both directions)
    goal_key = key(*goal)
    far: dict[frozenset, int] = {goal_key: 0}
    frontier = [goal]
    for depth in range(1, length):
        following = []
        for r, q in frontier:
            for n in near(r, q):
                k = frozenset(n.notes)
                if k not in far:
                    far[k] = depth
                    following.append((n.root, n.quality))
        frontier = following
    rng = random.Random(seed)
    budget = [60000]

    def options(r: int, q: str) -> list[Neighbour]:
        found = _take_turns(near(r, q), q)
        if seed:
            head, tail = found[:10], found[10:]
            rng.shuffle(head)
            found = head + tail
        return found

    def walk(r: int, q: str, left: int, seen: frozenset, met: bool) -> list[Neighbour] | None:
        """`left` moves remain; the last one must land on the goal."""
        budget[0] -= 1
        if budget[0] < 0:
            return None
        found = options(r, q)
        if not met:
            found.sort(key=lambda n: not wanted(n.quality))     # stable: first the chords asked for
        for n in found:
            k = frozenset(n.notes)
            if left == 1:
                if k == goal_key and (met or wanted(n.quality)):
                    return [n]
                continue
            if k == goal_key or k in seen or far.get(k, length) > left - 1:
                continue
            rest = walk(n.root, n.quality, left - 1, seen | {k}, met or wanted(n.quality))
            if rest is not None:
                return [n] + rest
        return None

    start_key = key(root, quality)
    found = walk(root, quality, length - 1, frozenset({start_key}), via is None)
    if found is None:
        raise VoiceLeadingError(
            f"no progression of {length} chords within {max_cents:.0f} cents per move"
            + (f" that passes a {'chord a piano lacks' if via == 'xen' else via + ' chord'}" if via else "")
            + "; allow more movement (max_cents), more chords (length) or other chord sizes (sizes='any')")
    # the last move is named after the goal as it was asked for, not after another name of the same notes
    if (found[-1].root, found[-1].quality) != goal:
        before = (root, quality) if len(found) == 1 else (found[-2].root, found[-2].quality)
        found[-1] = move(tuning, before[0], before[1], goal[0], goal[1])
    return found


# --- voicing ---

def voiced(pitches: list[int], moves: tuple[Move, ...], edo: int) -> list[int]:
    """Carry a voicing along a move: each sounding note goes where its voice goes, so held
    notes stay where they are. `pitches` are steps above C0; every note of the first chord
    should be in it."""
    out = []
    for mv in moves:
        for p in pitches:
            if p % edo == mv.source % edo:
                out.append(p + mv.steps)
    return sorted(set(out))
