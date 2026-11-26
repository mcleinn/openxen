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

import statistics

BANDS = {"beginner": (40, 80, 120), "intermediate": (25, 50, 90), "advanced": (15, 35, 70)}
GRADES = ("on it", "close", "near")

# One cycle of each pattern: `pulses` equal parts, `beats` clicks in it, taps on `onsets`.
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
    counts = {g: 0 for g in GRADES}
    counts["off"] = 0
    for e in hit:
        ms = abs(e) * 1000
        counts[next((g for g, limit in zip(GRADES, bands) if ms <= limit), "off")] += 1
    out: dict = {"due": len(due), "played": len(hit), "missed": errors.count(None), "extra": len(free), **counts}
    if hit:
        mean = statistics.fmean(hit) * 1000
        out["mean_ms"] = round(mean)
        out["spread_ms"] = round(statistics.pstdev(hit) * 1000) if len(hit) > 1 else 0
        out["tendency"] = "ahead of the beat (rushing)" if mean < -bands[0] / 2 else "behind the beat (dragging)" if mean > bands[0] / 2 else "centred"
        if len(hit) >= 6:       # does the error grow or shrink over the take?
            xs = [t for t, e in zip(due, errors) if e is not None]
            mx, my = statistics.fmean(xs), statistics.fmean(hit)
            denominator = sum((x - mx) ** 2 for x in xs)
            slope = sum((x - mx) * (y - my) for x, y in zip(xs, hit)) / denominator if denominator else 0.0
            drift = slope * (xs[-1] - xs[0]) * 1000
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
