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


# --- scores: pieces in two staves, read from engraved scores ---

# Machine-readable scores under reference/music/, each `{"title", "composer", "tuning", "bars": [{"n", "time",
# "staves": {"upper": [{"beat", "dur", "notes": [{"step"}]}], "lower": [...]}}]}` (beat = 1 + quarter notes into
# the bar; step = steps of the piece's tuning above its lowest reference). How each was made is in its folder.
# Where two sources differ (the print and a recording), a note carries both readings:
# `{"step": 48, "source": "print", "also": [{"step": 47, "source": "recording"}]}`; they are kept per bar
# as `variants` and handed to the tutor with the bar.
SCORES = [
    ("woyten16/dont_take_five.json", "dont-take-five", 4, "read from the MuseScore PDF (transcription by Stephen Weigel)"),
    ("woyten/final/ephemeral_happiness.json", "ephemeral-happiness", 4, "optical recognition of the score, accidentals revised"),
]

# How far each transcription was checked: this project's own judgement from the verification notes kept with
# each piece (reference/music/*/VERIFY.md, REPAIR.md, REPORT.md, verification_per_bar.txt). Three grades:
#   well checked  most notes confirmed against a recording, hardly any contradicted
#   partly checked  most notes confirmed, known doubtful bars
#   unverified    a recording could not confirm most notes, or contradicts many that nobody looked into
# None of them is proofread by a person. `doubtful` are bar numbers as the file counts them.
CHECK_WORDS = {
    "well checked": "Most notes were confirmed against a recording; single wrong notes are still possible.",
    "partly checked": "Most notes were confirmed against a recording, but some bars are doubtful.",
    "unverified": "A machine reading that recordings could not confirm for most notes; expect wrong notes.",
}
CHECK_SAY = ("Tell the player once, before starting: this is a machine reading of the score, not a proofread edition; "
             "listen to a recording of the piece and trust your ear and the printed score over what is shown here. "
             "Rhythm inside a bar, ties and grace notes are less certain than the notes themselves.")
SCORE_CHECKS = {
    "dont-take-five": {"grade": "partly checked", "doubtful": [65, 87],
                       "how": "read exactly from the engraving's vector PDF (every bar adds up, all symbols accounted for); not compared with a recording",
                       "listen": "Woyten, \"Don't Take Five\" (the composer's own recording)"},
    "ephemeral-happiness": {"grade": "well checked", "doubtful": [107, 108, 184, 185, 186, 187, 188, 189, 190],
                            "how": "optical reading of the score; pitches checked note by note against the composer's recording (65 % confirmed, "
                                   "29 % hidden behind other notes, 2 contradicted); rhythm checked by bar sums only; the last seven bars rest on the image alone",
                            "listen": "Woyten, \"Ephemeral Happiness\" (the composer's own recording)"},
}
PRELUDES_WELL = {1, 3, 4, 10, 14, 17}       # every note read against the composer's two-staff edition (Belaieff 418): PROOF_418_P*.md
PRELUDES_UNVERIFIED = set()        # every prelude has at least the check against recordings
PRELUDES_DOUBTFUL = {1: [6, 23, 26], 2: [3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 30, 31], 3: [24, 25, 26, 47, 48, 49],
                     5: [6, 22, 26, 27, 32, 33, 35, 44, 45, 46, 48], 6: [16, 17, 18, 19, 20], 7: [7, 11, 12, 13, 18, 19, 29, 30, 31, 32, 33],
                     8: [5, 6, 11, 12, 17, 18, 19, 20, 23, 24, 25, 26, 36, 37], 9: [20, 21, 23, 28, 29],
                     11: [8, 11, 12, 13, 23, 24, 25, 26, 35, 36, 37], 12: [3, 9, 10, 12, 15, 17],
                     13: [4, 6, 11, 13, 15, 19, 21, 24, 25], 14: [17, 18, 22, 23, 27, 35, 38], 15: [14],
                     16: [15, 16, 17, 21, 27, 30, 31, 32, 39, 41, 42, 46], 17: [4, 5, 10, 13, 14, 15, 16, 18, 21], 18: [3, 4],
                     19: [4, 6, 8, 16, 19, 26, 27, 28, 29, 30, 31, 32, 33, 37, 39, 41], 20: [3, 5, 11, 12, 13, 14, 15, 21, 22, 25, 27],
                     21: [1, 13, 17, 19, 21, 22, 23, 24, 27, 28, 29, 30], 22: [5, 9, 15, 17, 18, 19],
                     24: [14, 15, 16, 17, 20, 21, 22, 24, 28, 34, 36, 37, 38, 39, 41, 42, 43, 44, 45, 46, 48, 49, 51, 52, 53, 54, 55, 56, 57],
                     23: [5, 6, 7, 8, 9, 12, 13, 23, 24, 29, 30, 31]}      # file numbering; renumbered below
PRELUDES_HOW = ("read from Ueli Raz's engraving (a PDF), repaired, then checked by ear against his own rendering and against "
                "the recording by Sylvaine Billier and Martine Joste")
PRELUDES_PROOFREAD = ("proofread note by note (pitch, rhythm, hands) against the composer's own edition for one quarter-tone "
                      "instrument (Belaieff 418), and checked by ear against recordings")
PRELUDES_LISTEN = "Sylvaine Billier and Martine Joste, 24 Preludes op. 22 (col legno; played there on two pianos tuned a quarter-tone apart)"


def checked(grade: str, how: str, listen: str, doubtful: list[int]) -> dict:
    out = {"grade": grade, "means": CHECK_WORDS[grade], "how": how, "listen_to": listen, "say": CHECK_SAY}
    if doubtful:
        out["doubtful_bars"] = sorted(set(doubtful))
    return out


def score_piece(path: Path, slug: str, level: int, how: str) -> dict | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    bars = []
    for bar in data.get("bars", []):
        staves, variants = {}, []
        for staff, events in (bar.get("staves") or {}).items():
            kept = []
            for e in events:
                steps = [n["step"] for n in e.get("notes", []) if isinstance(n.get("step"), int)]
                if steps and not e.get("rest") and float(e.get("dur", 0)) > 0:
                    kept.append([round(float(e["beat"]) - 1.0, 4), round(float(e["dur"]), 4), sorted(set(steps))])
                    for n in e["notes"]:
                        for other in n.get("also") or []:
                            variants.append({"staff": staff, "beat": round(float(e["beat"]) - 1.0, 4), "step": n["step"],
                                             "source": n.get("source", "print"), "other": other["step"], "other_source": other.get("source", "recording")})
            staves[staff] = kept
        num, _, den = str(bar.get("time") or "4/4").partition("/")
        bars.append({"n": bar.get("n", len(bars) + 1), "time": bar.get("time") or "4/4",
                     "length": round(4.0 * float(num) / float(den or 4), 4), "staves": staves})
        if variants:
            bars[-1]["variants"] = variants
    if not bars:
        return None
    tuning = data["tuning"]["edo"] if isinstance(data["tuning"], dict) else data["tuning"]      # either the number or {"edo": ...}
    return {
        "id": f"score/{slug}", "title": data.get("title", slug), "tradition": "composition", "mode": f"{tuning} notes per octave",
        "form": "piano piece in two staves", "meter": bars[0]["time"], "composer": data.get("composer", ""), "level": level,
        "tuning": int(tuning), "source": how, "licence": "private use", "notes": [], "theory": {}, "phrases": [],
        "score": bars, "bars": len(bars),
        "tempi": [[int(m["bar"]), float(m["bpm"])] for m in data.get("tempo") or [] if m.get("bar") and m.get("bpm")],
        **({"checked": checked(c["grade"], c["how"], c["listen"], c["doubtful"])} if (c := SCORE_CHECKS.get(slug)) else {}),
    }


def scores(source: Path):
    for relative, slug, level, how in SCORES:
        path = source / relative
        if path.exists():
            piece = score_piece(path, slug, level, how)
            if piece:
                yield piece
    yield from wyschnegradsky(source / "wyschnegradsky" / "preludes.json")


def wyschnegradsky(path: Path):
    """Ivan Wyschnegradsky, 24 Preludes op. 22 for two pianos a quarter-tone apart: a list of
    preludes, each with notes `{"onset", "dur", "step" (24 per octave, C4 = 96), "piano", "bar"}`
    and its time signatures. Read from Ueli Raz's engraving (see reference/music/wyschnegradsky);
    repaired and checked against recordings, not proofread as a whole. The two pianos were the
    composer's way to get quarter-tones from ordinary instruments; here both are merged into one
    quarter-tone instrument and every note stays on the staff it is printed on: the upper staves
    of both pianos are the upper staff (right hand), the lower staves the lower one (left hand),
    so melody and bass stay where the composer put them (`scores.musicxml.prelude_hands`, which
    the sheets use too; notes without a printed staff follow the lines around them). The tutor
    never sees the two-piano layout. What was written for four hands does not always fit two:
    `two_hands` names the bars in which one staff asks for more than a hand reaches
    (`scores.hands.playability`); no note is left out or moved for that. `zero_length_bars` are barlines the
    reader counted that are no bars (a time signature announced at the end of a system): they are
    left out and the bars renumbered, which gives the engraving's own bar numbers. A note with
    two readings (`source`, `also`) keeps both, as in the other scores."""
    if not path.exists():
        return
    for prelude in json.loads(path.read_text(encoding="utf-8")):
        changes = sorted(prelude.get("time_changes") or [{"bar": 1, "time": prelude.get("time", "4/4")}], key=lambda c: c["bar"])

        def time_of(bar: int) -> str:
            return [c["time"] for c in changes if c["bar"] <= bar][-1]

        empty = set(prelude.get("zero_length_bars") or [])
        starts: dict[int, float] = {}
        lengths: dict[int, float] = {}
        at = 0.0
        for n in range(1, int(prelude["bars"]) + 1):
            starts[n] = at
            num, _, den = time_of(n).partition("/")
            lengths[n] = 0.0 if n in empty else 4.0 * float(num) / float(den or 4)
            at += lengths[n]
        bars = {n: {"n": n, "time": time_of(n), "length": round(lengths[n], 4), "staves": {"upper": {}, "lower": {}}, "variants": []}
                for n in starts if n not in empty}
        from .scores.hands import playability
        from .scores.musicxml import prelude_hands
        every, staff_of = prelude_hands(prelude)
        kept = [(n, hand) for n, hand in zip(every, staff_of) if n["bar"] in bars]
        sounding, hands = [n for n, _ in kept], [hand for _, hand in kept]
        for note, hand in zip(sounding, hands):
            bar = bars[note["bar"]]
            beat = round(max(0.0, float(note["onset"]) - starts[note["bar"]]), 4)
            staff = bar["staves"]["lower" if hand else "upper"]
            event = staff.setdefault(beat, [beat, round(float(note["dur"]), 4), []])
            event[2].append(int(note["step"]))
            event[1] = max(event[1], round(float(note["dur"]), 4))
            for other in note.get("also") or []:
                bar["variants"].append({"staff": "lower" if hand else "upper", "beat": beat, "step": int(note["step"]),
                                        "source": note.get("source", "engraving"), "other": int(other["step"]),
                                        "other_source": other.get("source", "recording")})
        out = []
        renumbered: dict[int, int] = {}
        for n in sorted(bars):
            bar = bars[n]
            bar["staves"] = {name: [[b, d, sorted(set(s))] for b, d, s in (events[k] for k in sorted(events))] for name, events in bar["staves"].items()}
            renumbered[n] = bar["n"] = len(out) + 1
            if not bar["variants"]:
                del bar["variants"]
            out.append(bar)
        number = int(prelude["number"])
        grade = "well checked" if number in PRELUDES_WELL else "unverified" if number in PRELUDES_UNVERIFIED else "partly checked"
        doubtful = PRELUDES_DOUBTFUL.get(number, []) + [u["bar"] for u in prelude.get("uncertain") or [] if isinstance(u.get("bar"), int)]
        doubtful = [renumbered[b] for b in doubtful if b in renumbered]
        play = playability([(n["onset"], n["onset"] + n["dur"], n["step"]) for n in sounding], hands, per_octave=24)
        ends = sorted((starts[n] + lengths[n], renumbered[n]) for n in renumbered)

        def bars_of(times: list[float]) -> list[int]:
            return sorted({next((number for end, number in ends if t < end - 1e-9), ends[-1][1]) for t in times})

        tight, four = bars_of(play["over_span"]), bars_of(play["unplayable"])
        two_hands = {"fits": not tight, "tight_bars": tight, "four_hand_bars": four, "most_notes_at_once": play["max_sounding"],
                     "pedal_bars": [b for b in bars_of(play["held_over"]) if b not in tight],
                     "reach": "judged by what a medium hand reaches on a piano (a ninth, thumb to little finger); on this keyboard the reach depends on the layout"}
        if tight:
            two_hands["say"] = ("This music was written for two players. In the bars named in tight_bars one hand has more to strike at once "
                                "than it reaches (in four_hand_bars no division between two hands would fit): nothing is left out there. "
                                "Tell the player so before such a bar, take the upper line first, then break the chord or leave "
                                "its inner notes out. In pedal_bars a hand has to let go of held notes (or use a sustain pedal).")
        # the tempo (quarter notes per minute) at the start of each bar where it changes; a change inside a bar counts for its bar
        tempi: list[list] = []
        for mark in sorted((m for m in prelude.get("tempi") or [] if "onset" in m), key=lambda m: m["onset"]):
            file_bar = max((n for n in starts if starts[n] <= float(mark["onset"]) + 1e-6 and n in renumbered), default=None)
            bpm = float(mark.get("bpm_quarter") or 0)
            if file_bar is not None and bpm > 0 and (not tempi or tempi[-1][0] != renumbered[file_bar]):
                tempi.append([renumbered[file_bar], round(bpm, 1)])
        seconds = max(1.0, at * 60.0 / (tempi[0][1] if tempi else 80.0))
        density = len(prelude["notes"]) / seconds
        yield {
            "id": f"score/wyschnegradsky-prelude-{int(prelude['number']):02d}", "title": f"Prelude {prelude['number']} (24 Preludes op. 22)",
            "tradition": "composition", "mode": "24 notes per octave", "form": "piano piece in quarter-tones, two staves (upper = right hand, lower = left hand)",
            "meter": out[0]["time"], "composer": "Ivan Wyschnegradsky", "level": 3 if density < 3 else 4 if density < 6 else 5, "tuning": 24,
            "source": ("proofread against the composer's own edition for one quarter-tone instrument (Belaieff 418); first read from "
                       "Ueli Raz's engraving of the two-piano version" if prelude.get("hands_from") else
                       "read from Ueli Raz's engraving of the two-piano version and checked against recordings; not yet proofread "
                       "against the composer's edition throughout"), "licence": "private use",
            "notes": [], "theory": {}, "phrases": [], "score": out, "bars": len(out),
            "tempi": tempi,
            "checked": checked(grade, PRELUDES_PROOFREAD if prelude.get("hands_from") else PRELUDES_HOW, PRELUDES_LISTEN, doubtful),
            "two_hands": two_hands,
        }


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
                if not piece or not (piece["phrases"] or piece.get("changes") or piece.get("score")):
                    continue
                at = f.tell()
                f.write(json.dumps(piece, ensure_ascii=False, separators=(",", ":")) + "\n")
                sounding = [p for p, _ in piece["notes"] if p is not None]
                entry = {k: piece[k] for k in INDEX_FIELDS}
                entry.update(file=f"{collection}.jsonl", at=at, notes=len(sounding), phrases=len(piece["phrases"]))
                if piece.get("changes") or piece.get("score"):
                    entry["bars"] = piece.get("bars", 0)
                if piece.get("checked"):
                    entry["checked"] = piece["checked"]["grade"]
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
    if any((source / relative).exists() for relative, *_ in SCORES) or (source / "wyschnegradsky" / "preludes.json").exists():
        write("scores", scores(source))
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
