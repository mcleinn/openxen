"""What the tutor knows about one player and keeps between sessions: the measured hand and
the player's own fingerings (the "fingering book").

Stored as one JSON file (default `host/tutor/state/player.json`, not in git). Without a file
everything lives in memory only, which is what the tests use.

    {"hand": {"size": "medium",
              "rest": {"1": [x, y], ...},          resting fingertips, mm, as a right hand
              "thumb_span_mm": 205.0,               widest stretch thumb - little finger
              "finger_span_mm": 160.0},             widest stretch index - little finger
     "book": [{"hand": "right", "shape": [[0, 0], [38, -33], [67, -17]],
               "fingers": [2, 1, 5], "label": "C major"}],
     "trills": [{"hand": "right", "to": [10, 17], "fingers": [2, 3],
                 "label": "trill to the key to the upper right"}]}

A book entry belongs to a hand shape (the keys' positions relative to the lowest note, in
mm), not to a chord name: on an isomorphic keyboard the same shape is the same chord
quality on every root, so one entry serves all of them.

A trill entry is kept apart from the book's chords (holding two keys and alternating them
are different tasks). It belongs to a hand and to where the other key lies as seen from the
main note (`to`, mm to the right and away from the player), so the direction counts: up to
the right neighbour and down to the left neighbour are two entries. It does not belong to a
tuning: the same two keys are a whole tone in one layout and a quarter tone in another, and
the hand does the same thing. `fingers` = main note first. A file without `trills` (written
before there were any) loads as a player without trill entries.
"""

from __future__ import annotations

import json
import math
import threading
from pathlib import Path

from . import fingering as F

Shape = tuple[tuple[int, int], ...]
TRILL_SAME_MM = 1.5     # two trill shapes this close are the same keys (rounding, a slightly different key pitch)


def shape_of(points: list[tuple[float, float]]) -> Shape:
    """Positions relative to the first key, in whole millimetres."""
    x0, y0 = points[0]
    return tuple((round(x - x0), round(y - y0)) for x, y in points)


class Player:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self.size = "medium"
        self.rest: dict[int, tuple[float, float]] | None = None
        self.thumb_span_mm: float | None = None
        self.finger_span_mm: float | None = None
        self.offset_ms: float | None = None      # how far this player's taps lie from a click, on this equipment
        self.book: dict[tuple[str, Shape], dict] = {}
        self.trills: dict[tuple[str, tuple[int, int]], dict] = {}   # (hand, where the other key lies from the main one, mm)
        if self.path and self.path.exists():
            self._load(json.loads(self.path.read_text(encoding="utf-8")))

    # --- the hand ---

    def hand(self) -> F.Hand:
        """The hand model for this player: the size table, with what was measured put in."""
        base = F.default_hand(self.size)
        medium = F.default_hand("medium")
        thumb = finger = 1.0
        if self.thumb_span_mm:
            thumb = self.thumb_span_mm / (medium.span(1, 5)[5] / F.SPAN_TO_PRACTICAL)
            base = medium
        if self.finger_span_mm:
            finger = self.finger_span_mm / (medium.span(2, 5)[5] / F.SPAN_TO_PRACTICAL)
            base = medium
        return F.customise(base, rest=self.rest, thumb_factor=thumb, finger_factor=finger)

    @property
    def calibrated(self) -> list[str]:
        done = []
        if self.rest:
            done.append("resting hand")
        if self.thumb_span_mm:
            done.append("thumb to little finger stretch")
        if self.finger_span_mm:
            done.append("index to little finger stretch")
        return done

    def set_size(self, size: str) -> None:
        F.default_hand(size)    # raises on an unknown size
        with self._lock:
            self.size = size.strip().lower()
        self._save()

    def set_rest(self, rest: dict[int, tuple[float, float]]) -> None:
        with self._lock:
            self.rest = {int(f): (float(x), float(y)) for f, (x, y) in rest.items()}
        self._save()

    def set_span(self, fingers: tuple[int, int], mm: float) -> None:
        with self._lock:
            if fingers == (1, 5):
                self.thumb_span_mm = float(mm)
            elif fingers == (2, 5):
                self.finger_span_mm = float(mm)
            else:
                raise F.FingeringError("a stretch is measured between thumb and little finger (1, 5) or index and little finger (2, 5)")
        self._save()

    def set_offset(self, ms: float | None) -> None:
        with self._lock:
            self.offset_ms = None if ms is None else float(ms)
        self._save()

    def reset_hand(self) -> None:
        with self._lock:
            self.size, self.rest, self.thumb_span_mm, self.finger_span_mm = "medium", None, None, None
        self._save()

    # --- the fingering book ---

    def preferred(self, side: str, points: list[tuple[float, float]]) -> tuple[int, ...] | None:
        entry = self.book.get((side, shape_of(points)))
        return tuple(entry["fingers"]) if entry else None

    def remember(self, side: str, points: list[tuple[float, float]], fingers: tuple[int, ...], label: str) -> None:
        with self._lock:
            self.book[(side, shape_of(points))] = {"fingers": [int(f) for f in fingers], "label": label}
        self._save()

    def forget(self, side: str, points: list[tuple[float, float]]) -> bool:
        with self._lock:
            found = self.book.pop((side, shape_of(points)), None) is not None
        if found:
            self._save()
        return found

    def entries(self) -> list[dict]:
        return [{"hand": side, "for": e["label"], "fingers": "-".join(map(str, e["fingers"])), "keys": len(shape)}
                for (side, shape), e in sorted(self.book.items(), key=lambda kv: (kv[0][0], kv[1]["label"]))]

    # --- trills: a finger pair per hand and per place of the other key, seen from the main note ---

    def _trill_key(self, side: str, main: tuple[float, float], other: tuple[float, float]) -> tuple[str, tuple[int, int]]:
        to = shape_of([main, other])[1]
        if (side, to) in self.trills:
            return side, to
        near = [k for k in self.trills if k[0] == side and math.hypot(k[1][0] - to[0], k[1][1] - to[1]) <= TRILL_SAME_MM]
        return min(near, key=lambda k: math.hypot(k[1][0] - to[0], k[1][1] - to[1])) if near else (side, to)

    def trill_preferred(self, side: str, main: tuple[float, float], other: tuple[float, float]) -> tuple[int, int] | None:
        """The player's own two fingers (main note first) for a trill from `main` to `other`."""
        entry = self.trills.get(self._trill_key(side, main, other))
        return tuple(entry["fingers"]) if entry else None

    def remember_trill(self, side: str, main: tuple[float, float], other: tuple[float, float], fingers: tuple[int, int], label: str) -> None:
        fingers = tuple(int(f) for f in fingers)
        if len(fingers) != 2 or fingers[0] == fingers[1] or not set(fingers) <= {1, 2, 3, 4, 5}:
            raise F.FingeringError(f"a trill takes two different fingers, each 1 (thumb) to 5 (little finger), the main note's first; got {list(fingers)}")
        with self._lock:
            self.trills[self._trill_key(side, main, other)] = {"fingers": list(fingers), "label": label}
        self._save()

    def forget_trill(self, side: str, main: tuple[float, float], other: tuple[float, float]) -> bool:
        with self._lock:
            found = self.trills.pop(self._trill_key(side, main, other), None) is not None
        if found:
            self._save()
        return found

    def trill_entries(self) -> list[dict]:
        return [{"hand": side, "to": to, "fingers": tuple(e["fingers"]), "label": e["label"]}
                for (side, to), e in sorted(self.trills.items(), key=lambda kv: (kv[0][0] != "right", kv[1]["label"], kv[0][1]))]

    # --- file ---

    def _load(self, data: dict) -> None:
        hand = data.get("hand", {})
        self.size = hand.get("size", "medium")
        if hand.get("rest"):
            self.rest = {int(f): (float(x), float(y)) for f, (x, y) in hand["rest"].items()}
        self.thumb_span_mm = hand.get("thumb_span_mm")
        self.finger_span_mm = hand.get("finger_span_mm")
        self.offset_ms = data.get("offset_ms")
        for e in data.get("book", []):
            shape = tuple((int(x), int(y)) for x, y in e["shape"])
            self.book[(e["hand"], shape)] = {"fingers": [int(f) for f in e["fingers"]], "label": e.get("label", "")}
        for e in data.get("trills") or []:
            self.trills[(e["hand"], (int(e["to"][0]), int(e["to"][1])))] = {"fingers": [int(f) for f in e["fingers"]], "label": e.get("label", "")}

    def _save(self) -> None:
        if not self.path:
            return
        with self._lock:
            data = {
                "hand": {"size": self.size, "rest": {str(f): list(p) for f, p in (self.rest or {}).items()} or None,
                         "thumb_span_mm": self.thumb_span_mm, "finger_span_mm": self.finger_span_mm},
                "offset_ms": self.offset_ms,
                "book": [{"hand": side, "shape": [list(p) for p in shape], "fingers": e["fingers"], "label": e["label"]}
                         for (side, shape), e in self.book.items()],
                "trills": [{"hand": side, "to": list(to), "fingers": e["fingers"], "label": e["label"]}
                           for (side, to), e in self.trills.items()],
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
