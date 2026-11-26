"""Teaching material for the tutor: pieces from the converted collections, raga outlines and
practice patterns that work in any tuning.

Pieces: `build/tutor-library/` as written by `library_build.py` (Turkish makam music from
SymbTr, in 53 steps per octave; Gregorian chant from GregoBase, spelled note names that any
tuning with a chain of fifths plays, exactly Pythagorean in 53).

Ragas: authored here as outlines, not imported: no notated collection gives the fine
intonation (all are 12-position sargam). Each note is a just ratio, played on the nearest
step of the current tuning. The ratios are a MODEL (the 5-limit 22-shruti scheme as used by
Vidyadhar Oke, his per-raga choices where he gives them); measured performances differ and
scholars disagree, so the tutor is told to say so. Sources: reference/research/repertoire.md.

Patterns: the beginner exercises of Indian teaching (alankar / palta, sarali and janta
varisai), which are patterns over a scale and so work on any scale in any tuning.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from fractions import Fraction
from pathlib import Path

DEFAULT_FOLDER = Path(__file__).resolve().parents[2] / "build" / "tutor-library"


def _plain(text: str) -> str:
    """Lower case without accents, for searching ("Hüzzam" is found by "huzzam")."""
    text = text.replace("ı", "i").replace("İ", "I")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


class Library:
    def __init__(self, folder: str | Path | None = None):
        self.folder = Path(folder) if folder else DEFAULT_FOLDER
        self._index: list[dict] | None = None

    @property
    def index(self) -> list[dict]:
        if self._index is None:
            path = self.folder / "index.json"
            self._index = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
            self._by_id = {e["id"]: e for e in self._index}
        return self._index

    def counts(self) -> dict[str, dict[int, int]]:
        out: dict[str, dict[int, int]] = {}
        for e in self.index:
            out.setdefault(e["tradition"], {}).setdefault(e["level"], 0)
            out[e["tradition"]][e["level"]] += 1
        return out

    def modes(self, tradition: str, limit: int = 12) -> list[tuple[str, int]]:
        seen: dict[str, int] = {}
        for e in self.index:
            if e["tradition"] == tradition and e["mode"]:
                seen[e["mode"]] = seen.get(e["mode"], 0) + 1
        return sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]

    def search(self, tradition: str | None = None, mode: str | None = None, form: str | None = None, level: int | None = None,
               text: str | None = None, max_notes: int | None = None) -> list[dict]:
        """Matching entries, easiest and shortest first."""
        want_mode, want_form, want_text = (_plain(v) if v else None for v in (mode, form, text))
        found = []
        for e in self.index:
            if tradition and e["tradition"] != tradition:
                continue
            if level and e["level"] > level:
                continue
            if max_notes and e["notes"] > max_notes:
                continue
            if want_mode and want_mode not in _plain(e["mode"]):
                continue
            if want_form and want_form not in _plain(e["form"]):
                continue
            if want_text and want_text not in _plain(" ".join((e["title"], e["mode"], e["form"], e.get("composer", "")))):
                continue
            found.append(e)
        found.sort(key=lambda e: (e["level"], e["notes"], e["id"]))
        return found

    def piece(self, piece_id: str) -> dict | None:
        self.index
        entry = self._by_id.get(piece_id.strip())
        if entry is None:
            return None
        with (self.folder / entry["file"]).open(encoding="utf-8") as f:
            f.seek(entry["at"])
            return json.loads(f.readline())


# --- jazz chord symbols ---

_SYMBOL = re.compile(r"^([A-G](?:bb|b|##|#)?)([^/]*)(?:/([A-G](?:bb|b|##|#)?))?$")


def chord_from_symbol(symbol: str) -> tuple[str, str, str, str] | None:
    """A lead-sheet chord symbol as (root name, the tutor's chord quality, family, what
    was left out). Extensions and alterations beyond the seventh are left out: a beginner
    plays the seventh chord underneath. Family: major, minor, dominant, diminished."""
    m = _SYMBOL.match(symbol.strip())
    if not m:
        return None
    root, s = m.group(1), m.group(2).strip()
    s = s.replace("^", "maj").replace("-", "m").replace("ø", "m7b5").replace("°", "0")
    def rest(text: str, used: str) -> str:
        return text[len(used):].strip()
    if s.startswith("maj") or s.startswith("M"):
        body = s[3:] if s.startswith("maj") else s[1:]
        if body[:1] in ("7", "9") or body[:2] == "13":
            return root, "major7", "major", body.lstrip("7") if body[:1] == "7" else body
        return root, "major", "major", body
    if s.startswith("m") and not s.startswith("maj"):
        body = s[1:]
        if body.startswith("7b5"):
            return root, "half-diminished7", "diminished", rest(body, "7b5")
        if body.startswith(("maj7", "M7")):
            return root, "minor-major7", "minor", ""
        if body.startswith("6"):
            return root, "minor6", "minor", rest(body, "6")
        if body[:1] in ("7", "9") or body[:2] in ("11", "13"):
            return root, "minor7", "minor", rest(body, "7") if body[:1] == "7" else body
        return root, "minor", "minor", body
    if s.startswith(("0", "o", "dim")):
        body = s[3:] if s.startswith("dim") else s[1:]
        return (root, "diminished7", "diminished", "") if body.startswith("7") else (root, "diminished", "diminished", body)
    if s.startswith("h"):
        return root, "half-diminished7", "diminished", ""
    if s.startswith("6"):
        return root, "major6", "major", rest(s, "6")
    if s[:1] in ("7", "9") or s[:2] in ("11", "13"):
        if "sus" in s:
            return root, "dominant7sus4", "dominant", s.replace("sus", "").lstrip("7")
        return root, "dominant7", "dominant", rest(s, "7") if s[:1] == "7" else s
    if s.startswith("sus"):
        return root, "sus4", "major", ""
    if s.startswith(("aug", "+")):
        return root, "augmented", "major", ""
    return root, "major", "major", s


def parse_key(key: str) -> tuple[str, bool] | None:
    """"Gmin", "Eb", "F-", "Bbm" -> (tonic name, minor?)."""
    m = re.match(r"^([A-G](?:b|#)?)\s*(.*)$", (key or "").strip())
    if not m:
        return None
    return m.group(1), m.group(2).strip().lower() in ("min", "m", "-", "minor")


# --- ragas ---

# Sargam: S R G M P D N are the plain notes, lower case r g d n the lowered (komal) ones,
# M# the raised (tivra) Ma. A following "." is the octave below, "'" the octave above.
RAGAS: dict[str, dict] = {
    "Bhupali": {
        "tradition": "Hindustani", "also": "Mohanam in Carnatic music has the same notes", "time": "early evening",
        "notes": {"R": "9/8", "G": "5/4", "P": "3/2", "D": "5/3"},
        "up": "S R G P D S'", "down": "S' D P G R S", "phrase": "G R S D. S R G, P G, D P G, R S",
        "strong": ("G", "D"), "taught": "one of the first ragas: five notes, no half steps",
    },
    "Deshkar": {
        "tradition": "Hindustani", "time": "morning",
        "notes": {"R": "9/8", "G": "81/64", "P": "3/2", "D": "27/16"},
        "up": "S R G P D S'", "down": "S' D P G R S", "phrase": "D P G P D S' D P, G P D, G R S",
        "strong": ("D", "G"),
        "taught": "the same five notes as Bhupali but with the higher Ga and Dha, a comma above Bhupali's, and "
                  "the weight on the upper half: the pair to hear what one comma does",
    },
    "Yaman": {
        "tradition": "Hindustani", "time": "evening",
        "notes": {"R": "9/8", "G": "5/4", "M#": "45/32", "P": "3/2", "D": "27/16", "N": "15/8"},
        "up": "N. R G M# D N S'", "down": "S' N D P M# G R S", "phrase": "N. R G, R S, P M# G, R S",
        "strong": ("G", "N"), "taught": "very often the first full raga; the raised Ma is its mark",
        "disputed": "Dha is also given a comma lower (5/3)",
    },
    "Bilawal": {
        "tradition": "Hindustani", "time": "morning",
        "notes": {"R": "9/8", "G": "5/4", "M": "4/3", "P": "3/2", "D": "5/3", "N": "15/8"},
        "up": "S R G M P D N S'", "down": "S' N D P M G R S", "phrase": "G R, G P, D, N S'",
        "strong": ("D", "G"), "taught": "the plain scale, all notes natural; the reference the other ragas are described against",
    },
    "Bhairav": {
        "tradition": "Hindustani", "also": "Mayamalavagowla, the first raga of Carnatic teaching, has the same notes", "time": "dawn",
        "notes": {"r": "16/15", "G": "5/4", "M": "4/3", "P": "3/2", "d": "8/5", "N": "15/8"},
        "up": "S r G M P d N S'", "down": "S' N d P M G r S", "phrase": "G M d, d P, G M r, r S",
        "strong": ("d", "r"), "taught": "lowered second and sixth next to a major third; both are sung with a slow oscillation",
        "disputed": "no measured values were found for the lowered Re and Dha here; a comma lower (256/243, 128/81) is also given",
    },
    "Kafi": {
        "tradition": "Hindustani", "time": "late evening",
        "notes": {"R": "9/8", "g": "6/5", "M": "4/3", "P": "3/2", "D": "5/3", "n": "9/5"},
        "up": "S R g M P D n S'", "down": "S' n D P M g R S", "phrase": "R g M P, M P g R, S",
        "strong": ("P", "S"), "taught": "lowered third and seventh",
    },
    "Todi": {
        "tradition": "Hindustani", "time": "late morning",
        "notes": {"r": "256/243", "g": "32/27", "M#": "45/32", "P": "3/2", "d": "128/81", "N": "15/8"},
        "up": "S r g M# d N S'", "down": "S' N d P M# g r S", "phrase": "d. N. S r g, r g r S",
        "strong": ("d", "g"), "taught": "very low second, third and sixth; Pa is passed over in the ascent",
        "disputed": "Ni is also measured a comma higher (in a recording of Kishori Amonkar, analysed by Bernard Bel)",
    },
    "Bageshri": {
        "tradition": "Hindustani", "time": "night",
        "notes": {"R": "10/9", "g": "32/27", "M": "4/3", "P": "3/2", "D": "5/3", "n": "16/9"},
        "up": "S g M D n S'", "down": "S' n D M g R S", "phrase": "D. n. S M, g M D, M g R S",
        "strong": ("M", "S"), "taught": "Ma is the centre; Pa appears only in passing",
    },
}

SWARA_NAMES = {"S": "Sa", "r": "komal Re", "R": "Re", "g": "komal Ga", "G": "Ga", "M": "Ma", "M#": "tivra Ma", "P": "Pa",
               "d": "komal Dha", "D": "Dha", "n": "komal Ni", "N": "Ni"}


def raga_names() -> list[str]:
    return list(RAGAS)


def find_raga(name: str) -> tuple[str, dict] | None:
    want = _plain(name)
    for key, raga in RAGAS.items():
        if _plain(key) == want or want in _plain(raga.get("also", "")).split():
            return key, raga
    return None


def swara_steps(raga: dict, edo: int) -> dict[str, tuple[int, float]]:
    """Each note of the raga as steps above Sa in this tuning, with the error in cents
    against the model ratio."""
    out = {"S": (0, 0.0)}
    for swara, ratio in raga["notes"].items():
        cents = 1200 * math.log2(Fraction(ratio))
        steps = round(cents * edo / 1200)
        out[swara] = (steps, round(steps * 1200 / edo - cents, 1))
    return out


def sargam_to_steps(text: str, steps: dict[str, tuple[int, float]], edo: int) -> list[list[int]]:
    """A sargam line ("N. R G, R S") as groups of steps above the middle Sa; commas
    separate the groups."""
    groups: list[list[int]] = []
    for part in text.split(","):
        group = []
        for token in part.split():
            octave = token.count("'") - token.count(".")
            swara = token.replace("'", "").replace(".", "")
            if swara not in steps:
                raise KeyError(swara)
            group.append(steps[swara][0] + octave * edo)
        if group:
            groups.append(group)
    return groups


# --- patterns over a scale ---

PATTERNS = {
    "steps": "up and down the scale, one note at a time",
    "doubles": "every note twice (janta)",
    "threes": "three notes up from each degree: 1 2 3, 2 3 4, ... and back down",
    "fours": "four notes up from each degree: 1 2 3 4, 2 3 4 5, ...",
    "thirds": "skipping one note: 1 3, 2 4, 3 5, ... and back down",
    "turns": "each note, its upper neighbour and back: 1 2 1, 2 3 2, ...",
}


def pattern(name: str, scale: list[int]) -> list[list[int]]:
    """`scale`: ascending pitches from the tonic to its octave. Returns the exercise as
    groups (phrases) of pitches."""
    name = name.strip().lower()
    n = len(scale)
    down = scale[::-1]
    if name == "steps":
        return [list(scale), list(down)]
    if name == "doubles":
        return [[p for q in scale for p in (q, q)], [p for q in down for p in (q, q)]]
    if name in ("threes", "fours"):
        size = 3 if name == "threes" else 4
        ups = [scale[i:i + size] for i in range(n - size + 1)]
        downs = [down[i:i + size] for i in range(n - size + 1)]
        return ups + downs
    if name == "thirds":
        return [[scale[i], scale[i + 2]] for i in range(n - 2)] + [[down[i], down[i + 2]] for i in range(n - 2)]
    if name == "turns":
        return [[scale[i], scale[i + 1], scale[i]] for i in range(n - 1)] + [[down[i], down[i + 1], down[i]] for i in range(n - 1)]
    raise KeyError(name)
