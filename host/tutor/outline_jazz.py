"""The outline of a jazz tune: its form as players name it ("32 bars, AABA", "12-bar blues"), the
sections with their bars in the played form, what repeats what (exactly, with another ending,
transposed), the key areas, and an order to learn it in for improvising.

Two kinds of tune (library_build.py):

  standards   chord changes whose source ALREADY gives the form: sections with a label (A, B, C, D,
              i = intro, v = verse), repeats and endings, which library_build unfolds into played order
              ("A", "A (repeat)", "A (ending 2)"). `standard()` takes that as it is. Computed here, and
              said to be: letters for sections the source leaves without one, the sectioning of tunes
              without any label (8-bar units lettered by their chords), what repeats what, the blues,
              the key areas, the practice order.
  melodies    lead sheets in MusicXML. They carry repeat signs, endings (voltas), double bars and a few
              words (Verse, Chorus, Refrain); no rehearsal letters. `melody()` unfolds repeats and
              endings, cuts at what the print marks, divides the stretches into 8-bar units and letters
              them by the melody (outline.py's bar comparison: transposition-invariant, tolerant of a
              changed ending or pickup) together with the chords.

A known defect of the standards file: in some tunes every label stands one section early (the first
section is called B, the last has none: "Body And Soul" as B A - for sections that are A A B A). A form
does not begin at B, so those labels are moved one section later (`letters` = "source, moved").

This project's own choices: every threshold below, the rule for a blues, the cadence rule for key
areas, and the practice order.
"""
from __future__ import annotations

import re

from . import harmony
from . import library as lib

ALIKE = 0.6             # share of the bars two sections must have in common to share a letter
MELODY_ALIKE = 0.6      # the same for two stretches of melody (outline.OCCURRENCE)
CHORDS_HELP = 0.75      # ... or this share of the chords together with MELODY_WITH_CHORDS of the melody
MELODY_WITH_CHORDS = 0.3
UNIT = 8                # bars in a computed section
EXTRA = ("intro", "verse", "coda")          # sections that are not part of the chorus
RANK = {"same": 0, "ending": 1, "transposed": 2, "begins": 3, "varied": 4}
_UP = {1: "a half step", 2: "a whole step", 3: "a minor third", 4: "a major third", 5: "a fourth", 6: "a tritone"}
_PLAYED = re.compile(r"^(.*?)\s*\((?:ending (\d+)|(repeat))\)$")


# --- chords as comparable bars ---

def _pc(name: str) -> int:
    return (harmony._PITCH_CLASS[name[0]] + name.count("#") - name.count("b")) % 12


def tokens(bars: list[list[str]]) -> list[tuple]:
    """Each bar as a tuple of (root as one of twelve, chord family in harmony.py's shorthand)."""
    out = []
    for bar in bars:
        row = []
        for symbol in bar:
            parsed = lib.chord_from_symbol(symbol)
            if parsed:
                row.append((_pc(parsed[0]), harmony._SHORT.get(parsed[1], "")))
        out.append(tuple(row))
    return out


def _bar_score(a: tuple, b: tuple, shift: int) -> float:
    moved = tuple(((pc + shift) % 12, kind) for pc, kind in a)
    if moved == b:
        return 1.0
    if moved and b and (moved[0] == b[0] or [pc for pc, _ in moved] == [pc for pc, _ in b]):
        return 0.5
    return 0.0


def compare(earlier: list[tuple], later: list[tuple]) -> dict:
    """How the later section's chords relate to the earlier one's: {"kind", "shift"?, "share", "differs"?}.
    same | ending (alike but for the last bars) | transposed (every root moved by one interval, the chord
    kinds kept) | begins (the first half is the same) | varied | different."""
    n, m = min(len(earlier), len(later)), max(len(earlier), len(later))
    if not n:
        return {"kind": "different", "share": 0.0}
    best = None
    for shift in range(12):
        scores = [_bar_score(earlier[i], later[i], shift) for i in range(n)]
        if best is None or sum(scores) > sum(best[1]) + 1e-9:
            best = (shift, scores)
    shift, scores = best
    share = round(sum(scores) / m, 3)
    exact = all(s == 1.0 for s in scores) and len(earlier) == len(later)
    if exact:
        return {"kind": "same", "share": 1.0} if shift == 0 else {"kind": "transposed", "shift": shift, "share": 1.0}
    if shift:
        plain = sum(_bar_score(earlier[i], later[i], 0) for i in range(n)) / m
        if share >= 0.85 and len(earlier) == len(later):
            return {"kind": "transposed", "shift": shift, "share": share, "nearly": True}
        scores, share = [_bar_score(earlier[i], later[i], 0) for i in range(n)], round(plain, 3)
    differs = [i for i, s in enumerate(scores) if s < 1.0] + list(range(n, m))
    tail = max(2, m // 4)
    if share >= 0.5 and differs and min(differs) >= m - tail:
        return {"kind": "ending", "share": share, "differs": [min(differs) + 1, m]}
    if n >= 4 and all(s == 1.0 for s in scores[:(n + 1) // 2]) and len(later) >= len(earlier) // 2 * 2:
        return {"kind": "begins", "share": share, "differs": [min(differs) + 1, m]}
    return {"kind": "varied" if share >= ALIKE else "different", "share": share}


def interval_words(shift: int) -> str:
    """A move of the roots by `shift` of twelve semitones, as players say it: the smaller way round."""
    shift %= 12
    return f"{_UP[shift]} higher" if shift <= 6 else f"{_UP[12 - shift]} lower"


def _span(a: int, z: int) -> str:
    return f"bar {a}" if a == z else f"bars {a}-{z}"


# --- what the chords of a section say ---

def is_blues(bars: list[tuple], key: tuple[str, bool] | None = None) -> int:
    """This project's rule for a blues, read from the chords alone: twelve bars; bar 1 begins on the home
    chord (the key the source gives, else the first chord), bar 5 on the chord a fourth above it, bar 7
    or bar 11 on the home chord again (or the chord on its third, as in the blues with descending
    two-fives), and bar 9 or 10 has the chord a fifth above home. Chord kinds are not asked: home may be
    a seventh chord, minor or major. Twenty-four bars that are such a form with every bar doubled count
    too. Returns 12, 24 or 0."""
    if len(bars) == 24 and all(bars[k][:1] == bars[k + 1][:1] or not bars[k + 1] for k in (0, 8, 12)):
        return 24 if is_blues(bars[0::2], key) or is_blues([a + b for a, b in zip(bars[0::2], bars[1::2])], key) else 0
    if len(bars) != 12 or any(not bars[i] for i in (0, 4, 6, 10)):
        return 0
    home = _pc(key[0]) if key else bars[0][0][0]
    if bars[0][0][0] != home or bars[4][0][0] != (home + 5) % 12:
        return 0
    if not any(pc == (home + 7) % 12 for i in (8, 9) for pc, _ in bars[i]):
        return 0
    back = (home, (home + 3) % 12, (home + 4) % 12)
    return 12 if bars[6][0][0] in back or bars[10][0][0] == home else 0


def key_areas(symbols: list[list[str]], then: list[str] | None = None, key: tuple[str, bool] | None = None) -> list[str]:
    """The keys a stretch of changes settles in, read from its cadences with the chord reader of
    library.py: a dominant seventh chord whose root falls a fifth to a major chord or to a minor chord
    (minor, minor sixth; a minor seventh chord only where it is the home chord of the tune's own minor
    `key`, since elsewhere it is mostly the first chord of a two-five). `then`: the bar that follows
    the stretch, where its last dominant may resolve. A rule of this project, good for the plain cases."""
    line: list[tuple[str, int, str]] = []
    for bar in symbols + [(then or [])[:1]]:
        for symbol in bar:
            parsed = lib.chord_from_symbol(symbol)
            if parsed:
                entry = (parsed[0], _pc(parsed[0]), harmony._SHORT.get(parsed[1], ""))
                if not line or line[-1][1:] != entry[1:]:
                    line.append(entry)
    found: list[str] = []
    for i in range(len(line) - 1):
        (_, pc, kind), (name, to, target) = line[i], line[i + 1]
        if kind not in ("7", "7sus") or (pc + 5) % 12 != to:
            continue
        if target == "maj7":
            area = f"{name} major"
        elif target == "m" or (target == "m7" and key and key[1] and _pc(key[0]) == to):
            area = f"{name} minor"
        else:
            continue
        if area not in found:
            found.append(area)
    if not found and len({entry[1:] for entry in line[:len(line) - bool(then)] or line}) == 1 and len(symbols) >= 4:
        return [f"stays on {next(symbol for bar in symbols for symbol in bar if lib.chord_from_symbol(symbol))}"]
    return found


def sequence(bars: list[tuple]) -> str | None:
    """A section that is one short unit moved along: "bars 1-2, then three times more, each a fourth higher"."""
    n = len(bars)
    for unit in (n // 4, n // 2):
        if unit < 1 or n % unit or n // unit < 2 or n < 4:
            continue
        parts = [bars[k:k + unit] for k in range(0, n, unit)]
        if not all(parts[0]) or len({p for part in parts for p in part}) < 2:
            continue
        moves = set()
        for a, b in zip(parts, parts[1:]):
            r = compare(a, b)
            moves.add(r.get("shift") if r["kind"] == "transposed" and not r.get("nearly") else None)
        if len(moves) == 1 and None not in moves:
            times = {1: "once more", 2: "twice more", 3: "three times more"}.get(len(parts) - 1, f"{len(parts) - 1} times more")
            return f"a sequence: {_span(1, unit)} of it, then {times}, each {interval_words(moves.pop())}"
    return None


def turnaround(symbols: list[list[str]]) -> str | None:
    """The last bar leads back to the top: it ends on a dominant chord a fifth (or a half step) above
    the first chord of the form."""
    first = next((lib.chord_from_symbol(s) for bar in symbols for s in bar if lib.chord_from_symbol(s)), None)
    last = lib.chord_from_symbol(symbols[-1][-1]) if symbols and symbols[-1] else None
    if not first or not last or last[2] != "dominant":
        return None
    if (_pc(last[0]) - _pc(first[0])) % 12 not in (7, 1):
        return None
    chords = symbols[-1] if len(symbols[-1]) > 1 or len(symbols) < 2 else symbols[-2] + symbols[-1]
    start = len(symbols) if chords is symbols[-1] else len(symbols) - 1
    return f"{_span(start, len(symbols))} ({' '.join(chords)}) lead{'s' if start == len(symbols) else ''} back to bar 1"


# --- lettering ---

def units(n: int, relate, unit: int = UNIT) -> list[tuple[int, int]]:
    """A stretch of n bars without marks as (first index, length): units of eight bars, what is left over
    joined to the last one; up to 12 bars stay whole. Sixteen-bar units where the stretch has 48 bars or
    more and they repeat one another at least as well as the eight-bar ones do."""
    if n <= 12 or n < 2 * unit:
        return [(0, n)]

    def cut(size: int) -> list[tuple[int, int]]:
        parts = [(k, size) for k in range(0, n - size + 1, size)]
        return parts[:-1] + [(parts[-1][0], n - parts[-1][0])]

    def repeats(parts: list[tuple[int, int]]) -> int:
        return sum(1 for k, part in enumerate(parts) if any(relate(earlier, part) for earlier in parts[:k]))

    eight = cut(unit)
    if n >= 6 * unit and n % (2 * unit) == 0:
        sixteen = cut(2 * unit)
        if repeats(sixteen) and 2 * repeats(sixteen) >= repeats(eight):
            return sixteen
    return eight


def _letter(used: set[str]) -> str:
    return next(c for c in "ABCDEFGHJKLMNOPQRSTUWXYZ" if c not in used)


def form_letters(sections: list[dict]) -> str:
    return "".join(s["label"] for s in sections if s["label"] not in EXTRA)


def has_bridge(form: str) -> bool:
    """A form of two letters in which B comes once and A returns after it (AABA, ABA): its B is the bridge."""
    return set(form) == {"A", "B"} and form.count("B") == 1 and form[0] == "A" and form[-1] == "A"


def form_words(outline: dict) -> str:
    chorus = sum(s["length"] for s in outline["sections"] if s["label"] not in EXTRA)
    size = outline.get("blues")
    if size:
        text = f"{size}-bar blues" + (f", {chorus // size} choruses written out ({chorus} bars)" if chorus > size else "")
    else:
        text = f"{chorus} bars, {outline['form']}" if outline["form"] else f"{chorus} bars"
    extra = [f"a {s['length']}-bar {s['label']}" for s in outline["sections"] if s["label"] in EXTRA]
    return text + (", with " + " and ".join(dict.fromkeys(extra)) if extra else "")


def _relations(sections: list[dict], bars_of) -> None:
    """For each section the earlier one it is most like (`like`), by its chords."""
    for k, s in enumerate(sections):
        best = None
        for e in sections[:k]:
            r = compare(bars_of(e), bars_of(s))
            if r["kind"] == "different" or (r["kind"] == "transposed" and len(set(bars_of(s))) < 2 and e["label"] == s["label"]):
                continue
            rank = (RANK[r["kind"]], e["label"] != s["label"], e["n"])
            if best is None or rank < best[0]:
                best = (rank, e, r)
        if best:
            _, e, r = best
            s["like"] = {"of": e["n"], "kind": r["kind"], **{key: r[key] for key in ("shift", "differs") if key in r}}


def _like_words(s: dict, sections: list[dict]) -> str:
    like = s.get("like")
    if not like:
        return ""
    of = sections[like["of"] - 1]
    name = f"section {of['n']}"
    first = s["bars"][0]
    if like["kind"] == "same":
        return f"as {name}"
    if like["kind"] == "ending":
        a, z = like["differs"]
        return f"as {name}, another ending ({_span(first + a - 1, first + z - 1)})"
    if like["kind"] == "transposed":
        return f"{name} {interval_words(like['shift'])}" + (", nearly" if like.get("nearly") else "")
    if like["kind"] == "begins":
        return f"begins as {name}, new from bar {first + like['differs'][0] - 1}"
    return f"a variant of {name}"


# --- standards ---

def _displaced(labels: list[str]) -> tuple[list[str], str] | None:
    """The labels of a tune in which they stand one section off, put right, and which way they were off.
    early: the first section is called B or later (a form does not begin at B): each label belongs one
    section later, the first section is A. late: the first section has none and the second is A, or the
    intro before A (a form's first letter belongs to its first section): each label belongs one section earlier,
    and the last section is left without."""
    if len(labels) < 2:
        return None
    if re.fullmatch(r"[B-H]", labels[0]):
        return ["A"] + labels[:-1], "early"
    if not labels[0] and (labels[1] == "A" or labels[1:3] == ["i", "A"]):
        return labels[1:] + [""], "late"
    return None


def standard(piece: dict) -> dict | None:
    """The outline of a standard from its unfolded `changes` (library_build.jazz_changes)."""
    changes = piece.get("changes") or []
    if not changes:
        return None
    key = lib.parse_key(piece.get("key", ""))
    # the source's sections: the played entries of one of them (endings, a repeat) are one group
    groups: list[dict] = []
    for entry in changes:
        m = _PLAYED.match(entry["label"])
        base = (m.group(1) if m else entry["label"]).strip()
        again = bool(m and (m.group(3) or int(m.group(2) or 1) > 1))
        if again and groups and groups[-1]["source"] == base:
            groups[-1]["passes"].append(entry["bars"])
        else:
            groups.append({"source": base, "passes": [entry["bars"]], "endings": bool(m and m.group(2))})
    labels = [g["source"] for g in groups]
    letters = "source" if any(labels) else "computed"
    displaced = _displaced(labels)
    if displaced:
        # the moved letters stand unless the chords contradict them (two sections of one letter with unlike changes)
        first: dict[str, list] = {}
        clash = False
        for g, label in zip(groups, displaced[0]):
            mine = tokens(g["passes"][0])
            if label and label in first and compare(first[label], mine)["kind"] == "different":
                clash = True
            first.setdefault(label, mine)
        labels, letters = ([""] * len(groups), "computed") if clash else (displaced[0], "source, moved")
    # played sections; in a tune without any letter a section of 16 bars or more is divided into units, unless it is a blues
    played: list[dict] = []
    for g, label in zip(groups, labels):
        for bars in g["passes"]:
            toks = tokens(bars)
            parts = [(0, len(bars))]
            if letters == "computed" and not is_blues(toks, key):
                parts = units(len(bars), lambda a, b: compare(toks[a[0]:a[0] + a[1]], toks[b[0]:b[0] + b[1]])["kind"] in ("same", "ending", "varied"))
            for at, length in parts:
                played.append({"source": label, "symbols": bars[at:at + length], "tokens": toks[at:at + length]})
    used = {p["source"] for p in played if len(p["source"]) == 1 and p["source"].isupper()}
    named: list[dict] = []
    computed = 0
    for k, p in enumerate(played):
        source = p["source"]
        if source in ("i", "v"):
            p["label"] = "intro" if source == "i" else "verse"
        elif source:
            p["label"] = source
        else:
            computed += 1
            twin = next((q for q in [x for x in played if x["source"] and x["source"] not in ("i", "v")] + named
                         if compare(q["tokens"], p["tokens"])["kind"] in ("same", "ending", "varied")), None)
            if twin:
                p["label"] = twin.get("label") or twin["source"]
            elif k == len(played) - 1 and len(p["symbols"]) <= 4 and k:
                p["label"] = "coda"
            else:
                p["label"] = _letter(used)
                used.add(p["label"])
            named.append(p)
    if computed and letters != "computed":
        letters += " and computed"
    sections: list[dict] = []
    at = 1
    for k, p in enumerate(played):
        length = len(p["symbols"])
        s = {"n": k + 1, "label": p["label"], "bars": [at, at + length - 1], "length": length}
        if not p["source"]:
            s["computed"] = True
        if is_blues(p["tokens"], key):
            s["blues"] = is_blues(p["tokens"], key)
        else:
            run = sequence(p["tokens"])
            if run:
                s["sequence"] = run
        following = played[(k + 1) % len(played)]["symbols"]
        keys = key_areas(p["symbols"], following[0] if following else None, key)
        if keys:
            s["keys"] = keys
        sections.append(s)
        at += length
    by_n = {s["n"]: p["tokens"] for s, p in zip(sections, played)}
    _relations(sections, lambda s: by_n[s["n"]])
    out: dict = {"letters": letters, "form": form_letters(sections), "bars": at - 1, "sections": sections}
    chorus = [s for s in sections if s["label"] not in EXTRA]
    whole = [bar for s, p in zip(sections, played) if s["label"] not in EXTRA for bar in p["tokens"]]
    out["eights"] = eights(whole)
    if chorus and all(s.get("blues") for s in chorus):
        out["blues"] = chorus[0]["blues"]
    every = [bar for p in played for bar in p["symbols"]]
    back = turnaround(every)
    if back:
        out["turnaround"] = back
    if key:
        out["key"] = piece["key"]
    out["made"] = {
        "source": "Form from the source's labels, repeats and endings.",
        "source, moved": "Form from the source's labels, each moved one section (in this file they stand one section off).",
        "computed": "The source gives no section letters: eight-bar sections lettered here by their chords, not a published form.",
    }[letters.split(" and ")[0]]
    out["made"] += ((" A section it leaves without a letter is named here by its chords." if letters.endswith(" and computed") else "")
                    + (" That it is a blues is read from the chords." if out.get("blues") else "")
                    + " What repeats, the key areas and the practice order are worked out here: a suggestion.")
    out["practice_order"] = practice(out, "changes")
    return out


# --- what to practise in which order ---

def practice(outline: dict, what: str = "changes") -> list[str]:
    """An order to learn the tune in for improvising on it (`what` = changes) or to learn its melody.
    This project's suggestion, after the way players learn tunes: the section that fills most bars
    first, then the others, the join back to the top, one section looped, the whole form last."""
    sections = outline["sections"]
    chorus = [s for s in sections if s["label"] not in EXTRA]
    total = sum(s["length"] for s in chorus) or 1
    steps: list[str] = []
    if outline.get("blues") and what == "changes":
        double = " (two bars each)" if outline["blues"] == 24 else ""
        steps.append(f"Three lines of four bars{double}: home; the fourth and home again; the turn through the fifth. Roots first, then shells or guide tones.")
        later = [_span(*s["bars"]) for s in chorus[1:] if (s.get("like") or {}).get("kind") != "same"]
        if later:
            steps.append("The choruses differ a little: compare " + ", ".join(later[:3]) + " with the first.")
        steps.append("Solo: chord tones first, each line a question, an answer, a conclusion; then whole choruses.")
        return [f"{k}. {text}" for k, text in enumerate(steps, 1)]
    by_label: dict[str, list[dict]] = {}
    for s in chorus:
        by_label.setdefault(s["label"], []).append(s)
    order = sorted(by_label, key=lambda label: (-sum(s["length"] for s in by_label[label]), by_label[label][0]["n"]))
    how = ": roots, shells, guide tones" if what == "changes" else ": phrase by phrase"
    for k, label in enumerate(order[:3]):
        mine = by_label[label]
        first = mine[0]
        bridge = label == "B" and has_bridge(outline["form"])
        text = f"{'The bridge' if bridge else label} ({_span(*first['bars'])}"
        share = sum(s["length"] for s in mine)
        text += f"; {share} of the {total} bars)" if len(mine) > 1 else ")"
        like = first.get("like") or {}
        if like.get("kind") == "transposed" and what == "changes":
            text += f": {_like_words(first, sections)}, the same shapes moved"
        elif first.get("sequence") and what == "changes":
            text += ": " + first["sequence"]
        elif k == 0:
            text += how
        steps.append(text + ".")
    if len(order) > 3:
        steps.append("Then " + ", ".join(f"{x} ({_span(*by_label[x][0]['bars'])})" for x in order[3:]) + ".")
    if outline.get("turnaround") and what == "changes":
        steps.append(f"The join: {outline['turnaround']}.")
    extras = list(dict.fromkeys(s["label"] for s in sections if s["label"] in EXTRA))
    if extras:
        steps.append(f"The {' and the '.join(extras)} can wait: solos are played on the chorus.")
    steps.append("Solo on one section looped, chord tones first; then the whole form." if what == "changes" else
                 "Join the sections in their order; then the chords of each section.")
    return [f"{k}. {text}" for k, text in enumerate(steps, 1)]


# --- lead sheets ---

def unfold(measures: list[dict]) -> list[int]:
    """The order in which the written measures are played: repeat signs and endings (voltas) followed.
    D.C., D.S. and coda jumps are not followed."""
    order: list[int] = []
    start, passes, i, guard = 0, 1, 0, 0
    done: set[int] = set()              # backward repeats already taken
    while i < len(measures) and guard < 4 * len(measures) + 8:
        guard += 1
        m = measures[i]
        if m.get("forward") and i != start:
            start, passes = i, 1
        if m.get("ending") and passes not in m["ending"]:
            i += 1
            continue
        order.append(i)
        if m.get("backward") and i not in done:
            if passes < int(m.get("times") or 2):
                passes += 1
                i = start
                continue
            done.add(i)
            passes = 1
            start = i + 1
        i += 1
    return order


def _midi(name: str) -> int:
    m = re.match(r"^([A-G])([#b]*)(-?\d+)$", name)
    return 12 * (int(m.group(3)) + 1) + harmony._PITCH_CLASS[m.group(1)] + m.group(2).count("#") - m.group(2).count("b")


def melody(piece: dict, measures: list[dict]) -> dict | None:
    """The outline of a lead sheet. `measures`: one per written measure, `{"length" (quarter notes),
    "events": [[beat, note name], ...], "chords": [...], "notes": index of its first note in piece["notes"],
    "pickup"?, "forward"?, "backward"?, "times"?, "ending"? ([1], [2], ...), "double"? (a double bar after
    it), "word"? (verse | chorus), "jumps"? (D.C. ... as printed)}`."""
    from . import outline as two_staff
    if not measures:
        return None
    lead = 1 if measures[0].get("pickup") and len(measures) > 1 else 0
    played = unfold(measures)
    first = measures[0]
    late = not first["events"] or first["events"][0][0] >= first["length"] / 2 - 1e-6
    if not lead and len(measures) > 1 and late and (len(played) % 4 == 1 or measures[1].get("forward")
                                                    or (not first["chords"] and any(m["chords"] for m in measures))):
        lead = 1                        # a pickup written as a whole bar that begins with rests
    order = [i for i in played if i >= lead]
    n = len(order)
    if n < 4:
        return None
    # what the print marks: where a repeat begins or ends, where it starts over, a double bar, Verse / Chorus
    cuts: set[int] = {0}
    region: dict[int, str] = {}
    for p, i in enumerate(order):
        m = measures[i]
        before = order[p - 1] if p else None
        if p and (i != before + 1 and not (measures[i].get("ending") and i > before)):
            cuts.add(p)                 # the repeat starts over
        if p and m.get("forward"):
            cuts.add(p)
        if (m.get("backward") or m.get("double")) and p + 1 < n:
            cuts.add(p + 1)
        if m.get("ending") and p + 1 < n and not measures[order[p + 1]].get("ending") and order[p + 1] == i + 1:
            cuts.add(p + 1)             # after the last ending
        if m.get("word"):
            cuts.add(p)
            region[p] = m["word"]
    print_marks = len(cuts) > 1
    bars = two_staff._Bars([{"n": p + 1, "time": "", "length": measures[i]["length"],
                             "staves": {"upper": [[beat, 1.0, [_midi(name)]] for beat, name in measures[i]["events"]], "lower": []}}
                            for p, i in enumerate(order)])
    chord_bars: list[list[str]] = []
    last: list[str] = []
    seen_chord = False
    for i in range(len(measures)):
        seen_chord = seen_chord or bool(measures[i]["chords"])
        last = measures[i]["chords"] or last[-1:]
        chord_bars.append(list(last))
    toks = tokens([chord_bars[i] for i in order])

    def relate(a: tuple[int, int], b: tuple[int, int]) -> dict:
        """Stretch b (first index, length) against the earlier a: {"kind", "shift"?, "melody", "chords"}."""
        size = min(a[1], b[1])
        r = bars.unit(a[0], b[0], size) if size else {"kind": "hands", "alike": 0.0}
        chords = compare(toks[a[0]:a[0] + a[1]], toks[b[0]:b[0] + b[1]]) if seen_chord else {"kind": "different", "share": 0.0}
        short = size / max(a[1], b[1])
        # how alike the melody is: bar against bar (outline.py's relation of one hand), weighted by the notes in the bars
        weights = [(max(bars.size[a[0] + k]["upper"], bars.size[b[0] + k]["upper"]), bars.hand(a[0] + k, b[0] + k, "upper")[2]) for k in range(size)]
        notes = sum(count for count, _ in weights)
        alike = sum(count * weight for count, weight in weights) / notes if notes else 0.0
        out = {"melody": round(alike * short, 3), "chords": chords["share"] if chords["kind"] != "transposed" else 0.0}
        sounding = sum(bars.notes[a[0]:a[0] + size]) >= 4
        if r["kind"] == "same" and a[1] == b[1] and sounding:
            out["kind"] = "same"
        elif r["kind"] == "transposed" and a[1] == b[1] and sounding:
            out.update(kind="transposed", shift=r["shift"])
        elif sounding and (out["melody"] >= MELODY_ALIKE or (out["chords"] >= CHORDS_HELP and out["melody"] >= MELODY_WITH_CHORDS)):
            out["kind"] = "varied"
        elif size >= 4 and a[1] == b[1] and sum(bars.notes[a[0]:a[0] + size // 2]) >= 4 and all(
                bars.hand(a[0] + k, b[0] + k, "upper")[0] in ("same", "rest") for k in range(size // 2)):
            out["kind"] = "varied"          # the first half is the same melody: the section starts over and ends otherwise
        else:
            out["kind"] = "different"
        return out

    edges = sorted(cuts) + [n]
    edges = [e for k, e in enumerate(edges) if e in (0, n) or edges[k + 1] - e > 2]        # a bar or two after a mark stay with what came before
    parts: list[tuple[int, int]] = []
    for a, z in zip(edges, edges[1:]):
        parts += [(a + at, length) for at, length in units(z - a, lambda x, y: relate((a + x[0], x[1]), (a + y[0], y[1]))["kind"] in ("same", "varied"))]
    # a part of one or two bars joins the one before it (a second ending standing alone, a final bar)
    joined: list[tuple[int, int]] = []
    for at, length in parts:
        if joined and length <= 2:
            joined[-1] = (joined[-1][0], joined[-1][1] + length)
        else:
            joined.append((at, length))
    parts = joined
    word_at = sorted(region)
    firsts: list[tuple[str, tuple[int, int]]] = []
    sections: list[dict] = []
    used: set[str] = set()
    offset = next((k for k, m in enumerate(measures) if m["chords"]), len(measures))       # written bars before the first chord symbol
    total_notes = len(piece["notes"])
    for k, (at, length) in enumerate(parts):
        word = next((region[w] for w in reversed(word_at) if w <= at), None)
        best = None
        for label, first in firsts:
            r = relate(first, (at, length))
            if r["kind"] in ("same", "varied") and (best is None or r["melody"] > best[1]["melody"]):
                best = (label, r, first)
        moved = next(((label, r, first) for label, first in firsts if (r := relate(first, (at, length)))["kind"] == "transposed"), None)
        if word == "verse" and "chorus" in region.values():
            label = "verse"
        elif best:
            label = best[0]
        else:
            label = _letter(used)
            used.add(label)
            firsts.append((label, (at, length)))
        written = [order[p] for p in range(at, at + length)]
        if k == 0 and lead:
            written = list(range(lead)) + written           # the pickup goes with the first section
        runs: list[list[int]] = []
        for i in written:
            if runs and runs[-1][1] == i - 1:
                runs[-1][1] = i
            else:
                runs.append([i, i])

        def note_end(i: int) -> int:
            return (measures[i + 1]["notes"] if i + 1 < len(measures) else total_notes) - 1

        s = {"n": k + 1, "label": label, "bars": [at + 1, at + length], "length": length,
             "written": [[a + 1 - lead, z + 1 - lead] for a, z in runs],
             "notes": [[measures[a]["notes"], note_end(z)] for a, z in runs if note_end(z) >= measures[a]["notes"]],
             "chords": [[max(a - offset, 0), z - offset] for a, z in runs if z >= offset]}
        if best and label != "verse":
            first_n = next(x["n"] for x in sections if x["label"] == label) if any(x["label"] == label for x in sections) else None
            if first_n:
                s["like"] = {"of": first_n, "kind": "same" if best[1]["kind"] == "same" else "varied"}
        elif moved and label != "verse":
            first_n = next((x["n"] for x in sections if x["label"] == moved[0]), None)
            if first_n:
                s["like"] = {"of": first_n, "kind": "transposed", "shift": moved[1]["shift"]}
        if seen_chord:
            if is_blues(toks[at:at + length]):
                s["blues"] = is_blues(toks[at:at + length])
            keys = key_areas([chord_bars[i] for i in order[at:at + length]], chord_bars[order[(at + length) % n]], lib.parse_key(piece.get("key", "")))
            if keys:
                s["keys"] = keys
        sections.append(s)
    # the whole form printed or repeated twice is given once
    half = len(sections) // 2
    twice = half >= 1 and len(sections) % 2 == 0 and all(
        x["label"] == y["label"] and x["length"] == y["length"] for x, y in zip(sections[:half], sections[half:]))
    if twice:
        sections, n = sections[:half], sections[half - 1]["bars"][1]
    out: dict = {"letters": "print and computed" if print_marks else "computed", "form": form_letters(sections), "bars": n, "sections": sections}
    if twice:
        out["twice"] = True
    chorus = [s for s in sections if s["label"] not in EXTRA]
    if chorus and all(s.get("blues") for s in chorus):
        out["blues"] = chorus[0]["blues"]
    if piece.get("key"):
        out["key"] = piece["key"]
    marks = [word for word, has in (("repeat signs", any(m.get("backward") for m in measures)), ("endings", any(m.get("ending") for m in measures)),
                                    ("double bars", any(m.get("double") for m in measures)),
                                    ("the words Verse and Chorus", bool(region))) if has]
    jumps = sorted({j for m in measures for j in m.get("jumps", [])})
    out["made"] = ((f"The print has {', '.join(marks)}: unfolded here into the order played and cut there, then into eight-bar units. "
                    if print_marks else "The print marks no sections. ")
                   + "Letters computed from melody and chords: a suggestion, not a published form. Whole bars only.")
    if twice:
        out["made"] += " The whole form comes twice in the print; it is given once."
    if jumps:
        out["made"] += f" The print also has {', '.join(jumps)}: not followed here."
    out["practice_order"] = practice(out, "melody")
    return out


# --- the same tune as changes and as a lead sheet ---

def _title(text: str) -> str:
    text = re.sub(r"\([^)]*\)", " ", lib._plain(text))
    text = re.sub(r",\s*(the|a|an)\s*$", "", text.strip())
    text = re.sub(r"^(the|a|an)\s+", "", text.replace("&", " and "))
    return re.sub(r"[^a-z0-9]+", "", text)


def _names(composer: str) -> set[str]:
    return {w for w in re.split(r"[^a-z]+", lib._plain(composer)) if len(w) >= 4}


def eights(bars: list[tuple]) -> str:
    """A chorus of chords as letters of eight-bar units (computed: a unit like an earlier one but for its
    ending shares its letter), so that a form the source gives as AB in sixteens compares with ABAC."""
    parts = [bars[k:k + UNIT] for k in range(0, len(bars) - len(bars) % UNIT, UNIT)] or [bars]
    if len(bars) % UNIT and len(bars) > UNIT:
        parts[-1] = parts[-1] + bars[len(parts) * UNIT:]
    letters: list[str] = []
    for k, part in enumerate(parts):
        twin = next((j for j in range(k) if compare(parts[j], part)["kind"] in ("same", "ending", "varied")), None)
        letters.append(letters[twin] if twin is not None else _letter(set(letters)))
    return "".join(letters)


def _canon(letters: str) -> str:
    seen: dict[str, str] = {}
    return "".join(seen.setdefault(c, "ABCDEFGHJKLMNOPQRSTUWXYZ"[len(seen) % 24]) for c in letters)


def agreement(changes: dict, sheet: dict) -> tuple[str, str]:
    """Do the forms of a standard's outline and a lead sheet's agree? (verdict, words). Verdicts: agree |
    agree in units (the same in eight-bar units, or one written in bars of half the length) | chorus (the
    lead sheet has more before the chorus) | differ."""
    def chorus(o: dict) -> int:
        return sum(s["length"] for s in o["sections"] if s["label"] not in EXTRA)

    a, b = _canon(changes["form"]), _canon(sheet["form"])
    bars_a, bars_b = chorus(changes), chorus(sheet)
    scale = bars_a == bars_b or bars_a == 2 * bars_b or bars_b == 2 * bars_a
    if a == b and bars_a == bars_b:
        return "agree", "the same form"
    if a == b and abs(bars_a - bars_b) <= 2:
        return "agree", "the same form (the lead sheet counts a bar or two more or less: a pickup, a final bar)"
    if a == b and scale:
        return "agree in units", "the same form, one of them written in bars of half the length"
    fine = _canon(changes.get("eights", ""))
    if fine == b and (scale or abs(bars_a - bars_b) <= 2):
        return "agree in units", f"the same form when the changes are read in eight-bar units ({fine})"
    for k in range(1, len(sheet["sections"])):
        tail = {"form": form_letters(sheet["sections"][k:]), "sections": sheet["sections"][k:]}
        if _canon(tail["form"]) == a and chorus(tail) in (bars_a, 2 * bars_a):
            return "chorus", f"the lead sheet has {chorus(sheet) - chorus(tail)} bars (a verse) before the chorus, which has the same form"
    return "differ", "the two forms differ"


def link(standards: list[dict], sheets: list[dict]) -> list[dict]:
    """Mark a standard and a lead sheet of the same tune in both outlines (`same_tune`): the same title
    without articles, brackets and punctuation, and a composer's name in common where both name one.
    Returns the pairs with their verdict, for reporting."""
    by_title: dict[str, list[dict]] = {}
    for piece in standards:
        by_title.setdefault(_title(piece["title"]), []).append(piece)
    pairs: list[dict] = []
    for sheet in sheets:
        for piece in by_title.get(_title(sheet["title"]), []):
            a, b = _names(piece.get("composer", "")), _names(sheet.get("composer", ""))
            if a and b and not a & b:
                pairs.append({"changes": piece["id"], "melody": sheet["id"], "verdict": "not linked", "says": "the same title, another composer"})
                continue
            if not piece.get("outline") or not sheet.get("outline"):
                continue
            verdict, says = agreement(piece["outline"], sheet["outline"])
            for mine, other in ((piece, sheet), (sheet, piece)):
                if "same_tune" not in mine["outline"]:
                    mine["outline"]["same_tune"] = {"id": other["id"], "what": "the lead sheet with the melody" if other is sheet else "the chord changes",
                                                    "form": form_words(other["outline"]), "agrees": verdict, "says": says}
            pairs.append({"changes": piece["id"], "melody": sheet["id"], "verdict": verdict, "says": says,
                          "forms": [form_words(piece["outline"]), form_words(sheet["outline"])]})
    return pairs


# --- for the tutor ---

def overview(outline: dict) -> dict:
    """The outline as the tutor reads it: the form in a line, a line per section, the practice order."""
    sections = outline["sections"]
    letters = [s["label"] for s in sections if s["label"] not in EXTRA]
    lines = []
    for s in sections:
        like = _melody_like(s, sections) if "written" in s else _like_words(s, sections)
        own = not s.get("like") or s["like"]["kind"] not in ("same", "ending")
        said = [x for x in (like, f"a {s['blues']}-bar blues" if s.get("blues") and not outline.get("blues") else None,
                            s.get("sequence") if own else None, ", ".join(s["keys"]) if s.get("keys") and own else None,
                            "named here" if s.get("computed") and outline["letters"].startswith("source") else None) if x]
        where = _span(*s["bars"])
        printed = [[max(a, 1), z] for a, z in s.get("written", [])]         # bar 0 is the pickup
        if printed and printed != [s["bars"]]:
            where += " (printed " + ", ".join(f"{a}-{z}" if z > a else str(a) for a, z in printed) + ")"
        bridge = s["label"] == "B" and has_bridge("".join(letters))
        lines.append(f"{s['n']}. {s['label']}{' (the bridge)' if bridge else ''}, {where}" + (": " + "; ".join(said) if said else ""))
    out = {"form": form_words(outline), **({"key": outline["key"]} if outline.get("key") else {}), "sections": lines}
    if outline.get("same_tune"):
        same = outline["same_tune"]
        out["same_tune"] = f"{same['what']}: {same['id']} ({same['form']}); {same['says']}"
    out["practice_order"] = outline["practice_order"]
    out["made"] = outline["made"]
    return out


HOW = ("get with section = a letter (A; A2 = the second A; bridge) or its number gives that section with the usual options; improvise "
       "takes id and section to loop it. Bars are counted through the form as played.")


def _melody_like(s: dict, sections: list[dict]) -> str:
    like = s.get("like")
    if not like:
        return ""
    of = sections[like["of"] - 1]
    name = f"section {of['n']}"
    if like["kind"] == "same":
        return f"the same melody as {name}"
    if like["kind"] == "transposed":
        up = like["shift"] > 0
        size = abs(like["shift"])
        words = "an octave" if size == 12 else _UP.get(size if size <= 6 else 12 - size, f"{size} half steps") if size < 12 else f"{size} half steps"
        if 6 < size < 12:
            words = {7: "a fifth", 8: "a minor sixth", 9: "a major sixth", 10: "a minor seventh", 11: "a major seventh"}[size]
        return f"the melody of {name} {words} {'higher' if up else 'lower'}"
    return f"the melody of {name}, varied"


def find_section(outline: dict, section) -> dict:
    """The section with this number, letter ("A": the first A; "A2": the second), or name (bridge, intro,
    verse, coda); ValueError says what there is."""
    sections = outline["sections"]
    text = str(section).strip()
    if text.isdigit() and 1 <= int(text) <= len(sections):
        return sections[int(text) - 1]
    want = text.lower()
    if want in ("bridge", "middle eight", "middle 8", "release"):
        letters = [s["label"] for s in sections if s["label"] not in EXTRA]
        once = [s for s in sections if s["label"] not in EXTRA and s["label"] != letters[0] and letters.count(s["label"]) == 1] if letters else []
        if once and len(set(letters)) == 2:
            return once[0]
        want = "b"
    m = re.fullmatch(r"([a-z]+)\s*(\d+)?", want)
    if m:
        named = [s for s in sections if s["label"].lower() == m.group(1)]
        k = int(m.group(2) or 1)
        if named and 1 <= k <= len(named):
            return named[k - 1]
    listing = ", ".join(f"{s['n']} ({s['label']}, {_span(*s['bars'])})" for s in sections)
    raise ValueError(f"there is no section '{section}'. Sections: {listing}")
