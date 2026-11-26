"""Build the tutor's rhythm library from the researched reference.

    python -m tutor.rhythm_build [--source tala.json] [--out build/tutor-library]

Reads `reference/music/rhythm/tala.json` (third-party research, not in git; see REPORT.md and
SOURCES.md next to it) and writes `build/tutor-library/rhythm.json`, which `rhythm.py` loads:

    {"about": {...}, "patterns": {key: cycle}, "tabla_bols": {...}, "silent_bols": [...],
     "gati": [...], "lessons_without_strokes": [...], "counts": {...}}

A cycle:

    name        as the source writes it        aliases   other names it is found by
    tradition   hindustani | carnatic | makam  kind      theka | tala | lesson | usul
    pulses      equal parts of one cycle       beats     clicks per cycle (= pulses here)
    onsets      where the player taps          accents   the beats that are clapped
    what        one line in a player's words
    strokes     [{at, stroke, dur, loud}]: what the drum plays, at/dur in pulses; a stroke
                the source does not name has stroke null; `say` is the syllable spoken
    sections    [{at, length, mark, gesture, name}]: vibhag, angas or groups
    gestures    Carnatic: the hand gesture of every beat
    sources     as listed by the research
    confidence  how well it is sourced; `conflict` = what the sources disagree on
    variants    [{name, source, strokes or note, ...}]: other versions the sources give

Nothing is added to what the sources state except: the even split of a matra that holds
several bols (stated as the convention by the research), and the loudness of each stroke
(LOUD below: this project's choice, the sources give none). Conflicting cycles are kept and
marked, not resolved.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from fractions import Fraction
from pathlib import Path

from .percussion import MRIDANGAM_STROKES, tabla_bols
from .rhythm import squash

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "reference" / "music" / "rhythm" / "tala.json"
OUT = ROOT / "build" / "tutor-library"

# Loudness 0..1 of a stroke: this project's choice.
LOUD = {"first": 0.95, "section": 0.85, "beat": 0.7, "between": 0.6}
USUL_LOUD = {"dum": 0.9, "tek": 0.7, "hek": 0.8, "ta": 0.4}       # te, ke, ka and unnamed strokes: 0.55
ABOUT = {
    "from": "reference/music/rhythm/tala.json (see REPORT.md and SOURCES.md there)",
    "rule": "Only what the sources state. Conflicts are marked, not resolved.",
    "this_projects_choice": "the loudness of each stroke; one click per syllable in the mridangam lessons; "
                            "how bols without a recording are sounded (tabla_bols)",
}
_BOLS = re.compile(r"[A-Z][a-zÀ-ỿ]*|-")
_MATRA = re.compile(r"(?:\s*(?:[A-Z][a-zÀ-ỿ]*|-))+\s*")


class Unreadable(ValueError):
    """A theka that is not written bol by bol (a remark, an ellipsis, free text)."""


def key_of(name: str) -> str:
    text = name.split("(")[0].replace("ı", "i")
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _num(x: Fraction | float | int):
    x = float(x)
    return int(x) if x == int(x) else round(x, 4)


def _spread(part, at: Fraction, dur: Fraction, out: list) -> None:
    """A matra, or a share of one: a list is split evenly among its members, a string
    among its bols ("TiRaKiTa" = four); "-" is a rest."""
    if isinstance(part, list):
        if not part:
            raise Unreadable("empty")
        for i, member in enumerate(part):
            _spread(member, at + dur * i / len(part), dur / len(part), out)
        return
    if not isinstance(part, str) or not _MATRA.fullmatch(part):
        raise Unreadable(str(part))
    bols = _BOLS.findall(part)
    for i, bol in enumerate(bols):
        if bol != "-":
            out.append((at + dur * i / len(bols), dur / len(bols), bol))


def theka_strokes(theka, matras: int, starts: dict[int, str]) -> list[dict]:
    """The bols of a theka as strokes. `starts`: matra -> mark of the section beginning there."""
    if not isinstance(theka, list) or len(theka) != matras:
        raise Unreadable("not one entry per matra")
    found: list = []
    for i, matra in enumerate(theka):
        _spread(matra, Fraction(i), Fraction(1), found)
    strokes = []
    for at, dur, bol in found:
        loud = (LOUD["first"] if at == 0 else LOUD["section"] if at in starts and starts[int(at)] != "0"
                else LOUD["beat"] if at.denominator == 1 else LOUD["between"])
        strokes.append({"at": _num(at), "stroke": bol, "dur": _num(dur), "loud": loud})
    return strokes


def _list_words(numbers: list[int]) -> str:
    words = [str(n) for n in numbers]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def vibhag_sections(vibhag: list[int], marks: list[str]) -> list[dict]:
    sections, at = [], 0
    for length, mark in zip(vibhag, marks):
        wave = str(mark) == "0"
        sections.append({"at": at, "length": length, "mark": str(mark), "gesture": "wave" if wave else "clap",
                         "name": "khali" if wave else "sam" if at == 0 else "tali"})
        at += length
    if sections and sections[0]["mark"] == "0":
        sections[0]["name"] = "sam, on khali"
    return sections


def _confidence(text: str) -> tuple[str, str | None]:
    """(short class, what the sources disagree on or None) from the research's remark."""
    low = text.lower()
    conflict = text if ("conflict" in low or "no agreement" in low) else None
    if low.startswith("no agreement") or low.startswith("conflicting"):
        return "conflicting", conflict
    if "single source" in low[:40]:
        return "single source", conflict
    if low.startswith("no stroke source"):
        return "no stroke source found", conflict
    return "", conflict


def hindustani(t: dict) -> dict:
    matras = t["matras"]
    sections = vibhag_sections(t["vibhag"], t["tali_khali"])
    starts = {s["at"]: s["mark"] for s in sections}
    claps = [s["at"] for s in sections if s["gesture"] == "clap"]
    waves = [s["at"] for s in sections if s["gesture"] == "wave"]
    kind, conflict = _confidence(t.get("agreement", ""))
    what = f"{matras} matras, {'+'.join(str(v) for v in t['vibhag'])}"
    if sections and sections[0]["gesture"] == "wave":
        what += ": it begins with a wave"
        if claps:
            what += f"; clap on {_list_words([c + 1 for c in claps])}"
        if waves[1:]:
            what += f", wave on {_list_words([w + 1 for w in waves[1:]])}"
    else:
        what += f": clap on {_list_words([c + 1 for c in claps])}" + (f", wave on {_list_words([w + 1 for w in waves])}" if waves else "")
    out = {
        "name": t["name"], "aliases": list(t.get("aliases", [])), "tradition": "hindustani", "kind": "theka",
        "pulses": matras, "beats": matras, "onsets": list(range(matras)), "accents": claps, "what": what,
        "strokes": theka_strokes(t["theka"], matras, starts), "sections": sections,
        "sources": list(t.get("sources", [])), "confidence": kind or "confirmed by two or more sources",
        "agreement": t.get("agreement", ""),
    }
    if conflict:
        out["conflict"] = conflict
    variants = []
    for v in t.get("variants", []):
        entry = {"name": v.get("name", ""), "source": v.get("source", "")}
        if v.get("note"):
            entry["note"] = v["note"]
        n = v.get("matras", matras)
        same_length = n == matras
        division = v.get("vibhag") or (t["vibhag"] if same_length else [n])     # another length without a division: one section
        marks = v.get("tali_khali") or (t["tali_khali"] if same_length and "vibhag" not in v else ["X"] * len(division))
        theka = t["theka"] if v.get("theka") == "same bols" else v.get("theka")
        try:
            if sum(division) != n or len(division) != len(marks):
                raise Unreadable("division")
            v_sections = vibhag_sections(division, marks)
            entry["strokes"] = theka_strokes(theka, n, {s["at"]: s["mark"] for s in v_sections})
            if n != matras or "vibhag" in v or "tali_khali" in v:
                entry.update(pulses=n, beats=n, onsets=list(range(n)), sections=v_sections,
                             accents=[s["at"] for s in v_sections if s["gesture"] == "clap"])
        except Unreadable:
            entry.setdefault("note", "not written bol by bol in the research; see the source")
        variants.append(entry)
    out["variants"] = variants
    return out


ANGA = {"L": "laghu", "D": "drutam", "A": "anudrutam"}


def _gesture(word: str | None) -> str | None:
    if not word or word == "-":
        return None
    return word.split(":")[1] + " finger" if word.startswith("finger:") else word


def carnatic(t: dict) -> dict:
    n = t["aksharas"]
    kriya = t.get("kriya")
    gestures = [_gesture(k) for k in kriya] if kriya else None
    sections, at = [], 0
    if isinstance(t.get("angas"), list):
        for anga in t["angas"]:
            length = {"L": t.get("laghu_beats"), "D": 2, "A": 1}[anga]
            sections.append({"at": at, "length": length, "name": ANGA[anga]})
            at += length
        grouping = "+".join(str(s["length"]) for s in sections)
    else:
        m = re.match(r"\s*(\d+(?:\+\d+)+)", str(t.get("angas", "")))
        lengths = [int(x) for x in m.group(1).split("+")] if m else [n]
        if sum(lengths) != n:
            lengths = [n]
        for length in lengths:
            sections.append({"at": at, "length": length, "name": "group"})
            at += length
        grouping = "+".join(str(x) for x in lengths)
    for s in sections:
        if gestures:
            s["gestures"] = gestures[s["at"]:s["at"] + s["length"]]
    if gestures:
        accents = [i for i, g in enumerate(gestures) if g and g.startswith("clap")]
        confidence = "gestures derived from the rules of the tala's parts, not stated for this tala" if t.get("kriya_derived") else "stated by a source"
        what = f"{n} beats, {grouping}: clap on {_list_words([a + 1 for a in accents])}" if accents else f"{n} beats, {grouping}"
        waves = [i + 1 for i, g in enumerate(gestures) if g == "wave"]
        if waves:
            what += f", wave on {_list_words(waves)}"
        if any(g and g.endswith("finger") for g in gestures):
            what += ", finger counts between"
    else:
        accents = [s["at"] for s in sections]
        confidence = "no source gives the hand gestures"
        what = f"{n} beats, {grouping}; no source gives the hand gestures, the accents mark the groups"
    popular = t.get("popular_name") or ""
    aliases = []
    if popular and squash(popular) != squash(t["name"]):
        aliases.append(popular)
        aliases += [a.strip() for a in re.split(r"[(/)]", popular) if a.strip() and not re.search(r"\d", a)]
    out = {
        "name": t["name"], "aliases": list(dict.fromkeys(aliases)), "tradition": "carnatic", "kind": "tala",
        "pulses": n, "beats": n, "onsets": list(range(n)), "accents": accents, "what": what,
        "strokes": [], "sections": sections, "sources": list(t.get("sources", [])), "confidence": confidence,
        "variants": [],
    }
    if gestures:
        out["gestures"] = gestures
    note = "; ".join(str(t[k]) for k in ("kriya_note", "aksharas_note", "note") if t.get(k))
    if note:
        out["agreement"] = note
    if "conflict" in note.lower():
        out["conflict"] = note
    if t.get("kriya_alt"):
        out["variants"].append({"name": "other gestures", "gestures": [_gesture(k) for k in t["kriya_alt"]], "source": "",
                                "note": "a source gives these hand gestures instead"})
    if t.get("common"):
        out["common"] = True
    return out


def syllable_strokes(table: dict) -> dict[str, str]:
    """Syllables that the research maps onto exactly one mridangam stroke (the entries it
    calls context-dependent or conflicting are left out)."""
    out, unclear = {}, set()
    for names, entry in table.items():
        stroke = (entry or {}).get("stroke")
        for name in names.split("(")[0].split("/"):
            name = name.strip().lower()
            if not name:
                continue
            if stroke in MRIDANGAM_STROKES:
                out[name] = stroke
            else:
                unclear.add(name)
    return {name: stroke for name, stroke in out.items() if name not in unclear}


_SYLLABLE = re.compile(r"(\(?)([A-Za-z]+)\)?(?: x(\d+))?")
_STROKE = re.compile(r"([A-Za-z]+)(?:\([A-Za-z]+\))?(?: x(\d+))?")


def lesson(entry: dict, known: dict[str, str]) -> dict | None:
    """A solkattu lesson whose syllables and strokes are given one by one; None otherwise."""
    syllables, strokes = entry.get("syllables"), entry.get("strokes")
    if not (isinstance(syllables, list) and isinstance(strokes, list) and len(syllables) == len(strokes)):
        return None
    units: list[tuple[str | None, str | None]] = []
    ending = None
    for i, (syllable, stroke) in enumerate(zip(syllables, strokes)):
        syllable = str(syllable).strip()
        if syllable == "/" and stroke is None:      # a divider between two halves, not a rest
            continue
        if syllable in (",", ".", "-", ";"):
            units.append((None, None))
            continue
        m = _SYLLABLE.fullmatch(syllable)
        if not m:
            return None
        word, count = m.group(2), int(m.group(3) or 1)
        if stroke is None:
            name = known.get(word.lower())
        else:
            k = _STROKE.fullmatch(str(stroke).strip())
            if not k or k.group(1) not in MRIDANGAM_STROKES or int(k.group(2) or 1) != count:
                return None
            name = k.group(1)
        if m.group(1) and i == len(syllables) - 1:  # "(THA)": lands on the first beat of the next round
            ending = {"stroke": name, "say": word.capitalize(), "loud": LOUD["first"]}
            continue
        units += [(word.capitalize(), name)] * count
    if not units:
        return None
    n = len(units)
    out_strokes = [{"at": i, "stroke": name, "dur": 1, "loud": LOUD["first"] if i == 0 else LOUD["beat"], "say": word}
                   for i, (word, name) in enumerate(units) if word]
    said = " ".join(word or "-" for word, _ in units)
    what = f"mridangam lesson, {n} counts (- is a silent count): {said}" + (f"; it ends on {ending['say']} at the start of the next round" if ending else "")
    if entry.get("repeat_with"):
        what += "; then the same beginning with " + ", ".join(w.capitalize() for w in entry["repeat_with"])
    out = {
        "name": entry["name"], "aliases": [], "tradition": "carnatic", "kind": "lesson",
        "pulses": n, "beats": n, "onsets": [s["at"] for s in out_strokes], "accents": [0], "what": what,
        "strokes": out_strokes, "sections": [{"at": 0, "length": n, "name": "round"}],
        "sources": list(entry.get("sources", [])), "confidence": "strokes as given by the lesson's source",
        "variants": [],
    }
    if ending:
        out["ending"] = ending
    notes = [str(entry[k]) for k in ("speeds", "stroke_basis", "note") if entry.get(k)]
    if entry.get("tala"):
        notes.insert(0, f"in {entry['tala']} tala" + (f", {entry['gati']} gati" if entry.get("gati") else ""))
    out["agreement"] = "; ".join(notes)
    if any(s["stroke"] is None for s in out_strokes):
        out["conflict"] = "the source names no recorded stroke for " + ", ".join(sorted({s["say"] for s in out_strokes if s["stroke"] is None}))
    return out


def usul_strokes(strokes: list[dict]) -> list[dict]:
    out = []
    for s in strokes or []:
        name = s.get("stroke")
        out.append({"at": _num(s["at"]), "stroke": name, "dur": _num(s["dur"]),
                    "loud": LOUD["first"] if s["at"] == 0 else USUL_LOUD.get(name or "", 0.55)})
    return out


def _groups(grouping, pulses) -> list[dict]:
    lengths = grouping if grouping and sum(grouping) == pulses else [pulses]
    sections, at = [], 0
    for length in lengths:
        sections.append({"at": at, "length": length, "name": "group"})
        at += length
    return sections


def usul(u: dict) -> dict:
    pulses = u["pulses"]
    strokes = usul_strokes(u.get("strokes"))
    sections = _groups(u.get("grouping"), pulses)
    text = u.get("confidence", "")
    kind, conflict = _confidence(text)
    if not kind:
        kind = "confirmed by two independent sources" if text.lower().startswith("confirmed by two") else text
    said = " ".join(s["stroke"] or "(unnamed)" for s in strokes)
    grouping = "+".join(str(s["length"]) for s in sections)
    what = f"{pulses} pulses ({pulses}/{u.get('unit', '?')}), {grouping}" + (f": {said}" if strokes and len(strokes) <= 24 else
                                                                                f": {len(strokes)} strokes" if strokes else "; no source gives its strokes")
    display = u.get("display", u["name"])
    aliases = [display, u.get("symbtr_name", "")]
    if squash(display).startswith("kapali"):
        aliases.append("K. " + display.split(" ", 1)[-1])      # as SymbTr abbreviates it
    out = {
        "name": display, "aliases": [a for a in dict.fromkeys(aliases) if a], "tradition": "makam", "kind": "usul",
        "pulses": pulses, "beats": pulses, "unit": u.get("unit"),
        "onsets": sorted({s["at"] for s in strokes}) or list(range(pulses)),
        "accents": [s["at"] for s in sections], "what": what, "strokes": strokes, "sections": sections,
        "sources": list(u.get("sources", [])), "confidence": kind, "agreement": "; ".join(x for x in (text, u.get("notes", "")) if x),
        "variants": [],
    }
    if conflict:
        out["conflict"] = conflict
    if any(s["stroke"] is None for s in strokes):
        out["unnamed_strokes"] = "the source gives the lengths of the strokes but not their names"
    for v in u.get("variants") or []:
        entry = {"name": v.get("label", ""), "source": "", "strokes": usul_strokes(v.get("strokes"))}
        if v.get("grouping"):
            entry["sections"] = _groups(v["grouping"], pulses)
            entry["accents"] = [s["at"] for s in entry["sections"]]
        entry["onsets"] = sorted({s["at"] for s in entry["strokes"]})
        out["variants"].append(entry)
    return out


def convert(tala: dict) -> dict:
    """The whole reference as the tutor's rhythm library."""
    patterns: dict[str, dict] = {}

    def add(cycle: dict, key: str | None = None) -> None:
        key = key or key_of(cycle["name"])
        while key in patterns:
            key += "_2"
        patterns[key] = cycle

    for t in tala.get("hindustani", []):
        add(hindustani(t))
    for t in tala.get("carnatic", []):
        add(carnatic(t))
    known = syllable_strokes(tala.get("syllable_to_stroke", {}))
    text_only = []
    for entry in tala.get("solkattu_lessons", []):
        made = lesson(entry, known)
        if made:
            add(made)
        else:
            text_only.append({k: entry[k] for k in ("name", "tala", "gati", "syllables", "strokes", "speeds", "note", "sources") if entry.get(k)})
    for u in tala.get("usul", []):
        add(usul(u), key_of(u["name"]))

    bols = {s["stroke"] for c in patterns.values() if c["tradition"] == "hindustani"
            for group in [c["strokes"]] + [v.get("strokes", []) for v in c["variants"]] for s in group}
    table, silent = tabla_bols(bols, tala.get("tabla_bol_timbre_classes", {}))
    counts: dict[str, int] = {}
    for c in patterns.values():
        label = c["tradition"] + " " + c["kind"]
        counts[label] = counts.get(label, 0) + 1
    return {
        "about": {**ABOUT, "generated_from": (tala.get("_about") or {}).get("generated", "")},
        "counts": counts,
        "patterns": patterns,
        "tabla_bols": table,
        "silent_bols": silent,
        "syllable_strokes": known,
        "gati": [{"name": g["name"], "per_beat": g["per_beat"], "syllables": g.get("syllables", {}), **({"note": g["note"]} if g.get("note") else {})}
                 for g in tala.get("gati", [])],
        "lessons_without_strokes": text_only,
    }


def build(source: Path = SOURCE, out: Path = OUT) -> dict:
    data = convert(json.loads(Path(source).read_text(encoding="utf-8")))
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "rhythm.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return data


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--source", type=Path, default=SOURCE)
    p.add_argument("--out", type=Path, default=OUT)
    args = p.parse_args()
    result = build(args.source, args.out)
    print(", ".join(f"{n} {what}" for what, n in result["counts"].items()), f"-> {args.out / 'rhythm.json'}")
    if result["silent_bols"]:
        print("bols without a sound (variants only are affected if the list is short):", ", ".join(result["silent_bols"]))
