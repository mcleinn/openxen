"""Turn the Xenharmonic Wiki backup into the tutor's tuning notes.

    python -m tutor.wiki_build            (from host/; needs `pip install zstandard`)

Reads `reference/literature/xenwiki/pages.xml.zst`: the wiki's own MediaWiki backup from
https://archive.org/download/XenharmonicWikiBackups/xenwiki_en_mediawiki/<date>/pages.xml.zst
(the live site refuses automated requests). Licence of the wiki: CC BY-NC-SA 4.0; this is
private reference material and is not distributed.

Writes `build/tutor-wiki/pages.json`: for every selected page its title, the date of the
revision used, and its sections as plain text. Selected: the pages of the tunings the
keyboard has layouts for (the tuning page, its subpages and companion pages, its Lumatone
mapping), notation, the chain of fifths, the main temperaments and commas, and the
beginners' guides.

Wikitext is reduced to readable text: links and formatting removed, tables as one line per
row with " | " between cells. Tables the wiki computes when a page is shown (harmonics,
interval tables from templates) are not in the backup; the tutor's theory tool computes
such values itself.
"""

from __future__ import annotations

import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "reference" / "literature" / "xenwiki" / "pages.xml.zst"
OUT = ROOT / "build" / "tutor-wiki"

TUNINGS = (12, 19, 22, 24, 29, 31, 41, 53, 56)
PAGES = """
Chain of fifths | Spiral chart | Chain-of-fifths notation | Ups and downs notation | Kite's color notation | Color notation
Sagittal notation | Helmholtz–Ellis notation | Standard Lumatone mapping for Pythagorean | Lumatone | Keyboard
Generalized keyboard | Isomorphic keyboard | 5L 2s | MOS scale | Regular temperament | Comma | Comma pump | 12edo comma pump examples
Kite Guitar | Kite Guitar Exercises and Techniques by Kite Giedraitis | Kite Guitar translations by Kite Giedraitis
Xen concepts for beginners | Basic introduction to xenharmonic music | Beginner's guide to scales and tunings
Holdrian comma | Mercator's comma | Schisma | Schismic | Schismatic family | Pythagorean tuning | Pythagorean comma
81/80 | 64/63 | 5/4 | 6/5 | 7/4 | 7/6 | 11/9 | 3/2 | Kleismic family | Hanson | Garibaldi | Turkish maqam music temperaments
Middle-Eastern music | Arabic, Turkish, Persian | Indian music | Maqam | Meantone | Meantone family | Quarter-comma meantone
Extended meantone notation | Diesis | 128/125 | 648/625 | Superpyth | Porcupine | Orwell | Magic | Pajara | Mohajira
Neutral third | Harmonic seventh | Septimal comma | Syntonic comma | Just intonation | Harmonic series | Equal-step tuning | EDO
Blues | Jazz | Barbershop | Diminished seventh chord | Tritone substitution | Dominant seventh chord
"""
WANTED = {t.strip() for t in PAGES.replace("\n", "|").split("|") if t.strip()}
_TUNING_PAGE = re.compile(r"^(?:(?P<n>\d+)edo\b.*|Lumatone mapping for (?P<n2>\d+)edo.*|List of MOS scales in (?P<n3>\d+)edo"
                          r"|Table of (?P<n4>\d+)edo intervals|List of (?P<n5>\d+)edo chords)$")


def wanted(title: str) -> bool:
    if ":" in title.split(" ")[0] and not title[0].isdigit():      # User:, Talk:, File:, Template: ...
        return False
    if title in WANTED:
        return True
    m = _TUNING_PAGE.match(title)
    if not m:
        return False
    n = next(int(v) for v in m.groups() if v)
    return n in TUNINGS


# --- wikitext to text ---

_TEMPLATE = re.compile(r"\{\{([^{}]*)\}\}", re.S)


def _template(m: re.Match) -> str:
    parts = [p.strip() for p in m.group(1).split("|")]
    name = parts[0].lower()
    if name in ("w", "wikipedia") and len(parts) > 1:
        return parts[-1]
    if name == "lumatone edo mapping":
        return "Lumatone layout parameters: " + " ".join(parts[1:])
    if name in ("monzo", "val") and len(parts) > 1:
        return "[" + " ".join(parts[1:]) + ">"
    if name in ("nowrap", "c", "sg", "mono", "abbr", "frac", "sfrac", "main", "see also", "todo", "idiosyncratic terms"):
        return " ".join(p for p in parts[1:2] if "=" not in p)
    if name.startswith(("harmonics in", "interval table", "infobox", "q-odd-limit", "15-odd-limit")):
        return "(a table the wiki computes; ask the theory tool for such values)"
    return ""


def _cell(text: str) -> str:
    # 'colspan="3" | text' -> 'text'
    if "|" in text and re.match(r"^\s*[\w\-]+\s*=", text):
        text = text.split("|", 1)[1]
    return text.strip()


def _tables(text: str) -> str:
    out: list[str] = []
    row: list[str] = []
    inside = False
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("{|"):
            inside, row = True, []
            continue
        if not inside:
            out.append(line)
            continue
        if s.startswith("|}") or s.startswith("|-"):
            if row:
                out.append(" | ".join(c for c in row if c != ""))
            row = []
            if s.startswith("|}"):
                inside = False
            continue
        if s.startswith("|+"):
            out.append(s[2:].strip())
        elif s.startswith("!"):
            row.extend(_cell(c) for c in re.split(r"!!|\|\|", s[1:]))
        elif s.startswith("|"):
            row.extend(_cell(c) for c in s[1:].split("||"))
        elif row:
            row[-1] = (row[-1] + " " + s).strip()
    if row:
        out.append(" | ".join(row))
    return "\n".join(out)


def plain(wikitext: str) -> str:
    t = re.sub(r"<!--.*?-->", "", wikitext, flags=re.S)
    t = re.sub(r"<ref[^>]*/>", "", t)
    t = re.sub(r"<ref[^>]*>.*?</ref>", "", t, flags=re.S)
    t = re.sub(r"<(gallery|imagemap|math|score|syntaxhighlight)[^>]*>.*?</\1>", "", t, flags=re.S)
    for _ in range(6):                      # nested templates, innermost first
        t, n = _TEMPLATE.subn(_template, t)
        if not n:
            break
    t = re.sub(r"\[\[(?:File|Image|Category):[^\]]*\]\]", "", t)
    t = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"\[\[#?([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"\[https?://\S+\s+([^\]]*)\]", r"\1", t)
    t = re.sub(r"\[https?://\S+\]", "", t)
    t = re.sub(r"^[*#:;]+\s*", "- ", t, flags=re.M)        # list items; before tables, where "#" may be a cell
    t = _tables(t)
    t = re.sub(r"<br\s*/?>", " ", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace("\xa0", " ")
    t = re.sub(r"'{2,}", "", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def sections(wikitext: str) -> list[dict]:
    """The page as sections: {"heading": "Theory > Prime harmonics", "text": ...}."""
    out: list[dict] = []
    path: list[tuple[int, str]] = []
    buffer: list[str] = []

    def flush() -> None:
        text = plain("\n".join(buffer))
        if text:
            out.append({"heading": " > ".join(h for _, h in path) or "Introduction", "text": text})
        buffer.clear()

    for line in wikitext.split("\n"):
        m = re.match(r"^(={2,5})\s*(.*?)\s*\1\s*$", line)
        if m:
            flush()
            level = len(m.group(1))
            while path and path[-1][0] >= level:
                path.pop()
            path.append((level, plain(m.group(2))))
        else:
            buffer.append(line)
    flush()
    return out


# --- the backup ---

def read_pages(source: Path):
    """(title, timestamp of the latest revision, its text) for every page of the backup."""
    import zstandard
    with source.open("rb") as raw:
        stream = zstandard.ZstdDecompressor().stream_reader(raw)
        for _, el in ET.iterparse(stream, events=("end",)):
            if not el.tag.endswith("}page"):
                continue
            ns = el.tag.split("}")[0] + "}"
            title = el.findtext(ns + "title") or ""
            latest = None
            for rev in el.findall(ns + "revision"):
                stamp = rev.findtext(ns + "timestamp") or ""
                if latest is None or stamp >= latest[0]:
                    latest = (stamp, rev.findtext(ns + "text") or "")
            el.clear()
            if latest:
                yield title, latest[0], latest[1]


def build(source: Path = SOURCE, out: Path = OUT) -> int:
    texts: dict[str, tuple[str, str]] = {}
    redirects: dict[str, str] = {}
    for title, stamp, text in read_pages(source):
        m = re.match(r"^\s*#REDIRECT\s*\[\[([^\]#|]+)", text, flags=re.I)
        if m:
            redirects[title] = m.group(1).strip().replace("_", " ")
        texts_wanted = wanted(title) or title in WANTED
        if texts_wanted or not m:
            # keep every non-redirect page's text only if wanted; redirect targets are resolved below
            if texts_wanted and not m:
                texts[title] = (stamp, text)
    # a wanted title that is a redirect: take its target under the target's name
    targets = {redirects[t] for t in redirects if (wanted(t) or t in WANTED)} - set(texts)
    if targets:
        for title, stamp, text in read_pages(source):
            if title in targets and not text.lstrip().upper().startswith("#REDIRECT"):
                texts[title] = (stamp, text)
    pages = []
    for title in sorted(texts):
        stamp, text = texts[title]
        parts = sections(text)
        if parts:
            pages.append({"title": title, "revision": stamp[:10], "url": "https://en.xen.wiki/w/" + title.replace(" ", "_"),
                          "sections": parts})
    out.mkdir(parents=True, exist_ok=True)
    aliases = {a: t for a, t in redirects.items() if t in texts and (wanted(a) or a in WANTED or len(a) < 40)}
    (out / "pages.json").write_text(json.dumps({"pages": pages, "aliases": aliases}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return len(pages)


if __name__ == "__main__":
    if not SOURCE.exists():
        print(f"{SOURCE} is missing; see the top of this file for where to download it", file=sys.stderr)
        sys.exit(1)
    count = build()
    print(f"{count} pages written to {OUT}")
