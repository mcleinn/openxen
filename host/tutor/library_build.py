"""Convert the downloaded music collections into the tutor's library.

    python -m tutor.library_build            (from host/)

Reads `reference/music/` (third-party material, never committed; see reference/SOURCES.md):

  symbtr/txt/*.txt                     SymbTr 2.4.3, Turkish makam music, CC BY-NC-SA 4.0
                                       (Karaosmanoglu, ISMIR 2012). Pitches are 53 steps per
                                       octave already: step above C0 = Koma53 - 53.
  gregobase/gregobasecorpus-v0.4.zip   GregoBaseCorpus, Gregorian chant in GABC, CC0.
  jazz/JazzStandards.json              github.com/mikeoliphant/JazzStandards: the chord changes
                                       of 1,382 standards (from the iReal Pro community
                                       database), no licence stated. Changes only, no melodies.
  jazz/OpenEWLD.zip                    github.com/00sapo/OpenEWLD: 502 lead sheets (melody and
                                       chords, MusicXML) from the former Wikifonia. Not all of
                                       them are free of copyright everywhere; this folder is
                                       private reference material and is not distributed.

Writes `build/tutor-library/`: `index.json` (one entry per piece, no notes) and one
`<collection>.jsonl` with the notes. A piece is

    {"id", "title", "tradition", "mode", "form", "meter", "level", "source", "licence",
     "tuning": 53 or null (any tuning: notes are spelled names),
     "notes": [[pitch, beats], ...]      pitch: steps above C0 (fixed tuning), a note name
                                         ("Bb3"), or null for a rest
     "theory": {"index": pitch}          makam only: where the written theory (Arel-Ezgi-
                                         Uzdilek) differs from the practice value in "notes"
     "phrases": [[first, last], ...],    note indices, both included
     "key": "Gmin",                      jazz only
     "changes": [{"label": "A", "bars": [["Cm7"], ["F7"], ["Gm7", "Gb7"], ...]}, ...]}
                                         jazz only: the form with repeats and endings written
                                         out, chord symbols per bar (evenly spread in the bar)

Levels 1 (first pieces) to 5 are a rough grading by form, length and range; see `_level_*`.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "reference" / "music"
OUT = ROOT / "build" / "tutor-library"

MAX_PHRASE = 12     # notes; longer stretches are cut at a bar line or a long note
MIN_NOTES = 6


def cut_phrases(notes: list, breaks: set[int]) -> list[list[int]]:
    """Phrases end at rests and at the given break positions (index of the note after the
    break); stretches longer than MAX_PHRASE are cut at their longest note."""
    phrases: list[list[int]] = []
    start = None
    for i, (pitch, _) in enumerate(notes):
        if pitch is None or (i in breaks and start is not None and i - start >= 3):
            if start is not None and i - 1 >= start:
                phrases.append([start, i - 1])
            start = None if pitch is None else i
        elif start is None:
            start = i
    if start is not None:
        phrases.append([start, len(notes) - 1])
    out: list[list[int]] = []
    for a, b in phrases:
        while b - a + 1 > MAX_PHRASE:
            # cut after the longest note in the middle part
            window = range(a + 3, min(a + MAX_PHRASE, b - 2))
            cut = max(window, key=lambda i: (notes[i][1], -abs(i - (a + 7)))) if len(window) else a + MAX_PHRASE - 1
            out.append([a, cut])
            a = cut + 1
        out.append([a, b])
    return [p for p in out if p[1] >= p[0]]


# --- SymbTr ---

FORMS = {"ornek_oz": ("teaching example", 1), "seyir": ("seyir (the makam's melodic path)", 2), "etud": ("study", 2),
         "turku": ("folk song", 3), "sarki": ("song", 4), "ilahi": ("hymn", 3), "aranagme": ("interlude", 3)}
EASY_USUL = ("sofyan", "duyek", "nimsofyan", "semai", "serbest")


def _words(slug: str) -> str:
    return slug.replace("_", " ").strip().title()


def symbtr_piece(path: Path) -> dict | None:
    parts = path.stem.split("--")
    if len(parts) < 5:
        return None
    makam, form, usul, title, composer = parts[:5]
    notes: list = []
    theory: dict[str, int] = {}
    breaks: set[int] = set()
    meter = _words(usul)
    with path.open(encoding="utf-8", errors="replace") as f:
        header = f.readline().rstrip("\n").split("\t")
        col = {name: i for i, name in enumerate(header)}
        need = ("Kod", "Koma53", "KomaAE", "Pay", "Payda", "Offset")
        if any(n not in col for n in need):
            return None
        last_measure = None
        for line in f:
            row = line.rstrip("\n").split("\t")
            if len(row) < len(header):
                continue
            try:
                kod, k53, kae = int(row[col["Kod"]]), int(row[col["Koma53"]]), int(row[col["KomaAE"]])
                pay, payda = int(row[col["Pay"]]), int(row[col["Payda"]])
                offset = float(row[col["Offset"]] or 0)
            except ValueError:
                continue
            if kod == 51:
                if not notes and "Soz1" in col and row[col["Soz1"]].strip():
                    meter = row[col["Soz1"]].strip()
                    if payda and "(" not in meter:
                        meter = f"{meter} ({pay}/{payda})"
                continue
            if kod not in (9, 7, 12, 23) or payda <= 0 or pay <= 0:
                continue        # grace notes and control rows
            beats = round(4.0 * pay / payda, 3)
            if k53 < 0:
                if notes and notes[-1][0] is None:
                    notes[-1][1] = round(notes[-1][1] + beats, 3)
                else:
                    notes.append([None, beats])
            else:
                measure = int(offset - 1e-9)
                if last_measure is not None and measure != last_measure:
                    breaks.add(len(notes))
                notes.append([k53 - 53, beats])
                if kae >= 0 and kae != k53:
                    theory[str(len(notes) - 1)] = kae - 53
            last_measure = int(offset - 1e-9) if k53 >= 0 else last_measure
    sounding = [p for p, _ in notes if p is not None]
    if len(sounding) < MIN_NOTES:
        return None
    form_words, level = FORMS.get(form, (_words(form), 5))
    span = max(sounding) - min(sounding)
    if span > 80:
        level += 1
    if not usul.startswith(EASY_USUL) and level < 5:
        level += 1 if form in ("turku", "sarki", "ilahi") else 0
    return {
        "id": f"makam/{path.stem}",
        "title": _words(title) if title and not title.isdigit() else f"{_words(makam)} {form_words.split(' (')[0]} {title}".strip(),
        "tradition": "makam", "mode": _words(makam), "form": form_words, "meter": meter,
        "composer": _words(composer) if composer else "", "level": min(level, 5), "tuning": 53,
        "source": "SymbTr 2.4.3", "licence": "CC BY-NC-SA 4.0",
        "notes": notes, "theory": theory, "phrases": cut_phrases(notes, breaks),
    }


# --- Gregorian chant (GABC) ---

LETTERS = "CDEFGAB"
_LINE_POSITION = {1: 3, 2: 5, 3: 7, 4: 9}       # staff line -> position (a = 0 ... m = 12)
_CLEF = re.compile(r"^(c|f)(b?)([1-4])$")
_NOTE = re.compile(r"([a-mA-M])([xy#]?)")
PART_NAMES = {"an": "antiphon", "hy": "hymn", "in": "introit", "gr": "gradual", "al": "alleluia", "of": "offertory",
              "co": "communion", "re": "responsory", "ky": "Kyrie", "ps": "psalm tone", "se": "sequence", "tr": "tract",
              "ca": "canticle", "va": "varia", "or": "toni communes", "pr": "preface", "im": "improperia", "rb": "short responsory"}


def gabc_notes(gabc: str) -> tuple[list, set[int]] | None:
    """Notes of a GABC body as [name, beats] with the phrase breaks its bars give. One
    beat per note, two for a dotted one. Staff positions are read with the clef; a flat
    sign holds until the next bar, a flat in the clef throughout."""
    notes: list = []
    breaks: set[int] = set()
    clef: tuple[int, int] | None = None     # (diatonic number of the clef note, its position)
    clef_flat = False
    flat = False
    for group in re.findall(r"\(([^)]*)\)", gabc):
        g = group.strip()
        m = _CLEF.match(g)
        if m:
            base = 4 * 7 + 0 if m.group(1) == "c" else 3 * 7 + 3        # C4, or F3
            clef, clef_flat = (base, _LINE_POSITION[int(m.group(3))]), bool(m.group(2))
            continue
        if not g:
            continue
        if g[0] in ",;:`" or g.startswith("z"):
            flat = False
            if notes:
                breaks.add(len(notes))
            continue
        if clef is None:
            return None
        g = re.sub(r"\[[^\]]*\]", "", g)        # annotations
        g = re.sub(r"[a-m]\+", "", g)           # custos
        i = 0
        while i < len(g):
            m = _NOTE.match(g, i)
            if not m:
                if g[i] == "." and notes:
                    notes[-1][1] = 2.0
                i += 1
                continue
            i = m.end()
            position = "abcdefghijklm".index(m.group(1).lower())
            if m.group(2) == "x":
                flat = True
                continue
            if m.group(2) in ("y", "#"):
                flat = False if m.group(2) == "y" else flat
                continue
            diatonic = clef[0] + position - clef[1]
            octave, letter = divmod(diatonic, 7)
            name = LETTERS[letter]
            if name == "B" and (flat or clef_flat):
                name = "Bb"
            notes.append([f"{name}{octave}", 1.0])
    return notes, breaks


def chant_pieces(zip_path: Path):
    with zipfile.ZipFile(zip_path) as z, z.open("csv/chants.csv") as raw:
        for row in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8")):
            try:
                body = json.loads(row["gabc"]) if row["gabc"].startswith('"') else row["gabc"]
            except ValueError:
                continue
            if not body or not isinstance(body, str):
                continue
            parsed = gabc_notes(body)
            if not parsed:
                continue
            notes, breaks = parsed
            if not MIN_NOTES <= len(notes) <= 600:
                continue
            index = {n: LETTERS.index(n[0]) + 7 * int(n[-1]) for n, _ in notes}
            span = max(index.values()) - min(index.values())
            if span > 12:       # more than an octave and a fifth: a misread clef or not a chant melody
                continue
            level = 1 if (len(notes) <= 45 and span <= 6) else 2 if len(notes) <= 90 else 3 if len(notes) <= 200 else 4
            part = PART_NAMES.get((row.get("office_part") or "").strip(), (row.get("office_part") or "chant").strip() or "chant")
            mode = (row.get("mode") or "").strip()
            title = re.sub(r"\s*\([^)]*\)\s*$", "", (row.get("incipit") or "").strip()) or f"Chant {row['id']}"
            yield {
                "id": f"chant/{int(row['id']):05d}", "title": title, "tradition": "chant",
                "mode": f"mode {mode}" if mode else "", "form": part, "meter": "free", "composer": "",
                "level": level, "tuning": None, "source": f"GregoBase {row['id']} ({(row.get('version') or '').strip()})",
                "licence": "CC0", "notes": notes, "theory": {}, "phrases": cut_phrases(notes, breaks),
            }


# --- jazz: chord changes ---

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _bars(chords: str) -> list[list[str]]:
    out = []
    for bar in chords.split("|"):
        symbols = [re.sub(r"\([^)]*\)", "", c).strip() for c in bar.split(",")]      # "(Gm7)" is an alternative
        symbols = [c for c in symbols if c]
        if symbols:
            out.append(symbols)
    return out


def _changes_level(bars: list[list[str]], rhythm: str) -> int:
    distinct = len({c for bar in bars for c in bar})
    busy = sum(len(bar) > 2 for bar in bars)
    level = 1 if (len(bars) <= 16 and distinct <= 4) else 2 if distinct <= 7 else 3 if distinct <= 11 else 4 if distinct <= 16 else 5
    if "Up" in rhythm or busy > 4:
        level += 1
    return min(level, 5)


def jazz_changes(path: Path):
    seen: dict[str, int] = {}
    for tune in json.loads(path.read_text(encoding="utf-8")):
        sections = []
        for section in tune.get("Sections", []):
            main = _bars((section.get("MainSegment") or {}).get("Chords", ""))
            endings = [_bars(e.get("Chords", "")) for e in section.get("Endings") or []]
            if endings:
                for n, ending in enumerate(endings, 1):
                    sections.append({"label": f"{section.get('Label', '')} (ending {n})".strip(), "bars": main + ending})
            else:
                sections.append({"label": section.get("Label", ""), "bars": main})
                for _ in range(int(section.get("Repeats", 0) or 0)):
                    sections.append({"label": f"{section.get('Label', '')} (repeat)".strip(), "bars": main})
        sections = [s for s in sections if s["bars"]]
        if not sections:
            continue
        bars = [bar for s in sections for bar in s["bars"]]
        slug = _slug(tune["Title"])
        seen[slug] = seen.get(slug, 0) + 1
        yield {
            "id": f"jazz/{slug}" + (f"-{seen[slug]}" if seen[slug] > 1 else ""), "title": tune["Title"], "tradition": "jazz",
            "mode": tune.get("Key", ""), "form": tune.get("Rhythm", ""), "meter": tune.get("TimeSignature") or "4/4",
            "composer": tune.get("Composer", ""), "level": _changes_level(bars, tune.get("Rhythm", "")), "tuning": None,
            "source": "JazzStandards (iReal Pro community changes)", "licence": "chord changes; private use",
            "key": tune.get("Key", ""), "notes": [], "theory": {}, "phrases": [], "changes": sections, "bars": len(bars),
        }


# --- jazz: lead sheets (MusicXML) ---

_KINDS = {"major": "", "minor": "m", "dominant": "7", "major-seventh": "maj7", "minor-seventh": "m7", "diminished": "dim",
          "diminished-seventh": "07", "half-diminished": "m7b5", "augmented": "aug", "major-sixth": "6", "minor-sixth": "m6",
          "dominant-ninth": "9", "major-ninth": "maj9", "minor-ninth": "m9", "suspended-fourth": "sus", "suspended-second": "sus",
          "augmented-seventh": "7#5", "major-minor": "mmaj7", "dominant-11th": "9sus", "dominant-13th": "13", "minor-11th": "m11",
          "major-13th": "maj7", "minor-13th": "m7", "power": "", "none": ""}
_ALTER = {-2: "bb", -1: "b", 0: "", 1: "#", 2: "##"}


def leadsheet(xml: bytes) -> dict | None:
    """Melody (first part, first voice) and chords of a MusicXML lead sheet."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    part = root.find("part")
    if part is None:
        return None
    title = (root.findtext("movement-title") or root.findtext("work/work-title") or "").strip()
    composer = (root.findtext("identification/creator[@type='composer']") or "").strip()
    divisions, beats, beat_type, fifths, mode = 1, 4, 4, 0, "major"
    notes: list = []
    breaks: set[int] = set()
    bars: list[list[str]] = []
    tied = False
    for measure in part.findall("measure"):
        chords: list[str] = []
        for el in measure:
            if el.tag == "attributes":
                divisions = int(el.findtext("divisions") or divisions)
                beats = int(el.findtext("time/beats") or beats)
                beat_type = int(el.findtext("time/beat-type") or beat_type)
                if el.find("key") is not None:
                    fifths = int(el.findtext("key/fifths") or 0)
                    mode = el.findtext("key/mode") or mode
            elif el.tag == "harmony":
                step = el.findtext("root/root-step")
                if step:
                    alter = int(float(el.findtext("root/root-alter") or 0))
                    chords.append(step + _ALTER.get(alter, "") + _KINDS.get((el.findtext("kind") or "major").strip(), ""))
            elif el.tag == "note":
                if el.find("chord") is not None or el.find("grace") is not None or (el.findtext("voice") or "1") != "1":
                    continue
                length = round(int(el.findtext("duration") or 0) / divisions, 3)      # in quarter notes
                if length <= 0:
                    continue
                starts_tie = any(t.get("type") == "start" for t in el.findall("tie"))
                if el.find("rest") is not None:
                    if notes and notes[-1][0] is None:
                        notes[-1][1] = round(notes[-1][1] + length, 3)
                    else:
                        notes.append([None, length])
                    tied = False
                    continue
                name = el.findtext("pitch/step") + _ALTER.get(int(float(el.findtext("pitch/alter") or 0)), "") + (el.findtext("pitch/octave") or "4")
                if tied and notes and notes[-1][0] == name:
                    notes[-1][1] = round(notes[-1][1] + length, 3)
                else:
                    notes.append([name, length])
                tied = starts_tie
        bars.append(chords)
        breaks.add(len(notes))
    sounding = [n for n, _ in notes if n]
    if len(sounding) < MIN_NOTES or not title:
        return None
    # carry the chord of the bar before into bars without a symbol
    last: list[str] = []
    filled = []
    for chords in bars:
        last = chords or last[-1:]
        filled.append(list(last))
    filled = [b for b in filled if b]
    tonic = ["Cb", "Gb", "Db", "Ab", "Eb", "Bb", "F", "C", "G", "D", "A", "E", "B", "F#", "C#"][(fifths if mode != "minor" else fifths + 3) + 7]
    span = len({n for n in sounding})
    level = 2 if len(sounding) <= 70 and span <= 9 else 3 if len(sounding) <= 130 else 4
    # rests shorter than a beat do not end a phrase: join them to the note before
    joined: list = []
    for pitch, length in notes:
        if pitch is None and length < 1.0 and joined and joined[-1][0] is not None:
            joined[-1][1] = round(joined[-1][1] + length, 3)
        else:
            joined.append([pitch, length])
    return {
        "title": title, "tradition": "jazz", "mode": tonic + ("min" if mode == "minor" else ""), "form": "lead sheet with melody",
        "meter": f"{beats}/{beat_type}", "composer": composer, "level": level, "tuning": None,
        "source": "OpenEWLD (former Wikifonia)", "licence": "private use; copyright status varies by piece",
        "key": tonic + ("min" if mode == "minor" else ""), "notes": joined, "theory": {}, "phrases": cut_phrases(joined, set()),
        "changes": [{"label": "", "bars": filled}] if filled else [], "bars": len(filled),
    }


def leadsheets(zip_path: Path):
    seen: dict[str, int] = {}
    with zipfile.ZipFile(zip_path) as z:
        for name in sorted(n for n in z.namelist() if n.endswith(".mxl")):
            try:
                with zipfile.ZipFile(io.BytesIO(z.read(name))) as inner:
                    score = next(x for x in inner.namelist() if x.endswith(".xml") and not x.startswith("META-INF"))
                    piece = leadsheet(inner.read(score))
            except (zipfile.BadZipFile, StopIteration, ValueError):
                continue
            if not piece:
                continue
            slug = _slug(piece["title"])
            seen[slug] = seen.get(slug, 0) + 1
            piece["id"] = f"jazz/melody-{slug}" + (f"-{seen[slug]}" if seen[slug] > 1 else "")
            yield piece


# --- build ---

INDEX_FIELDS = ("id", "title", "tradition", "mode", "form", "meter", "composer", "level", "tuning", "source", "licence")


def build(source: Path = SOURCE, out: Path = OUT) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    index: list[dict] = []
    counts: dict[str, int] = {}

    def write(collection: str, pieces) -> None:
        n = 0
        with (out / f"{collection}.jsonl").open("w", encoding="utf-8", newline="\n") as f:
            for piece in pieces:
                if not piece or not (piece["phrases"] or piece.get("changes")):
                    continue
                at = f.tell()
                f.write(json.dumps(piece, ensure_ascii=False, separators=(",", ":")) + "\n")
                sounding = [p for p, _ in piece["notes"] if p is not None]
                entry = {k: piece[k] for k in INDEX_FIELDS}
                entry.update(file=f"{collection}.jsonl", at=at, notes=len(sounding), phrases=len(piece["phrases"]))
                if piece.get("changes"):
                    entry["bars"] = piece.get("bars", 0)
                if piece["tuning"] and sounding:
                    entry["low"], entry["high"] = min(sounding), max(sounding)
                index.append(entry)
                n += 1
        counts[collection] = n

    symbtr = source / "symbtr" / "txt"
    if symbtr.is_dir():
        write("makam", (symbtr_piece(p) for p in sorted(symbtr.glob("*.txt"))))
    chant = source / "gregobase" / "gregobasecorpus-v0.4.zip"
    if chant.exists():
        write("chant", chant_pieces(chant))
    jazz = source / "jazz"
    if (jazz / "JazzStandards.json").exists():
        write("jazz", jazz_changes(jazz / "JazzStandards.json"))
        from . import harmony       # what follows what, counted over these tunes
        stats = harmony.statistics(list(jazz_changes(jazz / "JazzStandards.json")))
        (out / "harmony.json").write_text(json.dumps(stats, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if (jazz / "OpenEWLD.zip").exists():
        write("jazz-melodies", leadsheets(jazz / "OpenEWLD.zip"))
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return counts


if __name__ == "__main__":
    result = build()
    if not result:
        print(f"nothing found under {SOURCE}; see docs/tutor.md for what to download", file=sys.stderr)
        sys.exit(1)
    for name, n in result.items():
        print(f"{name}: {n} pieces")
    print(f"written to {OUT}")
