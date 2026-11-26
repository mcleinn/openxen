"""The keyboard as the player has it in front of them: one field of hexagonal keys.

Built only from xentool's description (`GET /api/setup`): where each key is, what it plays,
and which lattice offset is "right", "upper left" and so on. Nothing here knows a
particular keyboard; several connected modules are simply more keys in the same field.

This module is where internals end. Outwards, a key is an opaque id plus a note name;
board numbers, lattice coordinates and step counts are not shown to the tutor model.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from . import fingering as fingering_model
from .theory import Tuning, tuning_for

LATTICE_DIRECTIONS = ("left", "right", "upper_left", "upper_right", "lower_left", "lower_right")
# Names a player uses for where a neighbouring key lies, by angle (0 = right, anticlockwise).
_COMPASS = {"right": 0, "upper_right": 60, "up": 90, "upper_left": 120, "left": 180, "lower_left": 240, "down": 270, "lower_right": 300}
ROW_HEIGHT = math.sqrt(3) / 2   # distance between key rows, in key widths
# A Lumatone-style keyfield (each module two rows lower and six keys further right than the
# one before) is mounted turned by this angle so that octaves run level.
LUMATONE_TILT_DEG = math.degrees(math.atan2(2 * ROW_HEIGHT, 6))
# Thumb-to-little-finger spans in key widths (a key is 19.2 mm wide on the openxen module).
REACH_EASY = 4.0
REACH_STRETCH = 7.0
KEY_PITCH_MM = 19.2     # centre to centre, unless xentool's description says otherwise


class BoardError(ValueError):
    """A request the keyboard cannot fulfil; the message says what to do instead."""


@dataclass(frozen=True)
class Key:
    id: str
    board: int      # internal address, never shown
    key: int
    x: int          # internal lattice position, never shown
    y: int
    pitch: int
    color: str
    name: str       # note name in the current tuning, e.g. "vE4"


@dataclass(frozen=True)
class Shape:
    """One way to play a set of notes: the keys, lowest note first."""
    keys: tuple[Key, ...]
    span: float                         # widest distance between two of its keys, key widths
    moves: tuple[dict[str, int], ...]   # from the first key to each further key
    offsets: tuple[tuple[int, int], ...]    # internal: lattice offsets from the first key

    @property
    def reach(self) -> str:
        if self.span <= REACH_EASY:
            return "easy"
        return "stretch" if self.span <= REACH_STRETCH else "too wide for one hand"


class Keyboard:
    def __init__(self, setup: dict, tuning: Tuning | None = None, tilt_deg: float = 0.0):
        """`tilt_deg`: how far the keyfield is turned anticlockwise in front of the player,
        compared with key rows running level (0 for a module lying square on the desk,
        `LUMATONE_TILT_DEG` for the assembled five-module case)."""
        self.tuning = tuning or tuning_for(int(setup["edo"]))
        self.layout = str(setup.get("layout", ""))
        self.tilt_deg = float(tilt_deg)
        self.key_pitch_mm = float(setup.get("key_pitch_mm", KEY_PITCH_MM))
        lattice = {d: tuple(setup["directions"][d]) for d in LATTICE_DIRECTIONS}
        self._up = lattice["upper_left"][0]     # lattice x change of one row away from the player
        self._cos, self._sin = math.cos(math.radians(self.tilt_deg)), math.sin(math.radians(self.tilt_deg))
        # The six neighbours, named by where the player sees them.
        self.offsets: dict[str, tuple[int, int]] = {}
        for dx, dy in lattice.values():
            px, py = self._turn(dy / 2, dx * self._up * ROW_HEIGHT)
            angle = math.degrees(math.atan2(py, px)) % 360
            name = min(_COMPASS, key=lambda n: (min(abs(angle - _COMPASS[n]), 360 - abs(angle - _COMPASS[n])), n))
            self.offsets[name] = (dx, dy)
        if len(self.offsets) != 6:
            raise BoardError(f"cannot name the six key directions at a tilt of {tilt_deg} degrees")
        self.directions = tuple(sorted(self.offsets, key=lambda n: _COMPASS[n]))
        wide = max((k["key"] for k in setup["keys"]), default=0) >= 100
        self.keys: dict[str, Key] = {}
        self._by_address: dict[tuple[int, int], Key] = {}
        self._by_position: dict[tuple[int, int], Key] = {}
        self._by_pitch: dict[int, list[Key]] = {}
        for k in setup["keys"]:
            kid = f"k{k['board'] + 1}{k['key']:0{3 if wide else 2}d}"
            key = Key(kid, k["board"], k["key"], k["x"], k["y"], k["pitch"], k.get("color", "000000"), self.tuning.name(k["pitch"]))
            self.keys[kid] = key
            self._by_address[(key.board, key.key)] = key
            self._by_position[(key.x, key.y)] = key
            self._by_pitch.setdefault(key.pitch, []).append(key)

    # --- lookups ---

    def key(self, kid: str) -> Key:
        try:
            return self.keys[kid.strip()]
        except KeyError:
            raise BoardError(
                f"there is no key '{kid}' on this keyboard. Key ids come from tool results "
                f"(keys, find_shape, listen); look the note up with the keys tool instead of guessing."
            ) from None

    def at_address(self, board: int, key: int) -> Key | None:
        return self._by_address.get((board, key))

    def keys_for_pitch(self, pitch: int, near: Key | None = None) -> list[Key]:
        """Every key that plays this exact pitch, nearest to `near` first."""
        found = list(self._by_pitch.get(pitch, []))
        ref = near or self.centre()
        found.sort(key=lambda k: (self.distance(k, ref), k.id))
        return found

    def same_note(self, key: Key) -> list[Key]:
        return [k for k in self.keys_for_pitch(key.pitch, key) if k.id != key.id]

    def neighbours(self, key: Key) -> dict[str, Key | None]:
        return {d: self._by_position.get((key.x + dx, key.y + dy)) for d, (dx, dy) in self.offsets.items()}

    def range(self) -> tuple[Key, Key]:
        if not self.keys:
            raise BoardError("no keyboard module is connected")
        ordered = sorted(self.keys.values(), key=lambda k: (k.pitch, k.id))
        return ordered[0], ordered[-1]

    def centre(self) -> Key:
        """The key closest to the middle of the keyfield."""
        if not self.keys:
            raise BoardError("no keyboard module is connected")
        ks = list(self.keys.values())
        cx = sum(self._lateral(k) for k in ks) / len(ks)
        cy = sum(self._height(k) for k in ks) / len(ks)
        return min(ks, key=lambda k: ((self._lateral(k) - cx) ** 2 + (self._height(k) - cy) ** 2, k.id))

    # --- geometry in the player's terms ---

    def _turn(self, lateral: float, height: float) -> tuple[float, float]:
        return lateral * self._cos - height * self._sin, lateral * self._sin + height * self._cos

    def _lateral(self, key: Key) -> float:
        """Position from the player's left to right, in key widths."""
        return self._turn(key.y / 2, key.x * self._up * ROW_HEIGHT)[0]

    def _height(self, key: Key) -> float:
        """Position away from the player, in key widths."""
        return self._turn(key.y / 2, key.x * self._up * ROW_HEIGHT)[1]

    def position_mm(self, key: Key) -> tuple[float, float]:
        """Where the key lies in front of the player: millimetres to the right and away."""
        return self._lateral(key) * self.key_pitch_mm, self._height(key) * self.key_pitch_mm

    def distance(self, a: Key, b: Key) -> float:
        """Centre-to-centre distance in key widths (neighbours are 1 apart)."""
        return math.hypot(self._lateral(a) - self._lateral(b), self._height(a) - self._height(b))

    def moves(self, a: Key, b: Key) -> dict[str, int]:
        """How to get from key a to key b: a number of steps per direction, along at most
        two of the six directions. `{"upper_right": 1, "right": 2}` = one key up and to the
        right and two keys to the right, in any order."""
        target = (b.x - a.x, b.y - a.y)
        if target == (0, 0):
            return {}
        best: tuple | None = None
        names = self.directions
        for i, n1 in enumerate(names):
            for n2 in names[i:]:
                (x1, y1), (x2, y2) = self.offsets[n1], self.offsets[n2]
                if n1 == n2:
                    count = target[0] // x1 if x1 else target[1] // y1
                    if count > 0 and (count * x1, count * y1) == target and (best is None or count < best[0]):
                        best = (count, {n1: count})
                    continue
                det = x1 * y2 - x2 * y1
                if det == 0:
                    continue
                c1, r1 = divmod(target[0] * y2 - x2 * target[1], det)
                c2, r2 = divmod(x1 * target[1] - target[0] * y1, det)
                if r1 or r2 or c1 <= 0 or c2 <= 0:
                    continue
                if best is None or c1 + c2 < best[0]:
                    best = (c1 + c2, {n1: c1, n2: c2})
        if best is None:
            raise BoardError(f"no path from {a.id} to {b.id}")
        return best[1]

    def direction_intervals(self) -> dict[str, int | None]:
        """Steps of the tuning each direction raises the pitch by, if it is the same
        everywhere on the keyboard (an isomorphic layout); None where it varies."""
        out: dict[str, int | None] = {}
        for d in self.directions:
            deltas = {n.pitch - k.pitch for k in self.keys.values() if (n := self.neighbours(k)[d]) is not None}
            out[d] = deltas.pop() if len(deltas) == 1 else None
        return out

    # --- playing a set of notes ---

    def shapes(self, pitches: list[int], near: Key | None = None, limit: int = 3) -> list[Shape]:
        """Ways to play these exact pitches close together, tightest first."""
        pitches = sorted(set(pitches))
        if not pitches:
            raise BoardError("no notes given")
        missing = [p for p in pitches if p not in self._by_pitch]
        if missing:
            low, high = self.range()
            names = ", ".join(self.tuning.name(p) for p in missing)
            raise BoardError(f"this keyboard has no key for {names}. It plays {low.name} to {high.name}; try another octave.")
        ref = near or self.centre()
        best: dict[frozenset, tuple[float, float, tuple[Key, ...]]] = {}
        for anchor in self.keys_for_pitch(pitches[0], ref)[:8]:
            options = [self.keys_for_pitch(p, anchor)[:3] for p in pitches[1:]]
            for combo in itertools.product(*options):
                keys = (anchor,) + combo
                span = max((self.distance(a, b) for a, b in itertools.combinations(keys, 2)), default=0.0)
                ident = frozenset(k.id for k in keys)
                entry = (round(span, 3), round(self.distance(anchor, ref), 3), keys)
                if ident not in best or entry[:2] < best[ident][:2]:
                    best[ident] = entry
        # one shape per starting key: its tightest
        per_anchor: dict[str, tuple[float, float, tuple[Key, ...]]] = {}
        for entry in best.values():
            a = entry[2][0].id
            if a not in per_anchor or entry[:2] < per_anchor[a][:2]:
                per_anchor[a] = entry
        ranked = sorted(per_anchor.values(), key=lambda e: (e[0], e[1], e[2][0].id))[:limit]
        return [
            Shape(
                keys=keys,
                span=span,
                moves=tuple(self.moves(keys[0], k) for k in keys[1:]),
                offsets=tuple((k.x - keys[0].x, k.y - keys[0].y) for k in keys[1:]),
            )
            for span, _, keys in ranked
        ]

    def fingering(self, keys: list[Key] | tuple[Key, ...], hand: str = "right") -> dict[str, int]:
        """The least effortful finger per key (1 = thumb .. 5 = little finger) for an average
        hand, the keys played together; see `fingering.py`. Empty for more than five keys."""
        try:
            ranked = fingering_model.fingerings(fingering_model.default_hand(), [self.position_mm(k) for k in keys], hand, 1)
        except fingering_model.FingeringError as e:
            raise BoardError(str(e)) from None
        return {k.id: f for k, f in zip(keys, ranked[0].fingers)} if ranked else {}

    # --- picture ---

    def text_map(self, octaves: bool = True, numbers: bool = False) -> str:
        """The keyfield as text, as the player sees it: far rows first, each key by its
        note name (or, with `numbers`, by its number within the octave), rows staggered
        by half a key like the hexagons."""
        if not self.keys:
            return "(no keyboard module connected)"
        cell = 4    # characters per half key width
        ks = list(self.keys.values())
        ymin = min(k.y for k in ks)
        rows: dict[int, list[Key]] = {}
        for k in ks:
            rows.setdefault(k.x * self._up, []).append(k)
        lines = []
        for h in sorted(rows, reverse=True):
            line = ""
            for k in sorted(rows[h], key=lambda k: k.y):
                if numbers:
                    label = str(self.tuning.number(k.pitch))
                else:
                    label = k.name if octaves else self.tuning.pitch_class_name(k.name)
                line = line.ljust((k.y - ymin) * cell) + label
            lines.append(line.rstrip())
        return "\n".join(lines)
