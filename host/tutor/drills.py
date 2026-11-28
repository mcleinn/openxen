"""Ready drills as library patterns: chord inversions and trills. Each returns steps that
`demo`, `fingering` and `run_exercise` accept unchanged, with what the tutor should say.

Conventions followed (not this project's):
- Names: a chord is in root position with its root lowest, in first inversion with its third
  lowest, in second inversion with its fifth lowest, in third inversion (four-note chords)
  with its seventh lowest; the inversion is decided by the lowest note alone, however the
  notes above it are arranged. Figured bass writes the triads 5/3, 6, 6/4 and the seventh
  chords 7, 6/5, 4/3, 4/2; lead sheets write a slash chord (C/E). (Any harmony textbook,
  e.g. Kostka & Payne, Tonal Harmony, ch. 3 and 4; "Inversion (music)", Wikipedia.)
- The drill form: graded piano syllabuses ask for triads "solid (blocked)" and "broken",
  beginning in root position and going on through the inversions, over one or two octaves
  (Royal Conservatory of Music, Piano Syllabus 2022, technical requirements, as tabulated at
  colorinmypiano.com; not checked against the syllabus itself).
- Nearest inversion from chord to chord: common tones are held and the other voices move by
  the smallest steps, the rule of keyboard-style voice leading. The voicing is computed by
  `voiceleading.py` (`move`, `voiced`), the code behind `harmony path` and `neighbours`.
- Trills: see `trills.py`; finger pairs: see `fingering.trill_fingerings`.

This project's own choices: the lengths of the steps, the three speeds of the trill drill,
how a single chord is split for a tremolo (lowest notes against the upper ones), and that a
naming drill is shuffled with a seed.
"""

from __future__ import annotations

import random
import re

from . import fingering as fingering_model
from . import library as lib
from . import trills
from . import voiceleading as voice_leading
from .theory import CHORDS

ORDINAL = {0: "root position", 1: "1st inversion", 2: "2nd inversion", 3: "3rd inversion"}
DEGREE = {1: "root", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh"}
FIGURES = {3: ("5/3", "6", "6/4"), 4: ("7", "6/5", "4/3", "4/2")}
_ROMAN = re.compile(r"^[ivIV]+(?:maj7|ø7|ø|°|dim|aug|\+|7)?$")
MOST_CHORDS = 32
SPEEDS = (("slow", 0.5), ("moderate", 0.25), ("fast", 0.125))      # strokes of an eighth, a sixteenth, a thirty-second note
SHAPES = ("On this keyboard an inversion of a chord quality is ONE hand shape wherever it is played: the same on every root and in "
          "every octave. So teach {count} shapes for a {quality} chord ({names}), not a new chord for each of the roots.")
SAY = ("Each step's 'say' names the inversion, the lowest note and the root; say it, and name the root and the fingers by their light "
       "colour (the root is lit orange without fingers=true).")


def _error(text: str):
    from .session import TutorError
    return TutorError(text)


def _safe(call, *args):
    """A theory call whose refusal is told to the tutor as it is."""
    try:
        return call(*args)
    except ValueError as e:
        raise _error(str(e)) from None


def _plain(name: str) -> str:
    return re.sub(r"-?\d+$", "", name)


def inversion_of(t, pitches: list[int], pc: int, quality: str) -> int:
    """Which inversion a voicing is: decided by its lowest note alone."""
    order = voice_leading.chord_notes(t, pc, quality)
    return order.index(min(pitches) % t.edo)


def chord_step(t, pitches: list[int], names: dict[int, str], pc: int, quality: str, root_name: str, beats: float = 2.0) -> dict:
    """A voicing as a chord step with its inversion named: what is lowest, where the root is."""
    pitches = sorted(pitches)
    inversion = inversion_of(t, pitches, pc, quality)
    degrees = (1,) + tuple(d for _, d in CHORDS[quality]["tones"])
    root_at = next(i for i, p in enumerate(pitches) if p % t.edo == pc % t.edo)
    labels = [t.label(p, names[p]) for p in pitches]
    title = f"{_plain(root_name)} {quality}, {ORDINAL[inversion]}"
    low, root = _plain(names[pitches[0]]), _plain(names[pitches[root_at]])
    if inversion == 0:
        say = f"{title}: the root {root} is lowest"
    else:
        where = "on top" if root_at == len(pitches) - 1 else "second from the top" if root_at == len(pitches) - 2 else "second from the bottom"
        say = f"{title}: {low}, the {DEGREE[degrees[inversion]]}, is lowest; the root {root} is {where}"
    step = {"notes": labels, "label": title, "root": labels[root_at], "lowest": labels[0], "inversion": inversion, "say": say, "beats": beats}
    if inversion and len(pitches) in FIGURES and all(d in (3, 5, 7) for d in degrees[1:]):
        step["also_written"] = f"{_plain(root_name)}/{low} (slash chord); figured bass {FIGURES[len(pitches)][inversion]}"
    return step


def _named(t, chord) -> tuple[list[int], dict[int, str]]:
    return list(chord.pitches), dict(zip(chord.pitches, chord.names))


def _missing(tutor, steps: list[dict]) -> list[str]:
    kb = tutor.keyboard
    t = kb.tuning
    out = []
    for step in steps:
        for label in step.get("notes") or ([step["note"]] if step.get("note") else []):
            if t.parse(label)[0] not in kb._by_pitch:
                out.append(label)
    return list(dict.fromkeys(out))


def _shapes_note(quality: str) -> str:
    size = len(CHORDS[quality]["tones"]) + 1
    names = ", ".join(ORDINAL[i] for i in range(size))
    return SHAPES.format(count={3: "three", 4: "four"}.get(size, size), quality=quality, names=names)


# --- the chords of a progression ---

def progression(tutor, root: str | None, scale: str, chords: list[str] | None, piece_id: str | None, section, plain_roots: bool
                ) -> tuple[list[tuple[int, str, str, str | None]], str]:
    """The chords to drill as (root as steps above C, quality, root name, what it is called in
    the source), and where they come from: a jazz tune of the library (`piece_id`, `section`),
    Roman numerals in the key `root` + `scale`, chord names, or the chords of the scale."""
    t = tutor.keyboard.tuning
    edo = t.edo
    if piece_id:
        piece = tutor.music.piece(piece_id)
        if piece is None or not piece.get("changes"):
            raise _error(f"there is no tune '{piece_id}' with chord changes in the library; ids come from library search (tradition jazz)")
        if section is not None:
            sec = tutor._tune_section(piece, section)
            bars = tutor._tune_bars(piece, sec)
            told = f"{piece['title']}, section {sec['n']} ({sec['label']}), bars {sec['bars'][0]}-{sec['bars'][1]}"
        else:
            bars = [bar for s in piece["changes"] for bar in s["bars"]]
            told = f"{piece['title']}, the whole form ({len(bars)} bars)"
        key = tutor._piece_key(piece)
        out: list[tuple[int, str, str, str | None]] = []
        for bar in bars:
            for symbol in bar:
                parsed = lib.chord_from_symbol(symbol)
                if not parsed:
                    continue
                root_name, quality, family, _ = parsed
                pc, spelled = tutor._key_root(root_name, family, key, plain_roots)
                if not out or out[-1][:2] != (pc, quality):
                    out.append((pc, quality, spelled, symbol))
        if not out:
            raise _error("this section has no chord symbols")
        if len(out) > MOST_CHORDS:
            told += f"; the first {MOST_CHORDS} chords (give a section for the rest)"
        return out[:MOST_CHORDS], told
    if chords:
        if len(chords) > MOST_CHORDS:
            raise _error(f"at most {MOST_CHORDS} chords in one drill")
        if all(_ROMAN.match(str(c).strip()) for c in chords):
            tonic, tonic_name = tutor._pitch(root or "C")
            found = _safe(t.progression, tonic, scale, [str(c).strip() for c in chords], tonic_name)
            return ([(c.root % edo, c.quality, _plain(c.names[0]), numeral) for c, numeral in zip(found, chords)],
                    f"{' - '.join(chords)} in {_plain(tonic_name)} {scale}")
        return [(*_safe(tutor._vl_chord, str(c)), None) for c in chords], "the chords given"
    tonic, tonic_name = tutor._pitch(root or "C")
    degrees = _safe(t.diatonic_chords, tonic, scale, False, tonic_name)
    items = [(d["root"] % edo, d["quality"], _plain(d["root_name"]), d["numeral"]) for d in degrees]
    return items + items[:1], f"the chords of {_plain(tonic_name)} {scale}, degree by degree"


# --- 1. all inversions of one chord, up the keyboard and back ---

def inversions(tutor, root: str | None, quality: str, voicing: str, direction: str, count: int | None) -> dict:
    kb = tutor.keyboard
    t = kb.tuning
    edo = t.edo
    quality = _safe(t.quality_key, quality)
    form = {"full": "solid", "solid": "solid", "blocked": "solid", "arpeggio": "broken", "broken": "broken"}.get(voicing.strip().lower())
    if form is None:
        raise _error("voicing must be full (solid: the notes together) or arpeggio (broken: one after another)")
    direction = direction.strip().lower()
    if direction not in ("up", "down"):
        raise _error("direction must be up (up the keyboard and back down) or down (from the top down and back up)")
    root = root or "C"
    pitch, name = tutor._pitch(root)
    size = len(CHORDS[quality]["tones"]) + 1

    def chords_from(start: int, octaves: int):
        return [_safe(t.chord, start + o * edo, quality, inv, name) for o in range(octaves) for inv in range(size)] \
            + [_safe(t.chord, start + octaves * edo, quality, 0, name)]

    low, high = kb.range()
    given = t.parse(root)[1]
    starts = [pitch] if given else [p for p in range(low.pitch - low.pitch % edo + pitch % edo - edo, high.pitch, edo)]
    chosen = None
    for octaves in range(max(1, min(int(count), 4)) if count else 2, 0, -1):
        fitting = [s for s in starts if all(p in kb._by_pitch for c in chords_from(s, octaves) for p in c.pitches)]
        if fitting:
            middle = kb.centre().pitch
            chosen = (min(fitting, key=lambda s: abs(s + octaves * edo / 2 - middle)), octaves)
            break
    start, octaves = chosen or (pitch, 1)
    rising = chords_from(start, octaves)
    order = rising + rising[-2::-1] if direction == "up" else rising[::-1] + rising[1:]
    half = len(rising)
    steps: list[dict] = []
    groups: list[dict] = []
    for n, chord in enumerate(order):
        pitches, names = _named(t, chord)
        step = chord_step(t, pitches, names, chord.root, quality, name)
        if form == "solid":
            steps.append(step)
            continue
        upwards = (n < half) == (direction == "up")
        notes = step["notes"] if upwards else step["notes"][::-1]
        broken = [{"note": label, "beats": 0.5} for label in notes[:-1]] + [{"note": notes[-1], "beats": 1}]
        groups.append({"label": step["label"], "say": step["say"] + ("" if upwards else "; played from the top down"), "root": step["root"],
                       "steps": broken})
        steps.extend(broken)
    out = {"pattern": "inversions", "what": lib.DRILLS["inversions"], "chord": f"{_plain(name)} {quality}", "form": form,
           "octaves": octaves, "order": " - ".join(dict.fromkeys(ORDINAL[c.inversion] for c in rising[:size])) + ", then the next octave; and back",
           "steps": steps}
    if groups:
        out["groups"] = groups
        out["note"] = ("Broken form: each group is one inversion, note by note; 'steps' is all of them in a row. Pass a group or the steps "
                       "to demo (outline=true keeps the shape lit), fingering and run_exercise. " + _shapes_note(quality))
    else:
        out["note"] = "One inversion per step; pass steps to demo, fingering and run_exercise. " + SAY + " " + _shapes_note(quality)
    if count and octaves < int(count):
        out["fits"] = f"{octaves} octave{'s' if octaves != 1 else ''} of it fit this keyboard from {t.label(start)}"
    missing = _missing(tutor, steps)
    if missing:
        out["not_on_this_keyboard"] = missing
    return out


# --- 2. one inversion through a progression ---

def through(tutor, root: str | None, scale: str, chords: list[str] | None, inversion: int, piece_id: str | None, section, plain_roots: bool) -> dict:
    kb = tutor.keyboard
    t = kb.tuning
    edo = t.edo
    items, told = progression(tutor, root, scale, chords, piece_id, section, plain_roots)
    inversion = int(inversion)
    if not 0 <= inversion <= 3:
        raise _error("inversion must be 0 (root position), 1, 2 or 3 (four-note chords only)")
    low, high = kb.range()
    bass = kb.centre().pitch - edo // 2
    steps = []
    for pc, quality, name, called in items:
        if inversion > len(CHORDS[quality]["tones"]):
            raise _error(f"{name} {quality} has three notes and no {ORDINAL[inversion]}; choose inversion 1 or 2, or seventh chords throughout")
        ways = [_safe(t.chord, octave * edo + pc, quality, inversion, name) for octave in range(low.pitch // edo - 1, high.pitch // edo + 1)]
        fitting = [c for c in ways if all(p in kb._by_pitch for p in c.pitches)] or ways
        chord = min(fitting, key=lambda c: abs(c.pitches[0] - bass))
        bass = chord.pitches[0]
        pitches, names = _named(t, chord)
        step = chord_step(t, pitches, names, pc, quality, name)
        if called:
            step["in_the_source"] = called
        steps.append(step)
    out = {"pattern": "inversion_through", "what": lib.DRILLS["inversion_through"], "progression": told, "inversion": ORDINAL[inversion],
           "steps": steps,
           "note": (f"Every chord in {ORDINAL[inversion]}, each as near to the one before as that inversion allows. Pass steps to demo, fingering "
                    f"and run_exercise. {SAY} Chords of one quality are one hand shape here, moved along: let the player find that out. "
                    + _shapes_note(items[0][1]))}
    missing = _missing(tutor, steps)
    if missing:
        out["not_on_this_keyboard"] = missing
    return out


# --- 3. the nearest inversion from chord to chord ---

def nearest(tutor, root: str | None, scale: str, chords: list[str] | None, piece_id: str | None, section, plain_roots: bool) -> dict:
    t = tutor.keyboard.tuning
    edo = t.edo
    items, told = progression(tutor, root, scale, chords, piece_id, section, plain_roots)
    pc, quality, name, called = items[0]
    home = tutor._vl_place(pc, quality, name)
    pitches = list(home.pitches)
    _, held = tutor._vl_step(pitches, pc, quality, name)
    first = chord_step(t, pitches, dict(zip(home.pitches, home.names)), pc, quality, name, 4)
    first["voices"] = "the start, in root position"
    if called:
        first["in_the_source"] = called
    steps = [first]
    for to_pc, to_quality, to_name, called in items[1:]:
        if (to_pc, to_quality) == (pc, quality):
            continue
        n = voice_leading.move(t, pc, quality, to_pc, to_quality)
        carried = voice_leading.voiced(pitches, n.moves, edo)
        entry, placed, name, names = tutor._vl_follow(n, pitches, held, name, to_name)
        full = {p: t.name_with_letter(p, t.letter_of(names[p % edo])) for p in placed}
        step = chord_step(t, placed, full, to_pc, to_quality, to_name, 4)
        if sorted(placed) == sorted(carried):
            stay = [held[mv.source] for mv in n.moves if not mv.steps]
            go = [f"{held[mv.source]} moves {'up' if mv.steps > 0 else 'down'} to {names[mv.target]}" for mv in n.moves if mv.steps]
            said = ([" and ".join(dict.fromkeys(stay)) + (" stay" if len(set(stay)) > 1 else " stays")] if stay else ["no note stays"]) \
                + list(dict.fromkeys(go))
            step["voices"] = "; ".join(said)
            step["moves"] = entry["moves"]
        else:
            step["voices"] = "set anew in another octave: led on from the chord before, it would leave the keyboard"
        step["say"] += f" ({step['voices']})"
        if called:
            step["in_the_source"] = called
        steps.append(step)
        pitches, held, pc, quality = placed, names, to_pc, to_quality
    out = {"pattern": "nearest_inversions", "what": lib.DRILLS["nearest_inversions"], "progression": told, "steps": steps,
           "small_steps": tutor._vl_step_names(),
           "note": ("Each chord is the inversion nearest to the one before: notes both chords have stay on their keys, the others move by the "
                    "smallest steps ('voices'). Pass steps to demo, fingering and run_exercise; held notes are the same keys, so let the "
                    "player keep those fingers down. " + SAY + " A progression that ends where it began may come back in another inversion. "
                    "The voicing is the one harmony path uses; a dominant seventh here has the plain seventh, not the one the jazz changes "
                    "take from the key."),
           "convention": "common tones held, the other voices by the smallest step: keyboard-style voice leading"}
    missing = _missing(tutor, steps)
    if missing:
        out["not_on_this_keyboard"] = missing
    return out


# --- 4. naming inversions ---

def naming(tutor, root: str | None, quality: str, scale: str, chords: list[str] | None, piece_id: str | None, section, plain_roots: bool,
           seed: int, count: int | None) -> dict:
    kb = tutor.keyboard
    t = kb.tuning
    if chords or piece_id:
        items, told = progression(tutor, root, scale, chords, piece_id, section, plain_roots)
        items = list(dict.fromkeys((pc, q, name) for pc, q, name, _ in items))
    else:
        items, told = [_safe(tutor._vl_chord, f"{root or 'C'} {quality}")], None
    steps = []
    for pc, q, name in items:
        home = tutor._vl_place(pc, q, name)
        for inversion in range(len(home.pitches)):
            chord = _safe(t.chord, home.pitches[0], q, inversion, name)
            if not all(p in kb._by_pitch for p in chord.pitches):
                chord = _safe(t.chord, home.pitches[0] - t.edo, q, inversion, name)
            pitches, names = _named(t, chord)
            step = chord_step(t, pitches, names, pc, q, name)
            step["answer"] = step["say"]
            steps.append(step)
    seed = int(seed)
    random.Random(seed).shuffle(steps)
    if count:
        steps = steps[:max(1, int(count))]
    out = {"pattern": "name_inversions", "what": lib.DRILLS["name_inversions"], "of": told or f"{_plain(items[0][2])} {items[0][1]}",
           "seed": seed, "steps": steps, "answers": [f"{n}. {step['answer']}" for n, step in enumerate(steps, 1)],
           "note": ("Shuffled; the same seed gives the same order, another seed another. Two ways to use it. You show, the player names: demo "
                    "ONE step (or light it with set_lights) without saying its name, ask which inversion it is and which note is the root, "
                    "then give the 'answer'. You name, the player plays: say the name and call run_exercise with the steps and hints="
                    "\"never\" (after_delay if they get stuck). " + _shapes_note(items[0][1]))}
    missing = _missing(tutor, steps)
    if missing:
        out["not_on_this_keyboard"] = missing
    return out


# --- trills and tremolos as a drill of their own ---

def interval_sizes(t) -> dict[str, int]:
    """The intervals a trill or tremolo drill can be asked for, by name -> steps of this tuning."""
    sizes = {"step": 1}
    for steps, name in sorted(voice_leading.step_names(t).items()):
        sizes[name.removeprefix("a ").split(" (")[0]] = steps
    sizes.setdefault("semitone", t.edo - t.steps_for(3 / 2) - t.steps_for(5 / 4))
    for name, ratio in (("minor third", 6 / 5), ("major third", 5 / 4), ("fourth", 4 / 3), ("fifth", 3 / 2), ("sixth", 5 / 3), ("octave", 2)):
        sizes[name] = t.steps_for(ratio)
    return sizes


def trill(tutor, kind: str, root: str | None, interval: str | None, chords: list[str] | None, hand: str, count: int | None) -> dict:
    kb = tutor.keyboard
    t = kb.tuning
    sizes = interval_sizes(t)
    sides: list[list[tuple[int, str]]]
    if chords:
        if kind != "tremolo":
            raise _error("a trill is between two single notes; for chords use the pattern tremolo")
        if len(chords) == 1:        # one chord: its lowest notes against the upper ones
            pc, quality, name = _safe(tutor._vl_chord, str(chords[0]))
            home = tutor._vl_place(pc, quality, name)
            tones = list(zip(home.pitches, home.names))
            cut = len(tones) // 2
            sides = [tones[:cut], tones[cut:]]
            between = f"{_plain(name)} {quality}: its lowest note{'s' if cut > 1 else ''} against the upper ones"
        elif len(chords) == 2:
            placed = []
            for text in chords:
                pc, quality, name = _safe(tutor._vl_chord, str(text))
                home = tutor._vl_place(pc, quality, name)
                placed.append(list(zip(home.pitches, home.names)))
            shared = {p for p, _ in placed[0]} & {p for p, _ in placed[1]}
            if shared:
                raise _error(f"these two chords share {', '.join(t.label(p) for p in sorted(shared))}: a tremolo takes turns between different "
                             f"notes. Choose two chords without a common note, or one chord (it is split in two)")
            sides = placed
            between = " and ".join(str(c) for c in chords)
        else:
            raise _error("chords for a tremolo: one chord (split in two) or two chords without a common note")
        size_words = None
    else:
        wanted = (interval or ("semitone" if kind == "trill" else "fifth")).strip().lower().removeprefix("a ")
        if wanted.isdigit():
            steps = int(wanted)
        elif wanted in sizes:
            steps = sizes[wanted]
        else:
            raise _error(f"interval must be a number of steps or one of: {', '.join(sizes)}")
        if not 1 <= steps <= 2 * t.edo:
            raise _error("interval must be between one step and two octaves")
        main = tutor._pitch(root) if root else (kb.centre().pitch, kb.centre().name)
        other = main[0] + steps
        if other not in kb._by_pitch:
            raise _error(f"this keyboard has no key {steps} steps above {main[1]}; choose a lower root")
        sides = [[main], [(other, t.name(other))]]
        size_words = voice_leading.step_words(t, steps, direction=False) if steps in voice_leading.step_names(t) else t.interval_words(steps)
        between = f"{main[1]} and {t.name(other)}"
        kind = trills.kind_of((main[0],), (other,), t.steps_for(9 / 8)) if kind == "trill" else kind
    labels = [[t.label(p, n) for p, n in side] for side in sides]
    both = [labels[0][0] if len(labels[0]) == 1 else labels[0], labels[1][0] if len(labels[1]) == 1 else labels[1]]
    pairs: list = [None]
    own, ask, others = None, None, []
    if all(len(side) == 1 for side in sides):
        keys = kb.shapes([sides[0][0][0], sides[1][0][0]], None, 1)[0].keys
        by_pitch = {k.pitch: k for k in keys}
        two = [by_pitch[sides[0][0][0]], by_pitch[sides[1][0][0]]]
        # the player's own pair for this shape comes first and, unless more pairs are asked for, alone
        own, ranked = tutor._trill_pairs(two[0], two[1], hand)
        wanted = max(1, min(int(count or 3), 6))
        if own:
            computed = [f for f in ranked if f.fingers != own.fingers]
            pairs = [own] + (computed[:wanted - 1] if count else [])
            others = [f"{f.text} ({f.feel})" for f in computed[:3]]
        else:
            pairs = ranked[:wanted]
            ask = (tutor._trill_ask(two[0], two[1], ranked[0]), tutor._trill_save_hint(two[0], two[1], hand))
        shape = f"to {tutor._trill_where(two[0], two[1])} ({tutor._trill_interval(two[0], two[1])})"
    groups = []
    for pair in pairs:
        stages = []
        for word, stroke in SPEEDS:
            step = {"trill": both, "beats": 4, "lasts": 4, "stroke_beats": stroke,
                    "label": f"{kind} {between}" + (f", fingers {pair.text}" if pair else "") + f", {word}",
                    "say": f"{word}: {round(1 / stroke)} strokes to a beat, even and light" + (
                        f"; {fingering_model.FINGER_NAMES[pair.fingers[0]]} and {fingering_model.FINGER_NAMES[pair.fingers[1]]}" if pair else "")}
            if pair:
                step["fingers"] = list(pair.fingers)
            stages.append(step)
        group = {"steps": stages}
        if pair:
            group = {"fingers": pair.text, "feel": pair.feel, **({"why": list(pair.reasons)} if pair.reasons else {}),
                     **({"yours": "your own fingering for this shape: use it"} if pair.own else
                        {"suggestion": "computed, not tried on this keyboard" + (": an alternative to the player's own" if own else "")}), **group}
        groups.append(group)
    out = {"pattern": kind, "what": lib.DRILLS["trill" if kind == "trill" else "tremolo"], "between": both}
    if size_words:
        out["interval"] = size_words
        out["intervals_here"] = {name: f"{n} step{'' if n == 1 else 's'}" for name, n in sizes.items()}
    out["groups"] = groups
    out["steps"] = [step for group in groups for step in group["steps"]]
    out["note"] = ("Each step is the same " + kind + " for four beats at one speed: slow, moderate, fast (2, 4 and 8 strokes to a beat). "
                   "demo plays it as written at tempo_bpm (60: 2, 4, 8 strokes a second; a lower tempo slows all three) with both keys lit; "
                   "run_exercise (give it tempo_bpm too) judges the effect and says how fast and how even it was, never a number of "
                   "strokes. Go on to the next speed only when the slower one is even and the hand is loose. "
                   + ("The first group is the player's own fingering for this shape: practise with it" + (
                       "; the further groups are computed alternatives, only if the player wants to compare. " if len(pairs) > 1 else ". ")
                      if own else
                      "One group per finger pair, the likeliest first: let the player try them and keep what feels best, then save it "
                      "(fingering_book, trill true). "
                      if pairs[0] else "The fingering tool gives fingers for the two hand positions. ")
                   + "How to practise is C. P. E. Bach's advice (Versuch I, 2.3, par. 8): slowly first, then faster, always evenly, the fingers "
                   "not lifted high, the muscles relaxed.")
    if pairs[0]:
        ranked_by = "ranked by " + fingering_model.TRILL_SOURCE + ", and by where these two keys lie under the hand"
        out["shape"] = shape
        if own:
            out["finger_pairs"] = ("your own fingering for this shape, from the fingering book; it holds for this shape in every tuning. "
                                   "Computed pairs (" + ranked_by + ") are alternatives only")
            out["other_pairs"] = others
        else:
            out["finger_pairs"] = ranked_by + ": computed suggestions that nobody has tried on this keyboard"
            out["ask"], out["then"] = ask
    return out


def run(tutor, name: str, *, root: str | None, quality: str, scale: str, voicing: str, direction: str, count: int | None, inversion: int,
        chords: list[str] | None, piece_id: str | None, section, plain_roots: bool, seed: int, interval: str | None, hand: str) -> dict:
    if name == "inversions":
        return inversions(tutor, root, quality, voicing, direction, count)
    if name == "inversion_through":
        return through(tutor, root, scale, chords, inversion, piece_id, section, plain_roots)
    if name == "nearest_inversions":
        return nearest(tutor, root, scale, chords, piece_id, section, plain_roots)
    if name == "name_inversions":
        return naming(tutor, root, quality, scale, chords, piece_id, section, plain_roots, seed, count)
    if name in ("trill", "tremolo"):
        return trill(tutor, name, root, interval, chords, hand, count)
    raise KeyError(name)
