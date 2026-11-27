"""What the tutor's tools do. Everything a tool returns is in the player's terms: note
names, key ids, the six directions, seconds. Addresses, lattice positions and step counts
stay inside (`board.py`, `theory.py`).

`server.py` wraps these methods as MCP tools; tests call them directly.
"""

from __future__ import annotations

from pathlib import Path

import collections
import queue
import re
import threading
import time
from typing import Callable

from . import fingering as fingering_model
from .board import Key, Keyboard, Shape
import json
import math

from . import library as lib
from .theory import CHORDS as _CHORDS


def harmony_model_xen(quality: str) -> bool:
    """A chord quality that only tunings beyond twelve notes have."""
    return bool(_CHORDS.get(quality, {}).get("xen"))
from . import harmony as harmony_model
from . import percussion
from . import playalong
from . import voiceleading as voice_leading
from . import xen_progressions as xen_model
from . import rhythm as rhythm_model
from .osc import Sender
from .player import Player
from .wiki import Wiki
from .engine import Exercise, Finished, Mark, Press, ShowHint, Step, StepDone, Unmark
from .theory import CHORDS, SCALES, Chord, tuning_for
from .xt import EventPump, XentoolError

Rgb = tuple[int, int, int]
Progress = Callable[[float, float, str], None]

# What a colour means on the keys. Fingers: 1 = thumb .. 5 = little finger.
ROLES: dict[str, Rgb] = {
    "target": (255, 255, 255),
    "next": (90, 90, 90),
    "root": (255, 140, 0),
    "lh": (0, 90, 255),
    "rh": (0, 255, 80),
    "correct": (0, 255, 0),
    "wrong": (255, 0, 0),
    "finger1": (255, 255, 255),
    "finger2": (255, 220, 0),
    "finger3": (0, 255, 80),
    "finger4": (0, 200, 255),
    "finger5": (255, 0, 200),
}
ROLE_WORDS = {
    "target": "white: press this", "next": "dim white: comes next", "root": "orange: root of the chord",
    "lh": "blue: left hand", "rh": "green: right hand", "correct": "green while held: right", "wrong": "red while held: wrong",
    "finger1..finger5": "thumb white, index yellow, middle green, ring cyan, little finger magenta",
}
DIM_BASE = 0.2          # layout colours are dimmed to this while tutor lights are on
FINGER_NOTE = "1 thumb, 2 index, 3 middle, 4 ring, 5 little finger; 'fingers' lists them lowest note first. Computed for an average hand as a starting point: offer the alternatives and let the player choose."
FINGER_LIGHTS = {1: "white", 2: "yellow", 3: "green", 4: "cyan", 5: "magenta"}    # as in ROLES finger1..finger5
SAY_CHORD = ("When you introduce a chord, say which note is the root and where it lies in the shape, and name each finger with "
             "its light colour (the root is lit orange when fingers are not shown).")
IMPROVISE_MAX_S = 150.0     # an improvisation take may be this long; progress is reported with every chord
CLICK_CHANNEL = 10      # General MIDI percussion
CLICK_NOTES = (76, 77)  # accented click, plain click: high and low wood block
PAUSE_S = 12.0          # an exercise returns when the player tried a step and then kept quiet this long
MAX_BLOCK_S = 60.0      # longest a tool call waits for the player
CHORD_WINDOW_S = 0.12   # notes starting within this of each other were played together
MEMORY_S = 600.0        # how far back `played` can look
MEMORY_NOTES = 4000     # and how many notes are kept at most
PLAYED_ENTRIES = 60     # entries in one `played` answer; the latest ones if there are more


class TutorError(ValueError):
    """A tool was used in a way that cannot work; the message says how to fix the call."""


def _moves_text(moves: dict[str, int]) -> str:
    if not moves:
        return "the same key"
    return ", ".join(f"{n} {d.replace('_', ' ')}" for d, n in moves.items())


class Lights:
    """The tutor's colours on the keys. Remembers what is lit and sends only changes."""

    def __init__(self, client):
        self.client = client
        self.lit: dict[str, tuple[tuple[int, int], Rgb]] = {}   # key id -> (address, colour)

    def show(self, wanted: dict[Key, Rgb]) -> None:
        """Make exactly these keys lit."""
        new = {k.id: ((k.board, k.key), rgb) for k, rgb in wanted.items()}
        gone = [addr for kid, (addr, _) in self.lit.items() if kid not in new]
        changed = {addr: rgb for kid, (addr, rgb) in new.items() if self.lit.get(kid) != (addr, rgb)}
        if not new and self.lit:
            self.client.overlay(clear="all")
        elif gone or changed:
            self.client.overlay(set=changed, clear=gone or None, dim_base=DIM_BASE if not self.lit else None)
        self.lit = new

    def add(self, keys: dict[Key, Rgb]) -> None:
        merged = {kid: v for kid, v in self.lit.items()}
        merged.update({k.id: ((k.board, k.key), rgb) for k, rgb in keys.items()})
        changed = {addr: rgb for kid, (addr, rgb) in merged.items() if self.lit.get(kid) != (addr, rgb)}
        if changed:
            self.client.overlay(set=changed, dim_base=DIM_BASE if not self.lit else None)
        self.lit = merged

    def remove(self, keys: list[Key]) -> None:
        gone = [self.lit.pop(k.id)[0] for k in keys if k.id in self.lit]
        if gone:
            self.client.overlay(clear="all" if not self.lit else gone)

    def clear(self) -> None:
        self.client.overlay(clear="all")
        self.lit = {}


PRACTICE_NOTE = (
    "Practice mode: no real keyboard is attached; the one described here is a stand-in. "
    "Looking things up works (keyboard_info, keys, theory, find_shape). Lights and sound reach "
    "nobody and no key presses will arrive, so demo, listen and run_exercise are switched off. "
    "Tell the player this is a dry run and teach in words."
)


class Tutor:
    def __init__(self, client, tilt_deg: float = 0.0, practice: bool = False, player: Player | None = None,
                 library: lib.Library | None = None, wiki: Wiki | None = None, mridangam: Sender | None = None,
                 tabla: Sender | None = None, tanpura: Sender | None = None):
        self.client = client
        self.wiki = wiki or Wiki()
        self.music = library or lib.Library()
        self.player = player or Player()        # the measured hand and the player's own fingerings
        self.practice = practice    # a stand-in keyboard (--fake): nobody sees lights or presses keys
        self.tilt_deg = tilt_deg
        self.lights = Lights(client)
        self.hand_model = self.player.hand()    # an average hand until the player's is measured
        self._click_by_midi = True              # until xentool turns out not to know /api/midi
        self.mridangam = mridangam              # OSC sender to the mridangam patch, or None if there is none
        self.tabla = tabla                      # the same for the tabla patch
        self.tanpura = tanpura                  # the drone's own instrument (host/synth/tanpura.scd), if one is set up
        self.layouts_dir = Path(__file__).resolve().parents[2] / "build" / "layouts"     # the layout files the keyboard can be switched to
        self._layouts: dict | None = None
        self._drone: tuple[threading.Thread, threading.Event, dict] | None = None    # a sounding drone: thread, its stop, what it plays
        self._playing: tuple[threading.Thread, threading.Event, dict] | None = None  # a piece being played: thread, its stop, what it plays
        self._keyboard: Keyboard | None = None
        self._kb_lock = threading.Lock()
        self._activity = threading.Lock()   # one demo / listen / exercise at a time
        self._cancel = threading.Event()
        self._last_steps: tuple[list[Step], list[dict]] | None = None    # for continuing after a time limit
        self.pump = EventPump(client, on_setup=self._forget_keyboard)
        # Everything the player plays is remembered, whether or not a tool is waiting for it:
        # the model is slow and the player does not wait for it (see `played`).
        self._memory: collections.deque[dict] = collections.deque(maxlen=MEMORY_NOTES)   # {key, pitch, start, end}
        self._memory_down: dict[str, dict] = {}
        self._memory_lock = threading.Lock()
        self._checked = time.monotonic()    # the model has been told everything played before this
        self._memory_q = self.pump.subscribe()
        threading.Thread(target=self._remember, name="tutor-memory", daemon=True).start()
        self.pump.start()

    # --- keyboard ---

    def _forget_keyboard(self) -> None:
        with self._kb_lock:
            self._keyboard = None
        self._layouts = None            # the connected modules may have changed
        if self._playing:               # so do the keys of a piece being played
            self._playing[1].set()
        if self._drone:                 # its keys belong to the keyboard that is gone
            self._drone[1].set()

    @property
    def keyboard(self) -> Keyboard:
        with self._kb_lock:
            if self._keyboard is None:
                self._keyboard = Keyboard(self.client.setup(), tilt_deg=self.tilt_deg)
            if not self._keyboard.keys:
                self._keyboard = None
                raise TutorError("no keyboard module is connected to xentool. Plug one in and call keyboard_info again.")
            return self._keyboard

    def _key_brief(self, key: Key, name: str | None = None) -> dict:
        return {"key": key.id, "note": name or key.name, "number": self.keyboard.tuning.number(key.pitch)}

    def _direction_words(self, steps: int | None) -> str:
        if steps is None:
            return "varies from key to key"
        t = self.keyboard.tuning
        short = t.interval(abs(steps))
        n = abs(steps)
        return f"{t.words(short)} {'up' if steps > 0 else 'down'} ({short}, {n} step{'' if n == 1 else 's'})"

    def keyboard_info(self, include_map: bool = True) -> dict:
        kb = self.keyboard
        t = kb.tuning
        low, high = kb.range()
        per_direction = kb.direction_intervals()
        isomorphic = all(v is not None for v in per_direction.values())
        shared = sum(1 for keys in kb._by_pitch.values() if len(keys) > 1)
        facts = t.describe()
        out = {"practice_mode": PRACTICE_NOTE} if self.practice else {}
        out |= {
            "tuning": f"{t.edo} equal steps per octave",
            "note_numbers": (
                f"Every note has a name and a number: its step within the octave, counted from C = 0 "
                f"up to {t.edo - 1}. Players of this tuning often say the number. Results give both "
                f"(vE4 (17) means: name vE4, number 17); you may pass either, a number as 17 or 17(4) with its octave."
            ),
            "layout": kb.layout,
            "keys": len(kb.keys),
            "lowest_note": low.name,
            "highest_note": high.name,
            "directions": {d: self._direction_words(s) for d, s in per_direction.items()},
            "same_shape_everywhere": isomorphic,
            "notes_on_more_than_one_key": shared,
            "smallest_step_cents": facts["smallest_step_cents"],
            "fifth": facts["fifth"],
            "thirds": facts["thirds"],
            "chord_qualities": facts["chord_qualities"],
            "chords_beyond_12_tone": facts["beyond_12_tone"],
            "scales": list(SCALES),
            "light_colours": ROLE_WORDS,
            "good_to_know": list(facts["notes"]),
        }
        if isomorphic:
            out["good_to_know"].append(
                "Every direction is the same interval everywhere, so a chord is a hand shape: "
                "the same shape started on another key is the same kind of chord on another root."
            )
        else:
            out["good_to_know"].append("This layout is not the same everywhere; ask find_shape for each chord instead of moving a shape.")
        if include_map:
            out["map"] = kb.text_map() + "\n\nthe same keys by number:\n" + kb.text_map(numbers=True)
            out["map_legend"] = "Far side of the keyboard at the top; each row is shifted half a key against the next."
            if abs(kb.tilt_deg) > 1:
                out["map_legend"] += (
                    f" The map is drawn with key rows level; on the instrument the keyfield is turned "
                    f"{abs(kb.tilt_deg):.0f} degrees {'anticlockwise' if kb.tilt_deg > 0 else 'clockwise'}, "
                    f"which is what the direction names above describe."
                )
        return out

    # --- tuning ---

    @staticmethod
    def _layout_words(name: str, notes: int | None) -> dict:
        return {"layout": name, "notes_per_octave": notes}

    def tuning(self, to: str | None = None, include_map: bool = True) -> dict:
        """Without `to`: the tunings this keyboard can be switched to. With `to` (a layout
        name, or a number of notes per octave): switch, and describe the keyboard anew."""
        state = self.client.layouts()
        available = [(a["name"], a.get("edo")) for a in state.get("available", [])]
        current = state.get("current", "")
        if to is None or not str(to).strip():
            return {
                "current": self._layout_words(current, self.keyboard.tuning.edo),
                "available": [self._layout_words(n, e) for n, e in available],
                "how": "tuning with to = a layout name or a number of notes per octave switches the whole keyboard; "
                       "every note name, number, key and chord shape is different afterwards.",
            }
        want = str(to).strip()
        chosen = [n for n, _ in available if n.lower() == want.lower()]
        others: list[str] = []
        if not chosen:
            digits = re.fullmatch(r"(\d+)(?:\s*(?:edo|et|tet|notes?|tones?|steps?).*)?", want, re.I)
            if digits:
                same = [n for n, e in available if e == int(digits.group(1))]
                # the layout of the same kind as the current one first, then the usual one
                kind = current.split("-", 1)[1] if "-" in current else ""
                same.sort(key=lambda n: (not (kind and n.endswith(kind)), "bosanquet" not in n.lower(), n))
                chosen, others = same[:1], same[1:]
        if not chosen:
            names = ", ".join(f"{n} ({e})" for n, e in available) or "none"
            raise TutorError(f"this keyboard has no layout '{to}'. Available (name, notes per octave): {names}.")
        name = chosen[0]
        if name == current:
            return {"already": self._layout_words(current, self.keyboard.tuning.edo), "note": "The keyboard is in this tuning; nothing changed."}
        if not self._activity.acquire(blocking=False):
            raise TutorError("a demo, listen or exercise is still running; call stop first, or wait for it to end, then switch the tuning")
        try:
            self.lights.clear()
            self.client.switch_layout(name)
            self._forget_keyboard()
            self._last_steps = None
            with self._memory_lock:         # what was played belongs to the old tuning
                self._memory.clear()
                self._memory_down.clear()
            self._told_until_now()
        finally:
            self._activity.release()
        out = {"switched_from": current, "switched_to": name}
        if others:
            out["other_layouts_with_this_tuning"] = others
        out["note"] = ("Everything is different now: note names, numbers, key ids, chord shapes and fingerings. Look them up "
                       f"again. To go back: tuning with to = {current}.")
        out.update(self.keyboard_info(include_map))
        return out

    # --- notes and keys ---

    def _pitch(self, note: str, near: Key | None = None) -> tuple[int, str]:
        """A note name -> (pitch, name as spelled). Without an octave: the octave whose key
        lies nearest to `near` (or the middle of the keyboard)."""
        kb = self.keyboard
        t = kb.tuning
        pitch, has_octave = t.parse(note)
        if has_octave:
            letter = t.letter_of(note)
            return pitch, t.name_with_letter(pitch, letter) if letter else t.name(pitch)
        ref = near or kb.centre()
        low, high = kb.range()
        options = [p for p in range(pitch % t.edo, high.pitch + 1, t.edo) if p >= low.pitch and kb.keys_for_pitch(p)]
        if not options:
            raise TutorError(f"this keyboard has no key for {note}. It plays {low.name} to {high.name}.")
        best = min(options, key=lambda p: (kb.distance(kb.keys_for_pitch(p, ref)[0], ref), p))
        letter = t.letter_of(note)
        return best, t.name_with_letter(best, letter) if letter else t.name(best)

    def keys(self, key: str | None = None, note: str | None = None, near: str | None = None) -> dict:
        kb = self.keyboard
        t = kb.tuning
        if (key is None) == (note is None):
            raise TutorError("give either key (an id such as k319) or note (a name such as C4), not both and not neither")
        if key is not None:
            k = kb.key(key)
            neighbours = {}
            for d in kb.directions:
                n = kb.neighbours(k)[d]
                neighbours[d] = (
                    {**self._key_brief(n), "interval": self._direction_words(n.pitch - k.pitch)} if n else "edge of the keyboard"
                )
            return {
                "key": k.id,
                "note": k.name,
                "number": t.number(k.pitch),
                "other_names": [s for s in t.spellings(k.pitch) if s != k.name][:3],
                "neighbours": neighbours,
                "same_note_elsewhere": [{"key": o.id, "from_here": _moves_text(kb.moves(k, o))} for o in kb.same_note(k)],
            }
        ref = kb.key(near) if near else None
        pitch, has_octave = t.parse(note)
        if has_octave:
            pitches = [pitch]
        else:
            low, high = kb.range()
            pitches = [p for p in range(pitch % t.edo, high.pitch + 1, t.edo) if p >= low.pitch]
        letter = t.letter_of(note)
        found = []
        for p in pitches:
            for k in kb.keys_for_pitch(p, ref):
                entry = self._key_brief(k, t.name_with_letter(p, letter) if letter else None)
                if ref:
                    entry["from_near"] = _moves_text(kb.moves(ref, k))
                    entry["_d"] = kb.distance(ref, k)
                found.append(entry)
        if not found:
            low, high = kb.range()
            raise TutorError(f"this keyboard has no key for {note}. It plays {low.name} to {high.name}.")
        if ref:
            found.sort(key=lambda e: e.pop("_d"))
        return {"note": note, "keys": found[:12], "more": max(0, len(found) - 12)}

    # --- theory ---

    def _chord_dict(self, chord: Chord) -> dict:
        t = self.keyboard.tuning
        return {
            "chord": chord.label,
            "notes": [t.label(p, n) for p, n in zip(chord.pitches, chord.names)],
            "bass": t.label(chord.pitches[0], chord.names[0]),
            "intervals_above_bass": [t.interval_words(p - chord.pitches[0], i) for p, i in zip(chord.pitches[1:], chord.intervals[1:])],
            "sounds_like": CHORDS[chord.quality]["sounds"],
            "tuning": list(chord.purity),
        }

    def _parse_chord(self, root: str, quality: str, inversion: int = 0, near: Key | None = None) -> Chord:
        pitch, name = self._pitch(root, near)
        return self.keyboard.tuning.chord(pitch, quality, inversion, name)

    def _own_reading(self, pitches: list[int]) -> str | None:
        """Name a set of pitches with the tutor's own chord vocabulary, if it fits."""
        t = self.keyboard.tuning
        pcs = sorted({p % t.edo for p in pitches})
        bass_pc = min(pitches) % t.edo
        for root_pc in pcs:
            rel = tuple(sorted((pc - root_pc) % t.edo for pc in pcs if pc != root_pc))
            for q in t.qualities():
                if tuple(sorted(t._tone_steps(q))) == rel:
                    root_pitch = next(p for p in sorted(pitches) if p % t.edo == root_pc)
                    root = t.pitch_class_name(t.name(root_pitch))
                    if root_pc == bass_pc:
                        return f"{root} {q}"
                    order = sorted(((pc - root_pc) % t.edo) for pc in pcs)
                    inversion = order.index((bass_pc - root_pc) % t.edo)
                    return f"{root} {q}, {['', '1st', '2nd', '3rd'][inversion]} inversion"
        return None

    def _identify(self, pitches: list[int]) -> dict:
        t = self.keyboard.tuning
        pitches = sorted(set(pitches))
        out: dict = {"notes": [t.label(p) for p in pitches]}
        if len(pitches) < 2:
            return out
        out["intervals_above_bass"] = [t.interval_words(p - pitches[0]) for p in pitches[1:]]
        own = self._own_reading(pitches)
        if own:
            out["chord"] = own
        try:
            readings = self.client.chord_names(t.edo, sorted({p % t.edo for p in pitches}))
        except XentoolError:
            readings = []
        bass_pc = pitches[0] % t.edo
        others = []
        for r in readings:
            root_pitch = next((p for p in pitches if p % t.edo == r["root_pc"]), None)
            if root_pitch is None:
                continue
            entry = f"{t.pitch_class_name(t.name(root_pitch))}: {r['best']}"
            if r["root_pc"] == bass_pc:
                out["as_played"] = entry
            else:
                others.append(entry)
        if others:
            out["other_readings"] = others[:3]
        if "chord" not in out and "as_played" not in out:
            out["chord"] = "no common name"
        return out

    def theory(self, op: str, root: str | None = None, quality: str = "major", inversion: int = 0,
               notes: list[str] | None = None, keys: list[str] | None = None, mode: str = "major",
               numerals: list[str] | None = None, sevenths: bool = False) -> dict:
        kb = self.keyboard
        t = kb.tuning
        op = op.strip().lower()
        if op == "chord":
            if not root:
                raise TutorError("op chord needs root (a note name such as C or Eb4) and quality")
            return self._chord_dict(self._parse_chord(root, quality, inversion))
        if op == "identify":
            if keys:
                pitches = [kb.key(k).pitch for k in keys]
            elif notes:
                pitches = [self._pitch(n)[0] for n in notes]
            else:
                raise TutorError("op identify needs notes (names with octave) or keys (ids)")
            return self._identify(pitches)
        if op in ("scale", "progression"):
            if not root:
                raise TutorError(f"op {op} needs root (the tonic, such as C or F#) and mode")
            tonic, tonic_name = self._pitch(root)
            if op == "scale":
                degrees = t.diatonic_chords(tonic, mode, sevenths, tonic_name)
                return {
                    "scale": f"{t.pitch_class_name(tonic_name)} {mode}",
                    "notes": [t.label(p, n) for p, n in t.scale(tonic, mode, tonic_name)],
                    "chords": [f"{d['numeral']}: {t.pitch_class_name(d['root_name'])} {d['quality']}" for d in degrees],
                }
            if not numerals:
                raise TutorError("op progression needs numerals, for example ['I', 'IV', 'V7', 'I']")
            chords = t.progression(tonic, mode, numerals, tonic_name)
            return {
                "key": f"{t.pitch_class_name(tonic_name)} {mode}",
                "chords": [
                    {"numeral": n, "chord": c.label, "notes": [t.label(p, name) for p, name in zip(c.pitches, c.names)]}
                    for n, c in zip(numerals, chords)
                ],
            }
        if op == "tuning":
            return t.describe()
        raise TutorError("op must be one of: chord, identify, scale, progression, tuning")

    # --- shapes ---

    def _fingerings(self, keys, hand: str, limit: int = 3) -> list:
        """The player's own fingering of this shape first (if they have one), then the computed ones."""
        side = hand.strip().lower()
        try:
            pts = [self.keyboard.position_mm(k) for k in keys]
            ranked = fingering_model.fingerings(self.hand_model, pts, side, limit)
            chosen = self.player.preferred(side, pts) if ranked else None
            if chosen:
                ranked = fingering_model.with_own(ranked, fingering_model.own_fingering(self.hand_model, pts, chosen, side))[:limit]
            return ranked
        except fingering_model.FingeringError as e:
            raise TutorError(str(e)) from None

    @staticmethod
    def _fingering_brief(f) -> dict:
        out = {"fingers": f.text, "feel": f.feel, "effort": round(f.effort, 1)}
        if f.own:
            out["yours"] = "the player's own fingering for this shape: use it"
        if f.reasons:
            out["why"] = list(f.reasons)
        return out

    # --- the player's hand and their own fingerings ---

    def _hold_still(self, count: int, wait_s: float, progress: Progress | None) -> list[Key]:
        """Wait until exactly `count` keys are held and stay so for a second."""
        self._need_player("measuring the hand")
        kb = self.keyboard
        wait_s = max(3.0, min(float(wait_s), MAX_BLOCK_S))
        self._begin()
        try:
            deadline = time.monotonic() + wait_s
            steady_since, last = None, None
            while not self._cancel.is_set():
                now = time.monotonic()
                held = sorted(self.client.held())
                if len(held) == count and held == last:
                    if steady_since is None:
                        steady_since = now
                    elif now - steady_since >= 1.0:
                        keys = [kb.at_address(b, k) for b, k in held]
                        if all(keys):
                            return keys
                else:
                    steady_since, last = None, held
                    if progress:
                        progress(len(held), count, f"{len(held)} of {count} keys held")
                if now > deadline:
                    raise TutorError(f"waited {wait_s:.0f} s for {count} keys held still; {len(held)} are held now. "
                                     f"Explain again what to do and call this once more.")
                self._cancel.wait(0.1)
            raise TutorError("stopped")
        finally:
            self._activity.release()
            self._told_until_now()

    def _hand_status(self) -> dict:
        p = self.player
        out: dict = {"hand_size_table": p.size, "measured": p.calibrated or "nothing yet: an average hand is assumed"}
        if p.thumb_span_mm:
            out["thumb_to_little_finger_mm"] = round(p.thumb_span_mm)
        if p.finger_span_mm:
            out["index_to_little_finger_mm"] = round(p.finger_span_mm)
        if p.rest:
            tx, ty = p.rest[1]
            out["resting_thumb"] = f"{abs(tx):.0f} mm beside and {abs(ty):.0f} mm {'nearer than' if ty < 0 else 'beyond'} the middle finger"
        return out

    def hand(self, action: str = "status", hand: str = "right", fingers: list[int] | None = None, size: str | None = None,
             wait_s: float = 30, progress: Progress | None = None) -> dict:
        """Measure the player's hand so that fingerings fit it. Actions: status, rest (five
        fingers lying relaxed on five keys), stretch (the widest comfortable-to-reach
        stretch between fingers [1, 5] or [2, 5]), size (small / medium / large), reset."""
        action = action.strip().lower()
        kb = self.keyboard
        try:
            if action == "status":
                return self._hand_status()
            if action == "size":
                if not size:
                    raise TutorError("action size needs size: small, medium or large")
                self.player.set_size(size)
            elif action == "reset":
                self.player.reset_hand()
            elif action == "rest":
                keys = self._hold_still(5, wait_s, progress)
                self.player.set_rest(fingering_model.rest_from_handprint([kb.position_mm(k) for k in keys], hand))
            elif action == "stretch":
                pair = tuple(sorted(int(f) for f in (fingers or [1, 5])))
                if pair not in ((1, 5), (2, 5)):
                    raise TutorError("a stretch is measured with fingers [1, 5] (thumb and little finger) or [2, 5] (index and little finger)")
                a, b = self._hold_still(2, wait_s, progress)
                mm = kb.distance(a, b) * kb.key_pitch_mm
                if not 60 <= mm <= 320:
                    raise TutorError(f"those two keys are {mm:.0f} mm apart, which cannot be that stretch; ask the player to hold only the two keys")
                self.player.set_span(pair, mm)
            else:
                raise TutorError("action must be one of: status, rest, stretch, size, reset")
        except fingering_model.FingeringError as e:
            raise TutorError(str(e)) from None
        self.hand_model = self.player.hand()
        return {"done": action, **self._hand_status(), "note": "Fingerings are computed for this hand from now on."}

    def _shape_keys(self, keys: list[str] | None, root: str | None, quality: str, inversion: int, notes: list[str] | None) -> tuple[list[Key], str]:
        kb = self.keyboard
        if keys:
            ks = sorted((kb.key(k) for k in keys), key=lambda k: (k.pitch, k.id))
            return ks, " ".join(k.name for k in ks)
        if notes:
            resolved = [self._pitch(n) for n in notes]
            return list(kb.shapes([p for p, _ in resolved], None, 1)[0].keys), " ".join(n for _, n in resolved)
        if root:
            chord = self._parse_chord(root, quality, inversion)
            return list(kb.shapes(list(chord.pitches), None, 1)[0].keys), chord.label
        raise TutorError("say which shape: keys (ids), a chord (root, quality, inversion) or notes")

    def fingering_book(self, action: str = "list", fingers: list[int] | None = None, hand: str = "right", keys: list[str] | None = None,
                       root: str | None = None, quality: str = "major", inversion: int = 0, notes: list[str] | None = None) -> dict:
        """The player's own fingerings, kept between sessions. save: this shape is played
        with these fingers (lowest note first); forget; list."""
        action = action.strip().lower()
        side = hand.strip().lower()
        if side not in ("left", "right"):
            raise TutorError(f"hand must be 'left' or 'right', not '{hand}'")
        if action == "list":
            entries = self.player.entries()
            return {"own_fingerings": entries, "note": "These take precedence over computed fingerings, on every root with the same hand shape."
                    if entries else "The player has not settled on any fingering yet."}
        if action not in ("save", "forget"):
            raise TutorError("action must be one of: list, save, forget")
        ks, label = self._shape_keys(keys, root, quality, inversion, notes)
        pts = [self.keyboard.position_mm(k) for k in ks]
        if action == "forget":
            found = self.player.forget(side, pts)
            return {"forgotten": label if found else None, "note": None if found else "There was no own fingering for this shape."}
        if not fingers:
            raise TutorError("action save needs fingers: one per key, lowest note first, 1 (thumb) to 5 (little finger)")
        try:
            own = fingering_model.own_fingering(self.hand_model, pts, tuple(fingers), side)
        except fingering_model.FingeringError as e:
            raise TutorError(str(e)) from None
        # the quality without the root: the shape serves every root
        general = label.split(" ", 1)[1] if (root and " " in label) else label
        self.player.remember(side, pts, own.fingers, general if root else label)
        return {"saved": {"for": general if root else label, "hand": side, **self._fingering_brief(own)},
                "note": "Used from now on for this hand shape on every root, also inside phrases."}

    def _finger_words(self, finger: int | None, root: bool = False) -> dict:
        """What the tutor says about one key of a chord: the finger, the colour it is lit in
        when fingers are shown, and whether it is the root."""
        out: dict = {}
        if root:
            out["role"] = "root"
        if finger:
            out["finger"] = finger
            out["finger_light"] = FINGER_LIGHTS[finger]
        return out

    def _shape_dict(self, shape: Shape, names: dict[int, str], hand: str, ranked: list | None = None, root: int | None = None) -> dict:
        kb = self.keyboard
        edo = kb.tuning.edo
        ranked = self._fingerings(shape.keys, hand) if ranked is None else ranked
        fingers = dict(zip((k.id for k in shape.keys), ranked[0].fingers)) if ranked else {}
        first = shape.keys[0]
        out = {
            "keys": [
                {
                    **self._key_brief(k, names.get(k.pitch)),
                    **({"from_first": _moves_text(kb.moves(first, k))} if i else {}),
                    **self._finger_words(fingers.get(k.id), root is not None and k.pitch % edo == root % edo),
                }
                for i, k in enumerate(shape.keys)
            ],
            "reach": shape.reach,
            "span_key_widths": round(shape.span, 1),
        }
        if ranked:
            out["fingering"] = self._fingering_brief(ranked[0])
            if len(ranked) > 1:
                out["other_fingerings"] = [self._fingering_brief(f) for f in ranked[1:]]
        else:
            out["fingering"] = "more than five notes: two hands"
        return out

    def find_shape(self, root: str | None = None, quality: str = "major", inversion: int = 0,
                   notes: list[str] | None = None, near: str | None = None, hand: str = "right", limit: int = 3) -> dict:
        kb = self.keyboard
        ref = kb.key(near) if near else None
        chord_root: int | None = None
        if notes:
            resolved = [self._pitch(n, ref) for n in notes]
            pitches = [p for p, _ in resolved]
            names = {p: n for p, n in resolved}
            label = " ".join(n for _, n in resolved)
        elif root:
            chord = self._parse_chord(root, quality, inversion, ref)
            pitches, names, label = list(chord.pitches), dict(zip(chord.pitches, chord.names)), chord.label
            chord_root = chord.root
        else:
            raise TutorError("give a chord (root and quality) or notes (a list of note names)")
        limit = max(1, min(limit, 5))
        # among the ways that lie close, the ones that fall best under the hand come first
        found = [(s, self._fingerings(s.keys, hand)) for s in kb.shapes(pitches, ref, limit + 2)]
        order = sorted(range(len(found)), key=lambda i: (round(found[i][1][0].effort) if found[i][1] else 99, i))[:limit]
        shapes = [found[i][0] for i in order]
        out = {"for": label, "hand": hand, "ways": [self._shape_dict(found[i][0], names, hand, found[i][1], chord_root) for i in order],
               "fingers": FINGER_NOTE}
        if chord_root is not None:
            edo = kb.tuning.edo
            out["root"] = next((f"{n} ({kb.tuning.number(p)})" for p, n in names.items() if p % edo == chord_root % edo), label.split()[0])
            out["say"] = SAY_CHORD
        if len({s.offsets for s in shapes}) == 1 and len(shapes) > 1:
            out["note"] = "All of these are the same hand shape in different places."
        return out

    # --- harmony: what follows what ---

    def _harmony_stats(self) -> dict:
        if getattr(self, "_harmony", None) is None:
            path = self.music.folder / "harmony.json"
            self._harmony = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return self._harmony

    def _harmony_key(self, key: str) -> tuple[str, bool]:
        parsed = lib.parse_key(key.strip().replace(" minor", "min").replace(" major", ""))
        if not parsed:
            raise TutorError(f"key must be a note name, with 'minor' for a minor key (C, Eb, G minor), not '{key}'")
        return parsed

    def _degree_symbol(self, roman: str, key: tuple[str, bool]) -> str:
        """A degree of the key as a chord symbol: "bVII7" in C -> "Bb7"."""
        degree, suffix = harmony_model.split(roman)
        names = self._degrees(key[0])
        name = names[("I", "II", "III", "IV", "V", "VI", "VII").index(degree.lstrip("b#"))]
        if degree.startswith("b"):
            name = name[:-1] if name.endswith("#") else name + "b"
        elif degree.startswith("#"):
            name = name[:-1] if name.endswith("b") else name + "#"
        return name + suffix

    def _as_degree(self, chord: str, key: tuple[str, bool]) -> str:
        text = chord.strip()
        if text.lstrip("b#")[:1] in ("I", "V"):
            try:
                harmony_model.split(text)
                return text
            except ValueError:
                pass
        roman = harmony_model.numeral(text, key)
        if not roman:
            raise TutorError(f"'{chord}' is neither a chord symbol (Dm7, G7, Bbmaj7) nor a degree (IIm7, V7, bVII7)")
        return roman

    def _move_words(self, a: dict, b: dict) -> tuple[str, int]:
        """How the root moves from chord step a to b in this tuning, and how many notes they share."""
        t = self.keyboard.tuning
        edo = t.edo
        ra, rb = t.parse(a["root"])[0] % edo, t.parse(b["root"])[0] % edo
        up = (rb - ra) % edo
        fifth, fourth = t.steps_for(3 / 2), t.steps_for(4 / 3)
        if up == 0:
            words = "the root stays"
        elif up == fourth:
            words = "the root falls a fifth (rises a fourth)"
        elif up == fifth:
            words = "the root rises a fifth (falls a fourth)"
        elif abs(up - fourth) == 1 and edo > 24:
            words = f"the root rises a fourth that is one step {'wide' if up > fourth else 'narrow'}: here the comma shows"
        elif abs(up - fifth) == 1 and edo > 24:
            words = f"the root rises a fifth that is one step {'wide' if up > fifth else 'narrow'}: here the comma shows"
        else:
            down = edo - up
            words = f"the root {'rises' if up <= down else 'falls'} a {t.words(t.interval(min(up, down)))}"
        shared = len({t.parse(n)[0] % edo for n in a.get("tones", a["notes"])} & {t.parse(n)[0] % edo for n in b.get("tones", b["notes"])})
        return words, shared

    def _harmony_steps(self, romans: list[str], key: tuple[str, bool], voicing: str) -> list[dict]:
        piece = {"title": "", "key": key[0] + ("min" if key[1] else ""), "meter": "4/4", "bars": 0}
        symbols = [self._degree_symbol(r, key) for r in romans]
        steps = self._changes_steps(piece, [[s] for s in symbols], voicing, "plain", False)[0]
        if len(steps) != len(symbols):
            raise TutorError("one of these chords could not be read; write them as symbols (Dm7, G7) or degrees (IIm7, V7)")
        for step, roman in zip(steps, romans):
            step["degree"] = roman
        return steps

    def harmony(self, action: str = "overview", key: str = "C", chord: str | None = None, chords: list[str] | None = None,
                limit: int = 6, voicing: str = "shell", to: str | None = None, max_cents: float | None = None, length: int = 5,
                via: str | None = None, seed: int = 0, roots: str = "any", sizes: str = "same", name: str | None = None) -> dict:
        """Which chord tends to follow which. overview | next | common | analyse | steps | tuning;
        from the tuning itself: neighbours | path; from the wiki: xen."""
        action = action.strip().lower()
        if action in ("neighbours", "neighbors"):
            return self._harmony_neighbours(chord, to, limit, max_cents, roots, sizes)
        if action == "path":
            return self._harmony_path(chord, to, length, max_cents, via, seed, roots, sizes)
        if action == "xen":
            return self._harmony_xen(name, key)
        t = self.keyboard.tuning
        stats = self._harmony_stats()
        if not stats and action != "tuning":
            raise TutorError("the harmony statistics are not installed (python -m tutor.library_build builds them from the jazz changes)")
        k = self._harmony_key(key)
        mode = "minor" if k[1] else "major"
        table = stats.get(mode, {})
        source = (f"counted over the chord changes of {table.get('tunes', 0)} jazz standards in {mode} keys: what is common in that repertoire, "
                  "not a rule. Degrees are relative to the key.")
        limit = max(1, min(int(limit), 12))
        if voicing not in ("full", "shell", "guide", "root"):
            raise TutorError("voicing must be one of: full, shell, guide, root")

        if action == "overview":
            return {
                "source": source, "key": f"{k[0]} {mode}",
                "most_used_chords": [f"{self._degree_symbol(r, k)} ({r}, {share} %)" for r, share in table["chords"][:10]],
                "how": "next (chord): what usually follows; common: frequent runs of three and four chords; analyse (chords): how usual each "
                       "step of a progression is; steps (chords): any progression as chord steps for demo and improvise; tuning: what this "
                       "tuning does to these progressions.",
                "beyond_this_repertoire": "These counts know only twelve-tone chords. neighbours (chord): the chords closest to a chord in "
                                          "this tuning by the smallest movement of the voices, including those a piano lacks; path (chord): "
                                          "a short progression built from such moves; xen: progressions and chords microtonal musicians "
                                          "have written down for this tuning.",
                "other_musics": "Makam and raga have no chord progressions: what sounds right there is the path through the mode, the notes "
                                "that are dwelt on and the characteristic phrases. See library (search makam, action raga).",
            }

        if action == "next":
            if not chord:
                raise TutorError("action next needs chord: a symbol (Dm7) or a degree (IIm7)")
            roman = self._as_degree(chord, k)
            follows = table["next"].get(roman)
            if not follows:
                return {"chord": f"{self._degree_symbol(roman, k)} ({roman})", "source": source,
                        "note": "This chord is too rare in the repertoire counted to say what follows it. Try its plain form, or analyse a whole progression."}
            here = self._harmony_steps([roman], k, "full")[0]
            options = []
            for nxt, share in follows[:limit]:
                step = self._harmony_steps([nxt], k, "full")[0]
                move, shared = self._move_words(here, step)
                entry = {"chord": self._degree_symbol(nxt, k), "degree": nxt, "in_percent_of_cases": share, "move": move, "shared_notes": shared}
                if nxt in harmony_model.FUNCTIONS:
                    entry["role"] = harmony_model.FUNCTIONS[nxt]
                options.append(entry)
            out = {"after": f"{self._degree_symbol(roman, k)} ({roman})", "usually_follows": options,
                   "usually_before_it": [f"{self._degree_symbol(r, k)} ({r}, {s} %)" for r, s in table["before"].get(roman, [])[:4]], "source": source}
            if roman in harmony_model.FUNCTIONS:
                out["role"] = harmony_model.FUNCTIONS[roman]
            out["note"] = "harmony action steps with chords=[this, one of these] gives both as chord steps to hear the move."
            return out

        if action == "common":
            runs = []
            for run, share in table["runs"][:limit * 2]:
                romans = run.split(" ")
                runs.append({"degrees": run, "in_this_key": " ".join(self._degree_symbol(r, k) for r in romans), "in_percent_of_tunes": share})
            return {"key": f"{k[0]} {mode}", "frequent_runs": runs[:limit * 2], "source": source,
                    "note": "harmony action steps with chords = the degrees of a run gives it as chord steps."}

        if action in ("analyse", "steps"):
            if not chords:
                raise TutorError(f"action {action} needs chords: a list of symbols (Dm7, G7, Cmaj7) or degrees (IIm7, V7, Imaj7)")
            romans = [self._as_degree(c, k) for c in chords]
            steps = self._harmony_steps(romans, k, voicing if action == "steps" else "full")
            if action == "steps":
                return {"key": f"{k[0]} {mode}", "voicing": voicing, "steps": steps,
                        "note": "Pass steps to demo, fingering, run_exercise, or to improvise as changes."}
            lines = []
            for i, roman in enumerate(romans):
                entry: dict = {"chord": self._degree_symbol(roman, k), "degree": roman}
                if roman in harmony_model.FUNCTIONS:
                    entry["role"] = harmony_model.FUNCTIONS[roman]
                if i + 1 < len(romans):
                    follows = dict(table["next"].get(roman, []))
                    share = follows.get(romans[i + 1])
                    rank = sorted(follows.values(), reverse=True).index(share) + 1 if share else None
                    move, shared = self._move_words(steps[i], steps[i + 1])
                    entry["then"] = {"to": self._degree_symbol(romans[i + 1], k), "move": move, "shared_notes": shared,
                                     "how_usual": (f"the {'most common' if rank == 1 else 'number ' + str(rank)} continuation ({share} % of cases)" if share else
                                                   "rare or unheard of in the repertoire counted: an unusual step, which may be exactly the point")}
                lines.append(entry)
            return {"key": f"{k[0]} {mode}", "progression": lines, "source": source}

        if action == "tuning":
            edo = t.edo
            comma = t.steps_for(9 / 8) - t.steps_for(10 / 9)
            fifth, third = t.steps_for(3 / 2), t.steps_for(5 / 4)
            facts = []
            if comma:
                facts.append(f"This tuning tells the large whole tone from the small one ({comma} step apart, the comma). With the home note fixed, the "
                             "minor chord on the second degree sits a comma below its plain name, and its root reaches the fifth degree by a fourth "
                             "that is a comma wide. Every two-five-one and every turnaround (one, six, two, five) has this place; in 12 or 31 notes "
                             "per octave it does not exist.")
                facts.append("A turnaround played with every chord pure and every common note held comes home a comma low each round (library "
                             "action comma, name pump). Players either hide the step (in the bass, in a rest) or let the piece drift.")
            else:
                facts.append("Four fifths make the major third here, so two-five-one and the turnarounds close without any adjustment, as on a piano.")
            if t.has("harmonic7"):
                seventh = t.steps_for(7 / 4)
                facts.append(f"The harmonic seventh ({seventh} steps) gives dominant chords that rest instead of pulling: right for a blues, where one, "
                             f"four and five are all seventh chords; before a resolution the ordinary seventh ({t.steps_for(16 / 9)} steps) pulls more.")
            if (3 * third) % edo:
                facts.append("Three major thirds do not make an octave, so an augmented chord is not the same from each of its notes, and keys a major "
                             "third apart (the Giant Steps cycle) do not return to the start.")
            if (4 * t.steps_for(6 / 5)) % edo:
                facts.append("Four minor thirds do not make an octave, so the diminished seventh chord is not symmetric: it has one odd gap, and "
                             "'any of its notes can be the root' holds only roughly.")
            if (2 * t.steps_for(7 / 5)) % edo:
                facts.append(f"The tritone is not half the octave: there is a small one ({t.steps_for(7 / 5)} steps) and a large one "
                             f"({edo - t.steps_for(7 / 5)}). The tritone substitute of a dominant shares its third and seventh exactly only if one of "
                             "the two chords takes the harmonic seventh and the other the ordinary one.")
            beyond = [q for q in t.qualities() if harmony_model_xen(q)]
            if beyond:
                facts.append("Chords a piano does not have can stand in for ordinary ones: " + ", ".join(beyond) + ". Try the subminor chord where a "
                             "minor chord sounds too bright, the neutral one between major and minor.")
            facts.append(f"The fifth is {fifth} steps ({fifth * 1200 / edo - 701.955:+.1f} cents against pure), the major third {third} steps "
                         f"({third * 1200 / edo - 386.314:+.1f} cents).")
            return {"tuning": f"{edo} equal steps per octave", "what_it_does_to_progressions": facts,
                    "small_steps": self._vl_step_names(),
                    "note": "These follow from the tuning's arithmetic and from this project's choices; let the player hear each before taking it as given.",
                    "harmony_of_this_tuning": "action neighbours (chord) lists the chords closest to a chord here, action path builds a "
                                              "progression from them, action xen gives what microtonal musicians wrote for this tuning."}

        raise TutorError("action must be one of: overview, next, common, analyse, steps, tuning, neighbours, path, xen")

    # --- harmony from the tuning itself: nearest chords, progressions built from them, the wiki's progressions ---

    def _vl_step_names(self) -> dict:
        """The tuning's small distances by name: `1 step` -> `a comma (23 cents)`."""
        t = self.keyboard.tuning
        return {f"{n} step{'' if n == 1 else 's'}": f"{name} ({t.cents_of(n):.0f} cents)" for n, name in sorted(voice_leading.step_names(t).items())}

    def _vl_chord(self, text: str | None, what: str = "chord") -> tuple[int, str, str]:
        """ "C major", "vE minor", "17 neutral", "Dm7" -> (root as steps above C, quality, root name)."""
        t = self.keyboard.tuning
        parts = (text or "").strip().split(None, 1)
        if not parts:
            raise TutorError(f"this action needs {what}: a root and a quality (C major, vE minor, Bb harmonic7) or a symbol (Dm7)")
        symbol = lib.chord_from_symbol(parts[0]) if len(parts) == 1 else None
        if symbol:
            root, quality = symbol[0], symbol[1]
        else:
            root, quality = parts[0], t.quality_key(parts[1] if len(parts) > 1 else "major")
        pitch = t.parse(root)[0]
        if not t.has(quality):
            raise TutorError(f"this tuning has no {quality} chord of its own. Available: {', '.join(t.qualities())}.")
        return pitch % t.edo, quality, t.pitch_class_name(root) if t.letter_of(root) else t.pitch_class_name(t.name(pitch))

    def _vl_aim(self) -> int:
        kb = self.keyboard
        return kb.centre().pitch - kb.tuning.edo // 2

    def _vl_place(self, pc: int, quality: str, root_name: str) -> Chord:
        """A chord in root position in the octave where all of it has keys, nearest below
        the middle of the keyboard (as the jazz changes are placed)."""
        kb = self.keyboard
        t = kb.tuning
        low, high = kb.range()
        fitting = [c for c in (t.chord(octave * t.edo + pc, quality, 0, root_name) for octave in range(low.pitch // t.edo, high.pitch // t.edo + 1))
                   if all(p in kb._by_pitch for p in c.pitches)]
        if not fitting:
            raise TutorError(f"this keyboard has no place where all notes of {root_name} {quality} have keys")
        return min(fitting, key=lambda c: abs(c.pitches[0] - self._vl_aim()))

    def _vl_fit(self, pitches: list[int], stay: bool = False) -> list[int] | None:
        """These notes moved by whole octaves to where all of them have keys: as they are if
        possible (`stay`), else nearest below the middle of the keyboard."""
        kb = self.keyboard
        edo = kb.tuning.edo
        ways = [[p + k * edo for p in pitches] for k in range(-8, 9)]
        ways = [w for w in ways if all(p in kb._by_pitch for p in w)]
        if not ways:
            return None
        return min(ways, key=lambda w: abs(w[0] - pitches[0]) if stay else abs(w[0] - self._vl_aim()))

    def _vl_letters(self, pc: int, quality: str, root_name: str) -> dict[int, str]:
        """The letter each note of a chord is written on (a third above C is some E), as
        `Tuning.chord` spells it: note as steps above C -> letter."""
        t = self.keyboard.tuning
        start = "CDEFGAB".index(t.letter_of(root_name))
        degrees = (1,) + tuple(d for _, d in CHORDS[quality]["tones"])
        return {(pc + steps) % t.edo: "CDEFGAB"[(start + d - 1) % 7] for steps, d in zip((0,) + t.tone_steps(quality), degrees)}

    def _vl_root_name(self, pc: int, quality: str, held: dict[int, str]) -> str:
        """The spelling of a root under which the notes kept from the chord before keep
        their names (C vE G to vA C vE, not to a chord spelled with other letters)."""
        t = self.keyboard.tuning
        best, best_score = None, None
        for spelled in t.spellings(4 * t.edo + pc)[:6]:
            name = t.pitch_class_name(spelled)
            letters = self._vl_letters(pc, quality, name)
            names = {note: t.pitch_class_name(t.name_with_letter(4 * t.edo + note, letter)) for note, letter in letters.items()}
            kept = sum(1 for note, n in names.items() if held.get(note) == n)
            score = (kept, -sum(len(n) for n in names.values()))     # then the plainest spelling of the whole chord
            if best_score is None or score > best_score:
                best, best_score = name, score
        return best

    def _vl_step(self, pitches: list[int], pc: int, quality: str, root_name: str) -> tuple[dict, dict[int, str]]:
        """A chord step for demo, fingering, run_exercise and improvise, in the shape the jazz
        changes use; and the name of each of its notes."""
        t = self.keyboard.tuning
        letters = self._vl_letters(pc, quality, root_name)
        names = {p: t.name_with_letter(p, letters[p % t.edo]) for p in pitches}
        root = min(p for p in pitches if p % t.edo == pc)
        step = {"notes": [t.label(p, names[p]) for p in sorted(pitches)], "label": f"{t.pitch_class_name(names[root])} {quality}",
                "root": t.label(root, names[root]), "beats": 4}
        return step, {p % t.edo: t.pitch_class_name(n) for p, n in names.items()}

    def _vl_follow(self, n, pitches: list[int], held: dict[int, str], root_name: str, to_name: str | None = None) -> tuple[dict, list[int], str, dict[int, str]]:
        """One move as a chord step with what happens in it. The voicing follows the voices,
        so notes that stay are the same keys; if that leaves the keyboard, the chord moves by
        octaves or is set in root position. Returns the step, its pitches, root name, note names."""
        kb = self.keyboard
        t = kb.tuning
        edo = t.edo
        name = to_name or (root_name if n.root_steps == 0 else self._vl_root_name(n.root, n.quality, held))
        carried = voice_leading.voiced(pitches, n.moves, edo)
        placed = self._vl_fit(carried, stay=True) if max(carried) - min(carried) < 2 * edo else None
        if placed is None:
            placed = list(self._vl_place(n.root, n.quality, name).pitches)
        step, names = self._vl_step(placed, n.root, n.quality, name)
        moves = []
        for mv in n.moves:
            if not mv.steps:
                continue
            origin = next(p for p in sorted(pitches) if p % edo == mv.source)
            target = min((p for p in placed if p % edo == mv.target), key=lambda p: abs(p - origin - mv.steps))
            moves.append(f"{t.label(origin, t.name_with_letter(origin, t.letter_of(held[mv.source])))} to "
                         f"{t.label(target, t.name_with_letter(target, t.letter_of(names[mv.target])))}: {voice_leading.step_words(t, mv.steps)}")
        entry = {**step, "kind": n.kind, "stays": n.stays, "moves": moves, "total_cents": round(n.cents)}
        if n.also:
            entry["same_notes_as"] = [f"{t.pitch_class_name(t.name(4 * edo + r))} {q}" for r, q in n.also]
        if CHORDS[n.quality].get("xen"):
            entry["not_on_a_piano"] = CHORDS[n.quality]["sounds"]
        return entry, placed, name, names

    def _vl_limits(self, max_cents: float | None, roots: str, sizes: str) -> float:
        if roots not in voice_leading.ROOTS:
            raise TutorError(f"roots must be one of: {', '.join(voice_leading.ROOTS)}")
        if sizes not in voice_leading.SIZES:
            raise TutorError(f"sizes must be one of: {', '.join(voice_leading.SIZES)}")
        reach = voice_leading.DEFAULT_MAX_CENTS if max_cents is None else float(max_cents)
        if not 10 <= reach <= 1200:
            raise TutorError("max_cents (how far all voices together may move in one step) must be 10 to 1200")
        return reach

    def _harmony_neighbours(self, chord: str | None, to: str | None, limit: int, max_cents: float | None, roots: str, sizes: str) -> dict:
        """The chords closest to a chord in this tuning, or one given move described."""
        t = self.keyboard.tuning
        reach = self._vl_limits(max_cents, roots, sizes)
        pc, quality, root_name = self._vl_chord(chord)
        home = self._vl_place(pc, quality, root_name)
        here, held = self._vl_step(list(home.pitches), pc, quality, root_name)
        out: dict = {"from": here, "tuning": f"{t.edo} equal steps per octave"}
        if to:
            to_pc, to_quality, to_name = self._vl_chord(to, "to")
            out["move"] = self._vl_follow(voice_leading.move(t, pc, quality, to_pc, to_quality), list(home.pitches), held, root_name, to_name)[0]
        else:
            found = voice_leading.neighbours(t, pc, quality, limit=max(1, min(int(limit), 16)), max_cents=reach, roots=roots, sizes=sizes)
            out["neighbours"] = [self._vl_follow(n, list(home.pitches), held, root_name)[0] for n in found]
            out["ranking"] = (f"Within {reach:.0f} cents of total movement. The kinds of move take turns (another quality on the same root; "
                              "one voice moves; the whole chord slides; the rest), nearest first within each kind; diminished and augmented "
                              "chords come later. roots same/other, sizes triads/sevenths/any, max_cents and limit change the selection.")
            if not found:
                out["note"] = "No chord within this distance; raise max_cents."
        out["small_steps"] = self._vl_step_names()
        out["how"] = ("Each entry is a chord step: pass [from, entry] to demo to hear the move with the held notes on the same keys, or to "
                      "fingering and run_exercise. Found by measuring how far the voices move, not from any repertoire: let the player "
                      "hear a move and say what it does before you name it.")
        return out

    def _harmony_path(self, chord: str | None, to: str | None, length: int, max_cents: float | None, via: str | None, seed: int,
                      roots: str, sizes: str) -> dict:
        """A short progression in which every step is a small move of the voices."""
        t = self.keyboard.tuning
        reach = self._vl_limits(max_cents, roots, sizes)
        pc, quality, root_name = self._vl_chord(chord)
        end = self._vl_chord(to, "to") if to else None
        wanted = None
        if via:
            wanted = "xen" if via.strip().lower() in ("xen", "new", "beyond", "not on a piano") else t.quality_key(via)
        moves = voice_leading.path(t, pc, quality, length=int(length), end=(end[0], end[1]) if end else None, max_cents=reach,
                                   via=wanted, seed=int(seed), roots=roots, sizes=sizes)
        home = self._vl_place(pc, quality, root_name)
        here, held = self._vl_step(list(home.pitches), pc, quality, root_name)
        steps, pitches, name = [here], list(home.pitches), root_name
        for i, n in enumerate(moves):
            last = i == len(moves) - 1
            entry, pitches, name, held = self._vl_follow(n, pitches, held, name, (end[2] if end else root_name) if last else None)
            steps.append(entry)
        return {"progression": " - ".join(s["label"] for s in steps), "steps": steps, "tuning": f"{t.edo} equal steps per octave",
                "limits": f"{len(steps)} chords, no chord twice, at most {reach:.0f} cents of total movement per step"
                          + (f", passing {'a chord a piano does not have' if wanted == 'xen' else 'a ' + wanted + ' chord'}" if wanted else "")
                          + f"; seed {int(seed)} (another seed gives another way)",
                "small_steps": self._vl_step_names(),
                "note": "Pass steps to demo, fingering, run_exercise, or to improvise as changes. The voicing follows the voices, so the "
                        "last chord may come back in another inversion than the first. Built from distances alone: whether it is music "
                        "is for the player's ear."}

    def _harmony_xen(self, name: str | None, key: str) -> dict:
        """Progressions and chord vocabularies from the Xenharmonic Wiki for the current
        tuning: the list, or one entry as chord steps on the home note `key`."""
        kb = self.keyboard
        t = kb.tuning
        edo = t.edo
        source = ("Collected from the Xenharmonic Wiki (en.xen.wiki, CC BY-NC-SA): the chords are the authors', the summaries the "
                  "tutor's. tuning_notes with the page and section named gives the original text.")
        if not name:
            listed = []
            for e in xen_model.for_tuning(edo):
                item = {"name": e["id"], "title": e["name"], "kind": e["kind"]}
                if e["chords"]:
                    item["chords"] = " - ".join(c.split("|")[0].strip() for c in e["chords"])
                if edo not in e["tunings"]:
                    item["written_for"] = f"{' and '.join(str(n) for n in e['tunings'])} notes per octave; carried over by its pure intervals"
                listed.append(item)
            return {"tuning": f"{edo} equal steps per octave", "entries": listed, "source": source,
                    "not_found_in_the_wiki_copy": list(xen_model.MISSING),
                    "note": "action xen with name gives one entry: what it shows, its source, and its chords as steps on the home note "
                            "`key`. A vocabulary is a set of chords to compare, not a progression."
                            if listed else "The wiki copy has nothing written for this tuning; action neighbours and action path work in every tuning."}
        try:
            e = xen_model.entry(name)
            chords = xen_model.resolve(e, edo)
        except xen_model.ProgressionError as err:
            raise TutorError(f"{err}. action xen without name lists the entries for this tuning.") from None
        tonic_name = self._harmony_key(key)[0]
        tonic = t.parse(tonic_name)[0] % edo
        steps, missing = [], []
        for label, root, tones in chords:
            pc = (tonic + root) % edo
            placed = self._vl_fit([4 * edo + pc] + [4 * edo + pc + s for s in tones])
            if placed is None:
                missing.append(label)
                continue
            quality = next((q for q in t.qualities() if t.tone_steps(q) == tones), None)
            if quality:
                root_name = tonic_name if root == 0 else self._vl_root_name(pc, quality, {})
                step = self._vl_step(placed, pc, quality, root_name)[0]
                step["tutor_calls_it"] = step["label"]
            else:
                step = {"notes": [t.label(p) for p in placed], "root": t.label(placed[0]), "beats": 4}
            step["label"] = label
            steps.append(step)
        out = {"name": e["id"], "title": e["name"], "kind": e["kind"], "shows": e["shows"],
               "source": f"Xenharmonic Wiki (CC BY-NC-SA), page '{e['source'][0]}', section '{e['source'][1]}': the chords are the "
                         "author's, the summary is the tutor's; tuning_notes gives the original text"}
        if edo not in e["tunings"]:
            out["written_for"] = (f"{' and '.join(str(n) for n in e['tunings'])} notes per octave. Carried over here by the pure intervals "
                                  "its chords stand for; that step is the tutor's, not the author's.")
        if steps:
            out["home_note"] = t.label(tonic, tonic_name)
            out["steps"] = steps
            out["note"] = ("Pass steps to demo, fingering or run_exercise" + ("; play them in order." if e["kind"] == "progression" else
                           "; these are chords to compare, in no fixed order." if e["kind"] == "vocabulary" else
                           "; the chords only illustrate the idea."))
        if missing:
            out["no_keys_for"] = missing
        return out

    # --- tuning notes: the community's wiki ---

    def tuning_notes(self, query: str | None = None, page: str | None = None, section: str | None = None, part: int = 1, limit: int = 6) -> dict:
        """Look things up in the local copy of the Xenharmonic Wiki. query: search; page:
        its sections; page + section: the text."""
        if not self.wiki.available:
            raise TutorError("the tuning notes are not installed on this machine (python -m tutor.wiki_build builds them from the wiki backup)")
        source = ("Xenharmonic Wiki (en.xen.wiki), a community wiki; its words, not the tutor's. There 'Nedo' means N equal steps per "
                  "octave and an 'edostep' is one step.")
        if page and section:
            found = self.wiki.section(page, section, part)
            if not found:
                raise TutorError(f"no section '{section}' on the page '{page}'; ask with page alone for its sections")
            found["source"] = source
            if found["part"] < found["parts"]:
                found["more"] = f"part {found['part'] + 1} of {found['parts']} continues this section"
            return found
        if page and not query:
            found = self.wiki.page(page)
            if not found:
                near = [t for t in self.wiki.titles() if page.strip().lower() in t.lower()][:12]
                raise TutorError(f"no page '{page}' in the tuning notes." + (f" Similar: {', '.join(near)}." if near else " Search with query instead."))
            return {"page": found["title"], "revision": found["revision"], "url": found["url"], "source": source,
                    "sections": [{"section": s["heading"], "characters": len(s["text"])} for s in found["sections"]],
                    "note": "tuning_notes with page and section gives the text."}
        if query:
            hits = self.wiki.search(query, max(1, min(limit, 12)), page)
            return {"query": query, "hits": hits, "source": source,
                    "note": "tuning_notes with page and section gives the full text of a hit." if hits else
                            "Nothing found; try other words, or a page name such as 53edo."}
        t = self.keyboard.tuning
        titles = self.wiki.titles()
        own = [x for x in titles if x.lower().startswith(f"{t.edo}edo") or f" {t.edo}edo" in x.lower()]
        return {"about": source, "pages": len(titles), "for_the_current_tuning": own,
                "also": [x for x in titles if not x[0].isdigit() and "edo" not in x.lower()][:60],
                "how": "query searches all pages; page lists a page's sections; page with section gives the text."}

    # --- library: pieces, ragas, patterns ---

    def _fit_shift(self, pitches: list[int], have: set[int] | None = None, edo: int | None = None) -> tuple[int, int]:
        """By how many steps to move these pitches so that most of them have a key, and how many
        then have one. Any interval counts, not only octaves: on this keyboard a transposed
        piece is the same shapes on other keys. Ties go to no move, then to whole octaves, then
        to the smallest move."""
        kb = self.keyboard
        have = set(kb._by_pitch) if have is None else have
        edo = kb.tuning.edo if edo is None else edo
        counts = collections.Counter(pitches)
        if not counts or not have:
            return 0, 0
        low, high = min(have) - max(counts), max(have) - min(counts)

        def covered(shift: int) -> int:
            return sum(c for p, c in counts.items() if p + shift in have)

        best = max(range(low, high + 1), key=lambda s: (covered(s), s == 0, s % edo == 0, -abs(s)))
        return best, covered(best)

    def _shift_words(self, shift: int, edo: int | None = None) -> str:
        edo = self.keyboard.tuning.edo if edo is None else edo
        way = "up" if shift > 0 else "down"
        if shift % edo == 0:
            k = abs(shift) // edo
            return f"{k} octave{'s' if k != 1 else ''} {way}"
        return f"{abs(shift)} steps {way} ({abs(shift) * 1200 / edo:.0f} cents: every note by the same interval, so shapes and fingering stay)"

    def _layout_pitches(self) -> dict[str, tuple[int, set[int]]]:
        """The other layouts this keyboard can be switched to: name -> (notes per octave, the
        pitches its connected modules would have). Read from the layout files."""
        if self._layouts is None:
            import re
            found: dict[str, tuple[int, set[int]]] = {}
            boards = {k.board for k in self.keyboard.keys.values()}
            folder = self.layouts_dir
            for path in sorted(folder.glob("*.otn")) if folder and folder.is_dir() else []:
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                    edo = int(re.search(r"Edo=(\d+)", text).group(1))
                    offset = int(re.search(r"PitchOffset=(-?\d+)", text).group(1))
                    pitches: set[int] = set()
                    for m in re.finditer(r"\[Board(\d+)\](.*?)(?=\[Board|\Z)", text, re.S):
                        if int(m.group(1)) not in boards:
                            continue
                        notes = dict(re.findall(r"Key_(\d+)=(-?\d+)", m.group(2)))
                        chans = dict(re.findall(r"Chan_(\d+)=(-?\d+)", m.group(2)))
                        pitches |= {(int(chans[k]) - 1) * edo + int(v) + offset for k, v in notes.items() if int(chans.get(k, 0)) >= 1}
                    if pitches:
                        found[path.stem] = (edo, pitches)
                except (AttributeError, ValueError, OSError):
                    continue
            self._layouts = found
        return self._layouts

    def _piece_fit(self, piece: dict) -> dict:
        """How much of a composition can be played on the keyboard as it is now, and on the other
        tunings it can be switched to. The whole piece may be transposed by any interval."""
        kb = self.keyboard
        t = kb.tuning
        bars = piece["score"]
        own = tuning_for(piece["tuning"])

        by_part: dict[str, list[tuple[int, int]]] = {}
        near: dict[tuple[int, int], tuple[int, float]] = {}        # (notes per octave, step of the piece) -> nearest step there, cents off

        def steps_of(part: str) -> list[tuple[int, int]]:      # (bar, step in the piece's tuning)
            if part not in by_part:
                by_part[part] = [(bar["n"], s) for bar in bars for staff, events in bar["staves"].items() if part in (staff, "both")
                                 for _, _, steps in events for s in steps]
            return by_part[part]

        def nearest(target, s: int) -> tuple[int, float]:
            # The nearest step of another equal tuning, by arithmetic: for equal tunings this is what
            # `Tuning.retuned_from` (xenharmlib's retune) gives, and a hundred times faster, which matters
            # for an estimate over every layout (a test holds the two against each other).
            if target.edo == own.edo:
                return s, 0.0
            if (target.edo, s) not in near:
                step = round(s * target.edo / own.edo)
                near[(target.edo, s)] = (step, round(step * 1200.0 / target.edo - s * 1200.0 / own.edo, 1))
            return near[(target.edo, s)]

        def fit(target, have: set[int], part: str) -> tuple[int, int, int, list[int]]:
            notes = steps_of(part)
            pitches = [nearest(target, s)[0] for _, s in notes]
            shift, covered = self._fit_shift(pitches, have, target.edo)
            outside = sorted({bar for (bar, _), p in zip(notes, pitches) if p + shift not in have})
            return shift, covered, len(pitches), outside

        def words(target, have: set[int]) -> dict:
            out = {}
            for part, name in (("both", "both hands"), ("upper", "right hand alone"), ("lower", "left hand alone")):
                shift, covered, total, outside = fit(target, have, part)
                if not total:
                    continue
                entry = {"notes_with_a_key": f"{covered} of {total} ({100 * covered // total}%)"}
                if shift:
                    entry["transposed"] = self._shift_words(shift, target.edo)
                if outside:
                    entry["bars_with_notes_outside"] = (outside if len(outside) <= 12 else
                                                        f"{len(outside)} of {len(bars)} bars, the first: {', '.join(map(str, outside[:8]))}")
                out[name] = entry
            return out

        now = words(t, set(kb._by_pitch))
        result = {"now": {"tuning": f"{t.edo} notes per octave", **now}}
        if piece["tuning"] != t.edo:
            worst = max((abs(nearest(t, s)[1]) for _, s in steps_of("both")), default=0.0)
            result["now"]["approximation"] = f"the piece is written for {piece['tuning']} notes per octave; here on the nearest notes, up to {worst:.0f} cents off"
        full_now = fit(t, set(kb._by_pitch), "both")
        others = []
        for name, (edo, have) in self._layout_pitches().items():
            if edo == t.edo and have == set(kb._by_pitch):
                continue
            target = tuning_for(edo)
            worst = max((abs(nearest(target, s)[1]) for _, s in steps_of("both")), default=0.0)
            if worst > 20:              # a tuning that is further off than that does not render the piece
                continue
            shift, covered, total, _ = fit(target, have, "both")
            others.append((edo != own.edo, -covered, worst, name, edo, shift, covered, total))
        result["other_tunings"] = [
            {"layout": name, "tuning": f"{edo} notes per octave", "both hands": f"{covered} of {total} ({100 * covered // total}%)",
             **({"transposed": self._shift_words(shift, edo)} if shift else {}),
             "intervals": "exact (the piece's own tuning)" if not approx else f"approximated: nearest notes, up to {worst:.0f} cents off"}
            for approx, _, worst, name, edo, shift, covered, total in sorted(others)[:4]]
        own_layouts = [o for o in others if not o[0]]
        if full_now[1] == full_now[2] and piece["tuning"] == t.edo:
            result["say"] = "Everything in this piece has a key on the keyboard as it is."
        else:
            parts = []
            if full_now[1] < full_now[2]:
                parts.append(f"With the keyboard as it is, {full_now[2] - full_now[1]} of {full_now[2]} notes have no key even with the best "
                             f"transposition: tell the player before starting which bars cannot be played complete, or take one hand at a time "
                             f"(see right hand alone, left hand alone).")
            if piece["tuning"] != t.edo and own_layouts:
                best = min(own_layouts)
                parts.append(f"The piece is written for {piece['tuning']} notes per octave: switching the tuning to layout {best[3]} gives its "
                             f"intervals exactly ({100 * best[6] // best[7]}% of the notes have a key there, transposed as fits best).")
            result["say"] = " ".join(parts)
        return result

    def _fit_octaves(self, pitches: list[int]) -> int:
        """How many octaves to move these pitches so that most of them have a key."""
        kb = self.keyboard
        edo = kb.tuning.edo
        best = max(range(-4, 5), key=lambda k: (sum(1 for p in pitches if (p + k * edo) in kb._by_pitch), -abs(k)))
        return best

    def _as_steps(self, pitches: list[int], beats: list[float] | None = None) -> tuple[list[dict], list[str]]:
        """Pitches as steps for demo / run_exercise / fingering, and those the keyboard lacks."""
        kb = self.keyboard
        t = kb.tuning
        steps, missing = [], []
        for i, p in enumerate(pitches):
            if p not in kb._by_pitch:
                missing.append(t.label(p))
            step: dict = {"note": t.label(p)}
            if beats and beats[i] != 1:
                step["beats"] = beats[i]
            steps.append(step)
        return steps, list(dict.fromkeys(missing))

    def _piece_pitches(self, piece: dict, theory: bool) -> tuple[list[int | None], float]:
        """The piece's pitches in the current tuning, and the largest deviation in cents if
        it was written for another tuning and is played here on the nearest steps."""
        t = self.keyboard.tuning
        written = tuning_for(piece["tuning"]) if piece.get("tuning") and piece["tuning"] != t.edo else None
        out: list[int | None] = []
        worst = 0.0
        for i, (pitch, _) in enumerate(piece["notes"]):
            if pitch is None:
                out.append(None)
            elif isinstance(pitch, str):
                out.append(t.parse(pitch)[0])
            else:
                pitch = piece["theory"].get(str(i), pitch) if theory else pitch
                if written is not None:
                    pitch, off = t.retuned_from(written, pitch)
                    worst = max(worst, abs(off))
                out.append(pitch)
        return out, worst

    # --- jazz changes ---

    def _key_root(self, root_name: str, family: str, key: tuple[str, bool] | None, plain: bool) -> tuple[int, str]:
        """The pitch class of a chord root in a key, and its name. In tunings that tell 9/8
        from 10/9 (53, 41, 22), roots follow the key's pure scale, the tonic staying where it
        is: the third, sixth and seventh degree a comma below the chain of fifths, the minor
        chord on the second degree too (in major and in minor), the flat degrees a comma
        above. So the second-degree chord keeps the notes of the key and its root moves to
        the fifth degree by a fourth that is a comma wide: the price of a fixed tonic."""
        t = self.keyboard.tuning
        edo = t.edo
        pc = t.parse(root_name)[0] % edo
        comma = t.steps_for(9 / 8) - t.steps_for(10 / 9)
        if plain or not comma or key is None:
            return pc, root_name
        fifth = t.steps_for(3 / 2)
        tonic = t.parse(key[0])[0] % edo
        reference = (tonic - 3 * fifth) % edo if key[1] else tonic        # the relative major of a minor key
        k = next((k for k in range(-7, 10) if (k * fifth) % edo == (pc - reference) % edo), None)
        if k is None:
            return pc, root_name
        shift = 1 if key[1] else 0      # in commas
        if k >= 3 or (k == 2 and family in ("minor", "diminished")):
            shift -= 1
        elif k <= -3:
            shift += 1
        if key[1] and k == 5 and family in ("minor", "diminished"):
            shift -= 1                  # the second degree of the minor key
        name = ("^" * (shift * comma) if shift > 0 else "v" * (-shift * comma)) + root_name
        return (pc + shift * comma) % edo, name

    @staticmethod
    def _piece_key(piece: dict) -> tuple[str, bool] | None:
        """The key of a tune as its source gives it. Without one the chords keep their plain
        note names: guessing a key would move roots by a comma in the wrong places."""
        return lib.parse_key(piece.get("key", ""))

    def _changes_steps(self, piece: dict, bars: list[list[str]], voicing: str, sevenths: str, plain_roots: bool) -> tuple[list[dict], list[str]]:
        kb = self.keyboard
        t = kb.tuning
        low, high = kb.range()
        key = self._piece_key(piece)
        beats_per_bar = float((piece.get("meter") or "4/4").split("/")[0] or 4)
        blues = "blues" in piece["title"].lower() or piece.get("bars") == 12
        harmonic = sevenths == "harmonic" or (sevenths == "auto" and blues)
        steps: list[dict] = []
        left_out: list[str] = []
        for bar in bars:
            for symbol in bar:
                parsed = lib.chord_from_symbol(symbol)
                if not parsed:
                    continue
                root_name, quality, family, extra = parsed
                if quality == "dominant7" and harmonic and t.has("harmonic7"):
                    quality = "harmonic7"
                pc, spelled = self._key_root(root_name, family, key, plain_roots)
                # the octave in which the whole chord has keys, nearest below the middle of the keyboard
                aim = kb.centre().pitch - t.edo // 2
                fitting = []
                for octave in range(low.pitch // t.edo, high.pitch // t.edo + 1):
                    candidate = t.chord(octave * t.edo + pc, quality, 0, spelled)
                    if all(p in kb._by_pitch for p in candidate.pitches):
                        fitting.append(candidate)
                chord = min(fitting, key=lambda c: abs(c.pitches[0] - aim)) if fitting else \
                    t.chord((kb.centre().pitch // t.edo) * t.edo + pc, quality, 0, spelled)
                tones = list(zip(chord.pitches, chord.names))
                if quality in ("dominant7", "dominant7sus4"):
                    # the seventh of a dominant is the fourth of its key (16/9), not the wider 9/5
                    seventh = tones[0][0] + t.steps_for(16 / 9)
                    letter = t.letter_of(tones[-1][1])
                    tones[-1] = (seventh, t.name_with_letter(seventh, letter) if letter else t.name(seventh))
                if voicing == "root":
                    chosen = tones[:1]
                elif voicing == "shell" and len(tones) >= 4:
                    chosen = [tones[0], tones[1], tones[-1]]
                elif voicing == "guide":
                    chosen = [tones[1], tones[-1]]
                else:
                    chosen = tones
                step = {"notes": [f"{n} ({t.number(p)})" for p, n in chosen], "label": symbol,
                        "root": f"{tones[0][1]} ({t.number(tones[0][0])})", "beats": round(beats_per_bar / len(bar), 3)}
                if voicing == "guide":
                    step.pop("root")
                if len(chosen) != len(tones):
                    step["tones"] = [f"{n} ({t.number(p)})" for p, n in tones]     # the whole chord, for improvise
                steps.append(step)
                if extra and extra not in left_out:
                    left_out.append(f"{symbol}: {extra}")
        return steps, left_out

    def _fifths_facts(self) -> dict:
        """What the chain of fifths does in this tuning."""
        t = self.keyboard.tuning
        edo = t.edo
        fifth = t.steps_for(3 / 2)
        step_cents = 1200.0 / edo
        closes = edo // math.gcd(edo, fifth)
        twelve = 12 * fifth - 7 * edo
        third_by_fifths = 4 * fifth - 2 * edo
        pure_third = t.steps_for(5 / 4)
        eight_down = 5 * edo - 8 * fifth
        facts = {
            "fifth": f"{fifth} steps, {fifth * step_cents - 701.955:+.1f} cents against the pure fifth",
            "closes_after": (f"{closes} fifths: every note of the tuning lies on one chain" if closes == edo else
                             f"{closes} fifths: the tuning has {edo // closes} separate circles of {closes} notes"),
            "twelve_fifths": ("land exactly on the starting note (seven octaves up), as on a piano" if twelve == 0 else
                              f"land {abs(twelve)} step{'s' if abs(twelve) != 1 else ''} ({abs(twelve) * step_cents:.0f} cents) "
                              f"{'above' if twelve > 0 else 'below'} the starting note: the circle does not close after twelve, it is a spiral"),
            "four_fifths_and_the_major_third": (
                "four fifths up give the pure major third: the same key" if third_by_fifths == pure_third else
                f"four fifths up land {abs(third_by_fifths - pure_third)} step{'s' if abs(third_by_fifths - pure_third) != 1 else ''} "
                f"{'above' if third_by_fifths > pure_third else 'below'} the pure major third (the syntonic comma): two different keys"),
        }
        if eight_down == pure_third and third_by_fifths != pure_third:
            facts["eight_fifths_down"] = "give the pure major third: the third of a chord lies eight fifths down the spiral, not four up"
        return facts

    def _comma_lesson(self, kind: str, root: str, rounds: int) -> dict:
        """Small listening experiments on the chain of fifths: where it comes out, against
        where the ear expects it."""
        kb = self.keyboard
        t = kb.tuning
        edo = t.edo
        fifth, third, fourth, minor_third = (t.steps_for(r) for r in (3 / 2, 5 / 4, 4 / 3, 6 / 5))
        kinds = {"twelve_fifths": "twelve fifths against the note you started on",
                 "minor_third": "three fifths down against the pure minor third",
                 "third": "four fifths up against the pure major third",
                 "schismatic": "eight fifths down against the pure major third",
                 "pump": "a chord progression that comes back a comma away from where it began",
                 "thirds_cycle": "three major thirds against the octave"}
        if kind not in kinds:
            return {"lessons": kinds, "note": "action comma with name = one of these (and root); each gives notes to demo and a pair to compare."}
        start, start_name = self._pitch(root)

        def near(pitch: int) -> int:
            while pitch - start > edo // 2:
                pitch -= edo
            while start - pitch > edo // 2:
                pitch += edo
            return pitch

        def walk(count: int, step: int) -> list[dict]:
            return [{"note": t.label(near(start + i * step)), "beats": 1} for i in range(count + 1)]

        def pair(a: int, b: int, label: str) -> dict:
            return {"notes": [t.label(a), t.label(b)], "label": label, "beats": 4}

        def gap(steps: int) -> str:
            return "the same key" if steps == 0 else f"{abs(steps)} step{'s' if abs(steps) != 1 else ''} ({abs(steps) * 1200 / edo:.0f} cents) {'higher' if steps > 0 else 'lower'}"

        out: dict = {"lesson": kinds[kind], "from": t.label(start)}
        if kind == "twelve_fifths":
            diff = 12 * fifth - 7 * edo
            out["walk"] = walk(12, fifth)
            out["compare"] = [{"note": t.label(start), "beats": 2}, {"note": t.label(start + diff), "beats": 2}, pair(start, start + diff, "start and the twelfth fifth together")]
            out["result"] = f"The twelfth fifth is {gap(diff)} than the start."
        elif kind == "third":
            diff = 4 * fifth - 2 * edo - third
            out["walk"] = walk(4, fifth)
            out["compare"] = [pair(start, start + third + diff, "with the note four fifths up"), pair(start, start + third, "with the pure major third")]
            out["result"] = f"The note four fifths up is {gap(diff)} than the pure major third." + (
                " That step is the syntonic comma." if diff else " This tuning makes them one: that is what 'meantone' means.")
        elif kind == "minor_third":
            diff = 2 * edo - 3 * fifth - minor_third
            nine = 9 * fifth - 5 * edo - minor_third
            out["walk"] = walk(3, -fifth)
            out["compare"] = [pair(start, start + minor_third + diff, "with the note three fifths down"), pair(start, start + minor_third, "with the pure minor third")]
            out["result"] = f"The note three fifths down is {gap(diff)} than the pure minor third." + (
                " Nine fifths up give the pure one." if nine == 0 and diff else "")
        elif kind == "schismatic":
            diff = 5 * edo - 8 * fifth - third
            out["walk"] = walk(8, -fifth)
            out["compare"] = [pair(start, start + third + diff, "with the note eight fifths down"), pair(start, start + third, "with the pure major third")]
            out["result"] = f"The note eight fifths down is {gap(diff)} than the pure major third." + (
                " So the pure third of every chord lies on the chain of fifths, eight links down." if diff == 0 else "")
        elif kind == "thirds_cycle":
            diff = 3 * third - edo
            out["walk"] = [{"note": t.label(start + i * third), "beats": 1} for i in range(4)]
            out["compare"] = [pair(start + edo, start + 3 * third, "the octave and the third major third together")]
            out["result"] = f"Three pure major thirds end {gap(diff)} than the octave."
        else:
            rounds = max(1, min(int(rounds) if rounds and rounds < 12 else 3, 6))
            drift = 2 * fourth - minor_third - fifth
            steps, pitch = [], start
            for _ in range(rounds):
                for move, quality in ((0, "major"), (-minor_third, "minor"), (-fifth, "minor"), (fourth, "major")):
                    pitch = near(pitch + move)
                    chord = t.chord(pitch, quality)
                    steps.append({"notes": [f"{n} ({t.number(p)})" for p, n in zip(chord.pitches, chord.names)], "label": chord.label,
                                  "root": f"{chord.names[0]} ({t.number(chord.pitches[0])})", "beats": 2})
                pitch = near(pitch + fourth)
            chord = t.chord(pitch, "major")
            steps.append({"notes": [f"{n} ({t.number(p)})" for p, n in zip(chord.pitches, chord.names)], "label": chord.label,
                          "root": f"{chord.names[0]} ({t.number(chord.pitches[0])})", "beats": 4})
            out["steps"] = steps
            out["compare"] = [pair(start, pitch, "the first root and the last")]
            out["result"] = (f"One, six, two, five, one with every chord pure and every common note held: after {rounds} rounds the home chord is "
                             f"{gap(drift * rounds)}." + (" In this tuning the progression closes." if drift == 0 else
                                                         " Pure tuning does not close this progression; players choose where to hide the step."))
        out["result"] = out["result"].replace("the same key than", "the same key as")
        missing = [n for step in out.get("walk", []) + out.get("steps", []) + out["compare"]
                   for n in (step.get("notes") or [step["note"]]) if t.parse(n)[0] not in kb._by_pitch]
        if missing:
            out["not_on_this_keyboard"] = list(dict.fromkeys(missing))
        out["note"] = "demo the walk (or the steps), then the compare steps slowly; let the player say what they hear before you explain."
        return out

    # --- progressions that run around the circle ---

    KEY_ORDERS = {
        "fourths": ["C", "F", "Bb", "Eb", "Ab", "Db", "Gb", "B", "E", "A", "D", "G"],
        "fifths": ["C", "G", "D", "A", "E", "B", "F#", "Db", "Ab", "Eb", "Bb", "F"],
        "whole_steps": ["C", "Bb", "Ab", "Gb", "E", "D", "Db", "B", "A", "G", "F", "Eb"],
        "half_steps": ["C", "B", "Bb", "A", "Ab", "G", "Gb", "F", "E", "Eb", "D", "Db"],
    }

    def _degrees(self, key: str, mode: str = "major") -> list[str]:
        """The seven note names of a key, without octaves."""
        t = self.keyboard.tuning
        return [t.pitch_class_name(n) for _, n in t.scale(t.parse(key)[0], mode, key)]

    def _keys_from(self, root: str, order: str, count: int) -> list[str]:
        if order not in self.KEY_ORDERS:
            raise TutorError(f"the order of keys (scale) must be one of: {', '.join(self.KEY_ORDERS)}")
        names = self.KEY_ORDERS[order]
        start = self.keyboard.tuning.pitch_class_name(self._pitch(root)[1]).lstrip("^v")
        same = {"C#": "Db", "D#": "Eb", "G#": "Ab", "A#": "Bb", "F#": "Gb" if "Gb" in names else "F#", "Gb": "F#" if "F#" in names else "Gb"}
        start = start if start in names else same.get(start, "C")
        at = names.index(start) if start in names else 0
        return [names[(at + i) % 12] for i in range(max(1, min(int(count), 12)))]

    def _cycle(self, kind: str, root: str, voicing: str, order: str, count: int, sevenths: str, plain_roots: bool) -> dict:
        """Chord progressions and scales that run around the circle of fifths."""
        kb = self.keyboard
        t = kb.tuning
        edo = t.edo
        kinds = {
            "scales": "the major scale up and down, key after key (keys in the order given by scale: fifths, fourths, whole_steps, half_steps)",
            "two_five_one": "two-five-one in key after key (order of keys as for scales; fourths is the usual one)",
            "diatonic": "all seven chords of one key by falling fifths: one, four, seven, three, six, two, five, one",
            "minor_diatonic": "the same in a minor key: four, seven, three, six, two, five, one (as in Autumn Leaves)",
            "dominants": "a chain of dominant sevenths falling by fifths into the key: three, six, two, five, one",
            "bridge": "the bridge of rhythm changes: four dominants, two bars each, falling by fifths back to the key",
            "major_thirds": "three keys a major third apart, each reached through its dominant (the Giant Steps cycle)",
            "spoke": "the notes that twelve fifths apart put next to each other: one spoke of the spiral",
            "rings": "whether the fifths reach every note of this tuning or stay in one of several rings",
        }
        if kind not in kinds:
            return {"cycles": kinds, "note": "action cycle with name = one of these, root = the key (or starting note), voicing, scale = the order of keys, count = how many keys."}
        if voicing == "arpeggio" or voicing not in ("full", "shell", "guide", "root"):
            voicing = "full"
        out: dict = {"cycle": kinds[kind]}
        fifth, third = t.steps_for(3 / 2), t.steps_for(5 / 4)
        comma = t.steps_for(9 / 8) - t.steps_for(10 / 9)

        def changes(key: str, minor: bool, bars: list[list[str]]) -> list[dict]:
            piece = {"title": "", "key": key + ("min" if minor else ""), "meter": "4/4", "bars": 0}
            return self._changes_steps(piece, bars, voicing, "plain" if sevenths == "auto" else sevenths, plain_roots)[0]

        if kind == "scales":
            order = "fifths" if order == "major" else order      # "major" is the parameter's default: no order given
            groups = []
            for key in self._keys_from(root, order, count if count != 12 else 4):
                tonic, name = self._pitch(key)
                ladder = [p for p, _ in t.scale(tonic, "major", name)] + [tonic + edo]
                if not all(p in kb._by_pitch for p in ladder):
                    shift = next((s for s in (edo, -edo) if all((p + s) in kb._by_pitch for p in ladder)), 0)
                    ladder = [p + shift for p in ladder]
                notes = ladder + ladder[-2::-1]
                groups.append({"key": f"{key} major", "steps": [{"note": t.label(p), "beats": 0.5} for p in notes[:-1]] + [{"note": t.label(notes[-1]), "beats": 1}]})
            out["order_of_keys"] = order.replace("_", " ")
            out["groups"] = groups
            out["note"] = ("One key per group, up and back. The fingering is the same in every key here: let the player find that. "
                           "Pass a group to demo (slowly, outline=true) and run_exercise, or to fingering.")
            return out
        if kind == "two_five_one":
            order = "fourths" if order == "major" else order
            groups = []
            for key in self._keys_from(root, order, count if count != 12 else 4):
                d = self._degrees(key)
                groups.append({"key": f"{key} major", "steps": changes(key, False, [[d[1] + "m7"], [d[4] + "7"], [d[0] + "maj7"], [d[0] + "maj7"]])})
            out["order_of_keys"] = order.replace("_", " ")
            out["groups"] = groups
            out["note"] = "One key per group: second degree, fifth degree, home (two bars). The three shapes and the two moves are the same in every key."
        elif kind in ("diatonic", "minor_diatonic"):
            key = self._keys_from(root, "fourths", 1)[0]
            if kind == "diatonic":
                d = self._degrees(key)
                bars = [[d[0] + "maj7"], [d[3] + "maj7"], [d[6] + "m7b5"], [d[2] + "m7"], [d[5] + "m7"], [d[1] + "m7"], [d[4] + "7"], [d[0] + "maj7"]]
            else:
                d = self._degrees(key, "minor")
                bars = [[d[3] + "m7"], [d[6] + "7"], [d[2] + "maj7"], [d[5] + "maj7"], [d[1] + "m7b5"], [d[4] + "7"], [d[0] + "m6"], [d[0] + "m6"]]
            out["key"] = f"{key} {'minor' if kind == 'minor_diatonic' else 'major'}"
            out["steps"] = changes(key, kind == "minor_diatonic", bars)
            out["note"] = "Every root falls a fifth (or rises a fourth) to the next, all inside one key. One bar per chord."
        elif kind in ("dominants", "bridge"):
            key = self._keys_from(root, "fourths", 1)[0]
            d = self._degrees(key)
            chain = [d[2] + "7", d[5] + "7", d[1] + "7", d[4] + "7"]
            bars = [[c] for c in chain for _ in range(2)] if kind == "bridge" else [[c] for c in chain] + [[d[0] + "maj7"]]
            out["key"] = f"{key} major"
            out["steps"] = changes(key, False, bars)
            out["note"] = "Each chord is the dominant of the next: the third of one falls a small step to become the seventh of the next."
        elif kind == "major_thirds":
            start, _ = self._pitch(root)
            steps, tonic = [], start
            for i in range(4):
                home = t.chord(tonic, "major7")
                steps.append({"notes": [f"{n} ({t.number(p)})" for p, n in zip(home.pitches, home.names)], "label": home.label,
                              "root": f"{home.names[0]} ({t.number(home.pitches[0])})", "beats": 4})
                if i == 3:
                    break
                tonic -= third
                if tonic < kb.range()[0].pitch + edo // 3:
                    tonic += edo
                lead = t.chord(tonic + fifth - (edo if tonic + fifth > start + edo // 2 else 0), "dominant7")
                steps.append({"notes": [f"{n} ({t.number(p)})" for p, n in zip(lead.pitches, lead.names)], "label": lead.label,
                              "root": f"{lead.names[0]} ({t.number(lead.pitches[0])})", "beats": 4})
            off = (edo - 3 * third) % edo
            out["steps"] = steps
            out["result"] = ("Three major thirds down are exactly an octave here: the cycle closes." if off == 0 else
                             f"Three pure major thirds down do not make an octave here: the fourth key lies {off} step{'s' if off != 1 else ''} "
                             f"({off * 1200 / edo:.0f} cents) above the first. Compare the first and the last chord.")
            out["note"] = "Each new key lies a major third below the last and is reached through its own dominant."
        elif kind == "spoke":
            start, start_name = self._pitch(root)
            letter = t.letter_of(start_name)

            def spelled(p: int) -> str:     # all of them as inflections of the starting note
                return f"{t.name_with_letter(p, letter) if letter else t.name(p)} ({t.number(p)})"

            gap = 12 * fifth - 7 * edo
            if gap == 0:
                out["result"] = "Twelve fifths come home in this tuning: every spoke of the circle is a single key."
                out["steps"] = [{"note": t.label(start), "beats": 2}]
            else:
                notes = [start + k * gap for k in (-2, -1, 0, 1, 2) if (start + k * gap) in kb._by_pitch]
                out["steps"] = [{"note": spelled(p), "beats": 2} for p in notes]
                chain = ["two rounds of twelve fifths down", "twelve fifths down", "the starting note", "twelve fifths up", "two rounds up"]
                out["what_they_are"] = {spelled(start + k * gap): chain[k + 2] for k in (-2, -1, 0, 1, 2) if (start + k * gap) in kb._by_pitch}
                out["result"] = (f"Notes twelve fifths apart lie {abs(gap)} step{'s' if abs(gap) != 1 else ''} ({abs(gap) * 1200 / edo:.0f} cents) apart, "
                                 f"{'higher' if gap > 0 else 'lower'} with each round up. Light them and let the player name which is which.")
            out["note"] = "Use set_lights with these notes, or demo them slowly; then ask which one is the plain note."
            return out
        else:   # rings
            rings = math.gcd(edo, fifth)
            start, _ = self._pitch(root)
            if rings == 1:
                out["result"] = f"The fifths reach all {edo} notes of this tuning: one chain, no rings."
                return out
            size = edo // rings
            out["result"] = (f"The fifths never leave a ring of {size} notes; this tuning has {rings} such rings, {edo // size} step"
                             f"{'s' if edo // size != 1 else ''} apart. A note of the other ring cannot be reached by fifths.")
            out["steps"] = [{"note": t.label(start), "beats": 2}, {"note": t.label(start + 1), "beats": 2}]
            out["note"] = "The second note belongs to the neighbouring ring. Walk the circle from each (library fifths, count 0) and compare."
            return out
        if comma and not plain_roots and kind != "major_thirds":
            out["tuning_note"] = ("Roots follow the key's pure scale with the tonic fixed (the minor chord on the second degree a comma low); "
                                  "plain_roots=true gives the plain note names.")
        return out

    def _fifths(self, root: str, quality: str, voicing: str, direction: str, count: int, rhythm: str = "half") -> dict:
        kb = self.keyboard
        t = kb.tuning
        edo = t.edo
        fifth = t.steps_for(3 / 2)
        figures = {"half": None, "whole": None, "charleston": "on one and just before three", "reverse_charleston": "just after one and on three"}
        if rhythm not in figures:
            raise TutorError(f"rhythm must be one of: {', '.join(figures)}")
        if count == 0:          # the whole circle, home again
            count = edo // math.gcd(edo, fifth)
        direction = direction.strip().lower()
        if direction not in ("up", "down"):
            raise TutorError("direction must be up (up a fifth, then down a fourth, and so on) or down (down a fifth, up a fourth: the jazz cycle)")
        if voicing not in ("full", "shell", "guide", "root", "arpeggio"):
            raise TutorError("voicing must be one of: full, shell, guide, root, arpeggio")
        count = max(2, min(int(count), 60))
        start, start_name = self._pitch(root)
        letter_index = "FCGDAEB".index(start_name.lstrip("^v")[0])
        accidentals = start_name.lstrip("^v")[1:].rstrip("0123456789")
        position = letter_index + 7 * (accidentals.count("#") - accidentals.count("b"))
        ups = start_name[:len(start_name) - len(start_name.lstrip("^v"))]
        steps: list = []
        chain: list[str] = []
        missing: list[str] = []
        pitch = start
        for i in range(count + 1):
            k = i if direction == "up" else -i
            index = position + k
            name = "FCGDAEB"[index % 7] + ("#" * (index // 7) if index >= 0 else "b" * (-(index // 7)))
            plain = -1 <= index // 7 <= 1           # at most one sharp or flat: beyond that the tuning's own name is clearer
            if i:
                pitch += fifth if direction == "up" else -fifth
                while pitch - start > edo // 2:         # up a fifth, down a fourth: stay around the starting note
                    pitch -= edo
                while start - pitch > edo // 2:
                    pitch += edo
            try:
                chord = t.chord(pitch, quality, 0, (ups + name) if plain else None)
            except Exception as e:
                raise TutorError(str(e)) from None
            # move by octaves until the chord has keys
            for shift in (0, edo, -edo, 2 * edo, -2 * edo):
                if all((p + shift) in kb._by_pitch for p in chord.pitches):
                    if shift:
                        chord = t.chord(pitch + shift, quality, 0, (ups + name) if plain else None)
                    break
            tones = [(p, n) for p, n in zip(chord.pitches, chord.names)]
            missing.extend(t.label(p) for p, _ in tones if p not in kb._by_pitch)
            shown = t.pitch_class_name(tones[0][1])
            chain.append(shown if plain or shown == ups + name else f"{shown} (= {ups}{name})")
            label = f"{shown} {quality}"
            labels = [f"{n} ({t.number(p)})" for p, n in tones]
            if voicing == "arpeggio":
                up_and_back = labels + labels[-2:0:-1]
                steps.append([{"note": n, "beats": 0.5} for n in up_and_back[:-1]] + [{"note": up_and_back[-1] if len(up_and_back) > 1 else labels[0], "beats": 0.5}]
                             + [{"note": labels[0], "beats": 1}])
            else:
                chosen = labels[:1] if voicing == "root" else [labels[0], labels[1], labels[-1]] if voicing == "shell" and len(labels) >= 4 \
                    else [labels[1], labels[-1]] if voicing == "guide" else labels
                step = {"notes": chosen, "label": label, "beats": 4 if rhythm == "whole" else 2}
                if voicing != "guide":
                    step["root"] = labels[0]
                if rhythm == "charleston":
                    steps.extend([{**step, "beats": 1.5}, {**step, "beats": 2.5}])
                elif rhythm == "reverse_charleston":
                    steps.extend([{"rest": True, "beats": 0.5}, {**step, "beats": 1.5}, {**step, "beats": 2}])
                else:
                    steps.append(step)
        out = {
            "circle_in_this_tuning": self._fifths_facts(),
            "direction": "up a fifth, down a fourth, up a fifth ..." if direction == "up" else "down a fifth, up a fourth ... (the cycle most jazz progressions follow)",
            "chain": " - ".join(chain),
            "chord": quality, "voicing": voicing,
        }
        if voicing == "arpeggio":
            out["groups"] = steps
            out["note"] = ("Each group is one arpeggio up and back with its rhythm; pass a group to demo (outline=true shows the whole shape, "
                           "a slow tempo first) and to run_exercise. The hand shape is the same in every group: only its place moves.")
        else:
            out["steps"] = steps
            out["note"] = ("One chord per step; pass steps to demo, fingering, run_exercise, or to improvise as changes. The hand shape "
                           "stays the same: only its place moves, by the same two moves in turn.")
        if count >= 12 and (start + (12 * fifth if direction == "up" else -12 * fifth)) % edo != start % edo:
            out["after_twelve"] = "The twelfth fifth does not come home: compare it with the starting note. This is the spiral; say so and let the player hear both."
        if missing:
            out["not_on_this_keyboard"] = list(dict.fromkeys(missing))
        return out

    def _score_bars(self, piece: dict, first: int | None, count: int, part: str) -> dict:
        """A piece in two staves, bar by bar: what sounds together at each moment as one step."""
        kb = self.keyboard
        t = kb.tuning
        bars = piece["score"]
        written = tuning_for(piece["tuning"]) if piece["tuning"] != t.edo else None

        def here(step: int) -> tuple[int, float]:
            return t.retuned_from(written, step) if written else (step, 0.0)

        wanted = part if part in ("upper", "lower") else "both"         # one hand alone may fit where both do not
        every = [here(s)[0] for bar in bars for staff, events in bar["staves"].items() if wanted in (staff, "both")
                 for _, _, steps in events for s in steps]
        shift = self._fit_shift(every)[0]
        head = {"id": piece["id"], "title": piece["title"], "composer": piece.get("composer", ""), "written_for": piece["mode"],
                "bars": len(bars), "level": piece["level"], "source": piece["source"]}
        if piece.get("checked"):
            head["transcription"] = dict(piece["checked"])
        if written:
            worst = max((abs(here(s)[1]) for bar in bars for events in bar["staves"].values() for _, _, steps in events for s in steps), default=0.0)
            head["approximated"] = (f"written for {piece['tuning']} notes per octave, played here on the nearest notes of {t.edo}: up to "
                                    f"{worst:.0f} cents off, and notes that differ there may fall on one key here. Say so; switching the "
                                    f"tuning is better when the piece is the point.")
        if shift:
            head["moved"] = f"the whole piece {self._shift_words(shift)} to fit the keyboard" + ("" if wanted == "both" else " (for this hand alone)")
        if first is None:
            head["on_this_keyboard"] = self._piece_fit(piece)
            metres, last = [], None
            for bar in bars:
                if bar["time"] != last:
                    metres.append(f"bar {bar['n']}: {bar['time']}")
                    last = bar["time"]
            head["metre"] = metres[:12]
            differing = [bar["n"] for bar in bars if bar.get("variants")]
            if differing:
                head["two_readings"] = (f"in bar{'s' if len(differing) != 1 else ''} {', '.join(map(str, differing))} the sources of this "
                                        f"transcription differ (printed score, engraving or recording); those bars come with both readings")
            if piece.get("two_hands"):
                head["two_hands"] = dict(piece["two_hands"])
            from . import expression                    # the marks of the print the piece carries (expression.py)
            if expression.overview(piece):
                head["expression"] = expression.overview(piece)
            head["note"] = ("get with phrase = a bar number and phrases = how many bars (up to 4) gives those bars as steps; part = upper "
                            "(right hand), lower (left hand) or both. Teach hands separately first, a bar or two at a time.")
            return head
        if not 1 <= first <= len(bars):
            raise TutorError(f"phrase (the bar) must be between 1 and {len(bars)}")
        part = "upper" if part in ("auto", "melody") else part
        if part not in ("upper", "lower", "both"):
            raise TutorError("part must be upper (right hand), lower (left hand) or both")
        chosen = bars[first - 1:first - 1 + max(1, min(count, 4))]
        moments: dict[float, set[int]] = {}
        at = 0.0
        for bar in chosen:
            for staff, events in bar["staves"].items():
                if part in (staff, "both"):
                    for beat, _, steps in events:
                        moments.setdefault(round(at + beat, 4), set()).update(here(s)[0] + shift for s in steps)
            at += bar["length"]
        # what the print marks on a note: a grace note, the first stroke of a trill that the file holds written out
        marked: dict[tuple[float, int], str] = {}
        at_bar = 0.0
        for bar in chosen:
            for m in bar.get("marks", []):
                if part in (m["staff"], "both"):
                    marked[(round(at_bar + m["beat"], 4), here(m["step"])[0] + shift)] = m["mark"]
            at_bar += bar["length"]
        # a note without a key is left out of the steps (they must be playable) and named
        missing = [t.label(p) for when in sorted(moments) for p in sorted(moments[when]) if p not in kb._by_pitch]
        moments = {when: {p for p in pitches if p in kb._by_pitch} for when, pitches in moments.items()}
        moments = {when: pitches for when, pitches in moments.items() if pitches}
        times = sorted(moments)
        steps = []
        for i, when in enumerate(times):
            pitches = sorted(moments[when])
            length = round((times[i + 1] if i + 1 < len(times) else at) - when, 3)
            step = {"notes": [t.label(p) for p in pitches]} if len(pitches) > 1 else {"note": t.label(pitches[0])}
            if length != 1:
                step["beats"] = length
            marks = {marked.get((when, p)) for p in pitches}
            if marks == {"grace"}:
                step["grace"] = "a grace note: small, quick, just before the next note; not counted in the beat"
            if "trill" in marks:
                run = 1
                while i + run < len(times) and round(times[i + run] - times[i + run - 1], 4) == round(times[i + 1] - when, 4):
                    run += 1
                step["trill"] = (f"a trill begins here: the print has a trill sign, the next {run - 1} short notes are its strokes written out. "
                                 f"Teach it as a trill between its two notes, not stroke by stroke.")
            steps.append(step)
        if times and times[0] > 0:
            steps.insert(0, {"rest": True, "beats": times[0]})
        readings = []
        for bar in chosen:
            for v in bar.get("variants", []):
                if part in (v["staff"], "both"):
                    readings.append({"bar": bar["n"], "beat": round(v["beat"] + 1, 3), "hand": "right" if v["staff"] == "upper" else "left",
                                     f"the {v['source']} has": t.label(here(v["step"])[0] + shift), "given in steps": f"the {v['source']}'s note",
                                     f"the {v['other_source']} has": t.label(here(v["other"])[0] + shift)})
        last_bar = chosen[-1]["n"]
        if piece.get("checked"):
            check = piece["checked"]
            doubtful = [bar["n"] for bar in chosen if bar["n"] in check.get("doubtful_bars", [])]
            head["transcription"] = {"grade": check["grade"], "means": check["means"], "listen_to": check["listen_to"]}
            if doubtful:
                head["transcription"]["doubtful_here"] = (f"bar{'s' if len(doubtful) != 1 else ''} {', '.join(map(str, doubtful))}: the check "
                                                          f"disagreed with this reading or could not settle it. Say so before teaching it.")
        tight = [bar["n"] for bar in chosen if bar["n"] in (piece.get("two_hands") or {}).get("tight_bars", [])]
        if tight:
            head["two_hands_here"] = (f"bar{'s' if len(tight) != 1 else ''} {', '.join(map(str, tight))}: written for two players; one hand has "
                                      f"more to strike at once than it reaches. Say so, take the upper line first, then break the chord or "
                                      f"leave inner notes out.")
        if readings:
            head["two_readings"] = readings
            head["two_readings_note"] = ("Here the sources of this transcription differ (the printed score, an engraving of it, or a "
                                         "recording). Tell the player, show both (demo the bar once with each note) and let them choose; "
                                         "neither is an error of theirs.")
        head.update({"bars_given": f"{chosen[0]['n']}" + (f"-{last_bar}" if len(chosen) > 1 else ""), "time": chosen[0]["time"], "part": part,
                     "steps": steps})
        from . import expression                        # dynamics, hairpins, tempo words, pedal ... of these bars, in words
        said = expression.words(bars, chosen, part)
        if said:
            head["expression"] = said
        if missing:
            head["not_on_this_keyboard"] = list(dict.fromkeys(missing))
            head["not_on_this_keyboard_note"] = ("These notes of the bar have no key on the keyboard as it is and are left out of the steps. "
                                                 "Tell the player; library get without a bar says what fits on which tuning.")
        head["note"] = ("Pass steps to demo (lengths are in 'beats', one beat = a quarter note), then run_exercise; fingering gives the fingers. "
                        + (f"Next: bar {last_bar + 1}." if last_bar < len(bars) else "This is the last bar."))
        return head

    def _library_overview(self) -> dict:
        t = self.keyboard.tuning
        counts = self.music.counts()
        out: dict = {"tuning_now": f"{t.edo} equal steps per octave"}
        if not counts:
            out["pieces"] = "no pieces installed (python -m tutor.library_build builds them from the downloaded collections)"
        else:
            words = {"makam": "Turkish makam music, written for 53 steps per octave: teaching examples, seyir (the short melodic path "
                              "that shows a makam), folk songs, songs",
                     "chant": "Gregorian chant: one voice, no metre, built on pure fifths; playable in any tuning, exact in 53; over a drone on the final",
                     "composition": "pieces composed for a particular tuning, in two staves, bar by bar (get with phrase = bar number, "
                                    "part = upper, lower or both)",
                     "jazz": "jazz standards: the chord changes of about 1,400 tunes (form 'Medium Swing', 'Ballad', ...), and about 500 older "
                             "songs as lead sheets with melody (form 'lead sheet'); chords are spelled for the current tuning"}
            out["pieces"] = {
                trad: {"what": words.get(trad, trad), "pieces_by_level": {str(k): v for k, v in sorted(levels.items())},
                       "playable_now": (t.edo == 53 if trad == "makam" else "in the tuning each was written for, or with nearest=true"
                                        if trad == "composition" else True),
                       "most_common": [f"{m} ({n})" for m, n in self.music.modes(trad, 10)]}
                for trad, levels in counts.items()}
        out["ragas"] = {"what": "raga outlines (scale, ascent, descent, characteristic phrase, drone) as a model on the nearest steps of the "
                                "current tuning, with practice patterns", "names": lib.raga_names()}
        out["patterns"] = {"what": "beginner patterns over any scale or raga, in any tuning", "names": lib.PATTERNS}
        out["cycles"] = {"what": "scales and progressions that run around the circle: action cycle with name = scales, two_five_one, diatonic, "
                                 "minor_diatonic, dominants, bridge, major_thirds, spoke or rings",
                         "listening": "action comma: twelve_fifths, third, minor_third, schismatic, thirds_cycle, pump"}
        out["fifths"] = {"what": "the circle (or spiral) of fifths as chords or arpeggios, up a fifth and down a fourth in turn, or the "
                                 "other way; action fifths with root, name = chord quality, voicing, direction, count",
                         "in_this_tuning": self._fifths_facts()}
        out["how"] = ("action search (tradition, mode, form, level, text) lists pieces; get (id) describes one, get with phrase=N gives that "
                      "phrase as steps for demo, run_exercise and fingering; raga (name) and pattern (name + root/mode or raga) likewise.")
        out["levels"] = "1 = first pieces (short, narrow) ... 5 = long or wide-ranging; a rough grading by form, length and range"
        return out

    def library(self, action: str = "overview", id: str | None = None, phrase: int | None = None, phrases: int = 1,
                tradition: str | None = None, mode: str | None = None, form: str | None = None, level: int | None = None,
                text: str | None = None, limit: int = 10, name: str | None = None, root: str | None = None,
                scale: str = "major", theory_pitches: bool = False, part: str = "auto", voicing: str = "full",
                sevenths: str = "auto", plain_roots: bool = False, direction: str = "up", count: int = 12,
                rhythm: str = "half", nearest: bool = False) -> dict:
        """Teaching material. overview | search | get | raga | pattern | fifths | comma."""
        action = action.strip().lower()
        kb = self.keyboard
        t = kb.tuning
        if action == "overview":
            return self._library_overview()

        if action == "search":
            found = self.music.search(tradition, mode, form, level, text)
            if tradition == "makam" and t.edo != 53:
                return {"matches": len(found), "note": "Makam pieces are written in 53 steps per octave; switch the tuning to 53 to play them."}
            shown = found[:max(1, min(limit, 30))]
            return {"matches": len(found), "pieces": [
                {"id": e["id"], "title": e["title"], "mode": e["mode"], "form": e["form"], "meter": e["meter"], "level": e["level"],
                 "notes": e["notes"], "phrases": e["phrases"], **({"bars": e["bars"]} if e.get("bars") else {}),
                 **({"checked": e["checked"]} if e.get("checked") else {})} for e in shown],
                "note": "easiest and shortest first" + ("; narrow the search for others" if len(found) > len(shown) else "")}

        if action == "get":
            if not id:
                raise TutorError("action get needs id (from a search)")
            piece = self.music.piece(id)
            if piece is None:
                raise TutorError(f"there is no piece '{id}' in the library; ids come from action search")
            if piece["tuning"] and piece["tuning"] != t.edo and not nearest:
                raise TutorError(f"this piece is written in {piece['tuning']} steps per octave and the keyboard is in {t.edo}. "
                                 f"Switch with tuning to {piece['tuning']}, or ask again with nearest=true to play it here on the "
                                 f"nearest notes (an approximation), or choose another piece.")
            if piece.get("score"):
                return self._score_bars(piece, phrase, phrases, part)
            pitches, off = self._piece_pitches(piece, theory_pitches)
            shift = self._fit_octaves([p for p in pitches if p is not None]) * t.edo
            pitches = [None if p is None else p + shift for p in pitches]
            head = {"id": piece["id"], "title": piece["title"], "tradition": piece["tradition"], "mode": piece["mode"], "form": piece["form"],
                    "meter": piece["meter"], "level": piece["level"], "source": piece["source"], "licence": piece["licence"]}
            if piece.get("composer"):
                head["composer"] = piece["composer"]
            if piece["tuning"] and piece["tuning"] != t.edo:
                head["approximated"] = (f"written in {piece['tuning']} steps per octave, played here on the nearest notes of {t.edo}: "
                                        f"up to {off:.0f} cents off, and notes that differ there may fall on one key here. Say so.")
            if shift:
                head["moved"] = f"{abs(shift) // t.edo} octave{'s' if abs(shift) != t.edo else ''} {'up' if shift > 0 else 'down'} to fit the keyboard"
            if piece["tradition"] == "chant":
                final = next(p for p in reversed(pitches) if p is not None)
                head["drone"] = f"chant is sung over nothing or a drone: its last note {t.label(final)} is the home note"
            if piece["tradition"] == "makam":
                head["pitches"] = ("the written theory (Arel-Ezgi-Uzdilek)" if theory_pitches else
                                   "as played in practice; theory_pitches=true gives the textbook values, which differ by a comma in places"
                                   if piece["theory"] else "theory and practice agree in this piece")
            changes = piece.get("changes") or []
            want_changes = bool(changes) and (part == "changes" or (part != "melody" and not piece["notes"]))
            if changes:
                head["key"] = piece.get("key") or "not given"
                head["form"] = [{"section": n + 1, "label": s["label"], "bars": len(s["bars"]),
                                 "changes": " | ".join(" ".join(bar) for bar in s["bars"])} for n, s in enumerate(changes)]
            if want_changes and phrase is not None:
                if not 1 <= phrase <= len(changes):
                    raise TutorError(f"phrase (the section) must be between 1 and {len(changes)}")
                if voicing not in ("full", "shell", "guide", "root"):
                    raise TutorError("voicing must be one of: full, shell (root, third, seventh), guide (third and seventh), root")
                last = min(len(changes), phrase + max(1, min(phrases, 4)) - 1)
                bars = [bar for s in changes[phrase - 1:last] for bar in s["bars"]]
                steps, left_out = self._changes_steps(piece, bars, voicing, sevenths, plain_roots)
                head.pop("form")
                head.update({"section": phrase if last == phrase else f"{phrase}-{last}", "of": len(changes), "voicing": voicing,
                             "steps": steps})
                comma = t.steps_for(9 / 8) - t.steps_for(10 / 9)
                if not self._piece_key(piece):
                    head["key"] = "not given: chords are on their plain note names"
                if comma and not plain_roots and self._piece_key(piece):
                    head["tuning_note"] = ("Roots follow the key's pure scale with the tonic fixed, so some chords sit one step (a comma) "
                                           "off the plain note name, e.g. the minor chord on the second degree a comma low. plain_roots=true "
                                           "gives the plain names instead; the two versions are worth comparing by ear.")
                blues = "blues" in piece["title"].lower() or piece.get("bars") == 12
                if t.has("harmonic7"):
                    head["sevenths"] = ("dominant chords with the harmonic seventh (4:5:6:7), the calm blues and barbershop sound; "
                                        "sevenths=plain gives the ordinary one" if (sevenths == "harmonic" or (sevenths == "auto" and blues))
                                        else "dominant chords with the ordinary seventh (the fourth of the key they lead to); "
                                             "sevenths=harmonic gives the calm 4:5:6:7 sound")
                if left_out:
                    head["left_out"] = left_out[:8]
                head["note"] = ("Each step is one chord with its length in beats; pass steps to demo, fingering and run_exercise. Extensions "
                                "beyond the seventh are left out. " + (f"Next: section {last + 1}." if last < len(changes) else "This is the last section."))
                return head
            spans = piece["phrases"]
            if phrase is None and not spans:
                head["note"] = "Changes only, no melody. get with phrase=N gives section N as chord steps (voicing: full, shell, guide, root)."
                return head
            if phrase is None:
                head["phrase_count"] = len(spans)
                head["phrases"] = [{"phrase": n + 1, "notes": b - a + 1, "starts": t.label(pitches[a]), "ends": t.label(pitches[b])}
                                   for n, (a, b) in enumerate(spans[:24])]
                head["note"] = "get with phrase=N (and phrases=how many in a row) gives the notes as steps. Teach one phrase at a time."
                return head
            if not 1 <= phrase <= len(spans):
                raise TutorError(f"phrase must be between 1 and {len(spans)}")
            last = min(len(spans), phrase + max(1, min(phrases, 4)) - 1)
            a, b = spans[phrase - 1][0], spans[last - 1][1]
            chosen = [(p, piece["notes"][i][1]) for i, p in enumerate(pitches) if a <= i <= b and p is not None]
            steps, missing = self._as_steps([p for p, _ in chosen], [beats for _, beats in chosen])
            head.update({"phrase": phrase if last == phrase else f"{phrase}-{last}", "of": len(spans), "steps": steps})
            if missing:
                head["not_on_this_keyboard"] = missing
                head["note"] = "Some notes lie beyond this keyboard; choose another phrase or piece."
            else:
                head["note"] = ("Pass steps to demo (the note lengths are in 'beats'), then to run_exercise; fingering gives the fingers. "
                                + (f"Next: phrase {last + 1}." if last < len(spans) else "This is the last phrase."))
            return head

        if action == "fifths":
            return self._fifths(root or "C", name or "major", voicing, direction, count, rhythm)
        if action == "comma":
            return self._comma_lesson((name or "").strip().lower(), root or "C", count)
        if action == "cycle":
            return self._cycle((name or "").strip().lower(), root or "C", voicing, scale, count, sevenths, plain_roots)

        if action in ("raga", "pattern"):
            raga = None
            if action == "raga" or (name and lib.find_raga(name)):
                if not name:
                    return {"ragas": {k: v["taught"] for k, v in lib.RAGAS.items()},
                            "note": "action raga with name gives the outline; these are models, see 'intonation' in each."}
                found = lib.find_raga(name)
                if not found and action == "raga":
                    raise TutorError(f"no raga '{name}' in the library. Available: {', '.join(lib.raga_names())}.")
                raga = found
            sa_pitch, sa_name = self._pitch(root or "C")
            if raga:
                key, data = raga
                steps_of = lib.swara_steps(data, t.edo)
                order = sorted(steps_of, key=lambda s: steps_of[s][0])
                scale_pitches = [sa_pitch + steps_of[s][0] for s in order] + [sa_pitch + t.edo]
                if action == "raga":
                    def line(text: str) -> list[str]:
                        return [" ".join(t.label(sa_pitch + s) for s in group) for group in lib.sargam_to_steps(text, steps_of, t.edo)]
                    worst = max(abs(c) for _, c in steps_of.values())
                    out = {
                        "raga": key, "tradition": data["tradition"], "time_of_day": data["time"], "why_taught": data["taught"],
                        "sa": t.label(sa_pitch),
                        "drone": f"{t.label(sa_pitch - t.edo)} with {t.label(sa_pitch - t.edo + steps_of.get('P', (round(t.edo * 0.585), 0))[0])}"
                                 if "P" in steps_of else f"{t.label(sa_pitch - t.edo)} with {t.label(sa_pitch - t.edo + steps_of['M'][0])}",
                        "notes": {lib.SWARA_NAMES[s]: f"{t.label(sa_pitch + steps_of[s][0])}, ratio {data['notes'].get(s, '1/1')}" for s in order},
                        "ascent": line(data["up"]), "descent": line(data["down"]), "characteristic_phrase": line(data["phrase"]),
                        "strong_notes": [lib.SWARA_NAMES[s] for s in data["strong"]],
                        "intonation": ("A model: each note is the nearest step of this tuning to a just ratio "
                                       f"(largest deviation {worst:.0f} cents). Performers bend, slide and oscillate notes, and scholars "
                                       "disagree on some positions. Say so; do not present these as the one true pitches."),
                        "patterns": "action pattern with name = this raga and scale = one of: " + ", ".join(lib.PATTERNS),
                    }
                    out["tanpura"] = self._tanpura_words(data, sa_pitch)
                    if data.get("also"):
                        out["also"] = data["also"]
                    if data.get("disputed"):
                        out["disputed"] = data["disputed"]
                    missing = [n for n in (t.label(p) for p in scale_pitches) if t.parse(n)[0] not in kb._by_pitch]
                    if missing:
                        out["not_on_this_keyboard"] = missing
                    return out
                kind, label = (scale if scale in lib.PATTERNS else "steps"), f"{key} on {sa_name}"
            else:
                if not name or name.strip().lower() not in lib.PATTERNS:
                    raise TutorError(f"action pattern needs name: one of {', '.join(lib.PATTERNS)}; with root and scale (a mode such as major), "
                                     f"or name = a raga and scale = the pattern.")
                kind = name.strip().lower()
                try:
                    scale_pitches = [p for p, _ in t.scale(sa_pitch, scale, sa_name)] + [sa_pitch + t.edo]
                except Exception as e:
                    raise TutorError(str(e)) from None
                label = f"{sa_name} {scale}"
            groups = lib.pattern(kind, scale_pitches)
            exercises = []
            missing: list[str] = []
            for g in groups:
                steps, lacking = self._as_steps(g)
                missing.extend(lacking)
                exercises.append(steps)
            out = {"pattern": kind, "what": lib.PATTERNS[kind], "on": label, "groups": exercises,
                   "note": "Each group is one short exercise: pass it as steps to demo and run_exercise. Slowly first, the drone helps the ear."}
            if missing:
                out["not_on_this_keyboard"] = list(dict.fromkeys(missing))
            return out

        raise TutorError("action must be one of: overview, search, get, raga, pattern")

    # --- lights ---

    def _colour(self, role: str | None, color: str | None) -> Rgb:
        if color:
            h = color.strip().lstrip("#")
            if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
                raise TutorError(f"color must be six hex digits such as FF8000, not '{color}'")
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        role = (role or "target").strip().lower().replace(" ", "")
        if role in ("1", "2", "3", "4", "5"):
            role = "finger" + role
        if role not in ROLES:
            raise TutorError(f"unknown role '{role}'. Roles: {', '.join(ROLES)}; or give color as RRGGBB.")
        return ROLES[role]

    def _keys_of(self, item: dict) -> list[Key]:
        kb = self.keyboard
        if item.get("key"):
            return [kb.key(item["key"])]
        if item.get("note"):
            pitch, has_octave = kb.tuning.parse(item["note"])
            if not has_octave:
                raise TutorError(f"'{item['note']}' needs an octave to be lit (for example {item['note'].strip()}4), or give a key id")
            found = kb.keys_for_pitch(pitch)
            if not found:
                raise TutorError(f"this keyboard has no key for {item['note']}")
            return found
        raise TutorError("each light needs a key (id) or a note (name with octave)")

    def set_lights(self, lights: list[dict] | None = None, clear: list[str] | str | None = None) -> dict:
        """`lights`: [{key or note, role or color}]; `clear`: "all" or key ids."""
        kb = self.keyboard
        if clear == "all":
            self.lights.clear()
        elif clear:
            if isinstance(clear, str):
                raise TutorError('clear must be "all" or a list of key ids')
            self.lights.remove([kb.key(k) for k in clear])
        wanted: dict[Key, Rgb] = {}
        for item in lights or []:
            rgb = self._colour(item.get("role"), item.get("color"))
            for k in self._keys_of(item):
                wanted[k] = rgb
        if wanted:
            self.lights.add(wanted)
        out = {"lit": sorted(self.lights.lit), "count": len(self.lights.lit)}
        if self.practice:
            out["practice_mode"] = "No real keyboard is attached: the player sees none of these lights."
        return out

    # --- steps shared by demo and run_exercise ---

    def _resolve_steps(self, steps: list[dict], hand: str, exact_keys: bool, legato: bool = True, detail: bool = False) -> tuple[list[Step], list[dict]]:
        """Tool-level steps -> engine steps plus what to tell the model about each.
        A step is {"chord": "C major"} (optionally "inversion"), {"notes": [..]},
        {"note": "E4"} or {"keys": [ids]}; optional "label" and "near"."""
        kb = self.keyboard
        if not steps:
            raise TutorError("steps is empty; give at least one step")
        if hand.strip().lower() not in ("left", "right"):
            raise TutorError(f"hand must be 'left' or 'right', not '{hand}'")
        steps = [s for s in steps if not (isinstance(s, dict) and s.get("rest"))]       # a rest is not something to play
        if not steps:
            raise TutorError("steps has only rests; give at least one step to play")
        pending: list[tuple[str, dict, bool, list[list[Key]], int | None]] = []    # label, names, exact, ways to play it, root
        previous: Key | None = None
        for i, raw in enumerate(steps, 1):
            if not isinstance(raw, dict):
                raise TutorError(f"step {i} must be an object such as {{\"chord\": \"C major\"}}")
            near = kb.key(raw["near"]) if raw.get("near") else previous
            exact = exact_keys
            step_root: int | None = None
            if raw.get("keys"):
                keys = [kb.key(k) for k in raw["keys"]]
                names = {k.pitch: k.name for k in keys}
                label = raw.get("label") or " ".join(k.name for k in keys)
                exact = True
                ways = [keys]
            else:
                if raw.get("chord"):
                    parts = str(raw["chord"]).split(None, 1)
                    chord = self._parse_chord(parts[0], parts[1] if len(parts) > 1 else "major", int(raw.get("inversion", 0)), near)
                    pitches, names, label = list(chord.pitches), dict(zip(chord.pitches, chord.names)), chord.label
                    step_root = chord.root
                elif raw.get("notes") or raw.get("note"):
                    resolved = [self._pitch(n, near) for n in (raw.get("notes") or [raw["note"]])]
                    pitches, names = [p for p, _ in resolved], {p: n for p, n in resolved}
                    label = " ".join(n for _, n in resolved)
                    if raw.get("root"):
                        step_root = self._pitch(raw["root"], near)[0]
                else:
                    raise TutorError(f"step {i} needs one of: chord, notes, note, keys")
                label = raw.get("label") or label
                ways = [list(s.keys) for s in kb.shapes(pitches, near, 3)]
            previous = ways[0][0]
            pending.append((label, names, exact, ways, step_root))
        # The phrase is fingered as a whole: which of the ways to play each step, and which
        # fingers, depends on the steps around it.
        planned = fingering_model.plan(
            self.hand_model,
            [[fingering_model.Option(tuple((k.id, *kb.position_mm(k)) for k in way)) for way in ways] for _, _, _, ways, _ in pending],
            hand, legato, prefer=lambda pts: self.player.preferred(hand.strip().lower(), pts))
        out: list[Step] = []
        told: list[dict] = []
        edo = kb.tuning.edo
        for i, ((label, names, exact, ways, step_root), chosen) in enumerate(zip(pending, planned), 1):
            keys = ways[chosen.option] if chosen else ways[0]
            fingers = dict(zip((k.id for k in keys), chosen.fingering.fingers)) if chosen else {}
            out.append(Step(label=label, pitches=tuple(sorted({k.pitch for k in keys})), keys=tuple(k.id for k in keys), exact_keys=exact))
            entry = {
                "step": i,
                "asked": label,
                "keys": [{**self._key_brief(k, names.get(k.pitch)),
                          **self._finger_words(fingers.get(k.id), step_root is not None and k.pitch % edo == step_root % edo)} for k in keys],
            }
            if detail:
                if chosen:
                    entry["fingering"] = self._fingering_brief(chosen.fingering)
                    if chosen.notes:
                        entry["in_context"] = list(chosen.notes)
                    if chosen.alternatives:
                        entry["by_itself_also"] = [self._fingering_brief(f) for f in chosen.alternatives[:2]]
                else:
                    entry["fingering"] = "more than five notes: two hands"
            told.append(entry)
        for entry, raw in zip(told, steps):
            if raw.get("beats"):
                entry["beats"] = float(raw["beats"])
        return out, told

    def fingering(self, steps: list[dict], hand: str = "right", legato: bool = True) -> dict:
        """Fingers for a phrase (a melody, a progression, or both mixed), chosen for the
        phrase as a whole."""
        _, told = self._resolve_steps(steps, hand, False, legato, detail=True)
        return {
            "hand": hand, "playing": "legato (joined)" if legato else "detached",
            "steps": told,
            "fingers": FINGER_NOTE + " 'in_context' says what the neighbouring steps changed; "
                       "'by_itself_also' are other good fingerings of that step alone.",
        }

    def _hint_colours(self, step: Step, fingers: bool, info: dict | None = None) -> dict[Key, Rgb]:
        kb = self.keyboard
        keys = [kb.key(k) for k in step.keys]
        by_finger = {k["key"]: k["finger"] for k in (info or {}).get("keys", []) if "finger" in k}
        if fingers and by_finger:
            return {k: ROLES[f"finger{by_finger[k.id]}"] if k.id in by_finger else ROLES["target"] for k in keys}
        roots = {k["key"] for k in (info or {}).get("keys", []) if k.get("role") == "root"}
        return {k: ROLES["root"] if k.id in roots else ROLES["target"] for k in keys}

    def _need_player(self, what: str) -> None:
        if self.practice:
            raise TutorError(f"{what} needs the real keyboard. {PRACTICE_NOTE}")

    def _begin(self) -> None:
        if not self._activity.acquire(blocking=False):
            raise TutorError("a demo, listen or exercise is still running; call stop first, or wait for it to end")
        self._cancel.clear()

    def stop(self) -> dict:
        """End whatever is running and switch the tutor's lights off."""
        self._cancel.set()
        self._drone_end()
        self._play_end()
        try:
            self.client.notes(off=[addr for addr, _ in self.lights.lit.values()])
        except XentoolError:
            pass
        self.lights.clear()
        return {"stopped": True}

    # --- playing a piece of the library ---

    def _play_end(self) -> bool:
        playing, self._playing = self._playing, None
        if not playing:
            return False
        playing[1].set()
        if playing[0] is not threading.current_thread():
            playing[0].join(timeout=2.0)
        return True

    def _play_run(self, moments: list[tuple[float, list]], lights: bool, stop: threading.Event) -> None:
        """Strike each moment at its time, counted from one start: no step waits on the one before,
        so a slow call does not make the rest late. Every note is sent with its own length."""
        start = time.perf_counter()
        sounding: set = set()
        try:
            for at, notes in moments:
                if stop.wait(max(0.0, start + at - time.perf_counter())):
                    break
                try:
                    self.client.notes(on=[(addr, velocity, ms) for addr, velocity, ms in notes])
                    sounding.update(addr for addr, _, _ in notes)
                    if lights:
                        self.client.overlay(set={addr: (255, 255, 255) for addr, _, _ in notes}, clear="all", dim_base=0.15)
                except Exception:           # a keyboard that is away for a moment must not end the piece
                    pass
            else:
                stop.wait(max((ms for _, notes in moments[-1:] for _, _, ms in notes), default=0) / 1000.0)
        finally:
            if stop.is_set():
                try:
                    self.client.notes(off=list(sounding))
                except Exception:
                    pass
            if lights:
                try:
                    self.client.overlay(clear="all", dim_base=1.0)
                except Exception:
                    pass
            if self._playing and self._playing[0] is threading.current_thread():
                self._playing = None

    def play_piece(self, action: str = "start", id: str | None = None, from_bar: int = 1, to_bar: int | None = None, part: str = "both",
                   speed: float = 1.0, tempo_bpm: float | None = None, nearest: bool = False, lights: bool = False,
                   octave: int | None = None) -> dict:
        """Play a composition of the library from one bar to another as it is written: every note at
        its time and with its own length, at the piece's tempo or a share of it. start | stop | status."""
        action = action.strip().lower()
        if action == "stop":
            return {"playing": "stopped" if self._play_end() else "nothing was playing"}
        alive = self._playing if self._playing and self._playing[0].is_alive() else None
        if action == "status":
            return {"playing": "yes", **alive[2]} if alive else {"playing": "no"}
        if action != "start":
            raise TutorError("action must be one of: start, stop, status")
        self._need_player("play_piece")
        if not id:
            raise TutorError("give the id of a piece (library search tradition=composition lists them)")
        piece = self.music.piece(id)
        if not piece.get("score"):
            raise TutorError("play_piece plays compositions in two staves (tradition composition); for other pieces pass their phrases to demo")
        kb = self.keyboard
        t = kb.tuning
        bars = piece["score"]
        if piece["tuning"] != t.edo and not nearest:
            raise TutorError(f"this piece is written in {piece['tuning']} notes per octave and the keyboard is in {t.edo}. Switch with tuning to "
                             f"{piece['tuning']}, or ask again with nearest=true to hear it on the nearest notes here (an approximation).")
        to_bar = len(bars) if to_bar is None else to_bar
        if not 1 <= from_bar <= to_bar <= len(bars):
            raise TutorError(f"from_bar and to_bar must lie between 1 and {len(bars)}, from_bar first")
        if part not in ("upper", "lower", "both"):
            raise TutorError("part must be upper (right hand), lower (left hand) or both")
        if not 0.1 <= speed <= 2:
            raise TutorError("speed must be between 0.1 (a tenth of the tempo) and 2")
        written = tuning_for(piece["tuning"]) if piece["tuning"] != t.edo else None

        def here(step: int) -> int:
            return t.retuned_from(written, step)[0] if written else step

        # transposing: the whole piece by octaves so that most of it has a key (or as asked); then single
        # notes that still have none go to the nearest octave that has one
        every = [here(s) for bar in bars for events in bar["staves"].values() for _, _, steps in events for s in steps]
        shift = self._fit_shift(every)[0] if octave is None else int(octave) * t.edo
        tempi = sorted(piece.get("tempi") or [])
        chosen = bars[from_bar - 1:to_bar]
        from . import expression
        perform = expression.Performance(piece)         # loudness, ritardandi, fermatas after the print's marks (expression.py)
        by_time: dict[float, list] = {}
        folded: dict[str, str] = {}
        silent: list[str] = []
        at = 0.0
        slowest = None
        for bar in chosen:
            marked = [bpm for n, bpm in tempi if n <= bar["n"]]
            bpm = (float(tempo_bpm) if tempo_bpm else (marked[-1] if marked else 60.0) * speed)
            if not 10 <= bpm <= 400:
                raise TutorError(f"that gives {bpm:.0f} quarter notes per minute in bar {bar['n']}; choose a speed or tempo_bpm between 10 and 400")
            slowest = bpm if slowest is None else min(slowest, bpm)
            quarter = 60.0 / bpm
            for staff, events in bar["staves"].items():
                if part not in (staff, "both"):
                    continue
                for beat, dur, steps in events:
                    for step in steps:
                        pitch = here(step) + shift
                        if not kb.keys_for_pitch(pitch):
                            near = next((pitch + k * t.edo for k in (-1, 1, -2, 2, -3, 3) if kb.keys_for_pitch(pitch + k * t.edo)), None)
                            if near is None:
                                silent.append(t.label(pitch))
                                continue
                            folded[t.label(pitch)] = t.label(near)
                            pitch = near
                        key = kb.keys_for_pitch(pitch)[0]
                        velocity = perform.velocity(bar, beat, staff) or (84 if staff == "upper" else 68)
                        by_time.setdefault(round(at + perform.seconds(bar, beat, quarter), 4), []).append(
                            ((key.board, key.key), velocity, max(30, int(perform.held(bar, beat, dur, staff, quarter) * 950))))
            at += perform.seconds(bar, bar["length"], quarter)
        moments = sorted(by_time.items())
        if not moments:
            raise TutorError("there is nothing to play in these bars for this part")
        self._play_end()
        told = {"piece": piece["title"], "bars": f"{from_bar}-{to_bar}" if to_bar > from_bar else str(from_bar), "part": part,
                "seconds": round(at, 1), "notes": sum(len(n) for _, n in moments)}
        if tempo_bpm or speed != 1:
            told["tempo"] = f"{slowest:.0f} quarter notes per minute" + ("" if tempo_bpm else f" ({speed:g} of the piece's tempo)")
        if shift:
            told["moved"] = f"the whole piece {self._shift_words(shift)} to fit the keyboard"
        if folded:
            told["moved_single_notes"] = (f"{len(folded)} notes outside the keyboard are played an octave or more away: "
                                          + ", ".join(f"{a} as {b}" for a, b in list(folded.items())[:8]) + (" ..." if len(folded) > 8 else ""))
        if silent:
            told["left_out"] = sorted(set(silent))
        if written:
            told["approximated"] = f"written for {piece['tuning']} notes per octave, played on the nearest notes of {t.edo}"
        if piece.get("checked"):
            told["transcription"] = piece["checked"]["grade"]
        if perform.assumed:
            told["expression"] = perform.assumed
        stop = threading.Event()
        thread = threading.Thread(target=self._play_run, args=(moments, bool(lights), stop), name="tutor-play", daemon=True)
        self._playing = (thread, stop, told)
        thread.start()
        return {"playing": "started", **told,
                "note": "It plays by itself and this call has returned: talk over it, or wait the seconds given. play_piece action stop (or stop) "
                        "ends it. To let the player try, give them the same bars with library get and run_exercise."}

    def play_along(self, id: str | None = None, from_bar: int = 1, to_bar: int | None = None, part: str = "both", mode: str = "click",
                   speed: float = 1.0, tempo_bpm: float | None = None, nearest: bool = False, count_in: int = 1, click: bool = True,
                   accompany: bool = False, level: str = "beginner", pause_s: float = playalong.FOLLOW_PAUSE_S,
                   progress: Progress | None = None) -> dict:
        """The player plays bars of a composition in time and the rhythm is judged: with a click
        (mode click) or at their own tempo (mode follow). All of it is in `playalong.py`."""
        return playalong.run(self, id, from_bar, to_bar, part, mode, speed, tempo_bpm, nearest, count_in, click, accompany, level,
                             pause_s, progress)

    # --- demo ---

    def demo(self, steps: list[dict], tempo_bpm: float = 60, beats_per_step: float = 2, hand: str = "right",
             fingers: bool = False, repeat: int = 1, outline: bool = False, progress: Progress | None = None) -> dict:
        """Play and light steps in time. A step {"rest": true, "beats": n} is a silence.
        `repeat` plays the whole figure several times; `outline` keeps all its keys dimly
        lit while the note that sounds is bright."""
        self._need_player("demo")
        if not steps or not isinstance(steps, list):
            raise TutorError("steps is empty; give at least one step")
        rests_before: dict[int, float] = {}     # beats of silence before the n-th sounding step (len = after the last)
        sounding = []
        for raw in steps:
            if isinstance(raw, dict) and raw.get("rest"):
                rests_before[len(sounding)] = rests_before.get(len(sounding), 0.0) + float(raw.get("beats", beats_per_step))
            else:
                sounding.append(raw)
        resolved, told = self._resolve_steps(sounding, hand, False)
        if not 20 <= tempo_bpm <= 240:
            raise TutorError("tempo_bpm must be between 20 and 240")
        beat_s = 60.0 / tempo_bpm
        repeat = max(1, min(int(repeat), 16))
        once = [beat_s * info.get("beats", beats_per_step) for info in told]    # a step's own "beats" wins
        rest_s = {n: beat_s * b for n, b in rests_before.items()}
        if (sum(once) + sum(rest_s.values())) * repeat > MAX_BLOCK_S and repeat > 1:
            fit = int(MAX_BLOCK_S // (sum(once) + sum(rest_s.values())))
            raise TutorError(f"{repeat} times would take {(sum(once) + sum(rest_s.values())) * repeat:.0f} s; at most {MAX_BLOCK_S:.0f} s fit in one call: repeat up to {max(fit, 1)} times, or raise the tempo.")
        lengths = list(once) + list(rest_s.values())        # every sounding step and every rest, once through
        if sum(lengths) > MAX_BLOCK_S:
            fit, total = 0, 0.0
            for length in lengths:
                if total + length > MAX_BLOCK_S:
                    break
                total, fit = total + length, fit + 1
            raise TutorError(f"this demo would take {sum(lengths):.0f} s; at most {MAX_BLOCK_S:.0f} s fit in one call. Send up to {fit} steps at a time, or raise the tempo.")
        self._begin()
        kb = self.keyboard
        played = 0
        dim = {kb.key(k): ROLES["next"] for step in resolved for k in step.keys} if outline else {}
        try:
            for turn in range(repeat):
                for i, step in enumerate(resolved):
                    if self._cancel.is_set():
                        break
                    if rest_s.get(i):
                        self.lights.show(dim)
                        self._cancel.wait(rest_s[i])
                    keys = [kb.key(k) for k in step.keys]
                    self.lights.show({**dim, **self._hint_colours(step, fingers, told[i])})
                    step_s = once[i]
                    self.client.notes(on=[((k.board, k.key), 80, int(step_s * 900)) for k in keys])
                    played = max(played, i + 1)
                    if progress:
                        progress(turn * len(resolved) + i + 1, len(resolved) * repeat, step.label)
                    self._cancel.wait(step_s)
                if self._cancel.is_set():
                    break
                if rest_s.get(len(resolved)):
                    self.lights.show(dim)
                    self._cancel.wait(rest_s[len(resolved)])
        finally:
            self.lights.clear()
            self._activity.release()
        out = {"played": told[:played], "stopped_early": played < len(resolved) or self._cancel.is_set(),
               "lights": "each key in its finger's colour (finger_light)" if fingers else "the root of a chord orange, its other notes white"}
        if any(k.get("role") == "root" for info in told[:played] for k in info["keys"]):
            out["say"] = SAY_CHORD
        return out

    # --- rhythm ---

    def _drums(self) -> dict[str, Sender]:
        return {name: sender for name, sender in (("mridangam", self.mridangam), ("tabla", self.tabla)) if sender is not None}

    def _sound_of(self, sound: str, tradition: str | None = None) -> str:
        """What sounds: click, mridangam or tabla. "auto" = the drum of the pattern's
        tradition if it is set up, else the click."""
        sound = (sound or "click").strip().lower()
        if sound not in ("click", "mridangam", "tabla", "auto"):
            raise TutorError("sound must be click, mridangam, tabla or auto")
        if sound == "auto":
            return percussion.drum_for(tradition, set(self._drums()))
        if sound == "mridangam" and self.mridangam is None:
            raise TutorError("no mridangam is set up on this machine (start host/synth/mridangam.scd and the tutor with --mridangam); use sound click")
        if sound == "tabla" and self.tabla is None:
            raise TutorError("no tabla is set up on this machine (start host/synth/tabla.scd and the tutor with --tabla); use sound click")
        return sound

    def _beat(self, accent: bool = False, sound: str = "click", stroke: str | None = None) -> None:
        """One beat of the pulse: a click, or a drum stroke (a deep one on the accent)."""
        if sound == "mridangam" and self.mridangam is not None:
            self.mridangam.send("/mridangam/stroke", stroke or ("Thom" if accent else "Thi"), 0.9 if accent else 0.55)
        elif sound == "tabla" and self.tabla is not None:
            self.tabla.send("/tabla/stroke", stroke or percussion.PULSE["tabla"][0 if accent else 1], 0.9 if accent else 0.55)
        else:
            self._click(accent)

    def _click(self, accent: bool = False) -> None:
        """One metronome click: a note on the percussion channel (MIDI channel 10, the wood
        blocks of General MIDI), which the synth plays as a tick and a drum plugin as what
        it likes. With an xentool that cannot do that, the keyboard's highest note, short."""
        if self._click_by_midi:
            try:
                self.client.midi([(CLICK_CHANNEL, CLICK_NOTES[0 if accent else 1], 115 if accent else 75, 40)])
                return
            except (XentoolError, AttributeError):
                self._click_by_midi = False
        key = self.keyboard.range()[1]
        self.client.notes(on=[((key.board, key.key), 115 if accent else 75, 50)])

    def _clicked_take(self, clicks: list[tuple[float, bool]], end: float, progress: Progress | None, label: str,
                      sound: str = "click", extra: list[tuple[float, str, float]] | None = None,
                      strike: Callable[[str | None, float], None] | None = None, silent_from: int | None = None) -> tuple[list[float], list[float]]:
        """Sound the clicks at their times (seconds from now, accent) and collect the taps
        until `end`. Returns the click times and the tap times, both on the same clock."""
        # `extra`: drum strokes at their own times (seconds, name, loudness), merged into the schedule and
        # sounded by `strike` (without it: on the mridangam). `silent_from`: the clicks from this one on
        # are only timed, not sounded (the drum's strokes are the pulse then).
        events = sorted([(at, "beat", accent) for at, accent in clicks] + [(at, name, loud) for at, name, loud in (extra or [])],
                        key=lambda e: e[0])
        self._begin()
        q = self.pump.subscribe()
        taps: list[float] = []
        try:
            if self.pump.error:
                raise TutorError(self.pump.error)
            self.keyboard                   # built now if it was not yet: that takes a second, which must not fall into the count-in
            zero = time.monotonic() + 0.3
            sounded = []
            for n, (at, what, accent) in enumerate(events):
                while True:
                    ev = self._events_until(q, zero + at)
                    if ev is None:
                        break
                    if ev is not False and ev.on:
                        taps.append(ev.t)
                if self._cancel.is_set():
                    raise TutorError("stopped")
                if what == "beat":
                    if silent_from is None or len(sounded) < silent_from:
                        self._beat(bool(accent), sound)
                    sounded.append(zero + at)
                    if progress and (accent or len(clicks) <= 24):
                        progress(len(sounded), len(clicks), label)
                elif strike is not None:
                    strike(what, accent)
                elif self.mridangam is not None:
                    self.mridangam.send("/mridangam/stroke", what, accent)
            while True:
                ev = self._events_until(q, zero + end)
                if ev is None:
                    break
                if ev is not False and ev.on:
                    taps.append(ev.t)
            return sounded, taps
        finally:
            self.pump.unsubscribe(q)
            self._activity.release()
            self._told_until_now()

    def rhythm(self, action: str = "patterns", pattern: str | None = None, tempo_bpm: float = 90, cycles: int = 2,
               level: str = "beginner", onsets: list[int] | None = None, pulses: int | None = None, beats: int | None = None,
               sound: str = "auto", tap: str | None = None, variant: int | None = None, progress: Progress | None = None) -> dict:
        """Rhythm practice with a click or a drum. patterns | calibrate | demo | play | status | reset."""
        action = action.strip().lower()
        if action == "patterns":
            if pattern:
                return self._cycle_detail(pattern)
            sounds = ["click"] + (["mridangam (recorded strokes; also for demo, which plays the pattern itself)"] if self.mridangam else []) \
                + (["tabla (recorded strokes: the theka of a Hindustani tala)"] if self.tabla else [])
            out = {"sounds": sounds, "patterns": {name: {"what": p["what"], "taps_per_cycle": len(p["onsets"]), "clicks_per_cycle": p["beats"]}
                                                  for name, p in rhythm_model.PATTERNS.items() if name not in rhythm_model.LIBRARY},
                   "own": "or give your own: onsets (which of the equal parts get a tap, counted from 0), pulses (how many parts), beats (clicks per cycle)",
                   "how": "rhythm action play with pattern, tempo_bpm, cycles and level; calibrate once before the first take."}
            if rhythm_model.LIBRARY:
                out["cycles"] = self._cycle_lists()
                out["how"] += (" A cycle: action patterns with pattern = its name tells its sections, claps, strokes and how well it is sourced; "
                               "sound auto plays it on its own drum where one is set up; tap = beats, claps or strokes says what the player taps.")
            return out
        if action == "status":
            ms = self.player.offset_ms
            return {"calibrated": ms is not None, **({"offset_ms": round(ms)} if ms is not None else {}),
                    "note": "Timing is judged after taking this offset away." if ms is not None else
                            "Not calibrated: timing results include the equipment's delay. Run rhythm action calibrate once."}
        if action == "reset":
            self.player.set_offset(None)
            return {"calibrated": False}
        if level not in rhythm_model.BANDS:
            raise TutorError(f"level must be one of: {', '.join(rhythm_model.BANDS)}")
        if not 40 <= tempo_bpm <= 200:
            raise TutorError("tempo_bpm must be between 40 and 200")
        self._need_player("rhythm")
        given_sound = sound
        sound = self._sound_of(sound)
        beat_s = 60.0 / tempo_bpm
        if action == "calibrate":
            count = 20
            clicks = [(i * beat_s, i % 4 == 0) for i in range(count)]
            sounded, taps = self._clicked_take(clicks, count * beat_s, progress, "tap along", sound)
            found = rhythm_model.offset_from_taps(sounded, taps)
            if not found:
                raise TutorError(f"heard {len(taps)} taps for {count} clicks, too few to measure. Ask the player to tap any key exactly with "
                                 f"every click, from the fifth click on at the latest, and call this again.")
            offset, spread, used = found
            self.player.set_offset(offset * 1000)
            return {"calibrated": True, "offset_ms": round(offset * 1000), "spread_ms": round(spread * 1000), "taps_used": used,
                    "meaning": ("The player's taps lie this far from the click on this equipment (negative: before it). It is taken away "
                                "from now on. A spread under about 30 ms is steady tapping; above 60 ms repeat the calibration.")}
        if action not in ("play", "demo"):
            raise TutorError("action must be one of: patterns, calibrate, demo, play, status, reset")
        if onsets:
            if not pulses or not beats or not all(isinstance(o, int) and 0 <= o < pulses for o in onsets):
                raise TutorError("an own pattern needs onsets (numbers from 0), pulses (more than every onset) and beats (clicks per cycle)")
            chosen = {"pulses": int(pulses), "beats": int(beats), "onsets": sorted(set(onsets)), "what": "the player's own pattern"}
            name = "own pattern"
        else:
            found = rhythm_model.find(pattern or "")
            if not found:
                near = rhythm_model.close_names(pattern or "") or ([] if rhythm_model.LIBRARY else list(rhythm_model.PATTERNS))
                raise TutorError(f"no pattern '{pattern}'. " + (f"Close: {', '.join(near)}. " if near else "") +
                                 "rhythm action patterns lists them; or give onsets, pulses and beats.")
            name, chosen = found
        try:
            if variant:
                chosen = rhythm_model.variant_of(chosen, int(variant))
            tapped = {**chosen, "onsets": rhythm_model.tap_onsets(chosen, (tap or "").strip().lower() or None)}
        except ValueError as e:
            raise TutorError(f"{name}: {e}") from None
        if not tapped["onsets"]:
            raise TutorError(f"{name} has nothing to tap with tap = {tap}; use beats")
        tradition = chosen.get("tradition")
        sound = self._sound_of(given_sound, tradition)
        cycles = max(1, min(int(cycles), 16))
        per_cycle = chosen["beats"]
        lead = 4 if per_cycle % 4 == 0 or per_cycle > 8 else per_cycle       # the count-in
        total_beats = lead + cycles * per_cycle
        if total_beats * beat_s > MAX_BLOCK_S:
            raise TutorError(f"this would take {total_beats * beat_s:.0f} s; at most {MAX_BLOCK_S:.0f} s fit in one call. Fewer cycles or a faster tempo.")
        accents = set(chosen.get("accents", [0]))
        clicks = [(i * beat_s, i == 0) for i in range(lead)] + \
                 [((lead + c * per_cycle + b) * beat_s, b in accents) for c in range(cycles) for b in range(per_cycle)]
        pulse = per_cycle * beat_s / chosen["pulses"]
        end = total_beats * beat_s + beat_s / 2
        # the cycle's own strokes (a theka's bols, a lesson's strokes, an usul's dum and tek) on the drum that has them
        own = sound != "click" and bool(chosen.get("strokes")) and percussion.plays_own_strokes(sound, tradition)
        closing = chosen.get("ending")              # a lesson's last stroke, on the first beat after the last round
        own_strokes = [((lead + c * per_cycle) * beat_s + s["at"] * pulse, s["stroke"], s.get("loud", 0.7)) for c in range(cycles) for s in chosen.get("strokes", [])] \
            + ([(total_beats * beat_s, closing["stroke"], closing.get("loud", 0.9))] if closing else [])

        def strike(stroke: str | None, loud: float) -> None:
            sent = percussion.stroke_on(sound, tradition, stroke) if own else stroke
            if sent is None:                # a stroke the sources do not name
                self._click(False)
            else:
                self._drums()[sound].send(percussion.ADDRESS[sound], sent, loud)

        notes = self._cycle_notes(chosen, sound, own) if tradition else {}
        if action == "demo":
            # the pattern itself, played for the player to hear
            if own:
                self._clicked_take(clicks[:lead], end, progress, name, "click", own_strokes, strike)
            elif sound != "click":
                # a drum without strokes for this pattern: its taps as strokes, the first of a cycle (and a tala's claps) deep
                first, on_beat, between = percussion.GENERIC[sound]
                deep = (accents if tradition else set()) | {0}
                strokes = [((lead + c * per_cycle) * beat_s + o * pulse, first if o in deep else between if (o * per_cycle) % chosen["pulses"] else on_beat,
                            0.95 if o == 0 else 0.75) for c in range(cycles) for o in chosen["onsets"]]
                self._clicked_take(clicks[:lead], end, progress, name, "click", strokes, strike)
            elif tradition:
                # clicks only: every stroke of the cycle (or every beat), the claps accented
                at = sorted({s["at"] for s in chosen.get("strokes", [])}) or chosen["onsets"]
                self._clicked_take(clicks[:lead] + [((lead + c * per_cycle) * beat_s + o * pulse, o in accents or o == 0) for c in range(cycles) for o in at]
                                   + ([(total_beats * beat_s, True)] if closing else []), end, progress, name)
            else:
                # with clicks only: the pattern as accented clicks, no separate pulse after the count-in
                self._clicked_take(clicks[:lead] + [((lead + c * per_cycle) * beat_s + o * pulse, True) for c in range(cycles) for o in chosen["onsets"]],
                                   end, progress, name)
            return {"demonstrated": name, "what": chosen["what"], "tempo_bpm": tempo_bpm, "cycles": cycles, "sound": sound, **notes,
                    "note": "Now let the player try it: rhythm action play with the same pattern and tempo."}
        if own:
            # the count-in as clicks, then the drum's strokes are the pulse
            sounded, taps = self._clicked_take(clicks, end, progress, name, "click", own_strokes, strike, silent_from=lead)
        else:
            sounded, taps = self._clicked_take(clicks, end, progress, name, sound)
        start = sounded[lead] if len(sounded) > lead else sounded[0] + lead * beat_s
        due = rhythm_model.targets(tapped, cycles, start, beat_s)
        offset = (self.player.offset_ms or 0.0) / 1000
        judged = rhythm_model.grade(due, [t for t in taps if t > start - beat_s / 2], offset, level)
        errors = judged.pop("errors_ms")
        per = len(tapped["onsets"])
        worst = sorted(((abs(e) if e is not None else 9999, i) for i, e in enumerate(errors)), reverse=True)[:3]
        out = {"pattern": name, "what": chosen["what"], "tempo_bpm": tempo_bpm, "cycles": cycles, "level": level,
               **({"sound": sound, "tapped": tap or ("the strokes" if chosen.get("kind") in ("usul", "lesson") else "every beat"), **notes} if tradition else {}),
               **judged,
               "weakest": [f"cycle {i // per + 1}, tap {i % per + 1}: " + ("missed" if errors[i] is None else f"{errors[i]:+d} ms") for _, i in worst
                           if errors[i] is None or abs(errors[i]) > rhythm_model.BANDS[level][0]],
               "bands_ms": dict(zip(rhythm_model.GRADES, rhythm_model.BANDS[level]))}
        if self.player.offset_ms is None:
            out["not_calibrated"] = "The mean includes the equipment's delay; run rhythm action calibrate once and repeat."
        out["what_now"] = ("Say how it went in plain words: together with the click or not, early or late, steady or not, and the one tap "
                           "to watch. Negative numbers are early. Then repeat, slower if more than a few were missed.")
        return out

    # --- cycles of the rhythm library (talas with their theka, mridangam lessons, usul) ---

    CYCLE_KINDS = {"theka": "hindustani_talas", "tala": "carnatic_talas", "lesson": "mridangam_lessons", "usul": "usul"}

    def _cycle_lists(self) -> dict:
        """Every cycle of the library by kind and by how well it is sourced: name and length."""
        out: dict[str, dict] = {}
        for key, cycle in rhythm_model.LIBRARY.items():
            group = out.setdefault(self.CYCLE_KINDS.get(cycle.get("kind"), "other"), {"count": 0})
            group["count"] += 1
            group.setdefault(cycle.get("confidence", "?"), []).append(f"{key} {cycle['beats']}")
        for group in out.values():
            for confidence, names in group.items():
                if isinstance(names, list):
                    group[confidence] = ", ".join(names)
        out["read"] = ("name and beats per cycle, under how well the sources agree. Hindustani talas carry their theka (the tabla's syllables), "
                       "Carnatic talas their hand gestures, usul (the cycles of Turkish makam music) their dum and tek.")
        return out

    @staticmethod
    def _strokes_line(strokes: list[dict], start: float, length: float, unit: bool) -> str:
        """The strokes of a section as they are said: one word per beat, "-" a silent
        beat, several syllables in one beat run together (`unit`); else stroke(length)."""
        inside = [s for s in strokes if start <= s["at"] < start + length]
        if not unit:
            return " ".join((s.get("say") or s["stroke"] or "?") + (f"({s['dur']:g})" if s.get("dur", 1) != 1 else "") for s in inside)
        words = []
        for beat in range(int(start), int(start + length)):
            here = [s for s in inside if beat <= s["at"] < beat + 1]
            if not here:
                words.append("-")
                continue
            parts = round(1 / min(s.get("dur", 1) for s in here))
            slots = ["-"] * max(parts, 1)
            for s in here:
                slots[min(int(round((s["at"] - beat) * parts)), len(slots) - 1)] = s.get("say") or s["stroke"] or "?"
            words.append("".join(slots))
        return " ".join(words)

    def _cycle_notes(self, cycle: dict, sound: str, own: bool) -> dict:
        """What to tell with a cycle: how well it is sourced, and what the sound stands for."""
        out = {"tradition": cycle["tradition"], "confidence": cycle.get("confidence", "")}
        if cycle.get("variant"):
            out["variant"] = cycle["variant"]
        if cycle.get("conflict"):
            out["sources_disagree"] = cycle["conflict"]
        if cycle.get("unnamed_strokes"):
            out["unnamed_strokes"] = cycle["unnamed_strokes"] + "; they sound as a plain click"
        tradition = cycle["tradition"]
        if own and tradition == "makam":
            table = percussion.USUL_ON_TABLA if sound == "tabla" else percussion.USUL_ON_MRIDANGAM
            out["sound_note"] = percussion.USUL_NOTE.format(drum="the " + sound, dum=table["dum"], tek=table["tek"])
        elif own and tradition == "hindustani":
            table = rhythm_model.INFO.get("tabla_bols", {})
            bols = list(dict.fromkeys(s["stroke"] for s in cycle["strokes"] if s["stroke"]))
            made = [table[b]["note"] for b in bols if b in table and table[b]["how"] != "recorded" and table[b].get("note")]
            silent = [b for b in bols if b not in table]
            if made or silent:
                out["sound_note"] = "; ".join(made + ([f"no sound for {', '.join(silent)}"] if silent else []))
        elif sound != "click" and not own:
            out["sound_note"] = (f"no strokes are given for this cycle on the {sound}: the first beat and the claps sound deep, the other beats light "
                                 "(this project's choice, not a traditional accompaniment)")
        elif sound == "click" and percussion.DRUMS.get(tradition):
            out["sound_note"] = f"played as clicks: no {' or '.join(percussion.DRUMS[tradition])} is set up on this machine"
        return out

    def _cycle_detail(self, name: str) -> dict:
        found = rhythm_model.find(name)
        if not found:
            near = rhythm_model.close_names(name)
            raise TutorError(f"no pattern '{name}'. " + (f"Close: {', '.join(near)}. " if near else "") + "rhythm action patterns lists them.")
        key, cycle = found
        out: dict = {"pattern": key, "what": cycle["what"]}
        tradition = cycle.get("tradition")
        if not tradition:
            out.update(taps_per_cycle=len(cycle["onsets"]), clicks_per_cycle=cycle["beats"])
            return out
        kind = cycle.get("kind")
        unit = kind != "usul"
        word = {"theka": "matras", "usul": "pulses"}.get(kind, "beats")

        def sections(c: dict) -> list[str]:
            lines = []
            for s in c.get("sections", []):
                first, last = s["at"] + 1, s["at"] + s["length"]
                line = f"{word} {first}-{last}" if last > first else f"{word[:-1]} {first}"
                if s.get("gesture"):
                    line += f", {s['gesture']} ({s['name']})"
                elif s.get("name") not in (None, "group", "round"):
                    line += f" ({s['name']})"
                if s.get("gestures"):
                    line += ": " + ", ".join(g or "no gesture" for g in s["gestures"])
                said = self._strokes_line(c.get("strokes", []), s["at"], s["length"], unit)
                lines.append(line + (": " + said if said.strip("- ") else ""))
            return lines

        out.update(name=cycle["name"], tradition=tradition, **{word: cycle["beats"]})
        if cycle.get("aliases"):
            out["also_called"] = cycle["aliases"]
        out["sections"] = sections(cycle)
        if cycle.get("ending"):
            out["ends_on"] = f"{cycle['ending']['say']}, on the first beat after the last round"
        out["confidence"] = cycle.get("confidence", "")
        if cycle.get("conflict"):
            out["sources_disagree"] = cycle["conflict"]
        elif cycle.get("agreement"):
            out["sources_say"] = cycle["agreement"]
        if cycle.get("unnamed_strokes"):
            out["unnamed_strokes"] = cycle["unnamed_strokes"]
        variants, n = [], 0
        for v in cycle.get("variants", []):
            entry = {"name": v["name"]}
            if v.get("strokes"):
                n += 1
                whole = {**cycle, **{k: x for k, x in v.items() if k not in ("name", "source", "note")}}
                entry.update(variant=n, sections=sections(whole))
            elif v.get("gestures"):
                entry["gestures"] = ", ".join(g or "no gesture" for g in v["gestures"])
            if v.get("note"):
                entry["note"] = v["note"]
            if v.get("source"):
                entry["source"] = v["source"]
            variants.append(entry)
        if variants:
            out["variants"] = variants
        drum = percussion.drum_for(tradition, set(self._drums()))
        own = drum != "click" and bool(cycle.get("strokes")) and percussion.plays_own_strokes(drum, tradition)
        out["sound"] = {"auto": drum, **{k: v for k, v in self._cycle_notes(cycle, drum, own).items() if k in ("sound_note", "unnamed_strokes")}}
        out["sources"] = cycle.get("sources", [])
        out["how"] = ("rhythm action demo with this pattern lets the player hear it; action play judges their taps: tap = beats (every "
                      f"{word[:-1]}), claps (only the claps" + (" = the starts of the groups" if kind == "usul" else "") + ") or strokes"
                      + ("; variant = the number of a variant" if n else "") + ". tempo_bpm counts the " + word + ".")
        return out

    # --- drone ---

    def _tanpura(self, raga: dict, sa_pitch: int) -> tuple[list[int], dict]:
        """The four strings of the drone for a raga, in the order they are struck, as
        pitches around this Sa; and the rule that chose the tuning."""
        t = self.keyboard.tuning
        rule = lib.drone_tuning(raga)
        steps_of = lib.swara_steps(raga, t.edo)
        first = [sa_pitch - t.edo + steps_of[rule["first"]][0]] if rule["first"] else [sa_pitch - t.edo]
        return first + [sa_pitch, sa_pitch, sa_pitch - t.edo], rule

    def _tanpura_words(self, raga: dict, sa_pitch: int) -> dict:
        t = self.keyboard.tuning
        pitches, rule = self._tanpura(raga, sa_pitch)
        out = {"tuning": rule["tuning"], "strings": [t.label(p) for p in pitches], "rule": rule["rule"]}
        if rule.get("sources_disagree"):
            out["sources_disagree"] = rule["sources_disagree"]
        out["sound_it"] = "drone action start with raga and root holds these notes, struck in this order round and round, until drone action stop"
        return out

    def _drone_end(self) -> bool:
        drone, self._drone = self._drone, None
        if not drone:
            return False
        if drone[0] is None:            # sounding on the tanpura patch, which strikes the strings itself
            if self.tanpura is not None:
                self.tanpura.send("/tanpura/stop")
            return True
        drone[1].set()
        if drone[0] is not threading.current_thread():
            drone[0].join(timeout=2.0)
        return True

    def _drone_run(self, keys: list[Key], pace_s: float, loudness: int, stop: threading.Event) -> None:
        """Strike the strings one after the other, each ringing on until its next turn."""
        hold_ms = int(pace_s * len(keys) * 1150)
        try:
            while not stop.is_set():
                for key in keys:
                    try:
                        self.client.notes(on=[((key.board, key.key), loudness, hold_ms)])
                    except Exception:           # a keyboard that is away for a moment must not end the drone
                        pass
                    if stop.wait(pace_s):
                        break
        finally:
            try:
                self.client.notes(off=list(dict.fromkeys((k.board, k.key) for k in keys)))
            except Exception:
                pass

    def drone(self, action: str = "status", raga: str | None = None, root: str | None = None, notes: list[str] | None = None,
              pace_s: float = 1.0, octave: int = 0, loudness: int = 50) -> dict:
        """A drone under the playing: start | stop | status. It runs beside every other
        tool. Where a tanpura patch is set up it sounds there, apart from the keyboard's
        instrument, so no key the player presses can cut a string; only without one it
        falls back to held notes of the keyboard's own sound."""
        action = action.strip().lower()
        if action == "stop":
            return {"drone": "stopped" if self._drone_end() else "none was sounding"}
        if action == "status":
            alive = self._drone if self._drone and (self._drone[0] is None or self._drone[0].is_alive()) else None
            return {"drone": "sounding", **alive[2]} if alive else {"drone": "silent", "how": "drone action start with raga (and root = where Sa lies), or with notes"}
        if action != "start":
            raise TutorError("action must be one of: start, stop, status")
        self._need_player("drone")
        if not 0.3 <= pace_s <= 5:
            raise TutorError("pace_s (seconds from one string to the next) must be between 0.3 and 5")
        kb = self.keyboard
        t = kb.tuning
        told: dict = {}
        if notes:
            pitches = [self._pitch(n)[0] for n in notes]
            told["rule"] = "the notes that were given, in this order"
        else:
            sa_pitch, _ = self._pitch(root or "C")
            if raga:
                found = lib.find_raga(raga)
                if not found:
                    raise TutorError(f"no raga '{raga}' in the library. Available: {', '.join(lib.raga_names())}. Or give notes.")
                pitches, rule = self._tanpura(found[1], sa_pitch)
                told.update(raga=found[0], tuning=rule["tuning"], rule=rule["rule"])
                if rule.get("sources_disagree"):
                    told["sources_disagree"] = rule["sources_disagree"]
            else:
                pitches = [sa_pitch - t.edo + t.steps_for(3 / 2), sa_pitch, sa_pitch, sa_pitch - t.edo]
                told.update(tuning="Pa-Sa-Sa-Sa", rule="the usual tuning (no raga was named): the fifth below Sa, Sa twice, the low Sa")
        if self.tanpura is not None:
            # its own instrument: any pitch of the tuning, whether the keyboard has a key for it or not
            pitches = [p + int(octave) * t.edo for p in pitches]
            self._drone_end()
            told = {"strings": [t.label(p) for p in pitches], **told, "sound": "tanpura",
                    "pace": f"one string every {pace_s:g} s, round and round, until drone action stop (stop ends it too)"}
            self.tanpura.send("/tanpura/start", float(pace_s), max(1, min(int(loudness), 127)) / 127.0, *[float(t.hz(p)) for p in pitches])
            self._drone = (None, None, told)
            return {"drone": "sounding", **told,
                    "note": "A tanpura of its own, apart from the keyboard's sound: the player can play any key over it. "
                            "Lower loudness if it covers the playing."}
        keys, moved, missing = [], [], []
        for pitch in pitches:
            pitch += int(octave) * t.edo
            at = next((p for p in (pitch, pitch + t.edo, pitch - t.edo) if kb.keys_for_pitch(p)), None)
            if at is None:
                missing.append(t.label(pitch))
                continue
            if at != pitch:
                moved.append(f"{t.label(pitch)} sounds as {t.label(at)}")
            keys.append(kb.keys_for_pitch(at)[0])
        if not keys:
            raise TutorError(f"this keyboard has none of the drone's notes ({', '.join(missing)}); give another root or octave")
        self._drone_end()
        stop = threading.Event()
        told = {"strings": [t.label(k.pitch) for k in keys], **told,
                "pace": f"one string every {pace_s:g} s, round and round, until drone action stop (stop ends it too)"}
        if moved:
            told["moved_an_octave"] = moved
        if missing:
            told["not_on_this_keyboard"] = missing
        thread = threading.Thread(target=self._drone_run, args=(keys, float(pace_s), max(1, min(int(loudness), 127)), stop), name="tutor-drone", daemon=True)
        self._drone = (thread, stop, told)
        thread.start()
        return {"drone": "sounding", **told,
                "sound": "keyboard",
                "note": "No tanpura is set up on this machine, so these are held notes of the keyboard's own sound: a key of the drone that the "
                        "player presses is cut until its next strike. Tell the player; octave -1 keeps it out of the way."}

    # --- improvising ---

    def improvise(self, changes: list[dict], rule: str = "free", allowed: list[str] | None = None, tempo_bpm: float = 90,
                  backing: str = "chords", count_in: int = 4, choruses: int = 1, lights: bool = True,
                  click: bool = True, sound: str = "click", progress: Progress | None = None) -> dict:
        """The player improvises over chord changes while the server keeps time: it sounds
        a backing, lights the notes of the current chord, records what is played against
        which chord, and checks one simple rule."""
        self._need_player("improvise")
        kb = self.keyboard
        t = kb.tuning
        edo = t.edo
        rules = ("free", "only", "chord_tones", "chord_tone_first", "guide_tone_first")
        if rule not in rules:
            raise TutorError(f"rule must be one of: {', '.join(rules)}")
        if backing not in ("chords", "roots", "drone", "none"):
            raise TutorError("backing must be one of: chords, roots, drone, none")
        if not changes:
            raise TutorError("changes is empty; give chord steps, for example a section from the library")
        if not 30 <= tempo_bpm <= 240:
            raise TutorError("tempo_bpm must be between 30 and 240")
        if rule == "only" and not allowed:
            raise TutorError("rule only needs allowed: the notes that may be played (in any octave)")
        sound = self._sound_of(sound)
        allowed_pcs = {self._pitch(n)[0] % edo for n in allowed or []}
        beat_s = 60.0 / tempo_bpm
        chords = []
        for i, raw in enumerate(changes, 1):
            if isinstance(raw, dict) and raw.get("rest"):
                if chords:
                    chords[-1]["beats"] += float(raw.get("beats", 1))
                continue
            names = raw.get("notes") or ([raw["note"]] if isinstance(raw, dict) and raw.get("note") else None)
            if not isinstance(raw, dict) or not names:
                raise TutorError(f"change {i} needs notes (the chord); take the steps from library get, or write {{\"notes\": [...], \"beats\": 4}}")
            voiced = [self._pitch(n)[0] for n in names]
            tones = [self._pitch(n)[0] for n in raw.get("tones") or names]
            root = self._pitch(raw["root"])[0] if raw.get("root") else tones[0]
            chords.append({
                "label": raw.get("label") or " ".join(t.name(p) for p in voiced), "beats": float(raw.get("beats", 4)),
                "keys": [kb.keys_for_pitch(p)[0] for p in voiced if p in kb._by_pitch],
                "pcs": {p % edo for p in tones}, "root_pc": root % edo,
                "guide_pcs": {tones[1] % edo, tones[-1] % edo} if len(tones) >= 3 else {p % edo for p in tones},
            })
        choruses = max(1, min(int(choruses), 8))
        form = chords * choruses
        total = sum(c["beats"] for c in form) * beat_s + max(0, int(count_in)) * beat_s
        if total > IMPROVISE_MAX_S:
            raise TutorError(f"this would take {total:.0f} s; at most {IMPROVISE_MAX_S:.0f} s fit in one call. Fewer choruses, a faster tempo, or one section at a time.")

        def chord_lights(chord: dict) -> dict[Key, Rgb]:
            return {k: ROLES["root"] if k.pitch % edo == chord["root_pc"] else ROLES["next"]
                    for k in kb.keys.values() if k.pitch % edo in chord["pcs"]}

        self._begin()
        q = self.pump.subscribe()
        takes: list[list[tuple[float, int]]] = [[] for _ in form]     # per chord: (seconds after its start, pitch)
        stopped = False
        try:
            if self.pump.error:
                raise TutorError(self.pump.error)
            first = form[0]
            for n in range(max(0, int(count_in))):       # the count-in
                if self._cancel.is_set():
                    break
                self._beat(n == 0, sound)
                if progress:
                    progress(n + 1, count_in, "count-in")
                self._cancel.wait(beat_s)
            while True:                                   # what was pressed during the count-in does not count
                try:
                    q.get_nowait()
                except queue.Empty:
                    break
            start = time.monotonic()
            if backing == "drone" and not self._cancel.is_set():
                drone = list(first["keys"][:1])         # the first root with the fifth above it
                if drone:
                    drone += kb.keys_for_pitch(drone[0].pitch + t.steps_for(3 / 2))[:1]
                self.client.notes(on=[((k.board, k.key), 55, int((total - max(0, int(count_in)) * beat_s) * 1000)) for k in drone])
            at = start
            beat_count, bar_start = 0.0, True
            for i, chord in enumerate(form):
                if self._cancel.is_set():
                    stopped = True
                    break
                length = chord["beats"] * beat_s
                if backing in ("chords", "roots"):
                    sound = chord["keys"] if backing == "chords" else chord["keys"][:1]
                    self.client.notes(on=[((k.board, k.key), 55, int(length * 900)) for k in sound])
                if lights:
                    self.lights.show(chord_lights(chord))
                if progress:
                    progress(i + 1, len(form), chord["label"])
                beats_here = max(1, round(chord["beats"])) if click else 1
                for b in range(beats_here):
                    if click and b:
                        self._beat(False, sound)
                    elif click:
                        self._beat(i == 0 or bar_start, sound)
                    until = at + (length * (b + 1) / beats_here)
                    while True:
                        ev = self._events_until(q, until)
                        if ev is None:
                            break
                        if ev is not False and ev.on:
                            takes[i].append((ev.t - at, ev.pitch))
                    if self._cancel.is_set():
                        break
                beat_count += chord["beats"]
                bar_start = abs(beat_count % 4) < 1e-6
                at += length
            stopped = stopped or self._cancel.is_set()
        finally:
            self.pump.unsubscribe(q)
            self.lights.clear()
            self._activity.release()
            self._told_until_now()

        offset = (self.player.offset_ms or 0.0) / 1000
        absolute, at = [], 0.0
        for chord, take in zip(form, takes):
            absolute.extend(at + seconds for seconds, _ in take)
            at += chord["beats"] * beat_s
        timing = rhythm_model.grid_stats(absolute, beat_s / 2, offset)
        report = []
        notes_total = tone_total = first_ok = first_seen = outside = silent = 0
        for chord, take in zip(form, takes):
            pitches = [p for _, p in take]
            in_chord = sum(1 for p in pitches if p % edo in chord["pcs"])
            entry: dict = {"chord": chord["label"], "played": [t.label(p) for p in pitches][:16]}
            if pitches:
                entry["chord_tones"] = f"{in_chord} of {len(pitches)}"
                first_pitch = pitches[0]
                kind = ("root" if first_pitch % edo == chord["root_pc"] else "third or seventh" if first_pitch % edo in chord["guide_pcs"]
                        else "chord tone" if first_pitch % edo in chord["pcs"] else "not in the chord")
                entry["first_note"] = f"{t.label(first_pitch)}: {kind}"
                first_seen += 1
                wanted = chord["guide_pcs"] if rule == "guide_tone_first" else chord["pcs"]
                if first_pitch % edo in wanted:
                    first_ok += 1
                if rule == "only":
                    strangers = [t.label(p) for p in pitches if p % edo not in allowed_pcs]
                    if strangers:
                        entry["not_allowed"] = list(dict.fromkeys(strangers))
                        outside += len(strangers)
                if rule == "chord_tones":
                    strangers = [t.label(p) for p in pitches if p % edo not in chord["pcs"]]
                    if strangers:
                        entry["not_in_chord"] = list(dict.fromkeys(strangers))
                        outside += len(strangers)
            else:
                entry["played"] = "nothing"
                silent += 1
            notes_total += len(pitches)
            tone_total += in_chord
            report.append(entry)
        out: dict = {
            "outcome": "stopped" if stopped else "finished", "rule": rule, "tempo_bpm": tempo_bpm,
            "notes_played": notes_total, "chords": len(form), "chords_left_silent": silent,
            "chord_tone_share_percent": round(100 * tone_total / notes_total) if notes_total else 0,
        }
        if rule in ("chord_tone_first", "guide_tone_first"):
            out["rule_met"] = f"{first_ok} of {first_seen} chords started on a {'third or seventh' if rule == 'guide_tone_first' else 'chord tone'}"
        elif rule in ("only", "chord_tones"):
            out["rule_met"] = "yes" if not outside else f"no: {outside} notes outside"
        if timing:
            timing["against"] = "even half beats" + ("" if self.player.offset_ms is not None else
                                                      "; not calibrated (rhythm action calibrate), so the mean includes the equipment's delay")
            out["timing"] = timing
        out["per_chord"] = report
        out["what_now"] = ("Respond to the music first, then to the rule: name one thing that worked (a note that landed, a rest, a shape) "
                           "and one thing to try next. Silence is part of a solo, not a mistake."
                           if notes_total else "Nothing was played. Ask whether the task was clear, play an example with demo, and try again slower.")
        return out

    # --- listening ---

    def _remember(self) -> None:
        while not self.pump._stop.is_set():
            try:
                ev = self._memory_q.get(timeout=0.5)
            except queue.Empty:
                continue
            now = time.monotonic()
            try:
                key = self.keyboard.at_address(ev["board"], ev["key"])
            except Exception:
                key = None      # no keyboard just now; the event cannot be named
            if key is None:
                continue
            with self._memory_lock:
                if ev["kind"] == "on":
                    note = {"key": key.id, "pitch": key.pitch, "start": now, "end": None}
                    self._memory_down[key.id] = note
                    self._memory.append(note)
                elif key.id in self._memory_down:
                    self._memory_down.pop(key.id)["end"] = now

    def _told_until_now(self) -> None:
        self._checked = time.monotonic()

    def unheard(self) -> int:
        """How many notes the player has struck that no tool result has reported yet."""
        with self._memory_lock:
            return sum(1 for n in self._memory if n["start"] > self._checked)

    def _summary(self, notes: list[dict], end: float) -> list[dict]:
        """Notes in order, those struck together as one entry with the chord they make."""
        kb = self.keyboard
        first = notes[0]["start"]
        groups: list[list[dict]] = []
        for n in notes:
            if groups and n["start"] - groups[-1][0]["start"] <= CHORD_WINDOW_S:
                groups[-1].append(n)
            else:
                groups.append([n])
        played = []
        for g in groups:
            entry: dict = {
                "at_s": round(g[0]["start"] - first, 2),
                "held_s": round(max((n["end"] or end) for n in g) - g[0]["start"], 2),
                "keys": [self._key_brief(kb.key(n["key"])) for n in sorted(g, key=lambda n: n["pitch"])],
            }
            if len(g) > 1:
                ident = self._identify([n["pitch"] for n in g])
                entry["together"] = ident.get("chord") or ident.get("as_played") or "no common name"
                if "as_played" in ident and "chord" in ident:
                    entry["also_called"] = ident["as_played"]
            played.append(entry)
        return played

    def played(self, seconds: float | None = None) -> dict:
        """What the player has played since the model was last told (or in the last
        `seconds`), whether or not a tool was waiting for it. Returns at once."""
        self._need_player("played")
        kb = self.keyboard
        now = time.monotonic()
        if seconds is not None and not 0 < float(seconds) <= MEMORY_S:
            raise TutorError(f"seconds must be between 1 and {MEMORY_S:.0f}; leave it out for everything since you last checked")
        since = now - float(seconds) if seconds is not None else max(self._checked, now - MEMORY_S)
        with self._memory_lock:
            # keys of a module that has been unplugged since can no longer be named
            notes = [dict(n) for n in self._memory if n["start"] > since and n["key"] in kb.keys]
            held = sorted(self._memory_down)
        self._checked = now
        window = f"the last {now - since:.0f} seconds"
        if not notes:
            return {"played": [], "message": f"nothing was played in {window}"}
        entries = self._summary(notes, now)
        out: dict = {"window": window, "note_count": len(notes),
                     "first_note_s_ago": round(now - notes[0]["start"], 1),
                     "last_note_s_ago": round(now - notes[-1]["start"], 1)}
        if len(entries) > PLAYED_ENTRIES:
            out["earlier_left_out"] = f"{len(entries) - PLAYED_ENTRIES} earlier entries; ask with seconds for a shorter stretch"
            entries = entries[-PLAYED_ENTRIES:]
        out["played"] = entries
        out["still_held"] = [self._key_brief(kb.key(k)) for k in held if k in {n["key"] for n in notes}]
        return out

    def _events_until(self, q: queue.Queue, deadline: float):
        """Next key event as a Press, or None at the deadline or when stopped."""
        kb = self.keyboard
        while not self._cancel.is_set():
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            try:
                ev = q.get(timeout=min(left, 0.05))
            except queue.Empty:
                return False    # nothing yet; lets the caller tick
            key = kb.at_address(ev["board"], ev["key"])
            if key is None:
                continue
            return Press(t=time.monotonic(), key=key.id, pitch=key.pitch, on=ev["kind"] == "on")
        return None

    def _held_now(self) -> dict[str, int]:
        kb = self.keyboard
        held = {}
        for board, key in self.client.held():
            k = kb.at_address(board, key)
            if k:
                held[k.id] = k.pitch
        return held

    def listen(self, max_seconds: float = 20, stop_after_silence: float = 2.0, progress: Progress | None = None) -> dict:
        """Capture what the player plays: until they have played something and then kept
        quiet for `stop_after_silence` seconds, or until `max_seconds`."""
        self._need_player("listen")
        max_seconds = max(1.0, min(float(max_seconds), MAX_BLOCK_S))
        kb = self.keyboard
        t = kb.tuning
        self._begin()
        q = self.pump.subscribe()
        notes: list[dict] = []      # {key, pitch, start, end}
        down: dict[str, dict] = {}
        start = time.monotonic()
        last_activity: float | None = None
        try:
            if self.pump.error:
                raise TutorError(self.pump.error)
            while True:
                now = time.monotonic()
                if last_activity is not None and not down and now - last_activity >= stop_after_silence:
                    break
                ev = self._events_until(q, start + max_seconds)
                if ev is None:
                    break
                if ev is False:
                    continue
                last_activity = ev.t
                if ev.on:
                    note = {"key": ev.key, "pitch": ev.pitch, "start": ev.t, "end": None}
                    down[ev.key] = note
                    notes.append(note)
                    if progress:
                        progress(len(notes), 0, t.name(ev.pitch))
                elif ev.key in down:
                    down.pop(ev.key)["end"] = ev.t
        finally:
            self.pump.unsubscribe(q)
            self._activity.release()
        end = time.monotonic()
        self._told_until_now()
        if not notes:
            return {"played": [], "message": f"nothing was played in {end - start:.0f} seconds"}
        first = notes[0]["start"]
        played = self._summary(notes, end)
        return {"played": played, "note_count": len(notes), "length_s": round(end - first, 1), "still_held": sorted(down)}

    # --- exercise ---

    def run_exercise(self, steps: list[dict] | None = None, hints: str = "always", hint_delay_s: float = 4.0,
                     exact_keys: bool = False, max_extra: int = 0, timeout_s: float = 45, start_at: int = 1,
                     hand: str = "right", fingers: bool = False, pause_s: float = PAUSE_S,
                     progress: Progress | None = None) -> dict:
        """Wait mode: light each step's keys (per `hints`), wait until the player plays it,
        show right and wrong presses, go on. Returns when all steps are done, the time
        limit is reached, `stop` is called, or the player has tried a step and then stopped:
        something played in the step, all keys let go, and `pause_s` of silence (0 = never).
        Looking for the first key of a step never counts as a pause. `steps` None repeats
        the last exercise."""
        self._need_player("run_exercise")
        kb = self.keyboard
        t = kb.tuning
        if steps is None:
            if self._last_steps is None:
                raise TutorError("there is no earlier exercise to continue; give steps")
            resolved, told = self._last_steps
        else:
            resolved, told = self._resolve_steps(steps, hand, exact_keys)
            self._last_steps = (resolved, told)
        if not 1 <= start_at <= len(resolved):
            raise TutorError(f"start_at must be between 1 and {len(resolved)}")
        timeout_s = max(1.0, min(float(timeout_s), MAX_BLOCK_S))
        try:
            ex = Exercise(resolved, hints=hints, hint_delay_s=hint_delay_s, max_extra=max_extra)
        except ValueError as e:
            raise TutorError(str(e)) from e
        self._begin()
        q = self.pump.subscribe()
        hint: dict[Key, Rgb] = {}
        marks: dict[Key, Rgb] = {}

        def apply(actions: list) -> None:
            nonlocal hint
            for a in actions:
                if isinstance(a, ShowHint):
                    hint = self._hint_colours(resolved[a.step], fingers, told[a.step])
                elif isinstance(a, Mark):
                    marks[kb.key(a.key)] = ROLES["correct" if a.correct else "wrong"]
                elif isinstance(a, Unmark):
                    marks.pop(kb.key(a.key), None)
                elif isinstance(a, StepDone):
                    hint = {}
                    if progress:
                        progress(a.step + 1, len(resolved), f"{resolved[a.step].label}: done")
                elif isinstance(a, Finished):
                    hint = {}
            self.lights.show({**hint, **marks})

        started = time.monotonic()
        outcome = "finished"
        pause_s = max(0.0, float(pause_s))
        tried: list[int] = []       # what was pressed in the current step, in order
        down: set[str] = set()
        last_activity = started
        try:
            if self.pump.error:
                raise TutorError(self.pump.error)
            apply(ex.start_at(start_at - 1, started, self._held_now()))
            while not ex.finished:
                ev = self._events_until(q, started + timeout_s)
                if ev is None:
                    outcome = "stopped" if self._cancel.is_set() else "time limit"
                    ex.stop(time.monotonic(), "stopped" if self._cancel.is_set() else "timed out")
                    break
                if ev is False:
                    now = time.monotonic()
                    if pause_s and tried and not down and now - last_activity >= pause_s:
                        outcome = "player paused"
                        ex.stop(now, "tried, then paused")
                        break
                    apply(ex.tick(now))
                    continue
                last_activity = ev.t
                if ev.on:
                    down.add(ev.key)
                    tried.append(ev.pitch)
                else:
                    down.discard(ev.key)
                at = ex.index
                apply(ex.feed(ev))
                if ex.index != at:
                    tried = []      # that step is done; the next one starts fresh
        finally:
            self.pump.unsubscribe(q)
            self.lights.clear()
            self._activity.release()
            self._told_until_now()      # what was played in the exercise is judged in its result

        report = []
        for i, (r, info) in enumerate(zip(ex.results, told)):
            if i < start_at - 1:
                continue
            entry: dict = {"step": i + 1, "asked": r.label, "result": r.status}
            if r.status != "not reached":
                entry["seconds"] = r.seconds
                entry["attempts"] = r.attempts
                if r.wrong:
                    entry["wrong_notes"] = [t.label(p) for p in r.wrong]
                if r.status == "tried, then paused":
                    entry["played"] = [t.label(p) for p in tried]
                    entry["expected"] = [f"{n['note']} ({n['number']})" for n in info["keys"]]
                elif r.missing:
                    entry["missing_notes"] = [f"{n['note']} ({n['number']})" for n in info["keys"] if kb.key(n["key"]).pitch in r.missing]
                if hints != "always":
                    entry["needed_hint"] = r.hint_shown
            report.append(entry)
        done = ex.completed
        asked = len(resolved) - (start_at - 1)
        out = {
            "outcome": outcome,
            "completed": f"{done} of {asked} steps",
            "right_first_time": ex.first_try,
            "accuracy_percent": ex.accuracy,
            "steps": report,
        }
        if outcome == "player paused":
            out["what_now"] = ("The player tried this step and then stopped playing. Do not wait: tell them what was right and "
                               "what differs from the expected notes, or ask whether they want a hint or are done. No hurry is meant: "
                               "finding keys takes time on this keyboard.")
        if outcome != "finished":
            out["continue_with"] = f"run_exercise with start_at={ex.index + 1} and no steps repeats from where the player was"
        return out
