"""Music theory for one equal tuning, in the terms a player uses: note names, interval
names, chords, scales.

Note and interval names come from xenharmlib (ups-and-downs notation: `^` raises and `v`
lowers a note by one step of the tuning; `#`, `b`, `x` as usual). A pitch is an integer
number of tuning steps above C0, the same numbering xentool and xenharmlib use; pitches
stay inside the server, tool results carry names.

Chords are defined by what they should sound like (pure ratios such as 4:5:6), not by step
counts, so one definition gives the right notes in every tuning: the major third above C is
E in 31 steps per octave and vE in 53.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from xenharmlib import EDOTuning, UpDownNotation
from xenharmlib.notation.updown import MixedLeftEnharmStrategy

LETTERS = "CDEFGAB"
C0_HZ = 16.351597831287414
_NOTE_RE = re.compile(r"^([v^]*)([A-Ga-g])([#xb]*)(-?\d+)?$")
_NUMBER_RE = re.compile(r"^(\d+)(?:\s*\(\s*(-?\d+)\s*\))?$")
_LABEL_TAIL_RE = re.compile(r"(?<=[A-Ga-g#bx\d])\s+\(\d+\)$")
_INTERVAL_RE = re.compile(r"^([v^]*)(AA|dd|[PMmAd]?)(-?)(\d+)$")
_ORDINALS = {
    1: "unison", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh",
    8: "octave", 9: "ninth", 10: "tenth", 11: "eleventh", 12: "twelfth", 13: "thirteenth",
}
_QUALITY_WORDS = {
    "P": "perfect", "M": "major", "m": "minor", "A": "augmented", "d": "diminished",
    "AA": "doubly augmented", "dd": "doubly diminished", "": "",
}
_UPS = {"": "", "^": "up", "^^": "double-up", "^^^": "triple-up", "v": "down", "vv": "double-down", "vvv": "triple-down"}


class TheoryError(ValueError):
    """A request the theory cannot answer; the message says what to change."""


def cents(ratio: float) -> float:
    return 1200.0 * math.log2(ratio)


# Building blocks of chords: name -> pure ratio.
_PURE = {
    "M3": 5 / 4, "m3": 6 / 5, "P5": 3 / 2, "P4": 4 / 3, "M2": 9 / 8,
    "sub3": 7 / 6, "sup3": 9 / 7, "n3": 11 / 9, "h7": 7 / 4,
}

# Chord qualities: tones above the root as sums of building blocks, each with the degree it
# is spelled on (3 = some kind of third: C -> E). m7 = P5 + m3 and M7 = P5 + M3, so a
# seventh agrees with the triads inside its chord.
CHORDS: dict[str, dict] = {
    "major": {"tones": [(("M3",), 3), (("P5",), 5)], "sounds": "4:5:6"},
    "minor": {"tones": [(("m3",), 3), (("P5",), 5)], "sounds": "10:12:15"},
    "diminished": {"tones": [(("m3",), 3), (("m3", "m3"), 5)], "sounds": "two minor thirds stacked"},
    "augmented": {"tones": [(("M3",), 3), (("M3", "M3"), 5)], "sounds": "two major thirds stacked"},
    "sus2": {"tones": [(("M2",), 2), (("P5",), 5)], "sounds": "8:9:12"},
    "sus4": {"tones": [(("P4",), 4), (("P5",), 5)], "sounds": "6:8:9"},
    "major7": {"tones": [(("M3",), 3), (("P5",), 5), (("P5", "M3"), 7)], "sounds": "8:10:12:15"},
    "dominant7": {"tones": [(("M3",), 3), (("P5",), 5), (("P5", "m3"), 7)], "sounds": "major triad with a minor seventh"},
    "minor7": {"tones": [(("m3",), 3), (("P5",), 5), (("P5", "m3"), 7)], "sounds": "10:12:15:18"},
    "half-diminished7": {"tones": [(("m3",), 3), (("m3", "m3"), 5), (("P5", "m3"), 7)], "sounds": "diminished triad with a minor seventh"},
    "major6": {"tones": [(("M3",), 3), (("P5",), 5), (("P4", "M3"), 6)], "sounds": "12:15:18:20, a major triad with the sixth"},
    "minor6": {"tones": [(("m3",), 3), (("P5",), 5), (("P4", "M3"), 6)], "sounds": "minor triad with a major sixth"},
    "diminished7": {"tones": [(("m3",), 3), (("m3", "m3"), 5), (("m3", "m3", "m3"), 7)], "sounds": "three minor thirds stacked"},
    "minor-major7": {"tones": [(("m3",), 3), (("P5",), 5), (("P5", "M3"), 7)], "sounds": "minor triad with a major seventh"},
    "dominant7sus4": {"tones": [(("P4",), 4), (("P5",), 5), (("P5", "m3"), 7)], "sounds": "a seventh chord with the fourth in place of the third"},
    # Qualities a 12-tone keyboard cannot play; offered only where the tuning has them.
    "subminor": {"tones": [(("sub3",), 3), (("P5",), 5)], "sounds": "6:7:9, darker than minor", "xen": True},
    "supermajor": {"tones": [(("sup3",), 3), (("P5",), 5)], "sounds": "14:18:21, brighter than major", "xen": True},
    "neutral": {"tones": [(("n3",), 3), (("P5",), 5)], "sounds": "18:22:27, between major and minor", "xen": True},
    "harmonic7": {"tones": [(("M3",), 3), (("P5",), 5), (("h7",), 7)], "sounds": "4:5:6:7, a seventh chord that sits still", "xen": True},
}
_ALIASES = {
    "maj": "major", "": "major", "M": "major", "min": "minor", "m": "minor", "dim": "diminished",
    "aug": "augmented", "+": "augmented", "maj7": "major7", "M7": "major7", "7": "dominant7",
    "dom7": "dominant7", "m7": "minor7", "min7": "minor7", "m7b5": "half-diminished7",
    "halfdiminished": "half-diminished7", "harmonic": "harmonic7", "6": "major6", "m6": "minor6", "dim7": "diminished7",
    "o7": "diminished7", "mmaj7": "minor-major7", "7sus": "dominant7sus4", "7sus4": "dominant7sus4", "sus": "sus4",
}

# Seven-note scales as positions on the chain of fifths around the tonic.
SCALES: dict[str, tuple[int, ...]] = {
    "major": (-1, 0, 1, 2, 3, 4, 5),
    "minor": (-4, -3, -2, -1, 0, 1, 2),
    "dorian": (-3, -2, -1, 0, 1, 2, 3),
    "phrygian": (-5, -4, -3, -2, -1, 0, 1),
    "lydian": (0, 1, 2, 3, 4, 5, 6),
    "mixolydian": (-2, -1, 0, 1, 2, 3, 4),
    "locrian": (-6, -5, -4, -3, -2, -1, 0),
}
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7}


@dataclass(frozen=True)
class Chord:
    root: int                   # pitch of the root (root position, before inversion)
    quality: str
    pitches: tuple[int, ...]    # ascending, bass first
    names: tuple[str, ...]      # spelled note names, same order
    intervals: tuple[str, ...]  # each note above the bass
    inversion: int
    label: str                  # "C major", "C major, 1st inversion"
    purity: tuple[str, ...]     # how close each tone is to its pure ratio


_TUNINGS: dict[int, "Tuning"] = {}


def tuning_for(edo: int) -> "Tuning":
    """The shared Tuning of an EDO. Building note names is slow (about a second for a
    whole keyboard), so the tables are kept for the life of the process."""
    if edo not in _TUNINGS:
        _TUNINGS[edo] = Tuning(edo)
    return _TUNINGS[edo]


class Tuning:
    """One equal division of the octave, with notation."""

    def __init__(self, edo: int):
        if not 5 <= edo <= 72:
            raise TheoryError(f"tunings from 5 to 72 equal steps per octave are supported, not {edo}")
        self.edo = edo
        self._tuning = EDOTuning(edo)
        self._notation = UpDownNotation(self._tuning)
        self._notation.enharm_strategy = MixedLeftEnharmStrategy(self._notation)
        self._steps = {name: self.steps_for(ratio) for name, ratio in _PURE.items()}
        self._steps["P4"] = edo - self._steps["P5"]
        self._steps["M2"] = 2 * self._steps["P5"] - edo
        self._spell_cache: dict = {}
        self._interval_cache: dict = {}
        self._symbol_table: tuple | None = None

    # --- sizes ---

    def steps_for(self, ratio: float) -> int:
        """The tuning's closest interval to a pure ratio."""
        return round(self.edo * math.log2(ratio))

    def cents_of(self, steps: int) -> float:
        return 1200.0 * steps / self.edo

    def hz(self, pitch: int) -> float:
        return C0_HZ * 2 ** (pitch / self.edo)

    # --- note names ---

    def _symbols(self) -> tuple[tuple[str, str, int, int, int], ...]:
        """Every note symbol the notation can write with up to three ups or downs and a
        double accidental: (symbol, letter, steps above C of the same octave number, number
        of ups/downs, weight of sharps/flats). Cb lies below its octave's C, B# above its
        octave's B."""
        if self._symbol_table is None:
            out = []
            for letter in LETTERS:
                for acc in ("", "#", "b", "x", "bb"):
                    for prefix in ("", "^", "v", "^^", "vv", "^^^", "vvv"):
                        try:
                            rel = self._notation.note(prefix + letter + acc, 4).pitch_index - 4 * self.edo
                        except Exception:
                            continue    # symbol not available in this tuning
                        weight = sum({"#": 1, "b": 1, "x": 2}[c] for c in acc)
                        out.append((prefix + letter + acc, letter, rel, len(prefix), weight))
            self._symbol_table = tuple(out)
        return self._symbol_table

    def spellings(self, pitch: int, letter: str | None = None) -> tuple[str, ...]:
        """Spellings of a pitch, plainest first (fewest ups, downs and accidentals); with
        `letter`, only those written on that letter."""
        key = (pitch, letter)
        if key not in self._spell_cache:
            primary = self._notation.guess_note(self._tuning.pitch(pitch)).short_repr
            found = []
            for symbol, sym_letter, rel, arrows, weight in self._symbols():
                if (pitch - rel) % self.edo == 0 and (letter is None or sym_letter == letter):
                    name = f"{symbol}{(pitch - rel) // self.edo}"
                    # Fewest signs first. On a given letter (chord tones): then no more than
                    # one up or down if possible (^Eb before vvE, ^^Gb before vvvG). Free
                    # choice of letter: then the fewest sharps and flats (^C before B#,
                    # vvE before vFb).
                    order = (max(0, arrows - 1), weight) if letter else (weight, arrows)
                    found.append((arrows + weight, order, name != primary, len(found), name))
            names = tuple(name for *_, name in sorted(found))
            self._spell_cache[key] = names or ((primary,) if letter is None else ())
        return self._spell_cache[key]

    def name(self, pitch: int) -> str:
        return self.spellings(pitch)[0]

    def name_with_letter(self, pitch: int, letter: str) -> str:
        """The spelling that uses `letter`, if the notation has one; else the plainest."""
        on_letter = self.spellings(pitch, letter)
        return on_letter[0] if on_letter else self.name(pitch)

    @staticmethod
    def pitch_class_name(name: str) -> str:
        """`vEb4` -> `vEb`."""
        return re.sub(r"-?\d+$", "", name)

    # --- note numbers ---
    # In tunings with many notes per octave, players usually call a note by its number: the
    # step within the octave, counted from C = 0. "17" in 53 is vE; "17(4)" is vE4.

    def number(self, pitch: int) -> int:
        return pitch % self.edo

    def label(self, pitch: int, name: str | None = None) -> str:
        """Name and number together, the way notes are written in lists: `vE4 (17)`."""
        return f"{name or self.name(pitch)} ({self.number(pitch)})"

    def _numbered(self, text: str) -> tuple[int, bool] | None:
        """`17` or `17(4)` -> (pitch, has_octave); None if the text is not a number."""
        m = _NUMBER_RE.match(text.strip())
        if not m:
            return None
        n, octave = int(m.group(1)), m.group(2)
        if n >= self.edo:
            raise TheoryError(f"note number {n} does not exist: this tuning numbers its notes 0 to {self.edo - 1} (C = 0)")
        return (int(octave) if octave else 4) * self.edo + n, octave is not None

    def _note(self, text: str):
        """xenharmlib note for a name, and whether the name had an octave."""
        t = text.strip().replace("♭", "b").replace("♯", "#").replace("𝄪", "x").replace("𝄫", "bb")
        t = _LABEL_TAIL_RE.sub("", t)       # "vE4 (17)", as the tools write it
        numbered = self._numbered(t)
        if numbered is not None:
            pitch, has_octave = numbered
            return self._notation.guess_note(self._tuning.pitch(pitch)), has_octave
        m = _NOTE_RE.match(t)
        if not m:
            raise TheoryError(
                f"'{text}' is not a note. Write a name (a letter A-G, optional # b x, optional leading ^ or v, "
                f"optional octave: C4, Eb, vE4, ^F#3) or a number with optional octave (17, 17(4))."
            )
        prefix, letter, acc, octave = m.groups()
        try:
            note = self._notation.note(prefix + letter.upper() + acc, int(octave) if octave else 4)
        except Exception as e:  # xenharmlib: symbol not available in this tuning
            raise TheoryError(
                f"'{text}' cannot be written in {self.edo} steps per octave. "
                f"Names near C4 in this tuning: {', '.join(self.name(4 * self.edo + i) for i in range(4))}."
            ) from e
        return note, octave is not None

    def parse(self, text: str) -> tuple[int, bool]:
        """A note name -> (pitch, has_octave). Without an octave the pitch is in octave 4."""
        note, has_octave = self._note(text)
        return note.pitch_index, has_octave

    def parse_safe(self, name: str) -> int | None:
        """Pitch of a note name, or None if this tuning cannot write it."""
        try:
            return self.parse(name)[0]
        except TheoryError:
            return None

    # --- interval names ---

    @staticmethod
    def _interval_plainness(short: str) -> float:
        m = _INTERVAL_RE.match(short)
        if not m:
            return 9.0
        prefix, q, _, _ = m.groups()
        return len(prefix) + {"P": 0, "M": 0, "m": 0, "": 0, "A": 1.5, "d": 1.5, "AA": 3, "dd": 3}[q]

    def interval_between(self, low: str, high: str) -> str:
        """Interval from one spelled note up to another, named after the spelling
        (C to ^Eb is an upminor third, C to D# an augmented second)."""
        a, b = self._note(low)[0], self._note(high)[0]
        if b.pitch_index < a.pitch_index:
            return "-" + self.interval_between(high, low)
        try:
            return self._notation.interval(a, b).short_repr
        except Exception:
            return self.interval(b.pitch_index - a.pitch_index)

    def interval(self, steps: int) -> str:
        """Short name of an interval, e.g. `M3`, `vm7`; the plainest of the possible ones."""
        if steps < 0:
            return "-" + self.interval(-steps)
        if steps not in self._interval_cache:
            c4 = self._note("C4")[0]
            names = []
            for spelling in self.spellings(4 * self.edo + steps):
                try:
                    short = self._notation.interval(c4, self._note(spelling)[0]).short_repr
                except Exception:
                    continue
                names.append((self._interval_plainness(short), len(names), short))
            self._interval_cache[steps] = min(names)[2] if names else f"{self.cents_of(steps):.0f} cents"
        return self._interval_cache[steps]

    @staticmethod
    def words(short: str) -> str:
        """`vM3` -> `downmajor third`, `P5` -> `perfect fifth`, `-M2` -> `major second down`."""
        down = short.startswith("-")
        m = _INTERVAL_RE.match(short.lstrip("-"))
        if not m:
            return short
        prefix, q, _, num = m.groups()
        n = int(num)
        number = _ORDINALS.get(n, f"{n}th")
        if n in (1, 8) and q == "P" and not prefix:
            text = number
        else:
            text = f"{_UPS.get(prefix, prefix)}{_QUALITY_WORDS[q]} {number}".strip()
        return text + (" down" if down else "")

    def interval_words(self, steps: int, short: str | None = None) -> str:
        """`downmajor third (vM3, 17 steps)`: words, short name and size in steps of the
        tuning. `short` overrides the name (when it follows from a chord's spelling)."""
        short = short or self.interval(abs(steps))
        n = abs(steps)
        return f"{self.words(short.lstrip('-'))} ({short.lstrip('-')}, {n} step{'' if n == 1 else 's'})"

    @staticmethod
    def letter_of(text: str) -> str | None:
        """The letter a note name is written on; None for a number."""
        m = re.match(r"^\s*[v^]*([A-Ga-g])", text)
        return m.group(1).upper() if m else None

    # --- chords ---

    def _tone_steps(self, quality: str) -> tuple[int, ...]:
        return tuple(sum(self._steps[p] for p in parts) for parts, _ in CHORDS[quality]["tones"])

    def tone_steps(self, quality: str) -> tuple[int, ...]:
        """The tones of a chord quality as steps above its root (the root itself left out)."""
        return self._tone_steps(self.quality_key(quality))

    def has(self, quality: str) -> bool:
        """Whether the tuning plays this quality as something of its own."""
        q = CHORDS[quality]
        if not q.get("xen"):
            return True
        if self._tone_steps(quality) in [self._tone_steps(k) for k, v in CHORDS.items() if not v.get("xen")]:
            return False    # same keys as an ordinary chord
        # each special tone within 20 cents of the sound it is named after
        return all(
            abs(self.cents_of(self._steps[parts[0]]) - cents(_PURE[parts[0]])) <= 20
            for parts, _ in q["tones"]
            if len(parts) == 1 and parts[0] in ("sub3", "sup3", "n3", "h7")
        )

    def qualities(self) -> list[str]:
        return [q for q in CHORDS if self.has(q)]

    @staticmethod
    def quality_key(text: str) -> str:
        t = text.strip()
        if t in CHORDS:
            return t
        if t in _ALIASES:
            return _ALIASES[t]
        low = t.lower().replace(" ", "").replace("-", "").replace("_", "").replace("triad", "").replace("seventh", "7").replace("chord", "")
        for k in CHORDS:
            if k.replace("-", "") == low:
                return k
        if low in _ALIASES:
            return _ALIASES[low]
        raise TheoryError(f"unknown chord quality '{text}'. Available: {', '.join(CHORDS)}.")

    def chord(self, root: int, quality: str, inversion: int = 0, root_name: str | None = None) -> Chord:
        """A chord on `root` in close position; `inversion` 0 = root in the bass."""
        quality = self.quality_key(quality)
        if not self.has(quality):
            raise TheoryError(
                f"{self.edo} steps per octave has no {quality} chord of its own "
                f"(it would be the same keys as another quality). Available: {', '.join(self.qualities())}."
            )
        spec = CHORDS[quality]
        rel = (0,) + self._tone_steps(quality)
        degrees = (1,) + tuple(d for _, d in spec["tones"])
        if not 0 <= inversion < len(rel):
            raise TheoryError(f"a {quality} chord has inversions 0 to {len(rel) - 1}, not {inversion}")
        root_name = root_name or self.name(root)
        root_letter = _NOTE_RE.match(root_name).group(2).upper()
        tones, purity = [], []
        for i, (steps, degree) in enumerate(zip(rel, degrees)):
            letter = LETTERS[(LETTERS.index(root_letter) + degree - 1) % 7]
            if i > 0 and len(spec["tones"][i - 1][0]) == 1:
                block = spec["tones"][i - 1][0][0]
                diff = self.cents_of(steps) - cents(_PURE[block])
                twelve = round(12 * math.log2(_PURE[block])) * 100 - cents(_PURE[block])
                above_root = self.interval_between(self.name_with_letter(root, root_letter), self.name_with_letter(root + steps, letter))
                purity.append(f"{self.words(above_root)}: {diff:+.0f} cents from pure (12-tone: {twelve:+.0f})")
            pitch = root + steps + (self.edo if i < inversion else 0)
            tones.append((pitch, self.name_with_letter(pitch, letter)))
        tones.sort()
        pitches = tuple(p for p, _ in tones)
        names = tuple(n for _, n in tones)
        ordinal = {0: "", 1: ", 1st inversion", 2: ", 2nd inversion", 3: ", 3rd inversion"}[inversion]
        return Chord(
            root=root,
            quality=quality,
            pitches=pitches,
            names=names,
            intervals=tuple(self.interval_between(names[0], n) for n in names),
            inversion=inversion,
            label=f"{self.pitch_class_name(root_name)} {quality}{ordinal}",
            purity=tuple(purity),
        )

    # --- scales ---

    @staticmethod
    def _mode(mode: str) -> str:
        mode = mode.strip().lower()
        mode = {"natural minor": "minor", "aeolian": "minor", "ionian": "major"}.get(mode, mode)
        if mode not in SCALES:
            raise TheoryError(f"unknown scale '{mode}'. Available: {', '.join(SCALES)}.")
        return mode

    def _degrees(self, mode: str) -> list[tuple[int, int]]:
        """(steps above the tonic, position on the chain of fifths) per degree, ascending."""
        fifth = self._steps["P5"]
        return sorted(((k * fifth) % self.edo, k) for k in SCALES[mode])

    def scale(self, tonic: int, mode: str, tonic_name: str | None = None) -> list[tuple[int, str]]:
        """Seven notes from the tonic upwards, spelled with one letter each."""
        mode = self._mode(mode)
        tonic_name = tonic_name or self.name(tonic)
        start = LETTERS.index(_NOTE_RE.match(tonic_name).group(2).upper())
        return [
            (tonic + steps, self.name_with_letter(tonic + steps, LETTERS[(start + i) % 7]))
            for i, (steps, _) in enumerate(self._degrees(mode))
        ]

    def diatonic_chords(self, tonic: int, mode: str, sevenths: bool = False, tonic_name: str | None = None) -> list[dict]:
        """The chord on each scale degree, with its Roman numeral. Which third, fifth and
        seventh a degree gets follows from the scale; the chord itself is then built pure,
        as `chord` does (in 53 steps per octave: C vE G, not the scale's own E)."""
        mode = self._mode(mode)
        notes = self.scale(tonic, mode, tonic_name)
        in_scale = set(SCALES[mode])
        out = []
        for d, (_, k) in enumerate(self._degrees(mode)):
            major_third = (k + 4) in in_scale
            perfect_fifth = (k + 1) in in_scale
            major_seventh = (k + 5) in in_scale
            if not perfect_fifth:
                quality = "half-diminished7" if sevenths else "diminished"
            elif sevenths:
                quality = ("major7" if major_seventh else "dominant7") if major_third else "minor7"
            else:
                quality = "major" if major_third else "minor"
            numeral = list(_ROMAN)[d]
            if major_third:
                numeral = numeral.upper()
            numeral += {"diminished": "°", "half-diminished7": "ø7", "major7": "maj7", "dominant7": "7", "minor7": "7"}.get(quality, "")
            out.append({"numeral": numeral, "degree": d + 1, "root": notes[d][0], "root_name": notes[d][1], "quality": quality})
        return out

    def progression(self, tonic: int, mode: str, numerals: list[str], tonic_name: str | None = None) -> list[Chord]:
        """Chords for Roman numerals in a key: `I`, `IV`, `V7`, `vi`, `vii°`. A bare numeral
        (or one with only a 7) whose case fits the key takes the key's own chord; otherwise
        case and suffix choose the quality."""
        triads = self.diatonic_chords(tonic, mode, False, tonic_name)
        sevenths = self.diatonic_chords(tonic, mode, True, tonic_name)
        out = []
        for raw in numerals:
            m = re.match(r"^([ivIV]+)(.*)$", raw.strip())
            if not m or m.group(1).lower() not in _ROMAN:
                raise TheoryError(f"'{raw}' is not a Roman numeral chord. Examples: I, IV, V7, vi, vii°.")
            numeral, suffix = m.groups()
            entry = (sevenths if "7" in suffix else triads)[_ROMAN[numeral.lower()] - 1]
            diatonic = entry["quality"]
            if suffix in ("", "7") and numeral.isupper() == (diatonic in ("major", "major7", "dominant7")):
                quality = diatonic      # the key's own chord on this degree
            elif "ø" in suffix:
                quality = "half-diminished7"
            elif "°" in suffix or "dim" in suffix:
                quality = "diminished"
            elif "+" in suffix or "aug" in suffix:
                quality = "augmented"
            elif "maj7" in suffix:
                quality = "major7"
            elif "7" in suffix:
                quality = "dominant7" if numeral.isupper() else "minor7"
            else:
                quality = "major" if numeral.isupper() else "minor"
            out.append(self.chord(entry["root"], quality, 0, entry["root_name"]))
        return out

    # --- about the tuning ---

    def describe(self) -> dict:
        """What a player should know about this tuning, compared with 12-tone."""
        thirds, seen = [], set()
        for name, label in (("sub3", "subminor"), ("m3", "minor"), ("n3", "neutral"), ("M3", "major"), ("sup3", "supermajor")):
            steps = self._steps[name]
            off = self.cents_of(steps) - cents(_PURE[name])
            if steps in seen or abs(off) > 20:
                continue
            seen.add(steps)
            thirds.append({"kind": label, "interval": self.interval(steps), "steps": steps, "cents": round(self.cents_of(steps)), "from_pure_cents": round(off, 1)})
        fifth = self._steps["P5"]
        c4 = 4 * self.edo
        notes = []
        if self.parse_safe("Fb4") not in (None, self.parse("E4")[0]):
            notes.append("Sharps and flats are different notes here: E and Fb, G# and Ab are different keys. Spelling matters.")
        pure_third = self.pitch_class_name(self.name_with_letter(c4 + self._steps["M3"], "E"))
        if pure_third != "E":
            notes.append(f"The pure-sounding major third above C is {pure_third}, not E. Chords from the theory tool already use it.")
        if self.edo != 12:
            notes.append("^ before a note raises it by the smallest step of this tuning, v lowers it.")
        return {
            "steps_per_octave": self.edo,
            "smallest_step_cents": round(1200 / self.edo, 1),
            "fifth": {"interval": self.interval(fifth), "steps": fifth, "cents": round(self.cents_of(fifth), 1), "from_pure_cents": round(self.cents_of(fifth) - cents(3 / 2), 1)},
            "thirds": thirds,
            "chord_qualities": self.qualities(),
            "beyond_12_tone": {q: CHORDS[q]["sounds"] for q in self.qualities() if CHORDS[q].get("xen")},
            "notes": notes,
        }
