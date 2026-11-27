"""Write a machine-read score as MusicXML and engrave it, so that a reading can be proofread.

The score files under `reference/music/` hold what a reader made of a printed score: steps of
the tuning, onsets and durations in quarter notes. This module turns such a file back into
sheet music that shows exactly what the file holds, to be laid beside the original:

    score = bars_score(json.loads(path.read_text(encoding="utf-8")))      # bars with two staves
    score = prelude_score(prelude, sounding=False)                         # two pianos, four staves
    xml = to_musicxml(score)                                               # score-partwise 4.0
    render_pdf(xml_path, pdf_path)                                         # MuseScore if installed, else Verovio

A `Score` is plain data (see the classes below): parts with their staves, bars (number, time
signature, start and length in quarter notes), events (a chord on a staff with onset and
duration) and marks (texts over a staff). Any tuning can be written: a `Note` is a letter, an
octave and an accidental from `ACCIDENTALS`; `alter` (semitones away from the letter in
12-tone equal temperament, decimals allowed) may be given where the tuning's pitch is not what
the sign says in 12 tones.

What the writer decides, since the files do not hold it:

* voices: a chord goes to the first voice of its staff that is free at its onset (or to the
  voice the file names), so notes that sound together with different lengths end up in two
  or more voices; gaps become rests (at the end of a second voice: invisible);
* note values: a duration that is one note value (with dots) is written as such, anything else
  is split and tied; notes are cut and tied at barlines and, unless `keep_values` is set (the
  file holds the printed values), where they cross into the next beat group from off the beat;
* tuplets: where onsets do not lie on the binary grid, the smallest division (3, 5, 7 ...) of
  a stretch between two binary points that explains them; nested tuplets come out flat;
* accidentals: printed by the usual rule (valid for one staff position until the barline,
  key signature otherwise), worked out here for this layout, never copied from the source;
* beams: notes shorter than a quarter within one beat (or one tuplet).

Not written: slurs, dynamics, pedal, octave lines, the original's clefs, beams and stem
directions. Clefs: fixed (treble over bass) except where `set_clefs` is asked to choose them
after the notes (the preludes for one player), which changes clef at barlines only. Grace notes, fermatas, staccato dots, repeats and endings are written where
the file has them.

Rendering uses an existing engraver: MuseScore's command line if it is installed (or unpacked
under `reference/tools/`), otherwise the `verovio` package (MusicXML to SVG) with PyMuPDF
putting the pages into one PDF.

Command line (from `host/`):

    python -m tutor.scores.musicxml --all                 regenerate all sheets under reference/music/*/sheets
    python -m tutor.scores.musicxml --all --sounding      also the preludes with piano II at sounding pitch
    python -m tutor.scores.musicxml --all --updown        also the preludes in ups-and-downs notation (xenharmlib's names)
    python -m tutor.scores.musicxml FILE.json [OUT.musicxml] [--pdf] [--sounding] [--prelude N]
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
from bisect import bisect_right
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[3]
MUSIC = ROOT / "reference" / "music"

LETTERS = "CDEFGAB"
LETTER_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

# our accidental name -> (semitones in 12-tone terms, MusicXML <accidental> value, SMuFL glyph)
# The names are those of `musescore_pdf.ACCIDENTAL_NAMES` plus the plain ones. The glyph is the one
# the MusicXML value stands for (the arrows are SMuFL's "Gould arrow quartertone accidentals"; the
# names of those glyphs speak of quarter-tones, the scores here use the arrow for 25 cents and say so
# in `alter`). It would be written as smufl="..." only where MusicXML had no value of its own.
ACCIDENTALS: dict[str, tuple[float, str, str]] = {
    "natural": (0.0, "natural", "accidentalNatural"),
    "sharp": (1.0, "sharp", "accidentalSharp"),
    "flat": (-1.0, "flat", "accidentalFlat"),
    "double-sharp": (2.0, "double-sharp", "accidentalDoubleSharp"),
    "double-flat": (-2.0, "flat-flat", "accidentalDoubleFlat"),
    "half-sharp": (0.5, "quarter-sharp", "accidentalQuarterToneSharpStein"),
    "half-flat": (-0.5, "quarter-flat", "accidentalQuarterToneFlatStein"),
    "sesquisharp": (1.5, "three-quarters-sharp", "accidentalThreeQuarterTonesSharpStein"),
    "sesquiflat": (-1.5, "three-quarters-flat", "accidentalThreeQuarterTonesFlatZimmermann"),
    "natural-arrow-up": (0.25, "natural-up", "accidentalQuarterToneSharpNaturalArrowUp"),
    "natural-arrow-down": (-0.25, "natural-down", "accidentalQuarterToneFlatNaturalArrowDown"),
    "sharp-arrow-up": (1.25, "sharp-up", "accidentalThreeQuarterTonesSharpArrowUp"),
    "sharp-arrow-down": (0.75, "sharp-down", "accidentalQuarterToneSharpArrowDown"),
    "flat-arrow-up": (-0.75, "flat-up", "accidentalQuarterToneFlatArrowUp"),
    "flat-arrow-down": (-1.25, "flat-down", "accidentalThreeQuarterTonesFlatArrowDown"),
    "double-sharp-arrow-up": (2.25, "double-sharp-up", "accidentalFiveQuarterTonesSharpArrowUp"),
    "double-sharp-arrow-down": (1.75, "double-sharp-down", "accidentalThreeQuarterTonesSharpArrowDown"),
    "double-flat-arrow-up": (-1.75, "flat-flat-up", "accidentalThreeQuarterTonesFlatArrowUp"),
    "double-flat-arrow-down": (-2.25, "flat-flat-down", "accidentalFiveQuarterTonesFlatArrowDown"),
}
# how the accidentals are written in note names: "Ephemeral Happiness" (t, d), "Don't Take Five" (+, ^, v)
NAME_SUFFIX = {"": "natural", "#": "sharp", "b": "flat", "x": "double-sharp", "bb": "double-flat",
               "t": "half-sharp", "+": "half-sharp", "d": "half-flat", "#t": "sesquisharp", "#+": "sesquisharp", "db": "sesquiflat",
               "^": "natural-arrow-up", "v": "natural-arrow-down", "#^": "sharp-arrow-up", "#v": "sharp-arrow-down",
               "b^": "flat-arrow-up", "bv": "flat-arrow-down", "x^": "double-sharp-arrow-up", "xv": "double-sharp-arrow-down",
               "bb^": "double-flat-arrow-up", "bbv": "double-flat-arrow-down"}
SUFFIX_OF = {"natural": "", "sharp": "#", "flat": "b", "half-sharp": "t", "half-flat": "d", "sesquisharp": "#t", "sesquiflat": "db"}

# values Verovio 6.4 draws nothing for (checked glyph by glyph); MuseScore knows them
VEROVIO_UNDRAWN = {"double-sharp-up", "double-sharp-down", "flat-flat-up", "flat-flat-down", "arrow-up", "arrow-down",
                   "sharp-1", "sharp-2", "sharp-3", "sharp-5", "flat-1", "flat-2", "flat-3", "flat-4"}

NOTE_TYPES = [(Fraction(8), "breve"), (Fraction(4), "whole"), (Fraction(2), "half"), (Fraction(1), "quarter"), (Fraction(1, 2), "eighth"),
              (Fraction(1, 4), "16th"), (Fraction(1, 8), "32nd"), (Fraction(1, 16), "64th"), (Fraction(1, 32), "128th"), (Fraction(1, 64), "256th")]
SOURCE_SHORT = {"engraving": "engr.", "recording": "rec.", "print": "print"}


# ---------------------------------------------------------------- the score

@dataclass
class Note:
    letter: str
    octave: int                      # C4 = middle C
    accidental: str = "natural"      # a key of ACCIDENTALS
    alter: float | None = None       # semitones away from the letter in 12 tones; None = what the accidental says
    tie_in: bool = False             # continues the note of the same pitch that ends where this one begins
    other: str = ""                  # the other reading of this note, as it is to be printed ("B3")
    other_source: str = ""           # where the other reading comes from ("engr.")

    def name(self) -> str:
        return f"{self.letter}{SUFFIX_OF.get(self.accidental, '(' + self.accidental + ')')}{self.octave}"


@dataclass
class Event:
    staff: int                       # index over all staves of the score, top first
    onset: Fraction                  # quarter notes from the start of the piece
    dur: Fraction                    # quarter notes; 0 with `grace`
    notes: list[Note]
    voice: int = 0                   # 1.. if the source says which voice, 0 = the first free one
    grace: bool = False
    fermata: bool = False
    staccato: bool = False


@dataclass
class Bar:
    number: int | str
    time: str                        # "6/8"
    start: Fraction
    length: Fraction
    key: list[tuple[str, str]] | None = None     # key signature that begins here: [(letter, accidental), ...]
    repeat_start: bool = False
    repeat_end: bool = False
    ending: int = 0                  # number of the volta this bar is


@dataclass
class Part:
    name: str
    clefs: list[str] = field(default_factory=lambda: ["G", "F"])     # one per staff, a key of CLEFS
    transpose: float = 0.0           # sounding minus written, in semitones (-0.5: a quarter-tone lower). Written as <transpose> only
                                     # if whole: the schema allows decimals, but music21 refuses them, so the part name has to say it


@dataclass
class Mark:
    onset: Fraction
    staff: int
    text: str
    tempo: bool = False              # text is beats per minute of a quarter note


@dataclass
class Score:
    title: str
    parts: list[Part]
    bars: list[Bar]
    events: list[Event]
    marks: list[Mark] = field(default_factory=list)
    header: list[str] = field(default_factory=list)     # lines under the title
    composer: str = ""
    keep_values: bool = False        # durations are the printed note values: do not regroup them
    clefs: dict[tuple[int, int], str] = field(default_factory=dict)     # (bar index, staff) -> the clef that begins there
    warnings: list[str] = field(default_factory=list)


def frac(value, limit: int = 128) -> Fraction:
    """A stored float as the fraction it stands for (0.333333 -> 1/3)."""
    return Fraction(value).limit_denominator(limit) if not isinstance(value, Fraction) else value


def bar_length(time: str) -> Fraction:
    num, _, den = time.partition("/")
    return Fraction(4 * int(num), int(den or 4))


# ---------------------------------------------------------------- note values

def note_value(dur: Fraction, max_dots: int = 2) -> tuple[str, int] | None:
    """Note type and number of dots for a duration in quarter notes, None if it is not one value."""
    for base, name in NOTE_TYPES:
        for dots in range(max_dots + 1):
            if dur == base * (2 - Fraction(1, 2 ** dots)):
                return name, dots
    return None


def group_bounds(time: str) -> list[Fraction]:
    """Where the beat groups of a bar begin (without 0), in quarter notes: 4/4 = 2 + 2, 3/4 one group,
    6/8, 9/8, 12/8 in dotted quarters, 5/4 = 2 + 2 + 1, everything else in quarters with the rest at
    the end. A simple rule: the files do not say how an irregular bar is grouped."""
    num, _, den = time.partition("/")
    num, den = int(num), int(den or 4)
    length = Fraction(4 * num, den)
    if den == 8 and num % 3 == 0:
        sizes = [Fraction(3, 2)] * (num // 3)
    elif den == 4 and num <= 3:
        sizes = [length]
    elif den == 4 and num % 3 == 0:
        sizes = [Fraction(3)] * (num // 3)
    elif den == 4:
        sizes = [Fraction(2)] * (num // 2) + [Fraction(1)] * (num % 2)
    else:
        sizes = [Fraction(1)] * int(length) + ([length - int(length)] if length != int(length) else [])
    out, at = [], Fraction(0)
    for size in sizes[:-1]:
        at += size
        out.append(at)
    return out


def beat_unit(time: str) -> Fraction:
    num, _, den = time.partition("/")
    return Fraction(3, 2) if int(den or 4) == 8 and int(num) % 3 == 0 else Fraction(1)


def split_values(start: Fraction, end: Fraction, bounds=(), keep: bool = False, beat: Fraction | None = None) -> list[tuple[Fraction, Fraction]]:
    """Cut the stretch from `start` to `end` (quarter notes from the barline) into pieces that are one
    note value each. A piece may cross a group boundary only if it begins on one or on a beat (a half
    note on the second quarter of 4/4 stays), or with `keep`, when the duration is the printed value.
    Otherwise the cut is at the boundary, or inside a group at the most even point (the first multiple
    of the largest note value)."""
    dur = end - start
    inside = [b for b in bounds if start < b < end]
    on_bound = start == 0 or start in bounds or bool(beat) and start % beat == 0
    if keep and note_value(dur, 2):
        return [(start, end)]
    if note_value(dur, 1) and (not inside or on_bound):
        return [(start, end)]
    if inside and not on_bound:
        cut = inside[0]
    elif inside:
        whole = [b for b in inside if note_value(b - start, 1)]
        cut = whole[-1] if whole else inside[0]
    else:
        origin = max([Fraction(0)] + [b for b in bounds if b <= start])
        cut = None
        for unit, _ in NOTE_TYPES:
            point = origin + (math.floor((start - origin) / unit) + 1) * unit
            if point < end:
                cut = point
                break
        if cut is None:
            raise ValueError(f"no note values for {start}..{end}")
    return split_values(start, cut, bounds, keep, beat) + split_values(cut, end, bounds, keep, beat)


def is_binary(x: Fraction) -> bool:
    d = x.denominator
    return d & (d - 1) == 0 and d <= 64


@dataclass
class Tuplet:
    start: Fraction
    end: Fraction
    actual: int                      # so many equal parts ...
    normal: int                      # ... in the time of so many
    unit: Fraction                   # written value of one part, in quarter notes

    @property
    def part(self) -> Fraction:
        return (self.end - self.start) / self.actual


def tuplet_unit(span: Fraction, actual: int) -> tuple[Fraction, int] | None:
    """Written note value for one part of a tuplet and how many of them the stretch normally holds:
    the smallest value that is not shorter than a part and divides the stretch (eighths for three in a
    quarter, 3:2), else the largest shorter one (three in the time of seven eighths, 3:7)."""
    part = span / actual
    values = [v for v, _ in NOTE_TYPES]
    for value in reversed(values):
        if value >= part and (span / value).denominator == 1 and value < span * 2:
            return value, int(span / value)
    for value in values:
        if value < part and (span / value).denominator == 1:
            return value, int(span / value)
    return None


def find_tuplets(items: list[tuple[Fraction, Fraction, bool]], length: Fraction, max_parts: int = 64) -> list[Tuplet]:
    """Tuplets of one voice in one bar. `items` are (start, end, sounding) and cover the bar without
    gaps. For the first point that is not on the binary grid, every stretch between two binary points
    around it is tried (points of the voice, and sixteenth positions); it must be divisible into n equal
    parts so that all points inside lie on them. The cheapest wins: n, doubled for every note the stretch
    cuts and for a dotted stretch (five in the time of three eighths), tripled for a stretch that is no
    note value on its own grid and not the whole bar; then the longest parts. Raises ValueError if nothing fits."""
    points = sorted({p for s, e, _ in items for p in (s, e)} | {Fraction(0), length})
    grid = sorted({p for p in points if is_binary(p)} | {Fraction(k, 4) for k in range(int(length * 4) + 1)})
    out: list[Tuplet] = []
    done = Fraction(0)
    while True:
        odd = [p for p in points if p > done and not is_binary(p)]
        if not odd:
            return out
        p = odd[0]
        best = None
        for a in (x for x in grid if done <= x < p):
            for b in (x for x in grid if p < x <= length):
                span = b - a
                inner = [q for q in points if a < q < b]
                n = 1
                for q in inner:
                    n = math.lcm(n, ((q - a) / span).denominator)
                    if n > max_parts:
                        break
                if n > max_parts or n < 2 or tuplet_unit(span, n) is None:
                    continue
                cuts = sum(1 for x in (a, b) if any(s < x < e and sounding for s, e, sounding in items))
                third = span / 3
                plain = lambda value: is_binary(value) and is_binary(1 / value) and (a / value).denominator == 1     # noqa: E731
                odd_span = 0 if span == length or plain(span) else 1 if plain(third) else 2
                key = (n * (1 + cuts + odd_span), cuts, -span / n, span)
                if best is None or key < best[0]:
                    best = (key, a, b, n)
        if best is None:
            raise ValueError(f"no tuplet explains the point {p}")
        _, a, b, n = best
        unit, normal = tuplet_unit(b - a, n)
        out.append(Tuplet(a, b, n, normal, unit))
        done = b


# ---------------------------------------------------------------- layout: voices, bars, note values

@dataclass
class Seg:
    """One written note, chord or rest."""
    start: Fraction                  # from the barline, real time
    end: Fraction
    event: Event | None              # None = rest
    kind: str = "quarter"
    dots: int = 0
    tuplet: Tuplet | None = None
    tuplet_start: bool = False
    tuplet_stop: bool = False
    first: bool = True               # first written piece of its event
    tie_stop: set = field(default_factory=set)      # indices into event.notes
    tie_start: set = field(default_factory=set)
    show: dict = field(default_factory=dict)        # note index -> accidental to print
    beam: str = ""
    hidden: bool = False             # a rest that is not printed
    grace: list = field(default_factory=list)       # grace events before this one
    grace_tied: set = field(default_factory=set)    # id() of grace notes tied to their main note


def assign_voices(events: list[Event]) -> dict[int, int]:
    """Voice (0..) for every event of one staff, by id(event): the voice the source names, else the
    first one that is free at the onset. Events with the same onset are taken from the top note down;
    one that continues a tied note comes first and stays in the voice of the note it continues."""
    ends: list[Fraction] = []
    last: list[Event | None] = []
    out: dict[int, int] = {}

    def tied(e: Event) -> set:
        return {(n.letter, n.octave, n.accidental) for n in e.notes if n.tie_in}

    for ev in sorted(events, key=lambda e: (e.onset, not tied(e), -max((pitch_number(n) for n in e.notes), default=0), -e.dur)):
        if ev.grace or ev.dur <= 0:
            continue
        free = [i for i, end in enumerate(ends) if end <= ev.onset]
        if ev.voice:
            v = ev.voice - 1
        else:
            same = [i for i in free if ends[i] == ev.onset and tied(ev) & {(n.letter, n.octave, n.accidental) for n in last[i].notes}]
            v = (same or free or [len(ends)])[0]
        while len(ends) <= v:
            ends.append(Fraction(0))
            last.append(None)
        ends[v], last[v] = max(ends[v], ev.onset + ev.dur), ev
        out[id(ev)] = v
    return out


def pitch_number(note: Note) -> float:
    """Semitones above C0 in 12-tone terms, for ordering."""
    alter = note.alter if note.alter is not None else ACCIDENTALS[note.accidental][0]
    return 12 * note.octave + LETTER_SEMITONES[note.letter] + alter


def layout(score: Score) -> dict[tuple[int, int], dict[int, list[Seg]]]:
    """(bar index, staff) -> voice -> written notes and rests that fill the bar. A voice keeps its
    number through the piece, so a note tied over a barline stays in its voice; a bar holds only the
    voices that have notes in it."""
    starts = [b.start for b in score.bars]
    end_of_piece = score.bars[-1].start + score.bars[-1].length
    staves = sum(len(p.clefs) for p in score.parts)
    cells: dict[tuple[int, int], dict[int, list]] = {}
    graces: dict[tuple[int, Fraction], list[Event]] = {}
    for staff in range(staves):
        events = [e for e in score.events if e.staff == staff]
        voices = assign_voices(events)
        for ev in events:
            if ev.grace or ev.dur <= 0:
                graces.setdefault((staff, ev.onset), []).append(ev)
                continue
            if ev.onset >= end_of_piece or ev.onset < starts[0]:
                score.warnings.append(f"event at {ev.onset} lies outside the bars, left out")
                continue
            at, stop = ev.onset, min(ev.onset + ev.dur, end_of_piece)
            if stop < ev.onset + ev.dur:
                score.warnings.append(f"note at {ev.onset} is longer than the piece, cut")
            first = True
            while at < stop:
                i = bisect_right(starts, at) - 1
                bar = score.bars[i]
                piece_end = min(stop, bar.start + bar.length)
                cells.setdefault((i, staff), {}).setdefault(voices[id(ev)], []).append((at - bar.start, piece_end - bar.start, ev, first))
                at, first = piece_end, False
    out: dict[tuple[int, int], dict[int, list[Seg]]] = {}
    for (i, staff), by_voice in sorted(cells.items()):
        bar = score.bars[i]
        bounds = group_bounds(bar.time)
        written = {}
        for number, v in enumerate(sorted(by_voice)):
            items = sorted(by_voice[v], key=lambda item: item[0])
            filled, at = [], Fraction(0)
            for s, e, ev, first in items:
                if s < at:
                    score.warnings.append(f"bar {bar.number}, staff {staff + 1}: two events of one voice overlap at {s}; the later one is cut")
                    s = at
                    if e <= s:
                        continue
                if s > at:
                    filled.append((at, s, None, True))
                filled.append((s, e, ev, first))
                at = e
            if at < bar.length:
                filled.append((at, bar.length, None, True))
            written[v] = write_voice(filled, bar, bounds, score, hide_tail=number > 0)
        out[(i, staff)] = written
    for (i, staff), written in out.items():
        bar = score.bars[i]
        for (g_staff, onset), events in graces.items():
            if g_staff != staff or not bar.start <= onset < bar.start + bar.length:
                continue
            here = [seg for voice in written.values() for seg in voice if seg.event and seg.first and seg.start == onset - bar.start]
            pitches = {(n.letter, n.octave, n.accidental) for e in events for n in e.notes}
            here.sort(key=lambda seg: not any(n.tie_in and (n.letter, n.octave, n.accidental) in pitches for n in seg.event.notes))
            target = here[0] if here else None
            if target is None:
                score.warnings.append(f"bar {bar.number}: grace note at {onset - bar.start} has no note to stand before, left out")
            else:
                target.grace.extend(events)
    tie_segments(score, out)
    for (i, staff), written in out.items():
        print_accidentals(list(written.values()), key_at(score, i))
        for voice in written.values():
            beam_voice(voice, beat_unit(score.bars[i].time))
    return out


def write_voice(filled: list, bar: Bar, bounds: list[Fraction], score: Score, hide_tail: bool) -> list[Seg]:
    """Note values, ties and tuplets for one voice of one bar. `filled`: (start, end, event or None,
    first piece of the event) without gaps."""
    try:
        tuplets = find_tuplets([(s, e, ev is not None) for s, e, ev, _ in filled], bar.length)
    except ValueError as error:
        score.warnings.append(f"bar {bar.number}: {error}; onsets moved to the nearest 64th note")
        snap = lambda x: Fraction(round(x * 16), 16)                                    # noqa: E731
        filled = [(snap(s), snap(e), ev, first) for s, e, ev, first in filled if snap(e) > snap(s)]
        tuplets = []
    cuts = sorted({t.start for t in tuplets} | {t.end for t in tuplets})
    segs: list[Seg] = []
    for s, e, ev, first in filled:
        edges = [s] + [c for c in cuts if s < c < e] + [e]
        for a, b in zip(edges, edges[1:]):
            tuplet = next((t for t in tuplets if t.start <= a and b <= t.end), None)
            if tuplet:
                to_written = lambda x: (x - tuplet.start) / tuplet.part * tuplet.unit      # noqa: E731
                pieces = [(tuplet.start + ws / tuplet.unit * tuplet.part, tuplet.start + we / tuplet.unit * tuplet.part, we - ws)
                          for ws, we in split_values(to_written(a), to_written(b))]
            elif ev is None and (a, b) != (0, bar.length):         # a rest never hides where a beat group begins
                stops = [a] + [c for c in bounds if a < c < b] + [b]
                pieces = [(ps, pe, pe - ps) for x, y in zip(stops, stops[1:]) for ps, pe in split_values(x, y, bounds)]
            else:
                pieces = [(ps, pe, pe - ps) for ps, pe in split_values(a, b, bounds, score.keep_values and ev is not None, beat_unit(bar.time))]
            for ps, pe, value in pieces:
                kind, dots = note_value(value)
                seg = Seg(ps, pe, ev, kind, dots, tuplet, first=first)
                if ev is not None and not first:
                    seg.tie_stop = set(range(len(ev.notes)))        # the piece before gets its tie in tie_segments()
                segs.append(seg)
                first = False
    for t in tuplets:
        inside = [seg for seg in segs if t.start <= seg.start and seg.end <= t.end]
        inside[0].tuplet_start = inside[-1].tuplet_stop = True
    if hide_tail:
        for seg in reversed(segs):
            if seg.event is not None or seg.tuplet:
                break
            seg.hidden = True
    return segs


def tie_segments(score: Score, cells: dict) -> None:
    """Ties between the pieces of one event, and the ties the source marks on a note (`tie_in`): from
    the note of the same pitch on the same staff that ends where this one begins."""
    by_staff: dict[int, list[tuple[Fraction, Fraction, Seg]]] = {}
    for (i, staff), written in cells.items():
        for voice in written.values():
            for seg in voice:
                if seg.event is not None:
                    by_staff.setdefault(staff, []).append((score.bars[i].start + seg.start, score.bars[i].start + seg.end, seg))
    for staff, segs in by_staff.items():
        segs.sort(key=lambda item: item[0])
        pieces: dict[int, Seg] = {}
        for _, _, seg in segs:                               # pieces of one event, cut at barlines or into note values
            if not seg.first:
                pieces[id(seg.event)].tie_start = set(range(len(seg.event.notes)))
            pieces[id(seg.event)] = seg
        ending: dict[tuple, tuple[Seg, int]] = {}
        for _, end, seg in segs:
            for k, note in enumerate(seg.event.notes):
                ending[(end, note.letter, note.octave, note.accidental)] = (seg, k)
        for start, _, seg in segs:
            if not seg.first:
                continue
            for k, note in enumerate(seg.event.notes):
                if note.tie_in:
                    before = ending.get((start, note.letter, note.octave, note.accidental))
                    small = [g for e in seg.grace for g in e.notes if (g.letter, g.octave, g.accidental) == (note.letter, note.octave, note.accidental)]
                    if before is None and small:
                        seg.grace_tied.add(id(small[0]))
                        seg.tie_stop.add(k)
                    elif before is None:
                        score.warnings.append(f"staff {staff + 1}, {note.name()} at {start}: marked as tied, but no note of this pitch ends there")
                    else:
                        before[0].tie_start.add(before[1])
                        seg.tie_stop.add(k)


def key_at(score: Score, bar_index: int) -> dict[str, str]:
    key: dict[str, str] = {}
    for bar in score.bars[:bar_index + 1]:
        if bar.key is not None:
            key = dict(bar.key)
    return key


def print_accidentals(written: list[list[Seg]], key: dict[str, str]) -> None:
    """Which accidentals are printed in one bar of one staff: a sign holds for its line or space until
    the barline, in all voices; the key signature holds otherwise. A note tied over from before gets no
    sign, and the next note on its line gets one in any case."""
    state: dict[tuple[str, int], str] = {}
    order = sorted(((seg.start, v, seg) for v, voice in enumerate(written) for seg in voice if seg.event is not None), key=lambda x: x[:2])
    for _, _, seg in order:
        for extra in seg.grace:
            for note in extra.notes:
                state[(note.letter, note.octave)] = note.accidental       # grace notes always carry their sign
        for k, note in enumerate(seg.event.notes):
            place = (note.letter, note.octave)
            if k in seg.tie_stop:
                if place not in state:
                    state[place] = "?"
                continue
            if state.get(place, key.get(note.letter, "natural")) != note.accidental:
                seg.show[k] = note.accidental
            state[place] = note.accidental


def beam_voice(voice: list[Seg], unit: Fraction) -> None:
    short = {"eighth", "16th", "32nd", "64th", "128th", "256th"}
    group: list[Seg] = []

    def close() -> None:
        if len(group) > 1:
            for seg in group:
                seg.beam = "continue"
            group[0].beam, group[-1].beam = "begin", "end"
        group.clear()

    for seg in voice:
        if seg.event is None or seg.kind not in short:
            close()
            continue
        if group:
            last = group[-1]
            same = (seg.tuplet is last.tuplet) if (seg.tuplet or last.tuplet) else (seg.start // unit == last.start // unit)
            if not same or seg.start != last.end:
                close()
        group.append(seg)
    close()


# ---------------------------------------------------------------- MusicXML

def other_reading_marks(score: Score) -> list[Mark]:
    """One text per run of notes with a second reading: "engr.: B3 C4 Db4 D4" over the first of them.
    The notes themselves get parenthesised heads, so the names can be matched in order."""
    marks: list[Mark] = []
    starts = [b.start for b in score.bars]
    last: dict[int, tuple] = {}
    for ev in sorted((e for e in score.events if any(n.other for n in e.notes)), key=lambda e: (e.staff, e.onset)):
        bar = bisect_right(starts, ev.onset) - 1
        for note in sorted((n for n in ev.notes if n.other), key=pitch_number):
            before = last.get(ev.staff)
            if before and before[0] == bar and before[1] == note.other_source and ev.onset - before[2] <= 1 and before[4] < 6:
                before[3].text += " " + note.other
                last[ev.staff] = (bar, note.other_source, ev.onset, before[3], before[4] + 1)
            else:
                mark = Mark(ev.onset, ev.staff, f"{note.other_source}: {note.other}" if note.other_source else note.other)
                marks.append(mark)
                last[ev.staff] = (bar, note.other_source, ev.onset, mark, 1)
    return marks


def to_musicxml(score: Score) -> str:
    """The score as a MusicXML document (score-partwise 4.0)."""
    cells = layout(score)
    marks = score.marks + other_reading_marks(score)
    durations = {seg.end - seg.start for written in cells.values() for voice in written.values() for seg in voice}
    width = max([4] + [v + 1 for written in cells.values() for v in written])           # voices per staff: 1-4, 5-8 as MuseScore numbers them
    durations |= {m.onset for m in marks} | {b.start for b in score.bars} | {b.length for b in score.bars}
    divisions = math.lcm(*[d.denominator for d in durations]) if durations else 1
    ticks = lambda x: int(x * divisions)                                               # noqa: E731
    starts = [b.start for b in score.bars]

    x: list[str] = ['<?xml version="1.0" encoding="UTF-8"?>',
                    '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">',
                    '<score-partwise version="4.0">',
                    f"<work><work-title>{escape(score.title)}</work-title></work>",
                    "<identification>" + (f'<creator type="composer">{escape(score.composer)}</creator>' if score.composer else "")
                    + "<encoding><software>openxen host/tutor/scores/musicxml.py</software></encoding></identification>",
                    f'<credit page="1"><credit-type>title</credit-type><credit-words justify="center" valign="top" font-size="20">{escape(score.title)}</credit-words></credit>']
    for line in score.header:
        x.append(f'<credit page="1"><credit-type>subtitle</credit-type><credit-words justify="center" valign="top" font-size="9">{escape(line)}</credit-words></credit>')
    if score.composer:
        x.append(f'<credit page="1"><credit-type>composer</credit-type><credit-words justify="right" valign="top" font-size="10">{escape(score.composer)}</credit-words></credit>')
    x.append("<part-list>")
    for p, part in enumerate(score.parts):
        x.append(f'<score-part id="P{p + 1}"><part-name>{escape(part.name)}</part-name></score-part>')
    x.append("</part-list>")

    first_staff = 0
    for p, part in enumerate(score.parts):
        x.append(f'<part id="P{p + 1}">')
        time = None
        for i, bar in enumerate(score.bars):
            x.append(f'<measure number="{bar.number}">')
            attributes = []
            if i == 0:
                attributes.append(f"<divisions>{divisions}</divisions>")
            if bar.key is not None or i == 0:
                attributes.append(key_xml(bar.key or []))
            if bar.time != time:
                num, _, den = bar.time.partition("/")
                attributes.append(f"<time><beats>{num}</beats><beat-type>{den or 4}</beat-type></time>")
                time = bar.time
            if i == 0:
                attributes.append(f"<staves>{len(part.clefs)}</staves>")
                for s, clef in enumerate(part.clefs):
                    attributes.append(clef_xml(clef, s + 1))
                if part.transpose and part.transpose == int(part.transpose):
                    attributes.append(f"<transpose><diatonic>0</diatonic><chromatic>{int(part.transpose)}</chromatic></transpose>")
            if i:
                attributes += [clef_xml(score.clefs[(i, first_staff + s)], s + 1) for s in range(len(part.clefs)) if (i, first_staff + s) in score.clefs]
            if attributes:
                x.append("<attributes>" + "".join(attributes) + "</attributes>")
            if bar.repeat_start or bar.ending:
                x.append('<barline location="left">' + (f'<ending number="{bar.ending}" type="start"/>' if bar.ending else "")
                         + ('<repeat direction="forward"/>' if bar.repeat_start else "") + "</barline>")
            here = [m for m in marks if first_staff <= m.staff < first_staff + len(part.clefs) and bisect_right(starts, m.onset) - 1 == i]
            at = Fraction(0)
            for mark in sorted(here, key=lambda m: m.onset):
                offset = min(mark.onset - bar.start, bar.length)
                if offset > at:
                    x.append(f"<forward><duration>{ticks(offset - at)}</duration></forward>")
                    at = offset
                x.append(direction_xml(mark, mark.staff - first_staff + 1))
            if at:
                x.append(f"<backup><duration>{ticks(at)}</duration></backup>")
            lines = []
            for s in range(len(part.clefs)):
                written = cells.get((i, first_staff + s))
                if not written:
                    lines.append([f'<note><rest measure="yes"/><duration>{ticks(bar.length)}</duration><voice>{width * s + 1}</voice><staff>{s + 1}</staff></note>'])
                    continue
                for v, voice in sorted(written.items()):
                    lines.append(voice_xml(voice, width * s + v + 1, s + 1, ticks))
            for k, notes in enumerate(lines):
                if k:
                    x.append(f"<backup><duration>{ticks(bar.length)}</duration></backup>")
                x.extend(notes)
            if bar.repeat_end or bar.ending or i == len(score.bars) - 1:
                x.append('<barline location="right">' + ("<bar-style>light-heavy</bar-style>" if bar.repeat_end or i == len(score.bars) - 1 else "")
                         + (f'<ending number="{bar.ending}" type="{"stop" if bar.repeat_end else "discontinue"}"/>' if bar.ending else "")
                         + ('<repeat direction="backward"/>' if bar.repeat_end else "") + "</barline>")
            x.append("</measure>")
        x.append("</part>")
        first_staff += len(part.clefs)
    x.append("</score-partwise>")
    return "\n".join(x) + "\n"


# clef name -> (sign, line, octaves the clef is moved, staff position of its bottom line: 7 per octave, C0 = 0)
CLEFS = {"G": ("G", 2, 0, 30), "F": ("F", 4, 0, 18), "C": ("C", 3, 0, 24), "G8va": ("G", 2, 1, 37), "F8vb": ("F", 4, -1, 11)}


def clef_xml(clef: str, number: int) -> str:
    sign, line, octave, _ = CLEFS[clef]
    return (f'<clef number="{number}"><sign>{sign}</sign><line>{line}</line>'
            + (f"<clef-octave-change>{octave}</clef-octave-change>" if octave else "") + "</clef>")


def ledger_lines(note: Note, clef: str) -> int:
    """How many ledger lines the note needs in this clef."""
    bottom = CLEFS[clef][3]
    position = 7 * note.octave + LETTERS.index(note.letter)
    return (bottom - position) // 2 if position < bottom else max(0, (position - bottom - 8) // 2)


def choose_clefs(bars: list[list[Note]], first: str = "G", options=("G", "F", "F8vb", "G8va"), change: float = 6.0) -> list[str]:
    """A clef for every bar of one staff, given the notes of each bar: the clefs that need the fewest
    ledger lines over the whole piece (a note beyond three lines counts three times for each further
    one), a change of clef counting as much as `change` ledger lines (so a single low note does not
    bring a bass clef, a passage does) and a clef with an 8 a line and a half
    per note (the bass clef serves down to C2). An empty bar keeps the clef before it; `first` wins a tie in the first bar."""
    if not bars:
        return []
    def cost(notes, clef):
        lines = [ledger_lines(n, clef) for n in notes]
        return sum(k + 2 * max(0, k - 3) for k in lines) + (1.5 * len(lines) if CLEFS[clef][2] else 0.0)
    best = {c: (cost(bars[0], c) + (0.0 if c == first else 0.01), [c]) for c in options}
    for notes in bars[1:]:
        new = {}
        for c in options:
            before = min(options, key=lambda b: (best[b][0] + (change if b != c else 0.0), options.index(b)))
            new[c] = (best[before][0] + (change if before != c else 0.0) + cost(notes, c), best[before][1] + [c])
        best = new
    return min((best[c] for c in options), key=lambda item: item[0])[1]


def set_clefs(score: Score, staves=None) -> None:
    """Choose the clefs of the given staves (default: all) after their notes (`choose_clefs`): the
    first one goes into the part, every change into `score.clefs` at the bar where it begins."""
    starts = [b.start for b in score.bars]
    owner = [(part, s) for part in score.parts for s in range(len(part.clefs))]
    for staff in (range(len(owner)) if staves is None else staves):
        part, s = owner[staff]
        bars: list[list[Note]] = [[] for _ in score.bars]
        for e in score.events:
            if e.staff == staff and starts[0] <= e.onset < starts[-1] + score.bars[-1].length:
                first = bisect_right(starts, e.onset) - 1
                for i in range(first, len(starts)):           # a note held over the barline is drawn in the next bar too
                    if i > first and starts[i] >= e.onset + e.dur:
                        break
                    bars[i].extend(e.notes)
        chosen = choose_clefs(bars, first=part.clefs[s])
        used = next((c for c, notes in zip(chosen, bars) if notes), chosen[0])       # no change of clef before the first note
        part.clefs[s] = last = used
        seen = False
        for i, (clef, notes) in enumerate(zip(chosen, bars)):
            seen = seen or bool(notes)
            if seen and clef != last:
                score.clefs[(i, staff)] = last = clef


def alter_text(value: float) -> str:
    return f"{round(value, 4):g}"


def key_xml(key: list[tuple[str, str]]) -> str:
    """A key signature of any signs (MusicXML's non-traditional key); none = no signature."""
    if not key:
        return "<key><fifths>0</fifths></key>"
    plain = {name for _, name in key}
    if plain <= {"sharp"} or plain <= {"flat"}:
        order = "FCGDAEB" if plain == {"sharp"} else "BEADGCF"
        if [letter for letter, _ in key] == list(order[:len(key)]):
            return f"<key><fifths>{len(key) if plain == {'sharp'} else -len(key)}</fifths></key>"
    out = "<key>"
    for letter, name in key:
        alter, value, glyph = ACCIDENTALS[name]
        out += f"<key-step>{letter}</key-step><key-alter>{alter_text(alter)}</key-alter>" + accidental_xml(name, "key-accidental")
    return out + "</key>"


def accidental_xml(name: str, tag: str = "accidental") -> str:
    _, value, glyph = ACCIDENTALS[name]
    return f'<{tag} smufl="{glyph}">other</{tag}>' if value == "other" else f"<{tag}>{value}</{tag}>"


def direction_xml(mark: Mark, staff: int) -> str:
    if mark.tempo:
        number = re.match(r"[\d.]+", mark.text)
        kind = f"<metronome><beat-unit>quarter</beat-unit><per-minute>{escape(mark.text)}</per-minute></metronome>"
        sound = f'<sound tempo="{number.group(0)}"/>' if number else ""
    else:
        size = ' font-weight="bold" font-size="12"' if mark.text == "?" else ' font-size="8"'
        kind, sound = f"<words{size}>{escape(mark.text)}</words>", ""
    return f'<direction placement="above"><direction-type>{kind}</direction-type><staff>{staff}</staff>{sound}</direction>'


def voice_xml(voice: list[Seg], number: int, staff: int, ticks) -> list[str]:
    out: list[str] = []
    for seg in voice:
        duration = ticks(seg.end - seg.start)
        if seg.hidden:
            out.append(f"<forward><duration>{duration}</duration><voice>{number}</voice><staff>{staff}</staff></forward>")
            continue
        value = f"<voice>{number}</voice><type>{seg.kind}</type>" + "<dot/>" * seg.dots
        modification, tuplet = "", ""
        if seg.tuplet:
            t = seg.tuplet
            modification = (f"<time-modification><actual-notes>{t.actual}</actual-notes><normal-notes>{t.normal}</normal-notes>"
                            f"<normal-type>{note_value(t.unit)[0]}</normal-type></time-modification>")
            usual = t.normal == 2 ** (t.actual.bit_length() - 1) and t.normal < t.actual
            if seg.tuplet_start:
                tuplet += f'<tuplet type="start" bracket="yes" show-number="{"actual" if usual else "both"}"/>'
            if seg.tuplet_stop:
                tuplet += '<tuplet type="stop"/>'
        if seg.event is None:
            out.append(f"<note><rest/><duration>{duration}</duration>{value}{modification}<staff>{staff}</staff>"
                       + (f"<notations>{tuplet}</notations>" if tuplet else "") + "</note>")
            continue
        for extra in seg.grace:
            for k, note in enumerate(sorted(extra.notes, key=pitch_number)):
                held = id(note) in seg.grace_tied
                out.append('<note><grace slash="yes"/>' + ("<chord/>" if k else "") + pitch_xml(note) + ('<tie type="start"/>' if held else "")
                           + f"<voice>{number}</voice><type>eighth</type>" + accidental_xml(note.accidental) + f"<staff>{staff}</staff>"
                           + ('<notations><tied type="start"/></notations>' if held else "") + "</note>")
        ev = seg.event
        for position, k in enumerate(sorted(range(len(ev.notes)), key=lambda k: pitch_number(ev.notes[k]))):
            note = ev.notes[k]
            ties = ('<tie type="stop"/>' if k in seg.tie_stop else "") + ('<tie type="start"/>' if k in seg.tie_start else "")
            notations = ('<tied type="stop"/>' if k in seg.tie_stop else "") + ('<tied type="start"/>' if k in seg.tie_start else "")
            if position == 0:
                notations += tuplet
                if ev.staccato and seg.first:
                    notations += "<articulations><staccato/></articulations>"
                if ev.fermata and seg.first:
                    notations += "<fermata/>"
            out.append("<note>" + ("<chord/>" if position else "") + pitch_xml(note) + f"<duration>{duration}</duration>{ties}{value}"
                       + (accidental_xml(seg.show[k]) if k in seg.show else "") + modification
                       + ('<notehead parentheses="yes">normal</notehead>' if note.other else "") + f"<staff>{staff}</staff>"
                       + (f'<beam number="1">{seg.beam}</beam>' if seg.beam and position == 0 else "")
                       + (f"<notations>{notations}</notations>" if notations else "") + "</note>")
    return out


def pitch_xml(note: Note) -> str:
    alter = note.alter if note.alter is not None else ACCIDENTALS[note.accidental][0]
    return (f"<pitch><step>{note.letter}</step>" + (f"<alter>{alter_text(alter)}</alter>" if round(alter, 4) else "")
            + f"<octave>{note.octave}</octave></pitch>")


# ---------------------------------------------------------------- scores in bars with two staves (the Woyten pieces)

def parse_name(name: str) -> tuple[str, str, int]:
    """Letter, accidental name and octave of a note name such as "Ct4", "Edb4", "C#^4", "F+3"."""
    m = re.fullmatch(r"([A-G])([^\d-]*)(-?\d+)", name)
    if not m or m.group(2) not in NAME_SUFFIX:
        raise ValueError(f"cannot read the note name {name!r}")
    return m.group(1), NAME_SUFFIX[m.group(2)], int(m.group(3))


def edo_alter(step: int, edo: int, letter: str, octave: int) -> float:
    """`<alter>` of a note in an equal tuning (step 0 = C0, the letters a chain of the tuning's fifths):
    its pitch in semitones from A4, minus where the letter lies in 12 tones. In 17 notes per octave
    (A4 = step 81) a half-sharp C4 is 0.53 and a plain D4 -0.06 (its fifth to A is 6 cents wide)."""
    a4 = 4 * edo + 3 * round(edo * math.log2(1.5)) - edo
    return round((step - a4) * 12 / edo - (12 * octave + LETTER_SEMITONES[letter] - 57), 4)


def bars_score(data: dict, header: list[str] | None = None, doubtful=()) -> Score:
    """Score of a file with `bars`: [{"n", "time", "staves": {"upper": [...], "lower": [...]}}], events
    {"beat" (1 = barline), "dur", "notes": [{"step", "name", "accidental"?, "tied"?, "also"?}]}. The
    spelling is the stored one. Where a note has an `accidental` field, its signs mean what they mean in
    12 tones (arrow = 25 cents) and `alter` follows the sign; where it has only a name in the tuning's
    own signs (17 notes per octave), `alter` is the tuning's pitch, see `edo_alter`."""
    edo = data["tuning"]["edo"] if isinstance(data["tuning"], dict) else int(data["tuning"])
    keys: dict[int, list[tuple[str, str]]] = {}
    for span, text in (data.get("key_signatures") or {}).items():
        keys[int(span.split("-")[0])] = [parse_name(word + "0")[:2] for word in text.split()]
    score = Score(data.get("title", ""), [Part("")], [], [], header=list(header or []), composer=data.get("composer", ""), keep_values=True)
    marked: set[tuple] = set()
    at = Fraction(0)
    for bar in data["bars"]:
        length = bar_length(bar["time"])
        score.bars.append(Bar(bar["n"], bar["time"], at, length, keys.get(bar["n"]), bool(bar.get("repeat_start")), bool(bar.get("repeat_end")),
                              int(bar.get("volta") or 0)))
        for staff, name in enumerate(("upper", "lower")):
            for e in bar["staves"].get(name) or []:
                if e.get("rest") or not e.get("notes"):
                    continue
                notes = []
                for n in e["notes"]:
                    letter, accidental, octave = parse_name(n["name"])
                    if n.get("accidental") in ACCIDENTALS:
                        accidental = n["accidental"]
                    alter = None
                    if edo % 12 and "accidental" not in n and isinstance(n.get("step"), int):
                        alter = edo_alter(n["step"], edo, letter, octave)
                    other = (n.get("also") or [{}])[0]
                    notes.append(Note(letter, octave, accidental, alter, bool(n.get("tied")), other.get("name", ""),
                                      SOURCE_SHORT.get(other.get("source", ""), other.get("source", ""))))
                score.events.append(Event(staff, at + frac(e["beat"]) - 1, frac(e["dur"]), notes, int(e.get("voice") or 0), bool(e.get("grace")),
                                          bool(e.get("fermata")), bool(e.get("staccato"))))
        if bar["n"] in doubtful:
            marked.add((at, 0))
        at += length
    by_number = {b.number: b for b in score.bars}
    for u in data.get("uncertain") or []:
        bar = by_number.get(u.get("bar"))
        if bar is not None:
            onset = bar.start + min(frac(u.get("beat", 1)) - 1, bar.length - Fraction(1, 4))
            for staff in ((0, 1) if u.get("staff") == "both" else (1,) if u.get("staff") == "lower" else (0,)):
                marked.add((onset, staff))
    score.marks += [Mark(onset, staff, "?") for onset, staff in sorted(marked)]
    for t in data.get("tempo") or []:
        if t.get("bar") in by_number:
            score.marks.append(Mark(by_number[t["bar"]].start, 0, f"{t['bpm']:g}", tempo=True))
    return score


# ---------------------------------------------------------------- Wyschnegradsky, 24 Preludes op. 22

SHARP_SPELLING = [("C", "natural"), ("C", "sharp"), ("D", "natural"), ("D", "sharp"), ("E", "natural"), ("F", "natural"),
                  ("F", "sharp"), ("G", "natural"), ("G", "sharp"), ("A", "natural"), ("A", "sharp"), ("B", "natural")]
FLAT_SPELLING = [("C", "natural"), ("D", "flat"), ("D", "natural"), ("E", "flat"), ("E", "natural"), ("F", "natural"),
                 ("G", "flat"), ("G", "natural"), ("A", "flat"), ("A", "natural"), ("B", "flat"), ("B", "natural")]
QUARTER_LOWER = {"natural": "half-flat", "sharp": "half-sharp", "flat": "sesquiflat"}


class Speller:
    """Sharp or flat for the black keys of one staff, since the prelude file holds key numbers only.
    The rule, in this order: (1) as the same key was spelled earlier in the bar; (2) in a chord, not on
    the line of a white key that is in the chord too; (3) sharp when the note is higher than the nearest
    note of the chord before, flat when it is lower; (4) sharp."""

    def __init__(self) -> None:
        self.bar = None
        self.seen: dict[int, bool] = {}
        self.before: list[int] = []

    def chord(self, bar: int, keys: list[int]) -> dict[int, tuple[str, str, int]]:
        """`keys`: semitones above C0 (C4 = 48). Returns key -> (letter, accidental, octave)."""
        if bar != self.bar:
            self.bar, self.seen = bar, {}
        out = {}
        for key in sorted(set(keys)):
            sharp = SHARP_SPELLING[key % 12][1] == "sharp"
            if sharp:
                if key % 12 in self.seen:
                    sharp = self.seen[key % 12]
                elif (key - 1 in keys) != (key + 1 in keys):
                    sharp = key + 1 in keys
                elif self.before:
                    nearest = min(self.before, key=lambda k: abs(k - key))
                    sharp = key >= nearest
                self.seen[key % 12] = sharp
            letter, accidental = (SHARP_SPELLING if sharp else FLAT_SPELLING)[key % 12]
            out[key] = (letter, accidental, key // 12)
        self.before = sorted(set(keys))
        return out


def choose_staves(notes: list[tuple[Fraction, Fraction, int]]) -> list[int]:
    """Upper (0) or lower (1) staff for the notes of one piano, given as (onset, end, key) in order of
    onset: above F4 upper, below G3 lower, in between the staff of the nearest note that sounded within
    the last two quarters, else upper from middle C."""
    out: list[int] = []
    recent: list[tuple[Fraction, int, int]] = []
    for onset, end, key in notes:
        if key > 53:
            staff = 0
        elif key < 43:
            staff = 1
        else:
            recent = [r for r in recent if r[0] > onset - 2]
            near = min(recent, key=lambda r: abs(r[1] - key), default=None)
            staff = near[2] if near and abs(near[1] - key) <= 7 else (0 if key >= 48 else 1)
        out.append(staff)
        recent.append((end, key, staff))
    return out


def prelude_seconds(prelude: dict):
    """A function from quarter notes to seconds for one prelude, after its `tempi` ([{"onset",
    "bpm_quarter"}], the last one given for a moment counts; 80 where none is given)."""
    marks: dict[float, float] = {}
    for t in prelude.get("tempi") or []:
        bpm = float(t.get("bpm_quarter") or t.get("bpm") or 0)
        if bpm > 0:
            marks[float(t.get("onset") or 0.0)] = bpm
    if 0.0 not in marks:
        marks[0.0] = min(marks.items())[1] if marks else 80.0
    table, at = [], 0.0                                   # (from quarter, seconds there, seconds per quarter)
    ordered = sorted(marks.items())
    for k, (onset, bpm) in enumerate(ordered):
        table.append((onset, at, 60.0 / bpm))
        if k + 1 < len(ordered):
            at += (ordered[k + 1][0] - onset) * 60.0 / bpm
    starts = [row[0] for row in table]

    def seconds(quarter: float) -> float:
        onset, at, each = table[max(0, bisect_right(starts, quarter) - 1)]
        return round(at + (quarter - onset) * each, 6)

    return seconds


def prelude_hands(prelude: dict, model=None) -> tuple[list[dict], list[int]]:
    """The sounding notes of a prelude (both pianos, in order of onset and pitch) and the staff of each
    in the layout for one player: 0 = upper staff = right hand, 1 = lower staff = left hand. Where the
    file has the hand from the composer's own edition for one instrument (`hand`: "right" or "left",
    read from op. 22a on two staves), that is taken. Otherwise a note
    stays on the staff it is printed on (`staff`: "upper" or "lower" within its piano): the upper
    staves of both pianos become the upper staff, the lower staves the lower one. Notes without `staff`
    (bars typed in by hand) are placed by `hands.assign_hands` with all the others held fixed, so that
    they go on with the lines around them (times in seconds after the prelude's tempi, pitch in
    quarter-tone steps). The library and the sheet both take the division from here."""
    from .hands import DEFAULT, assign_hands
    notes = sorted((n for n in prelude["notes"] if float(n["dur"]) > 0), key=lambda n: (n["onset"], n["step"]))
    known = [{"right": 0, "left": 1}.get(n.get("hand"), {"upper": 0, "lower": 1}.get(n.get("staff"))) for n in notes]
    if None not in known:
        return notes, known
    seconds = prelude_seconds(prelude)
    timed = [(seconds(float(n["onset"])), seconds(float(n["onset"]) + float(n["dur"])), int(n["step"])) for n in notes]
    return notes, assign_hands(timed, per_octave=24, middle=96, model=model or DEFAULT, fixed=known)


def prelude_bars(prelude: dict) -> tuple[list[Bar], dict[int, Fraction]]:
    """Bars of a prelude (zero-length bars left out, the others renumbered: the engraver's numbers) and
    the start of every bar of the file's own numbering. Same arithmetic as `library_build.wyschnegradsky`."""
    changes = sorted(prelude.get("time_changes") or [{"bar": 1, "time": prelude.get("time", "4/4")}], key=lambda c: c["bar"])
    empty = set(prelude.get("zero_length_bars") or [])
    bars, starts, at = [], {}, Fraction(0)
    for n in range(1, int(prelude["bars"]) + 1):
        time = [c["time"] for c in changes if c["bar"] <= n][-1]
        starts[n] = at
        if n not in empty:
            bars.append(Bar(len(bars) + 1, time, at, bar_length(time)))
            at += bar_length(time)
    return bars, starts


def key_name(key: int, flat: bool = False) -> str:
    letter, accidental = (FLAT_SPELLING if flat else SHARP_SPELLING)[key % 12]
    return f"{letter}{SUFFIX_OF[accidental]}{key // 12}"


def updown_note(step: int) -> Note:
    """A quarter-tone step (C4 = 96) as xenharmlib's ups-and-downs notation names it in 24 notes per
    octave, the names the tutor uses: an arrow is one step (50 cents), a sharp two. xenharmlib's first
    name has sharps only and at most one arrow: C, ^C, C#, vD, D ..."""
    from ..theory import tuning_for
    name = tuning_for(24).name(step)
    arrows = len(name) - len(name.lstrip("^v"))
    letter, base, octave = parse_name(name[arrows:])
    if arrows > 1 or (arrows and base != "natural"):
        raise ValueError(f"no sign for {name}")
    if not arrows:
        return Note(letter, octave, base)
    up = name[0] == "^"
    return Note(letter, octave, "natural-arrow-up" if up else "natural-arrow-down", alter=0.5 if up else -0.5)


def prelude_score(prelude: dict, sounding: bool = False, doubtful=(), updown: bool = False) -> Score:
    """One prelude on four staves. Steps are quarter-tones (C4 = 96); piano II has the odd ones and is
    written, as in the two-piano edition, a quarter-tone above what sounds: in ordinary notation. With
    `sounding` piano II keeps the same letters and gets quarter-tone signs for the pitch that sounds
    (natural -> quarter-flat, sharp -> quarter-sharp, flat -> three-quarter-flat). On the four staves
    the staff of a note within its piano is chosen by pitch (`choose_staves`), as before.
    With `updown` the music is laid out for one player on two staves: every note on the staff it is
    printed on (`prelude_hands`: upper = right hand, lower = left hand), named in ups and downs, and
    the clefs follow what each staff holds (`set_clefs`)."""
    bars, starts = prelude_bars(prelude)
    total = bars[-1].start + bars[-1].length
    sounding = sounding or updown
    second = "Piano II (sounding pitch, quarter-tone signs)" if sounding else "Piano II (sounds a quarter-tone lower)"
    # in ups and downs the music is one quarter-tone instrument on two staves, as in the composer's own reduction (op. 22a)
    parts = [Part("Quarter-tone piano")] if updown else [Part("Piano I"), Part(second, transpose=0.0 if sounding else -0.5)]
    score = Score(prelude.get("title") or f"Prelude {prelude['number']}", parts, bars, [], composer="Ivan Wyschnegradsky, 24 Préludes op. 22")
    bar_starts = [b.start for b in bars]
    for piano in ((0,) if updown else (1, 2)):          # 0: both pianos together
        raw = sorted((n for n in prelude["notes"] if piano in (0, n["piano"]) and float(n["dur"]) > 0), key=lambda n: (n["onset"], n["step"]))
        timed = [(frac(n["onset"]), frac(n["onset"]) + frac(n["dur"]), (int(n["step"]) + 1) // 2 if updown else (int(n["step"]) + piano - 1) // 2)
                 for n in raw]
        staves = prelude_hands(prelude)[1] if updown else choose_staves(timed)       # one player: the printed staff; else by pitch
        chords: dict[tuple, list] = {}
        for n, (onset, end, key), staff in zip(raw, timed, staves):
            if piano and (int(n["step"]) + piano - 1) % 2:
                score.warnings.append(f"piano {piano}, step {n['step']} at {onset}: not a key of this piano, left out")
                continue
            chords.setdefault((staff, onset), []).append((end - onset, key, n))
        spellers = (Speller(), Speller())
        for (staff, onset), members in sorted(chords.items(), key=lambda c: (c[0][1], c[0][0])):
            if onset >= total:
                score.warnings.append(f"piano {piano}: note at {onset} after the last bar, left out")
                continue
            spelled = spellers[staff].chord(bisect_right(bar_starts, onset), [key for _, key, _ in members])
            by_length: dict[Fraction, list[Note]] = {}
            used: set[tuple] = set()
            for dur, key, n in members:
                if updown:
                    key = int(n["step"])            # two notes a quarter-tone apart share a written key number: tell them apart
                if (dur, key) in used:
                    score.warnings.append(f"piano {piano}, {key_name(key)} at {onset}: the same key twice with the same length, written once")
                    continue
                used.add((dur, key))
                letter, accidental, octave = spelled[(key + 1) // 2 if updown else key]
                note = Note(letter, octave, accidental)
                if updown:
                    note = updown_note(int(n["step"]))
                elif sounding and piano == 2:
                    note.accidental = QUARTER_LOWER[accidental]
                for other in (n.get("also") or [])[:1]:
                    if updown and other.get("source") == "engraving":
                        continue        # the playing sheet follows the print; the engraver's slips are shown on the four-staff sheet only
                    other_key = (int(other["step"]) + piano - 1) // 2
                    note.other = key_name(other_key, flat=accidental == "flat" or other_key > key)
                    if updown:
                        from ..theory import tuning_for
                        note.other = tuning_for(24).name(int(other["step"]))
                    elif sounding and piano == 2:
                        o_letter, o_accidental = (FLAT_SPELLING if "b" in note.other else SHARP_SPELLING)[other_key % 12]
                        note.other = f"{o_letter}{SUFFIX_OF[QUARTER_LOWER[o_accidental]]}{other_key // 12}"
                    note.other_source = SOURCE_SHORT.get(other.get("source", ""), other.get("source", ""))
                by_length.setdefault(dur, []).append(note)
            for dur, notes in by_length.items():
                score.events.append(Event(staff if updown else 2 * (piano - 1) + staff, onset, dur, notes))
    marked = {(starts[u["bar"]], 0 if updown else 2 * (int(u.get("piano", 1)) - 1)) for u in prelude.get("uncertain") or [] if u.get("bar") in starts}
    marked |= {(starts[b], 0) for b in doubtful if b in starts}
    score.marks += [Mark(onset, staff, "?") for onset, staff in sorted(marked) if onset < total]
    tempi: dict[Fraction, list[str]] = {}
    for t in prelude.get("tempi") or []:
        if frac(t["onset"]) < total:
            tempi.setdefault(frac(t["onset"]), []).append(f"{t['bpm_quarter']:g}")
    score.marks += [Mark(onset, 0, " / ".join(values), tempo=True) for onset, values in sorted(tempi.items())]
    if updown:
        set_clefs(score)                 # each staff holds what its hand plays, wherever that lies: the clef follows
    return score


# ---------------------------------------------------------------- engraving

def find_musescore() -> str | None:
    """MuseScore's program if there is one: on the path, under Program Files, or unpacked in reference/tools."""
    for name in ("MuseScore4.exe", "MuseScore3.exe", "mscore", "musescore", "mscore3"):
        found = shutil.which(name)
        if found:
            return found
    places = [Path(p) for p in (r"C:\Program Files", r"C:\Program Files (x86)") if Path(p).exists()]
    for place in places:
        for exe in sorted(place.glob("MuseScore*/bin/MuseScore*.exe"), reverse=True):
            return str(exe)
    tools = ROOT / "reference" / "tools"
    if tools.exists():
        for exe in sorted(tools.glob("**/MuseScore*.exe"), reverse=True):
            return str(exe)
    return None


def engraver() -> str:
    exe = find_musescore()
    if exe:
        return f"MuseScore ({exe})"
    import verovio
    return f"Verovio {verovio.toolkit().getVersion()} ({Path(verovio.__file__).parent})"


VEROVIO_OPTIONS = {
        "pageMarginTop": 100, "pageMarginBottom": 80, "pageMarginLeft": 80, "pageMarginRight": 80,
    "footer": "none", "header": "auto", "mnumInterval": 1, "breaks": "auto", "condense": "none",
    "spacingLinear": 0.5, "spacingNonLinear": 0.6, "spacingStaff": 10, "spacingSystem": 10,
    "svgRemoveXlink": True, "smuflTextFont": "none",
}


def render_pdf(xml_path: Path | str, pdf_path: Path | str, staff_mm: float = 6.0) -> int:
    """Engrave a MusicXML file as PDF (A4) and return the number of pages; `staff_mm` is the height of
    a staff (Verovio only: its staff is 72 units high, so the page is given so many units). MuseScore if installed,
    else Verovio: its SVG pages are converted by PyMuPDF, which knows neither style sheets nor nested
    <svg> nor the music font in texts, so `plain_svg` rewrites those parts first."""
    xml_path, pdf_path = Path(xml_path), Path(pdf_path)
    import pymupdf
    exe = find_musescore()
    if exe:
        subprocess.run([exe, "-o", str(pdf_path), str(xml_path)], check=True, capture_output=True, timeout=600)
        with pymupdf.open(pdf_path) as doc:
            return doc.page_count
    import verovio
    verovio.enableLog(verovio.LOG_OFF)                 # it reports every tightly set system on stderr
    toolkit = verovio.toolkit()
    toolkit.setOptions({**VEROVIO_OPTIONS, "pageWidth": round(210 * 72 / staff_mm), "pageHeight": round(297 * 72 / staff_mm)})
    if not toolkit.loadData(xml_path.read_text(encoding="utf-8")):
        raise RuntimeError(f"Verovio cannot read {xml_path}: {toolkit.getLog()}")
    a4 = pymupdf.paper_rect("a4")
    out = pymupdf.open()
    for number in range(1, toolkit.getPageCount() + 1):
        svg = plain_svg(toolkit.renderToSVG(number))
        with pymupdf.open(stream=svg.encode("utf-8"), filetype="svg") as page:
            source = pymupdf.open("pdf", page.convert_to_pdf())
        out.new_page(width=a4.width, height=a4.height).show_pdf_page(a4, source, 0)
    out.save(pdf_path, garbage=3, deflate=True)
    pages = out.page_count
    out.close()
    return pages


def plain_svg(svg: str) -> str:
    """Verovio's SVG without what PyMuPDF's SVG reader ignores: the inner <svg viewBox> becomes a scaled
    group, the style sheet's rules (lines are stroked, placeholders hidden, tempo bold) become
    attributes, and the quarter note of a metronome mark (a character of the music font) is drawn."""
    inner = re.search(r'<svg class="definition-scale"[^>]*viewBox="0 0 (\d+) (\d+)"[^>]*>', svg)
    width = float(re.search(r'<svg width="([\d.]+)px"', svg).group(1))
    head, tail = svg[:inner.start()], svg[inner.end():]
    close = tail.rfind("</svg>", 0, tail.rfind("</svg>"))
    tail = tail[:close] + "</g>" + tail[close + 6:]
    tail = re.sub(r"<style.*?</style>", "", tail, flags=re.S)
    tail = re.sub(r'<g [^>]*class="[^"]*placeholder[^"]*"[^>]*>\s*<ellipse[^>]*/>\s*</g>', "", tail)
    tail = tail.replace("<text ", '<text stroke="none" ')
    tail = re.sub(r'(<g [^>]*class="(?:tempo|ending)")', r'\1 font-weight="bold"', tail)
    tail = re.sub(r'(<g [^>]*class="mNum")', r'\1 font-style="italic"', tail)

    def metronome(match: re.Match) -> str:
        x, y, size = float(match.group(1)), float(match.group(2)), float(match.group(4))
        r = size * 0.13
        note = (f'<ellipse cx="{x + r * 1.2:.0f}" cy="{y - r * 0.8:.0f}" rx="{r * 1.25:.0f}" ry="{r * 0.85:.0f}" transform="rotate(-20 {x + r * 1.2:.0f} {y - r * 0.8:.0f})"/>'
                f'<rect x="{x + r * 2.2:.0f}" y="{y - r * 7:.0f}" width="{r * 0.25:.0f}" height="{r * 6.2:.0f}"/>')
        return note + f'<text stroke="none" x="{x + r * 3:.0f}" y="{y:.0f}"{match.group(3)}>'

    tail = re.sub(r'<text stroke="none" x="([\d.-]+)" y="([\d.-]+)"([^>]*)>\s*<tspan[^>]*>\s*<tspan[^>]*>\s*<tspan font-family="\w+" font-size="([\d.]+)px">[^<]*</tspan>\s*</tspan>\s*</tspan>',
                  metronome, tail)
    title = re.search(r'class="pgHead">.*?<tspan font-size="(\d+)px">', tail, flags=re.S)
    if title:
        tail = tail[:title.start(1)] + str(int(int(title.group(1)) * 1.7)) + tail[title.end(1):]
    scale = width / float(inner.group(1))
    return (head + f'<g transform="scale({scale})" font-family="Times, serif" fill="black" stroke="black">' + tail).replace("currentColor", "black")


# ---------------------------------------------------------------- command line

PRELUDE_HEADER = ["Machine reading of Ueli Raz's engraving (wyschnegradsky-22.pdf), not proofread; compare with the original.",
                  "Sharps or flats and the staff of each note are chosen by rule (the file holds keys only); bar numbers are the engraving's.",
                  "(x) = a note with a second reading, named above the staff in the same order; ? = doubtful bar."]
WOYTEN_HEADER = "(x) = a note with a second reading, named above the staff; ? = doubtful place. Voices, beams and stems are this sheet's."
SHEETS = [("woyten16/dont_take_five.json", "dont_take_five_as_read", "dont-take-five",
           "Machine reading of the score PDF (16 notes per octave, transcription by Stephen Weigel), not proofread; compare with the original."),
          ("woyten/final/ephemeral_happiness.json", "ephemeral_happiness_as_read", "ephemeral-happiness",
           "Machine reading (optical recognition) of the score in 17 notes per octave, not proofread; compare with the original.")]


def write_sheet(score: Score, base: Path, pdf: bool = True, staff_mm: float = 6.0) -> int:
    """Write `base`.musicxml (and .pdf); returns the number of pages (0 without PDF)."""
    base.parent.mkdir(parents=True, exist_ok=True)
    xml_path = base.with_name(base.name + ".musicxml")
    xml = to_musicxml(score)
    xml_path.write_text(xml, encoding="utf-8")
    if pdf and not find_musescore():
        missing = sorted(v for v in VEROVIO_UNDRAWN if f">{v}</accidental>" in xml)
        if missing:
            score.warnings.append(f"Verovio draws no sign for {', '.join(missing)}: these notes look like naturals in the PDF")
    return render_pdf(xml_path, base.with_name(base.name + ".pdf"), staff_mm) if pdf else 0


def doubtful_bars() -> tuple[dict, dict]:
    """Doubtful bars the library keeps per piece (`library_build.SCORE_CHECKS`, `PRELUDES_DOUBTFUL`)."""
    try:
        from .. import library_build
    except ImportError:
        return {}, {}
    return ({slug: check.get("doubtful", []) for slug, check in library_build.SCORE_CHECKS.items()}, dict(library_build.PRELUDES_DOUBTFUL))


def write_all(source: Path = MUSIC, sounding: bool = False, pdf: bool = True, log=print, updown: bool = False) -> list[Path]:
    """All sheets of our readings, next to the files they show (`sheets/` in each folder)."""
    by_slug, by_prelude = doubtful_bars()
    written: list[Path] = []
    for relative, name, slug, header in SHEETS:
        path = source / relative
        if not path.exists():
            continue
        score = bars_score(json.loads(path.read_text(encoding="utf-8")), [header, WOYTEN_HEADER], by_slug.get(slug, ()))
        base = path.parent / "sheets" / name
        pages = write_sheet(score, base, pdf, staff_mm=6.5)
        written.append(base.with_name(name + (".pdf" if pdf else ".musicxml")))
        log(f"{written[-1]}: {len(score.bars)} bars, {pages} pages, {len(score.warnings)} warnings")
        for warning in score.warnings:
            log(f"   {warning}")
    path = source / "wyschnegradsky" / "preludes.json"
    if path.exists():
        preludes = json.loads(path.read_text(encoding="utf-8"))
        for mode in [False] + (["sounding"] if sounding else []) + (["updown"] if updown else []):
            parts = []
            for prelude in preludes:
                number = int(prelude["number"])
                score = prelude_score(prelude, sounding=mode == "sounding", doubtful=by_prelude.get(number, ()), updown=mode == "updown")
                score.header = list(PRELUDE_HEADER)
                if mode == "sounding":
                    score.header[2] = "Piano II at sounding pitch (same letters as written, a quarter-tone lower). " + score.header[2]
                if mode == "updown":
                    hands = ("hands as in the composer's two-staff edition (Belaieff 418)" if prelude.get("hands_from")
                             else "hands by the staves of the two-piano print, not yet the composer's two-staff layout")
                    score.header[1] = f"One quarter-tone instrument, {hands}; ups and downs: arrow = quarter-tone, sharp = semitone."
                base = path.parent / "sheets" / (f"prelude_{number:02d}" + (f"_{mode}" if mode else ""))
                pages = write_sheet(score, base, pdf, staff_mm=5.0)
                parts.append(base.with_name(base.name + ".pdf"))
                log(f"{parts[-1] if pdf else base}: {len(score.bars)} bars, {pages} pages, {len(score.warnings)} warnings")
                for warning in score.warnings:
                    log(f"   {warning}")
            if pdf:
                import pymupdf
                combined = pymupdf.open()
                for part in parts:
                    with pymupdf.open(part) as doc:
                        combined.insert_pdf(doc)
                target = path.parent / "sheets" / (f"preludes_as_read_{mode}.pdf" if mode else "preludes_as_read.pdf")
                combined.save(target, garbage=3, deflate=True)
                log(f"{target}: {combined.page_count} pages")
                combined.close()
                written += parts + [target]
    return written


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    flags = {flag: flag in args for flag in ("--all", "--sounding", "--updown", "--pdf", "--no-pdf")}
    number = None
    if "--prelude" in args:
        number = int(args[args.index("--prelude") + 1])
        del args[args.index("--prelude"):args.index("--prelude") + 2]
    args = [a for a in args if a not in flags]
    if flags["--all"]:
        print(f"engraver: {engraver()}")
        write_all(sounding=flags["--sounding"], pdf=not flags["--no-pdf"], updown=flags["--updown"])
        return 0
    if not 1 <= len(args) <= 2:
        print(__doc__)
        return 2
    data = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    if isinstance(data, list):
        prelude = next(p for p in data if int(p["number"]) == (number or 1))
        score = prelude_score(prelude, sounding=flags["--sounding"], updown=flags["--updown"])
        score.header = list(PRELUDE_HEADER)
    else:
        score = bars_score(data, ["Machine reading, not proofread; compare with the original."])
    out = Path(args[1]) if len(args) == 2 else Path(args[0]).with_suffix(".musicxml")
    out.write_text(to_musicxml(score), encoding="utf-8")
    for warning in score.warnings:
        print(warning, file=sys.stderr)
    if flags["--pdf"]:
        print(f"{out.with_suffix('.pdf')}: {render_pdf(out, out.with_suffix('.pdf'))} pages, engraver: {engraver()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
