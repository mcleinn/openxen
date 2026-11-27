"""An outline of a composition in two staves: its sections, what repeats what (also transposed),
phrases, how hard each part is, and an order to practise it in.

Computed from the bars alone (`build`), for any piece in the library's bar format:

    {"n", "time", "length" (quarter notes), "staves": {"upper": [[beat, dur, [steps]], ...], "lower": [...]},
     "marks"? ([{"staff", "beat", "step", "mark": "grace" | "trill"}]), "expression"? (expression.py)}

It is a suggestion, not an analysis by a musician, and says so (`MADE`). Where the ideas come
from (reference/research/segmentation.md has the sources):

  repeats   Meredith, Lemstroem & Wiggins 2002 (SIA): notes are points (onset, step); a repeat is the
            pitch translation that moves the points of one bar onto those of another. Here only whole
            bars are compared. Each hand alone and both together; lengths are not compared (ties).
  patterns  Meredith's COSIATEC: a greedy cover of the piece by the unit (1, 2 or 4 bars) whose
            occurrences cover most bars.
  sections  repetition, novelty and homogeneity (Mueller, Fundamentals of Music Processing, ch. 4):
            a pattern starting over or being left, Foote's checkerboard novelty on the bar-to-bar
            similarity, a change of note density or register; and what the print says: tempo words
            and tempo marks, a lasting change of time signature, fermatas, rests in both hands
            (Lerdahl & Jackendoff's grouping rules 2 and 3).
  phrases   the same rules at bar lines (rest, long note, slur end: GPR 2; Cambouropoulos's LBDM), a
            pattern starting over (GPR 6), the end of a slowing. Whole bars only.

This project's own choices: the weights and thresholds below, what counts as a variant, the
difficulty points and the rule of the practice order.
"""
from __future__ import annotations

from collections import Counter
from typing import Callable

MADE = "computed from the notes; a suggestion, not an analysis by a musician"
HANDS = (("upper", "right"), ("lower", "left"))
UNITS = (4, 2, 1)               # bars in a recurring pattern
OCCURRENCE = 0.6                # how alike (0..1) a unit must be to count as an occurrence of a pattern
REPEAT = 0.5                    # ... and a bar to be said to repeat an earlier one
VARIANT_SHARE = 0.6             # share of the notes one interval must move for "varied"
MIN_TRANSPOSED = 3              # notes needed before a transposition is claimed (any two notes transpose)
BOUNDARY = 2.0                  # points that make a section boundary
PHRASE = 1.5                    # ... and a phrase boundary
MAX_PHRASE = 8                  # bars
MAX_SECTIONS = 14
MAX_SECTION_BARS = 24
MIN_OCCURRENCES = {4: 2, 2: 3, 1: 4}  # how often a unit of that many bars must occur to be called a pattern
MAJOR = 0.1                     # share of the bars a pattern must cover to divide the piece into sections
WEIGHT = {"same": 1.0, "transposed": 1.0, "ornamented": 0.85, "direction": 0.35, "rhythm": 0.25, "different": 0.0, "rest": 0.0}
DYNAMICS = ("ppp", "pp", "p", "mp", "mezzo", "mf", "f", "ff", "fff")
A_TEMPO = ("a tempo", "tempo i", "tempo primo", "tempo 1")
LEVELS = ("easy", "moderate", "hard", "very hard")


# --- the notes of a bar as points ---

def _points(bar: dict, staff: str, reduce: bool = False) -> dict[float, tuple[int, ...]]:
    """onset -> steps of one hand in a bar. `reduce`: without grace notes, and a trill that the file
    holds written out as the one note the trill sign stands on."""
    events = [(round(float(b), 3), set(steps)) for b, _, steps in bar["staves"].get(staff, [])]
    if reduce:
        marks = [m for m in bar.get("marks", []) if m["staff"] == staff]
        grace = {(round(float(m["beat"]), 3), m["step"]) for m in marks if m["mark"] == "grace"}
        events = [(b, {s for s in steps if (b, s) not in grace}) for b, steps in events]
        events = [(b, steps) for b, steps in events if steps]
        for m in sorted((m for m in marks if m["mark"] == "trill"), key=lambda m: m["beat"]):
            start = next((i for i, (b, steps) in enumerate(events) if b == round(float(m["beat"]), 3) and m["step"] in steps), None)
            if start is None or start + 1 >= len(events):
                continue
            pool = events[start][1] | events[start + 1][1]
            end = start + 1
            while end < len(events) and events[end][0] - events[end - 1][0] <= 0.3 + 1e-6 and events[end][1] <= pool:
                end += 1
            events[start:end] = [(events[start][0], {m["step"]})]
    return {b: tuple(sorted(steps)) for b, steps in events if steps}


def _count(points: dict) -> int:
    return sum(len(v) for v in points.values())


def _direction(points: dict) -> tuple[int, ...]:
    tops = [max(points[b]) for b in sorted(points)]
    return tuple((y > x) - (y < x) for x, y in zip(tops, tops[1:]))


def _relate(a: dict, b: dict) -> tuple[str, int | None, float]:
    """How the later point set `b` relates to the earlier `a`: (kind, steps, how alike 0..1).
    same | transposed | variant (most notes moved by one interval) | direction (same rhythm, same ups
    and downs) | rhythm (same rhythm only) | different | rest (both empty)."""
    na, nb = _count(a), _count(b)
    if not na and not nb:
        return "rest", None, 0.0
    if not na or not nb:
        return "different", None, 0.0
    moves: Counter = Counter()
    for onset, low in a.items():
        for y in b.get(onset, ()):
            for x in low:
                moves[y - x] += 1
    shift, hit = min(moves.items(), key=lambda kv: (-kv[1], abs(kv[0]), kv[0])) if moves else (None, 0)
    if hit == na == nb:
        if shift == 0:
            return "same", 0, 1.0
        if nb >= MIN_TRANSPOSED:
            return "transposed", shift, 1.0
    same_rhythm = a.keys() == b.keys()
    share = hit / max(na, nb)
    if max(na, nb) >= MIN_TRANSPOSED and share >= VARIANT_SHARE and hit < max(na, nb):
        return "variant", shift, round(0.8 * share, 3)
    if same_rhythm and len(a) >= 3:
        return ("direction", None, WEIGHT["direction"]) if _direction(a) == _direction(b) else ("rhythm", None, WEIGHT["rhythm"])
    return "different", None, 0.0


class _Bars:
    """The bars of a piece prepared for comparing."""

    def __init__(self, bars: list[dict]):
        self.bars = bars
        self.n = len(bars)
        self.raw = [{staff: _points(bar, staff) for staff, _ in HANDS} for bar in bars]
        self.plain = [{staff: _points(bar, staff, True) for staff, _ in HANDS} for bar in bars]
        self.both = []
        for points in self.raw:
            merged: dict[float, set] = {}
            for staff, _ in HANDS:
                for onset, steps in points[staff].items():
                    merged.setdefault(onset, set()).update(steps)
            self.both.append({o: tuple(sorted(s)) for o, s in merged.items()})
        self.size = [{staff: _count(p[staff]) for staff, _ in HANDS} for p in self.raw]
        self.notes = [sum(size.values()) for size in self.size]
        self.starts = [0.0]
        for bar in bars:
            self.starts.append(self.starts[-1] + float(bar["length"]))
        self._seen: dict[tuple[int, int], dict] = {}
        self._hands: dict[tuple[int, int, str], tuple] = {}
        self._units: dict[tuple[int, int, int], dict] = {}

    def hand(self, i: int, j: int, staff: str) -> tuple[str, int | None, float]:
        key = (i, j, staff)
        if key not in self._hands:
            self._hands[key] = self._hand(i, j, staff)
        return self._hands[key]

    def _hand(self, i: int, j: int, staff: str) -> tuple[str, int | None, float]:
        raw = _relate(self.raw[i][staff], self.raw[j][staff])
        if raw[0] in ("same", "transposed", "rest"):
            return raw
        if self.plain[i][staff] != self.raw[i][staff] or self.plain[j][staff] != self.raw[j][staff]:
            kind, shift, _ = _relate(self.plain[i][staff], self.plain[j][staff])
            if kind == "same" or (kind == "transposed" and max(self.size[i][staff], self.size[j][staff]) >= MIN_TRANSPOSED):
                return "ornamented", shift, WEIGHT["ornamented"]
        return raw

    def relation(self, i: int, j: int) -> dict:
        """Bar j (later) against bar i (indices): {"kind": same | transposed | hands, "shift"?, "right", "left", "alike"}."""
        if (i, j) not in self._seen:
            out: dict = {}
            whole = _relate(self.both[i], self.both[j])
            total = alike = 0.0
            for staff, name in HANDS:
                kind, shift, weight = self.hand(i, j, staff)
                out[name] = {"kind": kind, **({"shift": shift} if shift is not None else {})}
                n = max(self.size[i][staff], self.size[j][staff])
                total += n
                alike += n * weight
            if whole[0] in ("same", "transposed"):
                out.update(kind=whole[0], alike=1.0)
                if whole[0] == "transposed":
                    out["shift"] = whole[1]
                    for staff, name in HANDS:       # a hand with too few notes to claim it alone moves with the whole bar
                        moved = {o: tuple(x + whole[1] for x in steps) for o, steps in self.raw[i][staff].items()}
                        if moved and moved == self.raw[j][staff]:
                            out[name] = {"kind": "transposed", "shift": whole[1]}
            else:
                out.update(kind="hands", alike=round(alike / total, 3) if total else 0.0)
            self._seen[(i, j)] = out
        return self._seen[(i, j)]

    def unit(self, i: int, j: int, length: int) -> dict:
        """`length` bars from j against those from i, as one relation."""
        if length == 1:
            return self.relation(i, j)
        if (i, j, length) not in self._units:
            self._units[(i, j, length)] = self._unit(i, j, length)
        return self._units[(i, j, length)]

    def _unit(self, i: int, j: int, length: int) -> dict:
        each = [self.relation(i + k, j + k) for k in range(length)]
        sounding = [r for k, r in enumerate(each) if self.notes[i + k] or self.notes[j + k]]
        out: dict = {}
        if sounding and all(r["kind"] == "same" for r in sounding):
            out["kind"] = "same"
        elif sounding and all(r["kind"] in ("same", "transposed") for r in sounding) and len({r.get("shift", 0) for r in sounding}) == 1:
            out.update(kind="transposed", shift=sounding[0].get("shift", 0))
        else:
            out["kind"] = "hands"
        total = alike = 0.0
        for staff, name in HANDS:
            kinds = [r[name] for r in each if r[name]["kind"] != "rest"]
            shifts = {r.get("shift", 0) for r in kinds}
            weights = []
            for k in range(length):
                n = max(self.size[i + k][staff], self.size[j + k][staff])
                weights.append((n, self.hand(i + k, j + k, staff)[2]))
            n_hand = sum(n for n, _ in weights)
            mean = sum(n * w for n, w in weights) / n_hand if n_hand else 0.0
            if not kinds:
                hand = {"kind": "rest"}
            elif all(r["kind"] == "same" for r in kinds):
                hand = {"kind": "same"}
            elif all(r["kind"] in ("same", "transposed") for r in kinds) and len(shifts) == 1:
                hand = {"kind": "transposed", "shift": shifts.pop()}
            elif all(r["kind"] in ("same", "transposed", "ornamented") for r in kinds) and len(shifts) == 1:
                hand = {"kind": "ornamented", "shift": shifts.pop()}
            elif all(r["kind"] in ("same", "transposed", "ornamented", "variant") for r in kinds):
                hand = {"kind": "variant", **({"shift": shifts.pop()} if len(shifts) == 1 else {})}
                mean = min(mean, 0.8)
            elif all(r["kind"] != "different" for r in kinds):
                hand = {"kind": "rhythm"}
                mean = min(mean, 0.5)
            else:
                hand = {"kind": "different"}
                mean *= 0.5
            out[name] = hand
            total += n_hand
            alike += n_hand * mean
        out["alike"] = 1.0 if out["kind"] != "hands" else round(alike / total, 3) if total else 0.0
        return out


# --- recurring patterns (a greedy cover) ---

def _patterns(b: _Bars) -> list[dict]:
    free = {i for i in range(b.n) if b.notes[i]}
    found: list[dict] = []
    while len(found) < 6:
        best = None
        for length in UNITS:
            for i in range(b.n - 2 * length + 1):
                if not all(i + k in free for k in range(length)) or sum(b.notes[i:i + length]) < 3:
                    continue
                half = length // 2
                if half and b.unit(i, i + half, half)["kind"] == "same":
                    continue            # the unit is a shorter one twice
                seen, covered, j = [], 1.0, i + length
                while j + length <= b.n:
                    if all(j + k in free for k in range(length)):
                        r = b.unit(i, j, length)
                        if r["alike"] >= OCCURRENCE and "different" not in (r["right"]["kind"], r["left"]["kind"]):
                            seen.append((j, r))
                            covered += r["alike"]
                            j += length
                            continue
                    j += 1
                if len(seen) + 1 < MIN_OCCURRENCES[length]:
                    continue
                key = (round(covered * length, 3), length, -i)
                if best is None or key > best[0]:
                    best = (key, i, length, seen)
        if best is None:
            break
        _, i, length, seen = best
        found.append({"name": "abcdef"[len(found)], "at": i, "length": length, "seen": seen})
        for start in [i] + [j for j, _ in seen]:
            free -= set(range(start, start + length))
    return found


# --- words ---

def _steps_words(shift: int, interval: Callable[[int], str] | None) -> str:
    n = abs(shift)
    octave = getattr(interval, "octave", None)
    if octave and n % octave == 0:
        return f"{'an octave' if n == octave else f'{n // octave} octaves'} {'higher' if shift > 0 else 'lower'}"
    name = interval(n) if interval else ""
    name = "" if "unison" in name else name
    return f"{n} step{'' if n == 1 else 's'} {'higher' if shift > 0 else 'lower'}" + (f" ({name})" if name else "")


def _hand_words(rel: dict, interval) -> str:
    kind, shift = rel["kind"], rel.get("shift")
    if kind == "same":
        return "the same notes"
    if kind == "transposed":
        return _steps_words(shift, interval)
    if kind == "ornamented":
        return "the same but for the ornaments" + (f", {_steps_words(shift, interval)}" if shift else "")
    if kind == "variant":
        return "varied" + (f", mostly {_steps_words(shift, interval)}" if shift else "")
    if kind == "direction":
        return "the same rhythm and direction, other notes"
    if kind == "rhythm":
        return "the same rhythm, other notes"
    return "rests" if kind == "rest" else "different"


def relation_words(rel: dict, interval: Callable[[int], str] | None = None, part: str = "both") -> str:
    """A relation in words: "the same notes", "the same shape, every note 6 steps lower (minor third)",
    "right hand 2 steps lower (minor second), left hand varied". `part` upper or lower: that hand only."""
    if part in ("upper", "lower"):
        return _hand_words(rel["right" if part == "upper" else "left"], interval)
    if rel["kind"] == "same":
        return "the same notes"
    if rel["kind"] == "transposed":
        return f"the same shape, every note {_steps_words(rel['shift'], interval)}"
    right, left = _hand_words(rel["right"], interval), _hand_words(rel["left"], interval)
    if rel["right"]["kind"] == "rest":
        return f"left hand {left}"
    if rel["left"]["kind"] == "rest":
        return f"right hand {right}"
    return f"both hands {right}" if right == left else f"right hand {right}, left hand {left}"


def _span(a: int, b: int | None = None, word: bool = True) -> str:
    text = str(a) if b is None or b == a else f"{a}-{b}"
    return text if not word else ("bar " if b is None or b == a else "bars ") + text


def _spans(pairs: list, limit: int = 8) -> str:
    shown = [_span(a, b, False) for a, b in pairs[:limit]]
    return ("bar " if len(pairs) == 1 and pairs[0][0] == pairs[0][1] else "bars ") + ", ".join(shown) + (f" and {len(pairs) - limit} more" if len(pairs) > limit else "")


# --- sections ---

def _silences(b: _Bars) -> list[tuple[float, float]]:
    """Stretches in which neither hand sounds, in quarter notes from the start."""
    spans = sorted((b.starts[i] + float(beat), b.starts[i] + float(beat) + float(dur))
                   for i, bar in enumerate(b.bars) for events in bar["staves"].values() for beat, dur, _ in events)
    out, end = [], 0.0
    for start, stop in spans:
        if start - end > 1e-6:
            out.append((end, start))
        end = max(end, stop)
    return out


def _bar_at(b: _Bars, time: float) -> int:
    return max(i for i in range(b.n) if b.starts[i] <= time + 1e-6)


def _tempo_spans(piece: dict, n: int) -> list[tuple[int, int, float]]:
    """(first bar index, last bar index, quarter notes per minute) for each stretch of one tempo."""
    marks = sorted((int(bar) - 1, float(bpm)) for bar, bpm in piece.get("tempi") or [] if 1 <= int(bar) <= n)
    return [(at, (marks[k + 1][0] if k + 1 < len(marks) else n) - 1, bpm) for k, (at, bpm) in enumerate(marks)
            if (marks[k + 1][0] if k + 1 < len(marks) else n) > at]


def _signs(piece: dict, b: _Bars, patterns: list[dict], source: dict, alike) -> tuple[dict[int, dict[str, float]], dict[int, dict[str, float]]]:
    """What speaks for a boundary before each bar (index): for sections, and for phrases."""
    n = b.n
    section: dict[int, dict[str, float]] = {}
    phrase: dict[int, dict[str, float]] = {}

    def vote(table: dict, i: int, why: str, points: float) -> None:
        if 0 < i < n:
            table.setdefault(i, {})
            table[i][why] = max(table[i].get(why, 0.0), points)

    # the print: tempo words, tempo marks, time signatures, fermatas
    for i, bar in enumerate(b.bars):
        for mark in bar.get("expression", []):
            words = f"{mark.get('value', '')} {mark.get('text', '')}".lower()
            if mark["type"] == "tempo" and any(w in words for w in A_TEMPO):
                vote(section, i if float(mark["beat"]) < 0.5 else i + 1, "a tempo", 3.0)
            if mark["type"] == "fermata":          # what follows it in the bar leads on to the next
                vote(section, i + 1, "after a fermata", 2.0)
                vote(phrase, i + 1, "after a fermata", 2.0)
            if mark["type"] == "slur" and mark.get("to"):
                end_bar, end_beat = int(mark["to"][0]) - 1, float(mark["to"][1])
                if end_beat <= 1e-6:
                    vote(phrase, end_bar, "a slur ends", 1.0)
                elif end_bar < n and end_beat >= last_onset_of(b, end_bar) - 1e-6:
                    vote(phrase, end_bar + 1, "a slur ends", 1.0)
    spans = _tempo_spans(piece, n)
    steady = None                       # the last tempo that lasted
    dipped = False
    for k, (first, last, bpm) in enumerate(spans):
        long = last - first + 1 >= 4 or k == 0
        if long:
            if steady is not None and (dipped or abs(bpm - steady) / steady >= 0.08):
                vote(section, first, "the tempo returns after a slowing" if dipped and abs(bpm - steady) / steady < 0.08 else "a new tempo", 2.0)
            steady, dipped = bpm, False
        else:
            if steady is not None and bpm < 0.93 * steady:
                dipped = True
            elif steady is not None and dipped and abs(bpm - steady) / steady < 0.08 and last - first + 1 >= 2:
                vote(section, first, "the tempo returns after a slowing", 2.0)
                dipped = False
            if k and bpm > spans[k - 1][2] * 1.08 and spans[k - 1][1] - spans[k - 1][0] + 1 < 4:
                vote(phrase, first, "after a slowing", 1.5)
        if long and k and spans[k - 1][2] < bpm * 0.93:
            vote(phrase, first, "after a slowing", 1.5)
    runs: list[list] = []
    for i, bar in enumerate(b.bars):
        if runs and runs[-1][0] == bar["time"]:
            runs[-1][2] = i
        else:
            runs.append([bar["time"], i, i])
    for k, (_, first, last) in enumerate(runs[1:], 1):
        lasting = last - first + 1 >= 4 or (last == n - 1 and last - first + 1 >= 2)
        if lasting and runs[k - 1][2] - runs[k - 1][1] + 1 >= 4:
            vote(section, first, "the time signature changes", 2.0)
    # silence in both hands
    for start, end in _silences(b):
        i = _bar_at(b, end)
        length = float(b.bars[i]["length"])
        if start <= 1e-6 or end - start < 0.5 - 1e-6:
            continue
        before = any(b.starts[i] + float(beat) < start - 1e-6 for events in b.bars[i]["staves"].values() for beat, _, _ in events)
        at = i + 1 if before else i
        if end - start >= max(1.0, length / 3) - 1e-6:
            vote(section, at, "a rest in both hands", 3.0 if end - start >= length / 2 else 2.0)
        vote(phrase, at, "a rest in both hands", 2.0)
    # repetition: a pattern starts over, or is left
    member: dict[int, tuple[str, int]] = {}
    major, first_at = set(), {}
    for p in patterns:
        first_at[p["name"]] = p["at"]
        if (len(p["seen"]) + 1) * p["length"] >= MAJOR * n:
            major.add(p["name"])
        for start in [p["at"]] + [j for j, _ in p["seen"]]:
            for k in range(p["length"]):
                member[start + k] = (p["name"], k)
    for i in range(1, n):
        here, prev = member.get(i), member.get(i - 1)
        if here and here[1] == 0:
            vote(phrase, i, "a pattern starts over", 1.5)
            before = [member.get(k, ("", 0))[0] for k in range(max(0, i - 2), i)]
            if here[0] in major and i != first_at[here[0]] and here[0] not in before and len(before) == 2:
                vote(section, i, "the pattern returns", 2.0)
        if prev and prev[0] in major and (not here or here[0] != prev[0]):
            length = next(p["length"] for p in patterns if p["name"] == prev[0])
            back = [member.get(k, ("", 0))[0] for k in range(max(0, i - 2 * length), i)]
            ahead = [member.get(k, ("", 0))[0] for k in range(i, min(n, i + 2))]
            if len(back) == 2 * length and all(x == prev[0] for x in back) and prev[0] not in ahead:
                vote(section, i, "the pattern is left", 2.0)
    for j, (i, _) in source.items():        # an earlier bar comes again (and not as the continuation of a run)
        if j not in member and (j - 1 not in source or source[j - 1][0] != i - 1) and j - i >= 2:
            vote(phrase, j, "an earlier bar comes again", 1.5)
            if j - i >= 8 and j + 1 in source and source[j + 1][0] == i + 1:
                vote(section, j, "earlier bars return", 1.5)
    # homogeneity: note density and register (windows of up to four bars either side)
    density = [b.notes[i] / float(b.bars[i]["length"]) if float(b.bars[i]["length"]) else 0.0 for i in range(n)]
    changes = {}
    for i in range(2, n - 1):
        w = min(4, i, n - i)
        before, after = sum(density[i - w:i]) / w, sum(density[i:i + w]) / w
        ratio = (after + 0.25) / (before + 0.25)
        changes[i] = max(ratio, 1 / ratio)
    for i, change in changes.items():
        if change >= 2.0 and all(change >= changes.get(k, 0.0) for k in range(i - 2, i + 3)):
            vote(section, i, "the texture changes", 1.5)
            vote(phrase, i, "the texture changes", 1.5)
    # novelty (Foote's checkerboard kernel on the bar-to-bar likeness)
    w = 4 if n >= 16 else 2
    novelty = {}
    for i in range(w, n - w + 1):
        within = sum(alike(x, y) for x in range(i - w, i) for y in range(i - w, i) if x != y)
        within += sum(alike(x, y) for x in range(i, i + w) for y in range(i, i + w) if x != y)
        across = sum(alike(x, y) for x in range(i - w, i) for y in range(i, i + w))
        novelty[i] = within / (2 * w * (w - 1)) - across / (w * w)
    if novelty:
        mean = sum(novelty.values()) / len(novelty)
        spread = (sum((v - mean) ** 2 for v in novelty.values()) / len(novelty)) ** 0.5
        for i, value in novelty.items():
            if value >= max(0.15, mean + spread) and all(value >= novelty.get(k, -1.0) for k in range(i - 2, i + 3)):
                vote(section, i, "what follows is unlike what came before", 1.0)
    # a long note before the bar line (the upper line, or the lower where the upper is silent)
    for i in range(1, n):
        for staff, _ in HANDS:
            onsets = sorted(b.starts[k] + o for k in (i - 1, i) for o in b.raw[k][staff])
            earlier = [o for o in onsets if o < b.starts[i] - 1e-6]
            later = [o for o in onsets if o >= b.starts[i] - 1e-6]
            if len(earlier) >= 3 and later:
                gaps = [y - x for x, y in zip(earlier, earlier[1:])]
                if later[0] - earlier[-1] >= 2 * max(gaps[-2:]) and later[0] - earlier[-1] >= 1.0:
                    vote(phrase, i, "a long note", 1.0)
            if earlier or later:
                break
    return section, phrase


def last_onset_of(b: _Bars, i: int) -> float:
    return max((o for staff, _ in HANDS for o in b.raw[i][staff]), default=0.0)


def _cut(signs: dict[int, dict[str, float]], n: int, threshold: float, most: int) -> list[int]:
    """Bar indices at which a part begins: the signs that reach the threshold, none within one bar of
    a stronger one, no part of a single bar unless both its ends are strong, at most `most`."""
    score = {i: sum(why.values()) for i, why in signs.items() if sum(why.values()) >= threshold}
    for i in sorted(score, key=lambda i: (-score[i], i)):
        if i in score:
            for k in (i - 1, i + 1):
                if k in score and (score[k], -k) < (score[i], -i):
                    del score[k]
    cuts = sorted(score)
    while len(cuts) + 1 > most > 0:         # too many: the weakest goes, of equals the one between the two shortest parts
        edges = [0] + cuts + [n]
        cuts.remove(min(cuts, key=lambda i: (score[i], edges[edges.index(i) + 1] - edges[edges.index(i) - 1], i)))
    return [0] + cuts


# --- difficulty ---

def _bpm(piece: dict, i: int) -> float | None:
    marked = [bpm for bar, bpm in sorted(piece.get("tempi") or []) if bar <= i + 1]
    return float(marked[-1]) if marked else None


def _difficulty(piece: dict, b: _Bars, first: int, last: int, known: set[int]) -> dict:
    """How hard bars first..last (indices) are, from what the data holds. Points are this project's own scale."""
    rows = range(first, last + 1)
    quarters = sum(float(b.bars[i]["length"]) for i in rows) or 1.0
    notes = sum(b.notes[i] for i in rows)
    seconds = sum(float(b.bars[i]["length"]) * 60.0 / bpm for i in rows if (bpm := _bpm(piece, i)))
    timed = all(_bpm(piece, i) for i in rows)
    chord = max((len(steps) for i in rows for staff, _ in HANDS for steps in b.raw[i][staff].values()), default=0)
    tight = [b.bars[i]["n"] for i in rows if b.bars[i]["n"] in (piece.get("two_hands") or {}).get("tight_bars", [])]
    trills = sum(1 for i in rows if any(m["mark"] == "trill" for m in b.bars[i].get("marks", [])))
    graces = sum(1 for i in rows for m in b.bars[i].get("marks", []) if m["mark"] == "grace")
    doubtful = [b.bars[i]["n"] for i in rows if b.bars[i]["n"] in (piece.get("checked") or {}).get("doubtful_bars", [])]
    repeated = sum(1 for i in rows if i in known)
    rate = notes / seconds if timed and seconds else notes / quarters
    limits = (2.0, 4.0, 7.0) if timed else (1.5, 3.0, 5.0)
    points = sum(rate >= x for x in limits) + (chord >= 4) + (chord >= 5) + bool(tight) + (len(tight) * 3 >= len(rows)) + bool(trills)
    size = last - first + 1
    points += (size - repeated) / size >= 0.7 and size >= 2
    points -= repeated / size >= 0.8
    out = {"level": LEVELS[0 if points <= 0 else 1 if points <= 2 else 2 if points <= 4 else 3], "points": int(points),
           ("notes_per_second" if timed else "notes_per_beat"): round(rate, 1), "largest_chord": chord}
    for key, value in (("tight_bars", tight), ("trill_bars", trills), ("grace_notes", graces), ("doubtful_bars", doubtful)):
        if value:
            out[key] = value
    if repeated:
        out["repeats_earlier"] = f"{repeated} of {size} bars"
    return out


def _difficulty_words(d: dict) -> str:
    said = [f"{d['notes_per_second']:.1f} notes a second" if "notes_per_second" in d else f"{d['notes_per_beat']:.1f} notes a beat"]
    if d["largest_chord"] >= 4:
        said.append(f"chords of {d['largest_chord']} notes")
    if d.get("tight_bars"):
        said.append(f"{_spans(_ranges(d['tight_bars']))} too wide for one hand")
    return f"{d['level']} ({', '.join(said)})"


def _ranges(numbers: list[int]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for n in sorted(set(numbers)):
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return [(a, z) for a, z in out]


# --- the outline ---

def build(piece: dict, interval: Callable[[int], str] | None = None) -> dict | None:
    """The outline of a piece in two staves (None without bars). `interval` names a number of steps
    of the piece's tuning ("minor third"); without it sizes are given in steps only."""
    bars = piece.get("score") or []
    if not bars:
        return None
    b = _Bars(bars)
    n = b.n
    number = [bar["n"] for bar in bars]
    interval = namer(interval, piece.get("tuning"))

    def alike(i: int, j: int) -> float:
        return b.relation(min(i, j), max(i, j))["alike"] if i != j else 1.0

    patterns = _patterns(b)
    # what each bar repeats: its pattern's first statement, else the most alike earlier bar
    source: dict[int, tuple[int, dict]] = {}
    in_pattern: dict[int, str] = {}
    for p in patterns:
        for k in range(p["length"]):
            in_pattern[p["at"] + k] = p["name"]
        for j, _ in p["seen"]:
            for k in range(p["length"]):
                in_pattern[j + k] = p["name"]
                if b.notes[j + k]:
                    source[j + k] = (p["at"] + k, b.relation(p["at"] + k, j + k))
    for j in range(1, n):
        if j in source or not b.notes[j]:
            continue
        follow = source[j - 1][0] + 1 if j - 1 in source and source[j - 1][0] + 1 < j else None
        best = max(range(j), key=lambda i: (round(alike(i, j), 3) + (0.001 if i == follow else 0.0), -i))
        if alike(best, j) >= REPEAT and b.notes[best]:
            source[j] = (best, b.relation(best, j))
    known = set(source)

    section_signs, phrase_signs = _signs(piece, b, patterns, source, alike)
    starts = _cut(section_signs, n, BOUNDARY, min(MAX_SECTIONS, max(3, n // 4)))
    # a section longer than MAX_SECTION_BARS is cut again at its strongest lesser sign (those of the phrases count half)
    lesser = {i: sum(section_signs.get(i, {}).values()) + 0.5 * sum(phrase_signs.get(i, {}).values()) for i in set(section_signs) | set(phrase_signs)}
    while len(starts) < MAX_SECTIONS + 2:
        edges = starts + [n]
        long = [(a, z) for a, z in zip(edges, edges[1:]) if z - a > MAX_SECTION_BARS]
        inner = [(lesser[i], -abs(i - (a + z) / 2), i) for a, z in long for i in range(a + 4, z - 3) if lesser.get(i, 0.0) >= 1.0]
        if not inner:
            break
        starts = sorted(starts + [max(inner)[2]])
    # a section of one or two bars joins the one before it (the last bar of a slowing, a link) unless its sign is strong
    starts = [s for k, s in enumerate(starts) if s == 0 or (starts[k + 1] if k + 1 < len(starts) else n) - s >= 3
              or sum(section_signs.get(s, {}).values()) >= (3 if (starts[k + 1] if k + 1 < len(starts) else n) - s == 2 else 4)]
    ends = [s - 1 for s in starts[1:]] + [n - 1]

    def likeness(first: tuple[int, int], second: tuple[int, int]) -> float:
        if not any(b.notes[j] for j in range(second[0], second[1] + 1)):
            return 0.0
        each = [max(alike(i, j) for i in range(first[0], first[1] + 1)) for j in range(second[0], second[1] + 1)]
        return sum(each) / max(len(each), first[1] - first[0] + 1)

    labels: list[str] = []
    letters: list[tuple[str, int]] = []         # letter, index of the section that first has it
    primes: dict[str, int] = {}
    like: dict[int, int] = {}
    for k, (first, last) in enumerate(zip(starts, ends)):
        scores = [(likeness((starts[m], ends[m]), (first, last)), -m) for _, m in letters]
        top = max(scores, default=(0.0, 0))
        if top[0] >= 0.5:
            letter = next(letter for letter, m in letters if m == -top[1])
            like[k] = -top[1]
            if top[0] >= 0.9:
                labels.append(letter)
            else:
                primes[letter] = primes.get(letter, 0) + 1
                labels.append(letter + "'" * primes[letter])
        else:
            letter = chr(ord("A") + len(letters)) if len(letters) < 26 else f"S{len(letters) + 1}"
            letters.append((letter, k))
            labels.append(letter)

    def cut_phrases(first: int, last: int) -> list[tuple[int, int]]:
        signs = {i: why for i, why in phrase_signs.items() if first < i <= last}
        cuts = _cut(signs, n, PHRASE, n)[1:]
        edges = [first] + cuts + [last + 1]
        k = 0
        while k + 1 < len(edges):              # no phrase longer than MAX_PHRASE bars
            if edges[k + 1] - edges[k] > MAX_PHRASE:
                inner = [i for i in range(edges[k] + 2, edges[k + 1] - 1)]
                middle = (edges[k] + edges[k + 1]) / 2
                at = max(inner, key=lambda i: (sum(signs.get(i, {}).values()), -abs(i - middle), -i))
                edges.insert(k + 1, at)
            else:
                k += 1
        k = 1
        while k + 1 < len(edges) and len(edges) > 2:    # a phrase of one bar joins a neighbour unless both its ends are strong
            if edges[k + 1] - edges[k] == 1 or (k == 1 and edges[1] - edges[0] == 1):
                left = k if edges[k + 1] - edges[k] == 1 else 0
                a, z = edges[left], edges[left + 1]
                strength = [sum(signs.get(x, {}).values()) if first < x <= last else 9.0 for x in (a, z)]
                if min(strength) < 2.0:
                    drop = a if (strength[0] <= strength[1] and a != first) or z == last + 1 else z
                    if drop not in (first, last + 1) and all(y - x <= MAX_PHRASE for x, y in zip([e for e in edges if e != drop], [e for e in edges if e != drop][1:])):
                        edges.remove(drop)
                        continue
            k += 1
        return [(x, y - 1) for x, y in zip(edges, edges[1:])]

    density = sorted(b.notes[i] / float(bars[i]["length"]) for i in range(n) if b.notes[i] and float(bars[i]["length"]))
    usual = density[len(density) // 2] if density else 0.0

    def describe(k: int, first: int, last: int) -> str:
        rows = range(first, last + 1)
        said: list[str] = []
        for p in patterns:
            mine = [s for s in [p["at"]] + [j for j, _ in p["seen"]] if first <= s <= last]
            if not mine:
                continue
            unit = f"{p['length']}-bar pattern" if p["length"] > 1 else "one-bar pattern"
            if p["at"] in mine:
                said.append(f"{'the opening' if p['at'] <= 1 else 'a new'} {unit} {p['name']} ({_span(number[p['at']], number[p['at'] + p['length'] - 1])})"
                            + (f", {len(mine)} times" if len(mine) > 1 else ""))
            else:
                kinds = {r["kind"] for j, r in p["seen"] if j in mine}
                how = "unchanged" if kinds == {"same"} else "transposed" if kinds == {"transposed"} else "varied" if "same" not in kinds else "partly varied"
                said.append(f"pattern {p['name']} returns {how}" + (f", {len(mine)} times" if len(mine) > 1 else ""))
        if len(said) > 3:
            said[3:] = [f"and {len(said) - 3} more patterns"]
        loose = [i for i in rows if i not in in_pattern and b.notes[i]]
        if loose:
            old = [i for i in loose if i in known and source[i][0] < first]
            if not said:
                said.append("material of its own" if not old else "mostly earlier bars again" if len(old) * 2 > len(loose) else "partly new, partly earlier bars again")
            elif len(loose) * 3 >= len(rows):
                said.append("with bars of its own")
        if patterns and loose:
            main = patterns[0]
            echo = [number[i] for i in loose if any(
                0.25 <= (r := b.relation(main["at"] + k, i))["alike"] and "different" not in (r["right"]["kind"], r["left"]["kind"])
                for k in range(main["length"]) if main["at"] + k < i)]
            if len(echo) >= 2:
                said.append(f"{_spans(_ranges(echo))} keep the rhythm of pattern {main['name']} on other notes")
        if k in like and not any("returns" in s for s in said):
            said.append(f"like section {like[k] + 1}")
        if any(m["mark"] == "trill" for i in rows for m in bars[i].get("marks", [])):
            said.append("trills")
        mine = sum(b.notes[i] for i in rows) / (sum(float(bars[i]["length"]) for i in rows) or 1.0)
        if usual and mine >= 1.8 * usual:
            said.append("many notes")
        elif usual and mine <= 0.5 * usual:
            said.append("few notes")
        loud = [m.get("value") for i in rows for m in bars[i].get("expression", []) if m["type"] == "dynamic" and m.get("value") in DYNAMICS
                and m.get("hand") in ("right", "both")]
        if loud:
            said.append(loud[0] + (f" to {loud[-1]}" if loud[-1] != loud[0] else ""))
        slow = [m for i in rows for m in bars[i].get("expression", []) if m["type"] == "tempo" and m.get("value") in ("ritardando", "rallentando", "ritenuto")]
        tempi = [bpm for i in rows if (bpm := _bpm(piece, i))]
        if slow or (len(tempi) >= 2 and tempi[-1] < 0.9 * tempi[0]):
            said.append("slowing down")
        if first and bars[first]["time"] != bars[first - 1]["time"] and len({bars[i]["time"] for i in rows}) == 1:
            said.append(f"in {bars[first]['time']}")
        return "; ".join(said)

    sections = []
    for k, (first, last) in enumerate(zip(starts, ends)):
        why = sorted(section_signs.get(first, {}), key=lambda w: -section_signs[first][w]) if first else []
        sections.append({"n": k + 1, "label": labels[k], "bars": [number[first], number[last]], "says": describe(k, first, last),
                         **({"begins_at": why} if why else {}),
                         "phrases": [[number[x], number[y]] for x, y in cut_phrases(first, last)],
                         "difficulty": _difficulty(piece, b, first, last, known)})

    out_patterns = []
    for p in patterns:
        out_patterns.append({"name": p["name"], "bars": [number[p["at"]], number[p["at"] + p["length"] - 1]],
                             "returns": [{"bars": [number[j], number[j + p["length"] - 1]], **{k: v for k, v in r.items() if k != "alike"}}
                                         for j, r in p["seen"]]})
    repeats = {str(number[j]): {"of": number[i], **{k: v for k, v in r.items() if k != "alike"}} for j, (i, r) in sorted(source.items())}

    # the repeat map in words: patterns with their returns, then runs of other bars that repeat earlier ones
    lines: list[str] = []
    for p in out_patterns:
        groups: dict[str, list] = {}
        for r in p["returns"]:
            groups.setdefault(relation_words(r, interval), []).append(tuple(r["bars"]))
        lines.append(f"pattern {p['name']} = {_span(*p['bars'])}; " + "; ".join(
            f"{_spans(where, 10)}: {words}" for words, where in groups.items()))
    runs: list[list] = []
    for j, (i, r) in sorted(source.items()):
        if j in in_pattern:
            continue
        if not {r["right"]["kind"], r["left"]["kind"]} & {"same", "transposed", "ornamented"}:
            continue                # both hands only varied: said with the bar, too weak for the map
        words = relation_words(r, interval)
        if runs and runs[-1][1] == j - 1 and runs[-1][3] == i - 1 and runs[-1][4] == words:
            runs[-1][1], runs[-1][3] = j, i
        else:
            runs.append([j, j, i, i, words])
    for first, last, a, z, words in runs:
        lines.append(f"{_span(number[first], number[last])} = {_span(number[a], number[z])}" + ("" if words == "the same notes" else f": {words}"))

    out = {"made": MADE, "sections": sections, "patterns": out_patterns, "repeats": repeats, "repeat_map": lines}
    out["practice_order"] = _practice(piece, b, out, patterns, in_pattern, known, starts, interval)
    return out


def _practice(piece: dict, b: _Bars, out: dict, patterns: list[dict], in_pattern: dict, known: set[int], starts: list[int], interval) -> list[str]:
    """Pattern first (where it has fewest notes), its returns, its transpositions and variants, then what
    occurs once, hardest last; hands separately where a hand has more than it reaches."""
    number = [bar["n"] for bar in b.bars]
    tight = set((piece.get("two_hands") or {}).get("tight_bars", []))
    steps: list[str] = []

    def hands(first: int, last: int) -> str:
        hit = [n for n in range(first, last + 1) if n in tight]
        return f" Hands separately: in {_spans(_ranges(hit))} one hand has more than it reaches." if hit else ""

    lesser: list[str] = []
    for p, shown in zip(patterns, out["patterns"]):
        length = p["length"]
        exact = [p["at"]] + [j for j, r in p["seen"] if r["kind"] in ("same", "transposed")]
        easiest = min(exact, key=lambda j: (sum(b.notes[j:j + length]), j))
        a, z = number[easiest], number[easiest + length - 1]
        others = [r for r in shown["returns"] if r["bars"][0] != a] + ([{"bars": shown["bars"], "kind": "same"}] if easiest != p["at"] else [])
        if p is not patterns[0]:        # the lesser patterns: one step for all, the repeat map has the details
            lesser.append(f"{p['name']} ({_span(a, z)}; again in {_spans(sorted(tuple(r['bars']) for r in others), 6)})")
            continue
        steps.append(f"Learn pattern {p['name']} first, {_span(a, z)}" + (" (where it has fewest notes)" if easiest != p["at"] else "")
                     + ": each hand alone, then together." + hands(a, z))
        same = sorted(tuple(r["bars"]) for r in others if r["kind"] == "same")
        if same:
            steps.append(f"It comes back unchanged in {_spans(same)}: nothing new to learn.")
        moved = [r for r in others if r["kind"] == "transposed"]
        if moved:
            steps.append("Then its transpositions, the same hand shape on other keys: " + "; ".join(
                f"{_span(*r['bars'])} ({_steps_words(r['shift'], interval)})" for r in moved[:6]) + (f"; and {len(moved) - 6} more" if len(moved) > 6 else "") + ".")
        varied = [r for r in others if r["kind"] == "hands"]
        if varied:
            steps.append("Then its variants: " + "; ".join(f"{_span(*r['bars'])} ({relation_words(r, interval)})" for r in varied[:3])
                         + (f"; and {len(varied) - 3} more" if len(varied) > 3 else "") + "." + "".join(dict.fromkeys(hands(*r["bars"]) for r in varied)))
    if lesser:
        steps.append("Then the other patterns, each where it first stands, then where it comes again (the repeats say how each differs): "
                     + "; ".join(lesser) + ".")
    # what is in no pattern, cut at the section boundaries; a bar or two with hardly a note is not a passage
    edges = set(starts)
    passages: list[list[int]] = []
    for i in range(b.n):
        if i in in_pattern or not b.notes[i] or out["repeats"].get(str(number[i]), {}).get("kind") in ("same", "transposed"):
            continue
        if passages and passages[-1][1] == i - 1 and i not in edges:
            passages[-1][1] = i
        else:
            passages.append([i, i])
    passages = [x for x in passages if sum(b.notes[x[0]:x[1] + 1]) >= 6]
    rated = sorted(((_difficulty(piece, b, first, last, known), first, last) for first, last in passages), key=lambda x: (x[0]["points"], x[1]))
    if rated:
        if len(rated) > 6:
            by_section = sorted(out["sections"], key=lambda s: (s["difficulty"]["points"], s["n"]))
            steps.append(("Then" if steps else "No recurring pattern was found. Learn") + " section by section, easiest first: " + "; ".join(
                f"{s['n']} ({_span(*s['bars'])}, {s['difficulty']['level']})" for s in by_section) + ".")
        else:
            steps.append(("Then the passages that are not a pattern" if steps else "No recurring pattern was found. Learn the passages")
                         + ", easiest first, hardest last: " + "; ".join(
                f"{_span(number[first], number[last])} ({d['level']})" for d, first, last in rated) + ".")
            hit = sorted(n for _, first, last in rated for n in range(number[first], number[last] + 1) if n in tight)
            if hit:
                steps[-1] += f" Hands separately where one hand has more than it reaches: {_spans(_ranges(hit))}."
    steps.append("Last, join the sections in their order and play the whole piece slowly.")
    return [f"{k}. {text}" for k, text in enumerate(steps, 1)]


def namer(interval: Callable[[int], str] | None, octave: int | None) -> Callable[[int], str] | None:
    """An interval namer that also knows how many steps an octave has (whole octaves are said as such)."""
    if not octave or getattr(interval, "octave", None):
        return interval

    def name(steps: int) -> str:
        return interval(steps) if interval else ""
    name.octave = int(octave)
    return name


# --- for the tutor ---

def overview(outline: dict) -> dict:
    """The outline as the tutor reads it: no notes, a line per section, the repeat map, the practice order."""
    sections = []
    for s in outline["sections"]:
        phrases = s["phrases"]
        line = f"{s['n']}. {s['label']}, {_span(*s['bars'])}: {s['says']}. {_difficulty_words(s['difficulty']).capitalize()}."
        if len(phrases) > 1:
            line += (" Phrases: " + ", ".join(_span(a, z, False) for a, z in phrases) + "." if len(phrases) <= 5 else f" {len(phrases)} phrases.")
        sections.append(line)
    lines = outline["repeat_map"]
    shown = lines[:12] + ([f"... and {len(lines) - 12} more: a bar fetched with library get says what it repeats"] if len(lines) > 12 else [])
    return {"made": outline["made"], "sections": sections,
            "repeats": shown or ["no bar repeats an earlier one closely"],
            "practice_order": outline["practice_order"],
            "how": "library get with section = its number gives its bars as steps (phrase = which phrase, if it is long). "
                   "A starting point; phrases are suggestions cut at whole bars."}


def find_section(outline: dict, section) -> dict:
    """The section with this number or label; ValueError says what there is."""
    text = str(section).strip()
    sections = outline["sections"]
    if text.isdigit() and 1 <= int(text) <= len(sections):
        return sections[int(text) - 1]
    named = [s for s in sections if s["label"].lower() == text.lower()]
    if len(named) == 1:
        return named[0]
    listing = ", ".join(f"{s['n']} ({s['label']}, {_span(*s['bars'])})" for s in sections)
    if named:
        raise ValueError(f"several sections are labelled {named[0]['label']}: give the number. Sections: {listing}")
    raise ValueError(f"there is no section '{section}'. Sections: {listing}")


def bar_words(outline: dict, bar: int, interval: Callable[[int], str] | None = None, part: str = "both",
              scale: Callable[[int], int] | None = None) -> str | None:
    """What a bar repeats, in words, for the hand(s) asked for; None if nothing worth saying.
    `scale` converts steps of the piece's tuning to those of the keyboard's."""
    r = outline["repeats"].get(str(bar))
    if not r:
        return None
    if scale:
        r = {k: ({**v, "shift": scale(v["shift"])} if isinstance(v, dict) and "shift" in v else scale(v) if k == "shift" else v) for k, v in r.items()}
    if part in ("upper", "lower"):
        hand = r["right" if part == "upper" else "left"]
        if hand["kind"] in ("different", "rest", "rhythm", "direction"):
            return None
    words = relation_words(r, interval, part)
    return f"bar {bar}: " + ("the same notes as" if words == "the same notes" else "like") + f" bar {r['of']}" + ("" if words == "the same notes" else f", {words}")
