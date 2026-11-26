"""Read a score PDF exported from MuseScore into a machine-readable score.

Such a PDF is not a picture: the notation is text in the SMuFL music font Bravura (one
private-use code point per symbol: notehead, clef, accidental, rest, flag ...) and the
lines are vector paths (staff lines, bar lines, stems, beams, ledger lines, ties). So the
score can be reconstructed from positions, without optical recognition:

* five long horizontal lines with equal spacing are a staff; staves joined by a bar line
  are a system (the first staff is "upper", the second "lower");
* a vertical line that spans a staff exactly and touches no notehead is a bar line, a
  vertical line touching noteheads is their stem; noteheads on one stem are a chord;
* the notehead's baseline is its staff position (0 = bottom line, +1 per half space);
  clef and position give letter and octave;
* duration = notehead type (whole / half / black), then flags (glyphs) or beams (filled
  quadrilaterals crossing the stem) halve it, augmentation dots lengthen it;
* an accidental glyph belongs to the next notehead to its right on the same height and
  holds for that staff position until the bar ends (and over a tie);
* two voices in a bar are told apart by stem direction when the events of the staff do
  not fit the bar one after the other; rests go to the voice in which the bar adds up.

Pitch numbers come from a `Notation`: steps of the tuning for the seven letters and for
every accidental code point (fractions are allowed, see `WEIGEL_16`), and the result has
to be a whole number of steps, otherwise the note is reported as uncertain.

Not read (listed in the output's "uncertain" or simply absent): tuplets, cross-staff
beams (every chord is read on the staff it is drawn on), octave lines, grace notes' time
(they are kept with duration 0), tremolo, arpeggio, pedal, dynamics, articulation, slurs.

    python host/tutor/scores/musescore_pdf.py score.pdf out.json [--edo 16]

Needs PyMuPDF (`pip install pymupdf`) for reading the PDF; everything else is plain Python
and is used by the tests without it.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import product
from pathlib import Path

# ---------------------------------------------------------------- SMuFL code points

NOTEHEADS = {
    0xE0A2: "whole", 0xE0A3: "half", 0xE0A4: "black",
    # Bravura's "oversized" noteheads, which MuseScore 4 uses by default
    0xF4BC: "whole", 0xF4BD: "half", 0xF4BE: "black",
}
RESTS = {  # code point -> quarter notes
    0xE4E2: Fraction(8), 0xE4E3: Fraction(4), 0xE4E4: Fraction(2), 0xE4E5: Fraction(1),
    0xE4E6: Fraction(1, 2), 0xE4E7: Fraction(1, 4), 0xE4E8: Fraction(1, 8), 0xE4E9: Fraction(1, 16),
}
WHOLE_REST = 0xE4E3            # alone in a voice it means "the whole bar"
FLAGS = {0xE240: 1, 0xE241: 1, 0xE242: 2, 0xE243: 2, 0xE244: 3, 0xE245: 3, 0xE246: 4, 0xE247: 4}
DOT = 0xE1E7
CLEFS = {  # code point -> (name, letter index and octave of the bottom staff line)
    0xE050: "treble", 0xE07A: "treble", 0xF472: "treble",
    0xE062: "bass", 0xE07C: "bass", 0xF474: "bass",
    0xE05C: "alto", 0xE07B: "alto", 0xF473: "alto",
}
TIME_DIGITS = {0xE080 + d: d for d in range(10)}
TIME_COMMON, TIME_CUT = 0xE08A, 0xE08B
REPEAT_DOTS = 0xE044
ACCIDENTAL_RANGE = (0xE260, 0xE49F)
ACCIDENTAL_BRACKETS = {0xE26A, 0xE26B, 0xE26C, 0xE26D}
NOTEHEAD_BRACKETS = {0xE0F5, 0xE0F6}
FERMATAS = {0xE4C0, 0xE4C1}

NATURAL = 0xE261
# code point -> (readable name, ASCII suffix used in note names)
ACCIDENTAL_NAMES = {
    0xE260: ("flat", "b"), 0xE261: ("natural", ""), 0xE262: ("sharp", "#"),
    0xE263: ("double-sharp", "x"), 0xE264: ("double-flat", "bb"),
    0xE270: ("flat-arrow-up", "b^"), 0xE271: ("flat-arrow-down", "bv"),
    0xE272: ("natural-arrow-up", "^"), 0xE273: ("natural-arrow-down", "v"),
    0xE274: ("sharp-arrow-up", "#^"), 0xE275: ("sharp-arrow-down", "#v"),
    0xE276: ("double-sharp-arrow-up", "x^"), 0xE277: ("double-sharp-arrow-down", "xv"),
    0xE278: ("double-flat-arrow-up", "bb^"), 0xE279: ("double-flat-arrow-down", "bbv"),
    0xE280: ("half-flat", "d"), 0xE281: ("sesquiflat", "db"),
    0xE282: ("half-sharp", "+"), 0xE283: ("sesquisharp", "#+"),
}

LETTERS = "CDEFGAB"
CLEF_BOTTOM_LINE = {"treble": 4 * 7 + 2, "bass": 2 * 7 + 4, "alto": 3 * 7 + 3}   # E4, G2, F3


def accidental_name(cp: int) -> str:
    return ACCIDENTAL_NAMES[cp][0] if cp in ACCIDENTAL_NAMES else f"U+{cp:04X}"


def accidental_suffix(cp: int) -> str:
    return ACCIDENTAL_NAMES[cp][1] if cp in ACCIDENTAL_NAMES else f"[U+{cp:04X}]"


# ---------------------------------------------------------------- pure parts

def staff_position(y: float, lines: list[float]) -> int:
    """Staff position of a notehead at height `y` (PDF coordinates, y grows downwards):
    0 = bottom line, 1 = first space, 8 = top line, negative below the staff. `lines` are
    the y of the five staff lines in any order; ledger lines continue the same grid."""
    ys = sorted(lines)
    half_space = (ys[-1] - ys[0]) / (2 * (len(ys) - 1))
    return round((ys[-1] - y) / half_space)


def position_error(y: float, lines: list[float]) -> float:
    """How far (in half spaces) `y` is from the grid of lines and spaces; 0.5 is the worst."""
    ys = sorted(lines)
    half_space = (ys[-1] - ys[0]) / (2 * (len(ys) - 1))
    exact = (ys[-1] - y) / half_space
    return abs(exact - round(exact))


def pitch_at(position: int, clef: str) -> tuple[str, int]:
    """Letter and octave (C4 = middle C) of a staff position under a clef."""
    diatonic = CLEF_BOTTOM_LINE[clef] + position
    return LETTERS[diatonic % 7], diatonic // 7


def note_duration(head: str, beams_or_flags: int = 0, dots: int = 0, stem: bool = True) -> Fraction:
    """Duration in quarter notes. `head` is "whole", "half" or "black"; a black notehead
    is a quarter, halved for every flag or beam; every dot adds half of the previous value."""
    if head == "whole":
        base = Fraction(4)
    elif head == "half":
        base = Fraction(2) if stem else Fraction(4)
    elif head == "black":
        base = Fraction(1, 2 ** beams_or_flags)
    else:
        raise ValueError(f"unknown notehead {head!r}")
    return dotted(base, dots)


def dotted(base: Fraction, dots: int) -> Fraction:
    return base * (2 - Fraction(1, 2 ** dots))


def bar_length(time: tuple[int, int]) -> Fraction:
    """Length of a bar in quarter notes, time = (beats, unit)."""
    return Fraction(4 * time[0], time[1])


def voice_sums(events: list[dict]) -> dict[int, Fraction]:
    """Sum of the durations per voice; events are dicts with "dur" and optional "voice"."""
    out: dict[int, Fraction] = {}
    for e in events:
        if e.get("grace"):
            continue
        v = e.get("voice", 1)
        out[v] = out.get(v, Fraction(0)) + Fraction(e["dur"]).limit_denominator(1024)
    return out


def bar_adds_up(events: list[dict], time: tuple[int, int]) -> bool:
    """True if every voice of the staff fills the bar exactly (an empty staff does not)."""
    sums = voice_sums(events)
    return bool(sums) and all(s == bar_length(time) for s in sums.values())


@dataclass(frozen=True)
class Notation:
    """How written notes map to steps of a tuning. `nominals`: steps of C D E F G A B above
    C; `accidentals`: code point -> steps; `offset` is added to everything. Values may be
    fractions: a notation borrowed from another tuning (as `WEIGEL_16`) is exact only for
    some spellings, and `step()` says so."""

    edo: int
    nominals: dict[str, Fraction]
    accidentals: dict[int, Fraction]
    offset: Fraction = Fraction(0)
    description: str = ""

    def step(self, letter: str, octave: int, accidentals: tuple[int, ...] = ()) -> tuple[int | None, str]:
        """Steps above C0 and "" - or (nearest step or None, reason) if the spelling does
        not land on a step or uses an accidental that is not in the table."""
        total = Fraction(self.nominals[letter]) + self.offset + self.edo * octave
        for cp in accidentals:
            if cp not in self.accidentals:
                return None, f"accidental {accidental_name(cp)} is not in the table"
            total += Fraction(self.accidentals[cp])
        if total.denominator != 1:
            return round(total), f"{float(total):.3f} is not a whole step"
        return int(total), ""


def notation_from_cents(edo: int, accidental_cents: dict[int, float], offset_cents: float = 0,
                        description: str = "") -> Notation:
    """Notation with the letters at their 12-tone places (C 0, D 200 ... B 1100 cents) and
    accidentals given in cents, expressed in steps of `edo`."""
    def steps(cents):
        return Fraction(cents).limit_denominator(1000) * edo / 1200
    nominal_cents = dict(zip(LETTERS, (0, 200, 400, 500, 700, 900, 1100)))
    return Notation(edo, {k: steps(v) for k, v in nominal_cents.items()},
                    {cp: steps(c) for cp, c in accidental_cents.items()}, steps(offset_cents), description)


# 16 equal steps as Stephen Weigel writes them in "Don't Take Five": ordinary 12-tone
# letters and sharps, an arrow = 25 cents, a quarter-tone sign = 50 cents. 75 cents (one
# step of 16) = 3 arrows, so only every third spelling exists, and the plain notes are
# D, F, G#, B (the four notes 16 and 12 have in common when B is shared). Counted from
# C the grid sits 25 cents low: step 0 = C lowered by an arrow, B = step 15.
WEIGEL_16 = notation_from_cents(16, {
    0xE261: 0, 0xE262: 100, 0xE260: -100, 0xE263: 200, 0xE264: -200,
    0xE272: 25, 0xE273: -25, 0xE274: 125, 0xE275: 75, 0xE270: -75, 0xE271: -125,
    0xE280: -50, 0xE281: -150, 0xE282: 50, 0xE283: 150,
}, offset_cents=25, description="12-tone letters, arrow = 25 cents, quarter-tone sign = 50 cents; "
   "step = (cents above C + 25) / 75, so D, F, G sharp and B are plain notes")

NOTATIONS = {16: WEIGEL_16}


# ---------------------------------------------------------------- raw material of a page

@dataclass
class Glyph:
    cp: int
    x: float          # origin (left edge of the symbol)
    y: float          # baseline = the staff height the symbol sits on
    size: float
    w: float = 0.0


@dataclass
class PageData:
    """What the reader needs from one page, independent of the PDF library."""
    glyphs: list[Glyph] = field(default_factory=list)
    hlines: list[tuple[float, float, float]] = field(default_factory=list)   # y, x0, x1
    vlines: list[tuple[float, float, float]] = field(default_factory=list)   # x, y0, y1
    quads: list[list[tuple[float, float]]] = field(default_factory=list)     # filled, 4 corners
    curves: list[dict] = field(default_factory=list)                          # x0 y0 x1 y1 bulge
    texts: list[dict] = field(default_factory=list)                           # text x y size font


def extract_page(page) -> PageData:
    """Glyphs and paths of one PyMuPDF page."""
    data = PageData()
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                plain = []
                for ch in span["chars"]:
                    cp = ord(ch["c"])
                    if cp >= 0xE000:
                        bb = ch["bbox"]
                        data.glyphs.append(Glyph(cp, ch["origin"][0], ch["origin"][1], span["size"], bb[2] - bb[0]))
                    else:
                        plain.append(ch)
                if plain and "".join(c["c"] for c in plain).strip():
                    data.texts.append({
                        "text": "".join(c["c"] for c in plain).strip(), "x": plain[0]["origin"][0],
                        "y": plain[0]["origin"][1], "size": span["size"], "font": span["font"],
                    })
    for g in page.get_drawings():
        items = g["items"]
        if g["type"] == "s" and len(items) == 1 and items[0][0] == "l":
            a, b = items[0][1], items[0][2]
            if abs(a.y - b.y) < 0.05:
                data.hlines.append((a.y, min(a.x, b.x), max(a.x, b.x)))
            elif abs(a.x - b.x) < 0.05:
                data.vlines.append((a.x, min(a.y, b.y), max(a.y, b.y)))
        elif g["type"] == "f" and len(items) == 4 and all(it[0] == "l" for it in items):
            data.quads.append([(it[1].x, it[1].y) for it in items])
        elif g["type"] == "f" and [it[0] for it in items] == ["c", "l", "c", "l"]:
            c = items[0]
            x0, y0, x1, y1 = c[1].x, c[1].y, c[4].x, c[4].y
            if x0 > x1:
                x0, y0, x1, y1 = x1, y1, x0, y0
            data.curves.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1,
                                "bulge": (c[2].y + c[3].y) / 2 - (y0 + y1) / 2})
    return data


# ---------------------------------------------------------------- layout

@dataclass
class Staff:
    lines: list[float]            # five y, top to bottom
    x0: float
    x1: float

    @property
    def top(self):
        return self.lines[0]

    @property
    def bottom(self):
        return self.lines[-1]

    @property
    def space(self):
        return (self.bottom - self.top) / 4

    def distance(self, y: float) -> float:
        return max(self.top - y, y - self.bottom, 0.0)


def find_staves(hlines: list[tuple[float, float, float]], min_length: float = 100.0) -> list[Staff]:
    """Groups of five long horizontal lines with equal spacing, top to bottom."""
    ys: list[tuple[float, float, float]] = []
    for y, x0, x1 in sorted(hlines):
        if x1 - x0 < min_length:
            continue
        if ys and abs(ys[-1][0] - y) < 0.3:
            ys[-1] = (ys[-1][0], min(ys[-1][1], x0), max(ys[-1][2], x1))
        else:
            ys.append((y, x0, x1))
    staves, i = [], 0
    while i + 4 < len(ys):
        five = ys[i:i + 5]
        gaps = [five[k + 1][0] - five[k][0] for k in range(4)]
        if max(gaps) - min(gaps) < 0.15 * max(gaps):
            staves.append(Staff([f[0] for f in five], min(f[1] for f in five), max(f[2] for f in five)))
            i += 5
        else:
            i += 1
    return staves


def group_systems(staves: list[Staff], vlines: list[tuple[float, float, float]]) -> list[list[Staff]]:
    """Staves joined by a vertical line (the line at the left of a system) form a system."""
    systems: list[list[Staff]] = []
    for s in staves:
        joined = systems and any(
            y0 <= systems[-1][-1].bottom + 0.6 and y1 >= s.top - 0.6 for _, y0, y1 in vlines)
        if joined:
            systems[-1].append(s)
        else:
            systems.append([s])
    return systems


def key_signature_run(clef_x: float, accidental_xs: list[float], space: float) -> tuple[float, float]:
    """x range of the key signature after the clef at `clef_x`: the accidentals that begin
    within 5 staff spaces of the clef and follow each other by less than 1.6 spaces.
    (0, -1) if there is none. Whether they are attached to notes is checked elsewhere."""
    run: list[float] = []
    for x in sorted(x for x in accidental_xs if x > clef_x):
        if (not run and x - clef_x <= 5 * space) or (run and x - run[-1] <= 1.6 * space):
            run.append(x)
        elif run or x - clef_x > 5 * space:
            break
    return (run[0], run[-1]) if run else (0.0, -1.0)


def beams_at(stem_x: float, y0: float, y1: float, quads: list[list[tuple[float, float]]]) -> list[int]:
    """Indices of the beams (filled quadrilaterals with two vertical sides) that the stem
    at `stem_x` from `y0` to `y1` runs into."""
    hits = []
    for i, q in enumerate(quads):
        xs = sorted(p[0] for p in q)
        xa, xb = xs[0], xs[-1]
        if xb - xa < 1.5 or not (xa - 0.7 <= stem_x <= xb + 0.7):
            continue
        left = [p[1] for p in q if abs(p[0] - xa) < 0.05]
        right = [p[1] for p in q if abs(p[0] - xb) < 0.05]
        if len(left) != 2 or len(right) != 2:
            continue
        t = min(max((stem_x - xa) / (xb - xa), 0.0), 1.0)
        mid = (sum(left) / 2) * (1 - t) + (sum(right) / 2) * t
        if y0 - 1.0 <= mid <= y1 + 1.0:
            hits.append(i)
    return hits


def split_voices(events: list[dict], length: Fraction) -> tuple[list[dict], bool]:
    """Give every event of one staff and bar a "voice" and a "beat".

    Events (in x order) have "x", "dur", "stem" (+1 up, -1 down, 0 none), "rest" (bool) and
    "y". One voice if the durations fill the bar one after the other; otherwise stems up
    are voice 1, stems down voice 2, and rests go where the bar adds up (the higher rest to
    voice 1 if there is a choice). Returns the events and whether every voice adds up."""
    timed = [e for e in events if not e.get("grace")]

    def lay_out(voices: list[int]) -> bool:
        clock = {}
        for e, v in zip(timed, voices):
            e["voice"] = v
            e["beat"] = 1 + clock.get(v, Fraction(0))
            clock[v] = clock.get(v, Fraction(0)) + e["dur"]
        return bool(clock) and all(t == length for t in clock.values())

    for e in timed:        # a whole rest alone in the bar or in its voice is a bar rest
        if e.get("bar_rest"):
            e["dur"] = length
    stems = {e["stem"] for e in timed if not e["rest"]}
    if lay_out([1] * len(timed)):
        return events, True
    if stems >= {1, -1} or any(e["rest"] for e in timed):
        fixed = [None if e["rest"] or e["stem"] == 0 else (1 if e["stem"] > 0 else 2) for e in timed]
        free = [i for i, v in enumerate(fixed) if v is None]
        if len(free) <= 12:
            # rests: prefer "upper rest in voice 1"; try the assignments in that order
            ys = sorted(timed[i]["y"] for i in free)
            middle = ys[len(ys) // 2] if ys else 0.0
            prefer = [1 if timed[i]["y"] < middle or len(set(ys)) == 1 else 2 for i in free]
            options = sorted(product((1, 2), repeat=len(free)),
                             key=lambda c: sum(a != b for a, b in zip(c, prefer)))
            for choice in options:
                voices = list(fixed)
                for i, v in zip(free, choice):
                    voices[i] = v
                if 2 in voices and 1 in voices and lay_out(voices):
                    return events, True
        voices = [v or 1 for v in fixed]
        if 1 in voices and 2 in voices:
            lay_out(voices)
            return events, False
    lay_out([1] * len(timed))
    return events, False


# ---------------------------------------------------------------- the reader

@dataclass
class _Head:
    x: float
    y: float
    w: float
    kind: str
    grace: bool
    staff: int = -1
    accidentals: list[int] = field(default_factory=list)
    cautionary: bool = False
    bracketed: bool = False
    tie_from: "_Head | None" = None
    tie_out: bool = False
    tie_in: bool = False
    effective: tuple[int, ...] = ()
    printed: bool = False
    key: tuple[str, int] | None = None


@dataclass
class _Chord:
    heads: list[_Head]
    x: float                       # left edge of the main notehead column
    stem: int = 0
    stem_x: float = 0.0
    stem_y: tuple[float, float] = (0.0, 0.0)
    beams: list[int] = field(default_factory=list)
    flags: int = 0
    dots: int = 0
    grace: bool = False
    staff: int = -1


class ScoreReader:
    """Collects the bars of all pages; `result()` gives the JSON-ready document."""

    def __init__(self, notation: Notation | None = None):
        self.notation = notation
        self.bars: list[dict] = []
        self.uncertain: list[dict] = []
        self.time: tuple[int, int] | None = None
        self.clefs: dict[int, str] = {}
        self.key: dict[int, dict[str, int]] = {}
        self.pending_ties: dict[int, list[_Head]] = {}
        self.texts: list[dict] = []
        self.tempos: list[dict] = []
        self.counts: list[dict] = []
        self.printed_numbers: list[tuple[int, int]] = []

    # ---- helpers

    def _flag(self, bar: int | None, staff: str | None, what: str):
        self.uncertain.append({"bar": bar, "staff": staff, "what": what})

    @staticmethod
    def _staff_name(i: int) -> str:
        return ("upper", "lower")[i] if i < 2 else f"staff{i + 1}"

    # ---- one page

    def add_page(self, data: PageData, page_no: int = 1):
        staves = find_staves(data.hlines)
        systems = group_systems(staves, data.vlines)
        sizes = sorted(g.size for g in data.glyphs if g.cp in NOTEHEADS)
        normal = sizes[len(sizes) // 2] if sizes else 0.0
        count = {"page": page_no, "noteheads": 0, "grace_noteheads": 0, "accidentals": 0, "rests": 0,
                 "read_noteheads": 0, "read_grace_noteheads": 0, "read_accidentals": 0, "read_rests": 0}
        for g in data.glyphs:
            if g.cp in NOTEHEADS:
                count["grace_noteheads" if g.size < 0.8 * normal else "noteheads"] += 1
            elif g.cp in RESTS:
                count["rests"] += 1
            elif ACCIDENTAL_RANGE[0] <= g.cp <= ACCIDENTAL_RANGE[1] and g.cp not in ACCIDENTAL_BRACKETS:
                count["accidentals"] += 1
        self.counts.append(count)
        for t in data.texts:
            self.texts.append(dict(t, page=page_no))
        for si, system in enumerate(systems):
            lo = (system[0].top + systems[si - 1][-1].bottom) / 2 if si else 0.0
            hi = (system[-1].bottom + systems[si + 1][0].top) / 2 if si + 1 < len(systems) else 1e9
            self._add_system(system, data, lo, hi, normal, count, page_no)

    def _add_system(self, system: list[Staff], data: PageData, lo: float, hi: float, normal: float,
                    count: dict, page_no: int):
        space = system[0].space
        glyphs = [g for g in data.glyphs if lo <= g.y < hi]
        heads = [_Head(g.x, g.y, g.w or 1.3 * space, NOTEHEADS[g.cp], g.size < 0.8 * normal)
                 for g in glyphs if g.cp in NOTEHEADS]
        heads.sort(key=lambda h: (h.x, h.y))
        head_w = 1.3 * space

        # --- vertical lines: bar lines or stems
        def touches(x, y0, y1):
            return [h for h in heads if y0 - 0.35 * space <= h.y <= y1 + 0.35 * space
                    and (abs(x - h.x) < 0.25 * space or abs(x - (h.x + self._w(h, head_w))) < 0.25 * space)]

        barline_x, stems = [], []
        for x, y0, y1 in data.vlines:
            if y1 < lo or y0 > hi:
                continue
            attached = touches(x, y0, y1)
            spans = any(abs(y0 - a.top) < 0.6 and (abs(y1 - a.bottom) < 0.6 or abs(y1 - system[-1].bottom) < 0.6)
                        for a in system)
            if spans and not attached:
                barline_x.append(x)
            elif attached:
                stems.append((x, y0, y1, attached))
        barline_x.sort()
        edges: list[list[float]] = []
        for x in barline_x:
            if edges and x - edges[-1][-1] < 2.0 * space:
                edges[-1].append(x)
            else:
                edges.append([x])
        if not edges:
            return
        bounds = [(e[0], e[-1]) for e in edges]
        regions = [(bounds[i][1], bounds[i + 1][0]) for i in range(len(bounds) - 1)]
        regions.append((bounds[-1][1], system[0].x1 + 50))

        # --- chords
        chords: list[_Chord] = []
        used: set[int] = set()
        for x, y0, y1, attached in sorted(stems, key=lambda s: -(s[2] - s[1])):
            attached = [h for h in attached if id(h) not in used]
            if not attached:
                continue
            used.update(id(h) for h in attached)
            ys = [h.y for h in attached]
            up = (max(ys) - y0) > (y1 - min(ys))      # the free end is above the notes
            c = _Chord(attached, 0.0, 1 if up else -1, x, (y0, y1), grace=all(h.grace for h in attached))
            c.x = x - self._w(attached[0], head_w) if up else x
            c.beams = beams_at(x, y0, y1, data.quads)
            end_y = y0 if up else y1
            for g in glyphs:
                if g.cp in FLAGS and abs(g.x - x) < 0.5 * space and abs(g.y - end_y) < 0.6 * space:
                    c.flags = max(c.flags, FLAGS[g.cp])
            chords.append(c)
        loose = [h for h in heads if id(h) not in used]
        for h in loose:                                 # no stem: whole notes, chords by x
            for c in chords:
                if c.stem == 0 and abs(c.x - h.x) < 0.3 * space and c.grace == h.grace:
                    c.heads.append(h)
                    break
            else:
                chords.append(_Chord([h], h.x, grace=h.grace))

        # --- staff of every chord
        beam_groups: dict[int, list[_Chord]] = {}
        for c in chords:
            for b in c.beams:
                beam_groups.setdefault(b, []).append(c)

        def nearest(c: _Chord) -> tuple[int, float]:
            d = [min(s.distance(h.y) for h in c.heads) for s in system]
            best = min(range(len(system)), key=lambda i: d[i])
            return best, d[best]

        for c in chords:
            c.staff, dist = nearest(c)
            if dist > 2.5 * space and c.beams:
                votes = [nearest(o) for b in c.beams for o in beam_groups[b] if o is not c]
                sure = [s for s, d in votes if d <= 2.5 * space]
                if sure:
                    c.staff = max(set(sure), key=sure.count)
            for h in c.heads:
                h.staff = c.staff

        # --- clefs, key signature
        def staff_of(y):
            return min(range(len(system)), key=lambda i: system[i].distance(y))

        def is_accidental(g):
            return ACCIDENTAL_RANGE[0] <= g.cp <= ACCIDENTAL_RANGE[1] and g.cp not in ACCIDENTAL_BRACKETS

        clef_marks = sorted(((g.x, staff_of(g.y), CLEFS[g.cp]) for g in glyphs if g.cp in CLEFS))
        signature: dict[int, list[Glyph]] = {}
        for si, staff in enumerate(system):
            start = [(x, c) for x, s, c in clef_marks if s == si and x < bounds[0][1] + 4 * space]
            if not start:
                continue
            own = [g for g in glyphs if is_accidental(g) and staff.distance(g.y) <= 1.5 * space
                   and g.size >= 0.8 * normal
                   and not any(abs(h.y - g.y) < 0.2 * space and g.x < h.x < g.x + 2 * space for h in heads)]
            x0, x1 = key_signature_run(start[0][0], [g.x for g in own], space)
            signature[si] = [g for g in own if x0 <= g.x <= x1]
        if len(system) > 1:          # a key signature stands at the same places in every staff
            common = None
            for sig in signature.values():
                here = {(g.cp, round(g.x)) for g in sig}
                common = here if common is None else common & here
            signature = {si: [g for g in sig if (g.cp, round(g.x)) in (common or set())] for si, sig in signature.items()}
        in_signature = {id(g) for sig in signature.values() for g in sig}
        for si, sig in signature.items():
            clef = [c for x, s, c in clef_marks if s == si][0]
            self.key[si] = {pitch_at(staff_position(g.y, system[si].lines), clef)[0]: g.cp for g in sig}
            count["read_accidentals"] += len(sig)

        # --- dots, accidentals, brackets
        dots = [g for g in glyphs if g.cp == DOT]
        used_dots: set[int] = set()
        for c in sorted(chords, key=lambda c: c.x):
            right = max(h.x + self._w(h, head_w) for h in c.heads)
            ys = [h.y for h in c.heads]
            rows: dict[int, int] = {}
            for i, g in enumerate(dots):
                if i in used_dots or not (right - 0.2 * space < g.x < right + 2.2 * space):
                    continue
                if min(abs(g.y - y) for y in ys) <= 0.6 * space and g.size >= 0.8 * normal:
                    rows[round(g.y * 2)] = rows.get(round(g.y * 2), 0) + 1
                    used_dots.add(i)
            c.dots = max(rows.values(), default=0)
        stray: list[Glyph] = []
        for g in sorted(glyphs, key=lambda g: g.x):
            if not (ACCIDENTAL_RANGE[0] <= g.cp <= ACCIDENTAL_RANGE[1]) and g.cp not in NOTEHEAD_BRACKETS:
                continue
            if id(g) in in_signature:
                continue
            right = [h for h in heads if abs(h.y - g.y) < 0.2 * space and g.x - 0.5 < h.x < g.x + 9 * space]
            if g.cp in NOTEHEAD_BRACKETS:
                near = [h for h in heads if abs(h.y - g.y) < 0.2 * space and abs(h.x - g.x) < 2 * space]
                for h in near[:1]:
                    h.bracketed = True
                continue
            if not right:
                if g.cp not in ACCIDENTAL_BRACKETS:
                    stray.append(g)
                continue
            h = min(right, key=lambda h: h.x)
            if g.cp in ACCIDENTAL_BRACKETS:
                h.cautionary = True
            else:
                h.accidentals.append(g.cp)
                h.printed = True
                count["read_accidentals"] += 1

        # --- ties
        self._find_ties(data, system, heads, lo, hi, head_w)

        # --- rests, time signatures, repeats
        rests = [g for g in glyphs if g.cp in RESTS]
        rest_dots: dict[int, int] = {}
        for g in rests:
            for i, d in enumerate(dots):
                if (i not in used_dots and g.x + 0.5 * space < d.x < g.x + 3.5 * space
                        and -0.8 * space <= d.y - g.y <= 0.3 * space):
                    rest_dots[id(g)] = rest_dots.get(id(g), 0) + 1
                    used_dots.add(i)
        digits = sorted((g for g in glyphs if g.cp in TIME_DIGITS and system[0].top - space < g.y < system[-1].bottom + space),
                        key=lambda g: g.x)
        time_marks: list[tuple[float, tuple[int, int]]] = []
        top = [g for g in digits if staff_of(g.y) == 0]
        columns: list[list[Glyph]] = []
        for g in top:
            if columns and g.x - columns[-1][0].x < 3 * space:
                columns[-1].append(g)
            else:
                columns.append([g])
        for col in columns:
            mid = (min(g.y for g in col) + max(g.y for g in col)) / 2
            num = "".join(str(TIME_DIGITS[g.cp]) for g in col if g.y <= mid - 0.1)
            den = "".join(str(TIME_DIGITS[g.cp]) for g in col if g.y > mid - 0.1)
            if num and den:
                time_marks.append((col[0].x, (int(num), int(den))))
        for g in glyphs:
            if g.cp in (TIME_COMMON, TIME_CUT) and staff_of(g.y) == 0:
                time_marks.append((g.x, (4, 4) if g.cp == TIME_COMMON else (2, 2)))
        repeat_x = sorted({round(g.x, 1) for g in glyphs if g.cp == REPEAT_DOTS})
        fermata_x: set[int] = set()            # the chord under (or over) every fermata
        for g in glyphs:
            if g.cp in FERMATAS:
                under = [c for c in chords if abs(g.x - (c.x + head_w / 2)) < 1.5 * space]
                if under:
                    fermata_x.add(id(min(under, key=lambda c: min(
                        abs(g.y - y) for y in [h.y for h in c.heads] + list(c.stem_y if c.stem else ())))))

        # printed bar number at the start of the system
        for t in data.texts:
            if (t["text"].isdigit() and "Italic" in t["font"] and t["x"] < system[0].x0 + 4 * space
                    and system[0].top - 12 * space < t["y"] < system[0].top):
                self.printed_numbers.append((len(self.bars) + 1, int(t["text"])))

        # --- bars
        for (rx0, rx1), k in zip(regions, range(len(regions))):
            in_bar = [c for c in chords if rx0 <= c.x + 0.5 * head_w < rx1]
            bar_rests = [g for g in rests if rx0 <= g.x < rx1]
            for x, t in time_marks:
                if rx0 - 0.5 <= x < rx1:
                    self.time = t
            for x, s, clef in clef_marks:
                # a clef before the first note of the bar holds for the whole bar
                first = min([c.x for c in in_bar if c.staff == s] + [g.x for g in bar_rests] + [rx1])
                if rx0 - 0.5 <= x < rx1 and x < first:
                    self.clefs[s] = clef
            if not in_bar and not bar_rests:
                continue
            n = len(self.bars) + 1
            if self.time is None:
                self._flag(n, None, "no time signature seen so far, 4/4 assumed")
                self.time = (4, 4)
            length = bar_length(self.time)
            bar = {"n": n, "time": f"{self.time[0]}/{self.time[1]}", "page": page_no, "staves": {}}
            left_edge, right_edge = edges[k], edges[k + 1] if k + 1 < len(edges) else []
            if any(left_edge[-1] < x < left_edge[-1] + 2 * space for x in repeat_x):
                bar["repeat_start"] = True
            if right_edge and any(right_edge[0] - 2 * space < x < right_edge[0] for x in repeat_x):
                bar["repeat_end"] = True
            for t in data.texts:
                m = re.fullmatch(r"(\d)\.", t["text"])
                if m and rx0 - space <= t["x"] < rx1 and system[0].top - 12 * space < t["y"] < system[0].top:
                    bar["volta"] = int(m.group(1))
                m = re.search(r"=\s*(\d+)", t["text"])
                if m and rx0 - 4 * space <= t["x"] < rx1 and system[0].top - 12 * space < t["y"] < system[0].top:
                    self.tempos.append({"bar": n, "bpm": int(m.group(1))})
            ok_all = True
            # a rest drawn between two staves belongs to the one in which the bar then adds up
            home = {id(g): staff_of(g.y) for g in bar_rests}
            floating = [g for g in bar_rests if len(system) > 1 and min(s.distance(g.y) for s in system) > 0.5 * space]

            def timed(assign):
                return [self._time_events(n, self._staff_name(si), [c for c in in_bar if c.staff == si],
                                          [g for g in bar_rests if assign[id(g)] == si], rest_dots, length, space)
                        for si in range(len(system))]

            timing = timed(home)
            if floating and not all(ok for _, ok in timing) and len(floating) <= 6:
                for moves in product((0, -1, 1), repeat=len(floating)):
                    assign = dict(home)
                    for g, m in zip(floating, moves):
                        assign[id(g)] = min(max(home[id(g)] + m, 0), len(system) - 1)
                    trial = timed(assign)
                    if all(ok or not raw for raw, ok in trial):
                        timing = trial
                        break
            for si, staff in enumerate(system):
                name = self._staff_name(si)
                raw, ok = timing[si]
                events = self._staff_bar(n, si, staff, raw, [c for c in in_bar if c.staff == si], clef_marks,
                                         fermata_x, space, head_w, count)
                bar["staves"][name] = events
                if events and not ok:
                    ok_all = False
                    sums = {v: float(s) for v, s in voice_sums(events).items()}
                    self._flag(n, name, f"durations {sums} do not fill the bar of {float(length)} quarter notes")
            bar["adds_up"] = ok_all
            self.bars.append(bar)
        for g in stray:
            self._flag(None, self._staff_name(staff_of(g.y)),
                       f"page {page_no}: accidental {accidental_name(g.cp)} at x={g.x:.0f} belongs to no note")
        for h in heads:                      # ties that leave the system at its right end
            if h.tie_out:
                self.pending_ties.setdefault(h.staff, []).append(h)

    @staticmethod
    def _w(h: _Head, default: float) -> float:
        return h.w if 0 < h.w < 2 * default else default

    def _find_ties(self, data: PageData, system: list[Staff], heads: list[_Head], lo: float, hi: float, head_w: float):
        space = system[0].space
        normal = [h for h in heads]
        if not normal:
            return
        first_x, last_x = min(h.x for h in normal), max(h.x for h in normal)
        candidates = []          # (miss, curve index, start head, end head)
        open_ends = {}
        for ci, cv in enumerate(data.curves):
            if not (lo <= cv["y0"] < hi) or abs(cv["y0"] - cv["y1"]) > 0.25 * space:
                continue
            side = 1 if cv["bulge"] > 0 else -1          # +1: the curve hangs below the notes

            def near(x, at_start):
                out = []
                for h in normal:
                    dx = x - (h.x + self._w(h, head_w) / 2)
                    if (-0.9 * space < dx < 2.2 * space) if at_start else (-2.2 * space < dx < 0.9 * space):
                        dy = cv["y0"] - h.y
                        miss = min(abs(dy - side * 0.8 * space), abs(dy - side * 0.25 * space), abs(dy))
                        if miss < 0.45 * space:
                            out.append((miss, h))
                return out

            starts, ends = near(cv["x0"], True), near(cv["x1"], False)
            pairs = [(m1 + m2, ci, a, b) for m1, a in starts for m2, b in ends
                     if abs(a.y - b.y) < 0.1 * space and b.x > a.x + 0.5 * head_w and a.staff == b.staff]
            candidates += pairs
            if not pairs:
                open_ends[ci] = (cv, starts, ends)
        done: set[int] = set()
        for _, ci, a, b in sorted(candidates, key=lambda c: c[0]):   # best fits first, one tie per note
            if ci not in done and b.tie_from is None and not any(h.tie_from is a for h in normal):
                b.tie_from = a
                done.add(ci)
        for cv, starts, ends in open_ends.values():
            if starts and cv["x1"] > last_x + 1.5 * head_w:
                min(starts, key=lambda s: s[0])[1].tie_out = True
            elif ends and cv["x0"] < first_x - 0.5 * head_w:
                min(ends, key=lambda s: s[0])[1].tie_in = True

    def _time_events(self, n, name, chords, rests, rest_dots, length, space):
        """Durations, voices and beats of one staff in one bar; no pitches yet."""
        raw = []
        for c in chords:
            kinds = {h.kind for h in c.heads}
            kind = "black" if "black" in kinds else ("half" if "half" in kinds else "whole")
            dur = Fraction(0) if c.grace else note_duration(kind, max(len(c.beams), c.flags), c.dots, stem=c.stem != 0)
            raw.append({"x": c.x, "y": min(h.y for h in c.heads), "dur": dur, "stem": c.stem, "rest": False,
                        "grace": c.grace, "chord": c, "kind": kind, "mixed": len(kinds) > 1})
        for g in rests:
            raw.append({"x": g.x, "y": g.y, "dur": dotted(RESTS[g.cp], rest_dots.get(id(g), 0)), "stem": 0,
                        "rest": True, "grace": False, "bar_rest": g.cp == WHOLE_REST, "chord": None})
        raw.sort(key=lambda e: (round(e["x"] / (0.5 * space)), e["y"]))
        _, ok = split_voices(raw, length)
        return raw, ok

    def _staff_bar(self, n, si, staff, raw, chords, clef_marks, fermata_x, space, head_w, count):
        name = self._staff_name(si)
        for e in raw:
            if e["rest"]:
                count["read_rests"] += 1
            elif e["mixed"]:
                self._flag(n, name, "noteheads of different kinds on one stem")
            elif e["kind"] == "black" and e["stem"] == 0 and not e["grace"]:
                self._flag(n, name, "black notehead without a stem, read as a quarter note")
        two = any(e.get("voice") == 2 for e in raw)

        # pitches, in the order in which the notes stand in the bar
        clef = self.clefs.get(si)
        if clef is None:
            self._flag(n, name, "no clef seen, treble assumed")
            clef = self.clefs[si] = "treble"
        held: dict[tuple[str, int], tuple[int, ...]] = {}
        pending = self.pending_ties.pop(si, [])
        out = []
        for e in raw:
            item: dict = {"beat": _num(e.get("beat", 1)), "dur": _num(e["dur"]), "notes": []}
            if two:
                item["voice"] = e.get("voice", 1)
            if e["rest"]:
                item["rest"] = True
            else:
                c: _Chord = e["chord"]
                # clef changes inside the bar
                bar_start = min(ch.x for ch in chords)
                inside = [cl for x, s, cl in clef_marks if s == si and bar_start < x < c.x]
                use = inside[-1] if inside else clef
                if c.grace:
                    item["grace"] = True
                for h in sorted(c.heads, key=lambda h: -h.y):
                    pos = staff_position(h.y, staff.lines)
                    letter, octave = pitch_at(pos, use)
                    key = (letter, octave)
                    tied = None
                    if h.tie_from is not None:
                        tied = h.tie_from.effective
                    elif h.tie_in:
                        match = [p for p in pending if p.key == key]
                        if match:
                            tied = match[0].effective
                        else:
                            self._flag(n, name, f"tie into {letter}{octave} from the previous system has no partner")
                    if h.accidentals:
                        acc = tuple(h.accidentals)
                        held[key] = acc
                    elif tied is not None and (h.tie_in or key not in held):
                        acc = tied
                    elif key in held:
                        acc = held[key]
                    elif letter in self.key.get(si, {}):
                        acc = (self.key[si][letter],)
                    else:
                        acc = ()
                    h.effective = acc
                    h.key = key
                    shown = tuple(a for a in acc if a != NATURAL)
                    note = {"step": None, "name": letter + "".join(accidental_suffix(a) for a in shown) + str(octave),
                            "accidental": "+".join(accidental_name(a) for a in shown) or "natural"}
                    if self.notation is not None:
                        step, problem = self.notation.step(letter, octave, shown)
                        note["step"] = step
                        if problem:
                            self._flag(n, name, f"{note['name']} at beat {item['beat']}: {problem}")
                    if h.printed:
                        note["printed"] = True
                    if h.cautionary:
                        note["cautionary"] = True
                    if h.bracketed:
                        note["bracketed"] = True
                    if h.tie_from is not None or (h.tie_in and tied is not None):
                        note["tied"] = True
                    if position_error(h.y, staff.lines) > 0.2:
                        self._flag(n, name, f"{note['name']}: notehead between two staff positions")
                    item["notes"].append(note)
                    count["read_grace_noteheads" if c.grace else "read_noteheads"] += 1
                if id(c) in fermata_x:
                    item["fermata"] = True
                if c.grace:
                    self._flag(n, name, f"grace note {'/'.join(x['name'] for x in item['notes'])} kept with duration 0")
            out.append(item)
        return out

    # ---- result

    def result(self, title: str = "", composer: str = "") -> dict:
        big = sorted((t for t in self.texts if t["page"] == 1), key=lambda t: -t["size"])
        heading = big[0]["text"] if big else ""
        info = parse_heading(heading)
        for at, printed in self.printed_numbers:
            if at != printed:
                self._flag(at, None, f"the score prints bar number {printed} here, the reader counts {at}")
        notes = [x for b in self.bars for ev in b["staves"].values() for e in ev for x in e["notes"]]
        checks = {
            "bars": len(self.bars), "bars_adding_up": sum(b["adds_up"] for b in self.bars),
            "printed_bar_numbers": len(self.printed_numbers),
            "printed_bar_numbers_matching": sum(a == b for a, b in self.printed_numbers),
            "notes": len(notes), "notes_with_step": sum(x["step"] is not None for x in notes),
            "notes_not_on_a_step": sum("not a whole step" in u["what"] for u in self.uncertain),
        }
        tuning: dict = {"edo": self.notation.edo if self.notation else None}
        if self.notation:
            tuning["notation"] = self.notation.description
            tuning["step_0"] = "C0" if not self.notation.offset else (
                f"C0 {'minus' if self.notation.offset > 0 else 'plus'} "
                f"{float(abs(self.notation.offset) * 1200 / self.notation.edo):g} cents")
        if info.get("tuning"):
            tuning["stated"] = info["tuning"]
        return {
            "title": title or info.get("title", heading), "composer": composer or info.get("composer", ""),
            "transcriber": info.get("transcriber", ""), "heading": heading,
            "tuning": tuning, "tempo": self.tempos, "bars": self.bars,
            "checks": checks, "counts": self.counts, "uncertain": self.uncertain,
        }


def _num(x):
    """Fractions as JSON numbers: whole numbers as int, the rest as float."""
    x = Fraction(x)
    return int(x) if x.denominator == 1 else float(x)


def parse_heading(text: str) -> dict:
    """"Title (Composer) 16-TET - transcribed by X" -> its parts; unknown shapes give the
    whole text as the title."""
    out = {"title": text.strip()}
    m = re.search(r"\s*-\s*transcribed by\s+(.*)$", text, re.I)
    if m:
        out["transcriber"] = m.group(1).strip()
        text = text[:m.start()]
    m = re.search(r"\b(\d+)\s*-?\s*(TET|EDO|ET)\b", text, re.I)
    if m:
        out["tuning"] = m.group(0).strip()
        out["edo"] = int(m.group(1))
        text = text[:m.start()] + text[m.end():]
    m = re.search(r"\(([^)]*)\)", text)
    if m:
        out["composer"] = m.group(1).strip()
        text = text[:m.start()] + text[m.end():]
    out["title"] = " ".join(text.split()).strip(" -")
    return out


def read_pdf(path: str | Path, notation: Notation | None = None) -> dict:
    """The whole PDF as a score document. Without `notation` the tuning stated in the
    heading ("16-TET") selects one of `NOTATIONS`; notes then get "step": None if there
    is none for it."""
    import pymupdf       # here, so that the pure parts work without it

    doc = pymupdf.open(str(path))
    pages = [extract_page(p) for p in doc]
    if notation is None and pages:
        texts = sorted(pages[0].texts, key=lambda t: -t["size"])
        edo = parse_heading(texts[0]["text"]).get("edo") if texts else None
        notation = NOTATIONS.get(edo)
    reader = ScoreReader(notation)
    for i, data in enumerate(pages):
        reader.add_page(data, i + 1)
    return reader.result()


def summary(score: dict) -> dict:
    bars = score["bars"]
    bad = [b["n"] for b in bars if not b["adds_up"]]
    return {"bars": len(bars), "bars_adding_up": len(bars) - len(bad), "bars_not_adding_up": bad,
            "notes": sum(len(e["notes"]) for b in bars for s in b["staves"].values() for e in s),
            "uncertain": len(score["uncertain"])}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    edo = None
    if "--edo" in args:
        i = args.index("--edo")
        edo = int(args[i + 1])
        del args[i:i + 2]
    if not 1 <= len(args) <= 2:
        print(__doc__)
        return 2
    if edo is not None and edo not in NOTATIONS:
        raise SystemExit(f"no notation table for {edo} steps; pass a Notation to read_pdf()")
    score = read_pdf(args[0], NOTATIONS.get(edo) if edo else None)
    text = json.dumps(score, indent=1, ensure_ascii=False)
    if len(args) == 2:
        Path(args[1]).write_text(text, encoding="utf-8")
    else:
        print(text)
    print(json.dumps(summary(score)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
