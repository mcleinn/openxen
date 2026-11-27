"""Expression marks of a printed score (dynamics, crescendo and diminuendo, tempo words, pedal,
accents, fermatas, slurs) as the library carries them, and what the tutor does with them: say
them (`words`, `overview`) and play them (`Performance`, used by `play_piece`).

A bar of a piece in two staves may hold `"expression"`: a list of marks that START in it,

    {"type", "beat", "hand", "value"?, "text"?, "hairpin"?, "to"?}

    type   dynamic | crescendo | diminuendo | tempo | pedal | articulation | fermata | slur | expression
    beat   quarter notes from the barline (0 = the first beat)
    hand   "right" | "left" | "both": the staff the mark stands at
    value  the mark in a fixed vocabulary (dynamic: ppp..fff, mezzo, sf ...; tempo: rallentando,
           ritardando, accelerando, a tempo; pedal: down, simile; articulation: accent, staccato,
           tenuto, marcato, staccatissimo; expression: simile ...)
    text   the printed words, verbatim ("diminuendo poco a poco", "rallent. molto", "Ped.")
    to     [bar, beat] where a span ends (hairpin, "cresc. - - -", pedal to its release, "rall. - - -",
           the last note under a slur); the bar after the last one = the end of the piece

and the piece `"expression"`: {"kinds": {type: how many}, "from": where the marks were read}.

What `Performance` assumes (kept modest; `play_piece` reports it):

  loudness  key velocity by dynamic: ppp 28, pp 40, p 52, mp 64, mezzo 70, mf 76, f 90, ff 104, fff 116,
            per hand (a mark for both hands sets both); 70 before the first mark. "più f" / "meno f" move
            the level in force by 8. A crescendo or diminuendo (hairpin or words) is a straight ramp from
            the level in force to the next dynamic of that hand if it stands within a quarter note after
            the end of the span and lies in the right direction, otherwise one level (12) up or down; the
            level reached holds until the next dynamic. sf, sfz, fz, rf and an accent add 14 to the notes
            at that moment, a marcato 18. A piece without any dynamic keeps the tutor's plain loudness.
  tempo     ritardando / rallentando: the tempo falls in a straight line to 70 % of the tempo in force at
            the end of the span ("molto": 55 %, "poco": 85 %); accelerando: rises to 130 %. The span ends
            where the print ends it (dashes), else at the next tempo word if that comes within two bars,
            else at the end of the bar. After the span the tempo is the marked one again, with or without
            a printed "a tempo". A word is NOT applied where the piece's own metronome marks already
            change in the bars of the span (an engraver who wrote the slowing out in numbers).
  fermata   the moment under it lasts twice as long.
  staccato  half the length; staccatissimo a quarter.
  pedal, tenuto, slurs: said, not played.
"""
from __future__ import annotations

LEVELS = {"ppp": 28, "pp": 40, "p": 52, "mp": 64, "mezzo": 70, "mf": 76, "f": 90, "ff": 104, "fff": 116}
DEFAULT_LEVEL = 70
STEP = 12                       # one dynamic level
ACCENTS = {"accent": 14, "marcato": 18}
SHORT = {"staccato": 0.5, "staccatissimo": 0.25}
SLOWER = ("ritardando", "rallentando", "ritenuto")
HANDS = {"upper": ("right", "both"), "lower": ("left", "both"), "both": ("right", "left", "both")}
GLOSS = {"rallentando": "slow down gradually", "ritardando": "slow down gradually", "ritenuto": "hold back",
         "accelerando": "speed up gradually", "a tempo": "back to the tempo", "mezzo": "between mp and mf",
         "simile": "go on in the same way"}
KIND_WORDS = {"dynamic": "dynamics", "crescendo": "crescendo", "diminuendo": "diminuendo", "tempo": "tempo words",
              "pedal": "pedal marks", "articulation": "accents and other articulation", "fermata": "fermatas",
              "slur": "slurs", "expression": "other words"}


def _starts(bars: list) -> list[float]:
    out, at = [], 0.0
    for bar in bars:
        out.append(at)
        at += float(bar["length"])
    return out + [at]


def _end(mark: dict, starts: list[float]) -> float | None:
    """Where a span ends, in quarter notes from the start of the piece."""
    if not mark.get("to"):
        return None
    bar, beat = mark["to"]
    return starts[min(max(int(bar), 1), len(starts)) - 1] + float(beat)


def _beat(beat: float) -> str:
    return f"{beat + 1:g}"


def overview(piece: dict) -> dict | None:
    """What kinds of marks the piece carries, for the piece overview."""
    info = piece.get("expression")
    if not info or not info.get("kinds"):
        return None
    kinds = ", ".join(f"{KIND_WORDS.get(k, k)} ({n})" for k, n in info["kinds"].items())
    out = {"carries": kinds,
           "note": "the bars come with these marks in plain words (expression); play_piece plays the dynamics, the hairpins, "
                   "the tempo words and the fermatas. Teach the notes first, then the marks."}
    if info.get("from"):
        out["read_from"] = info["from"]
    return out


def words(bars: list, chosen: list, part: str = "both") -> list[str]:
    """The marks of the bars `chosen` (some of `bars`, in order) in words the tutor can say."""
    if not chosen:
        return []
    starts = _starts(bars)
    index = {id(bar): i for i, bar in enumerate(bars)}
    first, last = index[id(chosen[0])], index[id(chosen[-1])]
    wanted = HANDS.get(part, HANDS["both"])
    said: list[str] = []

    def where(i: int, mark: dict, hand: bool = True) -> str:
        out = f"bar {bars[i]['n']}"
        if float(mark["beat"]):
            out += f", beat {_beat(float(mark['beat']))}"
        if hand and mark.get("hand") in ("right", "left"):
            out += f", {mark['hand']} hand"
        return out

    def until(i: int, mark: dict) -> str:
        if not mark.get("to"):
            return ""
        bar, beat = int(mark["to"][0]), float(mark["to"][1])
        if bar > len(bars):
            return " to the end"
        number = bars[bar - 1]["n"]
        if bar - 1 == i:
            return f" to beat {_beat(beat)}"
        if not beat:
            return " to the next bar" if bar - 1 == i + 1 else f" to bar {number}"
        return f" to bar {number}, beat {_beat(beat)}"

    # spans that began before the first bar asked for and still run in it
    for i in range(first):
        for mark in bars[i].get("expression", []):
            end = _end(mark, starts)
            if end is None or end <= starts[first] + 1e-9 or mark.get("hand", "both") not in wanted or mark["type"] == "slur":
                continue
            whole = end >= starts[first + 1] - 1e-9
            if mark["type"] == "pedal":
                said.append("pedal: hold through the bar" if whole else f"pedal: held from bar {bars[i]['n']}, lift{until(first, mark).replace(' to ', ' at ')}")
            elif mark["type"] in ("crescendo", "diminuendo", "tempo"):
                name = mark.get("text") or mark["type"]
                said.append(f"bar {bars[first]['n']}: {name} goes on (from bar {bars[i]['n']}){until(first, mark)}")
    for i in range(first, last + 1):
        grouped: dict[tuple, list[str]] = {}
        for mark in sorted(bars[i].get("expression", []), key=lambda m: float(m["beat"])):
            if mark.get("hand", "both") not in wanted:
                continue
            kind, value, text = mark["type"], mark.get("value", ""), mark.get("text", "")
            gloss = f" ({GLOSS[value]})" if value in GLOSS else ""
            if kind == "dynamic":
                said.append(f"{where(i, mark)}: {text or value}{gloss}")
            elif kind in ("crescendo", "diminuendo"):
                named = kind if mark.get("hairpin") or not text else (text if text.lower().startswith(kind[:4]) else f"{kind} ({text})")
                said.append(f"{where(i, mark)}: {named}{until(i, mark)}")
            elif kind == "tempo":
                said.append(f"{where(i, mark, hand=False)}: {text or value}{gloss}{until(i, mark)}")
            elif kind == "pedal":
                if value == "simile":
                    said.append(f"{where(i, mark, hand=False)}: pedal as before (simile)")
                else:
                    said.append(f"{where(i, mark, hand=False)}: pedal down" + (f" ({text})" if text else "")
                                + until(i, mark).replace(" to ", ", lift at ", 1).replace("lift at the end", "hold to the end"))
            elif kind == "articulation":
                key = (f"bar {bars[i]['n']}" + (f", {mark['hand']} hand" if mark.get("hand") in ("right", "left") else ""), value)
                grouped.setdefault(key, []).append(_beat(float(mark["beat"])))
            elif kind == "fermata":
                said.append(f"{where(i, mark)}: fermata (hold it longer)")
            elif kind == "slur":
                said.append(f"{where(i, mark)}: slur{until(i, mark)}")
            else:
                said.append(f"{where(i, mark)}: {text or value}{gloss}")
        for (place, value), beats in grouped.items():
            said.append(f"{place}: {value} on beat{'s' if len(beats) > 1 else ''} {', '.join(dict.fromkeys(beats))}")
    return list(dict.fromkeys(said))


class Performance:
    """Loudness, tempo and length that the marks of a piece ask for (assumptions: the module docstring)."""

    def __init__(self, piece: dict):
        self.bars = bars = piece.get("score") or []
        self.starts = starts = _starts(bars)
        self._index = {id(bar): i for i, bar in enumerate(bars)}
        marks = [(starts[i] + float(m["beat"]), i, m) for i, bar in enumerate(bars) for m in bar.get("expression", [])]
        marks.sort(key=lambda item: item[0])
        self.assumed: list[str] = []
        # loudness: per hand, steps (time, level) and ramps (from, to, level, level)
        self._steps: dict[str, list[tuple[float, float]]] = {"right": [], "left": []}
        self._ramps: dict[str, list[tuple[float, float, float, float]]] = {"right": [], "left": []}
        self._bump: dict[tuple[str, float], int] = {}
        self._short: dict[tuple[str, float], float] = {}
        self.dynamics = any(m["type"] in ("dynamic", "crescendo", "diminuendo") for _, _, m in marks)
        for hand in ("right", "left"):
            mine = [(t, m) for t, _, m in marks if m.get("hand", "both") in (hand, "both")]
            levels = [(t, m) for t, m in mine if m["type"] == "dynamic"]
            for t, m in mine:
                value, text = m.get("value", ""), (m.get("text") or "").lower()
                if m["type"] == "dynamic":
                    now = self._level(hand, t)
                    if text.startswith(("più", "piu", "meno")) and value in LEVELS:
                        louder = (LEVELS[value] >= DEFAULT_LEVEL) == text.startswith(("più", "piu"))
                        self._steps[hand].append((t, min(120.0, max(20.0, now + (8 if louder else -8)))))
                    elif value in LEVELS:
                        self._steps[hand].append((t, float(LEVELS[value])))
                    else:                       # sf, sfz, fz, rf, fp ...: a stress on this moment
                        self._bump[(hand, round(t, 4))] = max(self._bump.get((hand, round(t, 4)), 0), ACCENTS["accent"])
                        if value.endswith("p") and value[:-1] in ("f", "sf"):
                            self._steps[hand].append((t + 1e-6, float(LEVELS["p"])))
                elif m["type"] in ("crescendo", "diminuendo"):
                    end = _end(m, starts)
                    if end is None or end <= t:
                        continue
                    up = m["type"] == "crescendo"
                    now = self._level(hand, t)
                    goal = next((float(LEVELS[d["value"]]) for dt, d in levels if end - 0.01 <= dt <= end + 1.0 and d.get("value") in LEVELS
                                 and not (d.get("text") or "").lower().startswith(("più", "piu", "meno"))), None)
                    if goal is None or (goal > now) != up:
                        goal = min(120.0, max(20.0, now + (STEP if up else -STEP)))
                    self._ramps[hand].append((t, end, now, goal))
                    self._steps[hand].append((end, goal))
                elif m["type"] == "articulation" and value in ACCENTS:
                    self._bump[(hand, round(t, 4))] = max(self._bump.get((hand, round(t, 4)), 0), ACCENTS[value])
                elif m["type"] == "articulation" and value in SHORT:
                    self._short[(hand, round(t, 4))] = SHORT[value]
        if self.dynamics:
            self.assumed.append("dynamics as key velocity (pp 40, p 52, mp 64, mf 76, f 90, ff 104), crescendo and diminuendo as straight ramps")
        # tempo: stretches (from, to, share of the tempo reached at the end), fermatas (from, to)
        self._stretch: list[tuple[float, float, float]] = []
        self._held: list[tuple[float, float]] = []
        tempo_marks = [(t, i, m) for t, i, m in marks if m["type"] == "tempo"]
        tempi = sorted(piece.get("tempi") or [])
        changes = [starts[n - 1] for k, (n, bpm) in enumerate(tempi) if k and 1 <= n <= len(bars) and bpm != tempi[k - 1][1]]
        for t, i, m in tempo_marks:
            value, text = m.get("value", ""), (m.get("text") or "").lower()
            if value not in SLOWER and value != "accelerando":
                continue
            end = _end(m, starts)
            if end is None:
                later = [t2 for t2, _, _ in tempo_marks if t2 > t + 1e-9]
                two_bars = starts[min(i + 2, len(bars))] + (t - starts[i])
                end = later[0] if later and later[0] <= two_bars else starts[i + 1]
            if end <= t:
                continue
            if any(starts[i] - 1e-9 <= c < end - 1e-9 for c in changes):
                self.assumed.append(f"bar {bars[i]['n']}: \"{m.get('text') or value}\" is already in the piece's metronome marks, not slowed again")
                continue
            share = 1.3 if value == "accelerando" else 0.55 if "molto" in text else 0.85 if "poco" in text else 0.7
            self._stretch.append((t, end, share))
            self.assumed.append(f"bar {bars[i]['n']}: \"{m.get('text') or value}\" as a straight change to {share:.0%} of the tempo "
                                f"over {end - t:g} quarter notes, then the marked tempo again")
        for t, i, m in marks:
            if m["type"] == "fermata":
                lengths = [float(d) for events in bars[i]["staves"].values() for b, d, _ in events if abs(float(b) - float(m["beat"])) < 1e-6]
                length = min(min(lengths, default=1.0), starts[i + 1] - t) or 1.0
                if (t, t + length) not in self._held:
                    self._held.append((t, t + length))
        if self._held:
            self.assumed.append("a fermata doubles the length of its moment")
        self.timed = bool(self._stretch or self._held)

    # --- loudness ---

    def _level(self, hand: str, t: float) -> float:
        for a, b, v0, v1 in self._ramps[hand]:
            if a <= t < b:
                return v0 + (v1 - v0) * (t - a) / (b - a)
        before = [(when, k, v) for k, (when, v) in enumerate(self._steps[hand]) if when <= t + 1e-9]
        return max(before)[2] if before else float(DEFAULT_LEVEL)     # the latest in time; of two at one moment the one entered last

    def velocity(self, bar: dict, beat: float, staff: str) -> int | None:
        """Key velocity of a note of `staff` ("upper" | "lower") at `beat` of `bar`; None if the piece has no dynamics."""
        hand = "right" if staff == "upper" else "left"
        t = self.starts[self._index[id(bar)]] + float(beat)
        bump = self._bump.get((hand, round(t, 4)), 0)
        if not self.dynamics and not bump:
            return None
        base = self._level(hand, t) if self.dynamics else (84 if staff == "upper" else 68)
        return int(round(min(127.0, max(1.0, base + bump))))

    # --- time ---

    def _slow(self, t: float) -> float:
        factor = 1.0
        for a, b, share in self._stretch:
            if a <= t < b:
                factor /= 1.0 - (1.0 - share) * (t - a) / (b - a)
        for a, b in self._held:
            if a <= t < b:
                factor *= 2.0
        return factor

    def _span(self, a: float, b: float) -> float:
        """Quarter notes from a to b, stretched by ritardandi and fermatas."""
        if not self.timed or b <= a:
            return max(0.0, b - a)
        total, at = 0.0, a
        while at < b - 1e-9:
            step = min(0.0625, b - at)
            total += step * self._slow(at + step / 2)
            at += step
        return total

    def seconds(self, bar: dict, beat: float, quarter: float) -> float:
        """Seconds from the barline of `bar` to `beat`, a quarter note lasting `quarter` seconds at the marked tempo."""
        start = self.starts[self._index[id(bar)]]
        return self._span(start, start + float(beat)) * quarter

    def held(self, bar: dict, beat: float, dur: float, staff: str, quarter: float) -> float:
        """Seconds a note of length `dur` (quarter notes) sounds."""
        start = self.starts[self._index[id(bar)]] + float(beat)
        short = self._short.get(("right" if staff == "upper" else "left", round(start, 4)), 1.0)
        return self._span(start, start + float(dur)) * quarter * short
