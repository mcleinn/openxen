"""Judging rhythm from the times of key presses.

A tap is compared with the place it was meant for: error = tap - target - offset, where the
offset is the player's own, measured once by tapping along to a click (it holds the delay of
keyboard, computer and sound, and the few tens of milliseconds by which people tap ahead of a
beat). Research behind the numbers: reference/research/fifths-rhythm-wiki.md.

Bands (milliseconds either side of the target): what counts as "on it", "close" and "near"
for three levels. They are this project's choice, placed between the windows rhythm games use
(about 20 to 50 ms for their best grade) and what is audible to a learner; a just noticeable
displacement is about 2.5 % of the distance between two notes.

Times measured here pass through USB polling, an HTTP request and thread scheduling: expect
about 10 ms of jitter. That is fine for the bands below and too coarse to judge an expert.
"""

from __future__ import annotations

import difflib
import json
import os
import statistics
import unicodedata
from pathlib import Path

BANDS = {"beginner": (40, 80, 120), "intermediate": (25, 50, 90), "advanced": (15, 35, 70)}
GRADES = ("on it", "close", "near")

# One cycle of each pattern: `pulses` equal parts, `beats` clicks in it, taps on `onsets`.
# The five tala entries at the end are a fallback: where the rhythm library is built
# (`rhythm_build.py`), `find` gives the sourced cycle of the same name instead.
PATTERNS: dict[str, dict] = {
    "quarters": {"pulses": 4, "beats": 4, "onsets": [0, 1, 2, 3], "what": "every beat"},
    "eighths": {"pulses": 8, "beats": 4, "onsets": list(range(8)), "what": "two even notes per beat"},
    "offbeats": {"pulses": 8, "beats": 4, "onsets": [1, 3, 5, 7], "what": "only between the beats"},
    "charleston": {"pulses": 8, "beats": 4, "onsets": [0, 3], "what": "on one, and just before three: the basic jazz comping figure"},
    "tresillo": {"pulses": 8, "beats": 4, "onsets": [0, 3, 6], "what": "3 + 3 + 2, the cell under much Latin and popular music"},
    "cinquillo": {"pulses": 8, "beats": 4, "onsets": [0, 2, 3, 5, 6], "what": "the tresillo filled in"},
    "son_clave_3_2": {"pulses": 16, "beats": 4, "onsets": [0, 3, 6, 10, 12], "what": "son clave, three side first"},
    "son_clave_2_3": {"pulses": 16, "beats": 4, "onsets": [2, 4, 8, 11, 14], "what": "son clave, two side first"},
    "rumba_clave_3_2": {"pulses": 16, "beats": 4, "onsets": [0, 3, 7, 10, 12], "what": "rumba clave: the third stroke comes later than in son"},
    "bossa": {"pulses": 16, "beats": 4, "onsets": [0, 3, 6, 10, 13], "what": "the bossa nova figure"},
    "bell_12_8": {"pulses": 12, "beats": 4, "onsets": [0, 2, 4, 5, 7, 9, 11], "what": "the seven-stroke bell pattern in 12/8"},
    "three_against_two": {"pulses": 6, "beats": 2, "onsets": [0, 2, 4], "what": "three even taps across two clicks"},
    "waltz": {"pulses": 3, "beats": 3, "onsets": [0, 1, 2], "what": "three beats, the first one strong"},
    "teental": {"pulses": 16, "beats": 16, "onsets": list(range(16)), "accents": [0, 4, 12],
                "what": "the 16-beat cycle of Hindustani music, 4+4+4+4: clap on beats 1, 5 and 13, wave on 9"},
    "jhaptal": {"pulses": 10, "beats": 10, "onsets": list(range(10)), "accents": [0, 2, 7], "what": "10 beats, 2+3+2+3: clap on 1, 3 and 8, wave on 6"},
    "rupak": {"pulses": 7, "beats": 7, "onsets": list(range(7)), "accents": [3, 5], "what": "7 beats, 3+2+2: it begins with a wave; clap on 4 and 6"},
    "dadra": {"pulses": 6, "beats": 6, "onsets": list(range(6)), "accents": [0], "what": "6 beats, 3+3: clap on 1, wave on 4"},
    "keherwa": {"pulses": 8, "beats": 8, "onsets": list(range(8)), "accents": [0], "what": "8 beats, 4+4: clap on 1, wave on 5"},
}

# --- the rhythm library: cycles converted from the researched sources by `rhythm_build.py` ---
#
# A cycle there has the fields of a pattern above and more:
#   name, tradition (hindustani | carnatic | makam), kind (theka | tala | lesson | usul),
#   strokes [{at, stroke, dur, loud}] in pulses (the theka's bols, a lesson's mridangam
#   strokes, an usul's dum and tek), sections [{at, length, mark, gesture, ...}] (vibhag,
#   angas or groups), sources, confidence, conflict (what the sources disagree on), variants.

LIBRARY_FILE = Path(os.environ.get("OPENXEN_RHYTHM_LIBRARY") or Path(__file__).resolve().parents[2] / "build" / "tutor-library" / "rhythm.json")
LIBRARY: dict[str, dict] = {}       # key -> cycle
INFO: dict = {}                     # the rest of the file: how tabla bols are sounded, gati, lessons without strokes
_NAMES: dict[str, str] = {}         # every name and alias without accents, spaces and signs -> key


def squash(text: str) -> str:
    """A name as it is compared: "Aksaksemâî (10/8)" and "aksak semai" are the same."""
    text = text.split("(")[0].replace("ı", "i").replace("İ", "I")
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return "".join(c for c in text.lower() if c.isalnum())


def load(path: str | Path | None = None) -> int:
    """Read the built rhythm library (none if the file is missing). Returns the number of cycles."""
    path = Path(path) if path else LIBRARY_FILE
    LIBRARY.clear()
    INFO.clear()
    _NAMES.clear()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        LIBRARY.update(data.get("patterns", {}))
        INFO.update({k: v for k, v in data.items() if k != "patterns"})
    for key in PATTERNS:
        _NAMES[squash(key)] = key
    for key in LIBRARY:                                 # a sourced cycle supersedes a built-in one of the same name
        _NAMES[squash(key)] = key
    for key, cycle in LIBRARY.items():
        for alias in [cycle.get("name", "")] + list(cycle.get("aliases", [])):
            _NAMES.setdefault(squash(alias), key)
    _NAMES.pop("", None)
    return len(LIBRARY)


def find(name: str) -> tuple[str, dict] | None:
    """A pattern by name or alias: the library's cycle if there is one, else the built-in pattern."""
    key = _NAMES.get(squash(name or ""))
    if key is None:
        return None
    return key, LIBRARY.get(key) or PATTERNS[key]


def close_names(name: str, limit: int = 6) -> list[str]:
    near = difflib.get_close_matches(squash(name or ""), list(_NAMES), n=limit, cutoff=0.6)
    return list(dict.fromkeys(_NAMES[n] for n in near))


def variant_of(pattern: dict, number: int) -> dict:
    """The pattern with the strokes (and sections, length) of its n-th playable variant, counted from 1."""
    usable = [v for v in pattern.get("variants", []) if v.get("strokes")]
    if not 1 <= number <= len(usable):
        raise ValueError(f"it has {len(usable)} variant(s) that can be played" if usable else "it has no variant that can be played")
    chosen = usable[number - 1]
    out = {**pattern, **{k: v for k, v in chosen.items() if k not in ("name", "source", "note")}}
    out["variant"] = chosen["name"]
    if chosen.get("source"):
        out["sources"] = [chosen["source"]]
    return out


def tap_onsets(pattern: dict, tap: str | None) -> list[float]:
    """Where the player taps: None = the pattern's own onsets, "beats" = every beat,
    "claps" = the claps of the cycle (its accents), "strokes" = every stroke of the drum."""
    if not tap:
        return list(pattern["onsets"])
    if tap == "beats":
        return [b * pattern["pulses"] / pattern["beats"] for b in range(pattern["beats"])]
    if tap == "claps":
        return [a * pattern["pulses"] / pattern["beats"] for a in sorted(pattern.get("accents", [0]))]
    if tap == "strokes":
        at = sorted({s["at"] for s in pattern.get("strokes", [])})
        if not at:
            raise ValueError("this pattern has no strokes of its own; tap beats or claps")
        return at
    raise ValueError("tap must be beats, claps or strokes")


load()


def targets(pattern: dict, cycles: int, start: float, beat_s: float) -> list[float]:
    """The times at which the pattern's taps are due."""
    pulse = pattern["beats"] * beat_s / pattern["pulses"]
    cycle = pattern["beats"] * beat_s
    return [start + c * cycle + onset * pulse for c in range(cycles) for onset in pattern["onsets"]]


def offset_from_taps(clicks: list[float], taps: list[float], skip: int = 4) -> tuple[float, float, int] | None:
    """The player's offset in seconds: the median of (tap - nearest click), the first
    `skip` clicks left out, with its spread and the number of taps used. None if there
    are too few to say."""
    used = clicks[skip:]
    if len(used) < 2:
        return None
    gap = min(b - a for a, b in zip(used, used[1:]))
    errors = []
    for tap in taps:
        nearest = min(used, key=lambda c: abs(tap - c))
        if abs(tap - nearest) < gap / 2:
            errors.append(tap - nearest)
    if len(errors) < 8:
        return None
    middle = statistics.median(errors)
    kept = [e for e in errors if abs(e - middle) < 0.15]       # a missed click is not an offset
    return statistics.median(kept), (statistics.pstdev(kept) if len(kept) > 1 else 0.0), len(kept)


def band_of(error_ms: float, level: str = "beginner") -> str:
    """The grade of one note that lies this far from its place: on it, close, near or off."""
    return next((g for g, limit in zip(GRADES, BANDS[level]) if abs(error_ms) <= limit), "off")


def lean(mean_ms: float, level: str = "beginner") -> str:
    """Which side several notes lie on together: "early", "late" or "on it". A mean counts from
    half the on-it band: single notes scatter, their mean does not."""
    half = BANDS[level][0] / 2
    return "early" if mean_ms < -half else "late" if mean_ms > half else "on it"


def spread_over_bands(errors: list[float], level: str = "beginner") -> dict:
    """Errors in seconds as counts per grade, with their mean and spread in milliseconds."""
    out: dict = {g: 0 for g in GRADES}
    out["off"] = 0
    for e in errors:
        out[band_of(e * 1000, level)] += 1
    if errors:
        out["mean_ms"] = round(statistics.fmean(errors) * 1000)
        out["spread_ms"] = round(statistics.pstdev(errors) * 1000) if len(errors) > 1 else 0
    return out


def drift_ms(at: list[float], errors: list[float]) -> float:
    """By how many milliseconds the error grew from the first to the last of these notes
    (positive: falling behind), from a straight line through them."""
    if len(at) < 2:
        return 0.0
    mx, my = statistics.fmean(at), statistics.fmean(errors)
    denominator = sum((x - mx) ** 2 for x in at)
    slope = sum((x - mx) * (y - my) for x, y in zip(at, errors)) / denominator if denominator else 0.0
    return slope * (at[-1] - at[0]) * 1000


def grade(due: list[float], taps: list[float], offset: float = 0.0, level: str = "beginner") -> dict:
    """Match taps to the times they were due and judge them."""
    bands = BANDS[level]
    gap = min((b - a for a, b in zip(due, due[1:])), default=1.0)
    window = min(gap / 2, 0.3)
    free = sorted(t - offset for t in taps)
    errors: list[float | None] = []
    for target in due:
        best = min(free, key=lambda t: abs(t - target), default=None)
        if best is not None and abs(best - target) <= window:
            free.remove(best)
            errors.append(best - target)
        else:
            errors.append(None)
    hit = [e for e in errors if e is not None]
    out: dict = {"due": len(due), "played": len(hit), "missed": errors.count(None), "extra": len(free), **spread_over_bands(hit, level)}
    if hit:
        side = lean(out["mean_ms"], level)
        out["tendency"] = {"early": "ahead of the beat (rushing)", "late": "behind the beat (dragging)"}.get(side, "centred")
        if len(hit) >= 6:       # does the error grow or shrink over the take?
            drift = drift_ms([t for t, e in zip(due, errors) if e is not None], hit)
            if abs(drift) > bands[0]:
                out["drift"] = f"{'falling behind' if drift > 0 else 'getting ahead'} by {abs(drift):.0f} ms over the take"
    out["errors_ms"] = [None if e is None else round(e * 1000) for e in errors]
    return out


def grid_stats(onsets: list[float], grid_s: float, offset: float = 0.0, level: str = "beginner") -> dict | None:
    """How free playing sits on a grid of equal parts (for example half beats): the
    distance of every note from the nearest grid line."""
    if len(onsets) < 4:
        return None
    errors = []
    for t in onsets:
        e = (t - offset) % grid_s
        errors.append(e - grid_s if e > grid_s / 2 else e)
    close = BANDS[level][1] / 1000
    return {"notes": len(errors), "mean_ms": round(statistics.fmean(errors) * 1000), "spread_ms": round(statistics.pstdev(errors) * 1000),
            "within_close_percent": round(100 * sum(abs(e) <= close for e in errors) / len(errors))}
