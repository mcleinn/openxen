"""The tutor's tuning notes: a local copy of pages of the Xenharmonic Wiki, as written by
`wiki_build.py`, with a small search. The wiki is where the community describes each
tuning: its intervals, notation, chords, scales, temperaments, history and music.

The text is the wiki's (CC BY-NC-SA 4.0), not the tutor's own: it uses the community's
vocabulary ("53edo" = 53 equal steps per octave, "edostep", "5-limit") and may disagree with
the tutor's simpler model. Results name the page and the date of the revision used.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "build" / "tutor-wiki" / "pages.json"
PART = 3500         # characters of a section given out at a time
_WORD = re.compile(r"[a-z0-9/#^]+")
_STOP = frozenset("the a an of to in is are and or for with as by on at it this that be can from which its not also".split())


def _words(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP]


class Wiki:
    def __init__(self, file: str | Path | None = None):
        self.file = Path(file) if file else DEFAULT_FILE
        self._pages: dict[str, dict] | None = None

    def _load(self) -> None:
        if self._pages is not None:
            return
        data = json.loads(self.file.read_text(encoding="utf-8")) if self.file.exists() else {"pages": [], "aliases": {}}
        self._pages = {p["title"]: p for p in data["pages"]}
        self._lower = {t.lower(): t for t in self._pages}
        self._lower.update({a.lower(): t for a, t in data.get("aliases", {}).items() if t in self._pages})
        # search index: per section its words; document frequencies
        self._sections: list[tuple[str, int, dict[str, int], set[str]]] = []
        df: dict[str, int] = {}
        for title, page in self._pages.items():
            for n, section in enumerate(page["sections"]):
                counts: dict[str, int] = {}
                for w in _words(section["text"]):
                    counts[w] = counts.get(w, 0) + 1
                heading = set(_words(title + " " + section["heading"]))
                for w in set(counts) | heading:
                    df[w] = df.get(w, 0) + 1
                self._sections.append((title, n, counts, heading))
        self._df = df

    @property
    def available(self) -> bool:
        self._load()
        return bool(self._pages)

    def titles(self) -> list[str]:
        self._load()
        return sorted(self._pages)

    def page(self, name: str) -> dict | None:
        self._load()
        title = self._lower.get(name.strip().lower().replace("_", " "))
        return self._pages[title] if title else None

    def search(self, query: str, limit: int = 6, page: str | None = None) -> list[dict]:
        """Sections that best match the words of `query` (optionally within one page)."""
        self._load()
        terms = _words(query)
        if not terms:
            return []
        only = self.page(page)["title"] if page and self.page(page) else None
        total = len(self._sections) or 1
        scored = []
        for title, n, counts, heading in self._sections:
            if only and title != only:
                continue
            score = 0.0
            hit = 0
            for term in terms:
                tf = counts.get(term, 0)
                in_heading = term in heading
                if not tf and not in_heading:
                    continue
                hit += 1
                idf = math.log(1 + total / (1 + self._df.get(term, 0)))
                score += idf * (tf / (tf + 1.5) + (2.0 if in_heading else 0.0))
            if hit:
                scored.append((score * (hit / len(terms)) ** 2, title, n))
        scored.sort(key=lambda s: (-s[0], s[1], s[2]))
        out = []
        for score, title, n in scored[:limit]:
            section = self._pages[title]["sections"][n]
            text = section["text"]
            at = min((i for i in (text.lower().find(t) for t in terms) if i >= 0), default=0)
            start = max(0, at - 80)
            out.append({"page": title, "section": section["heading"], "characters": len(text),
                        "excerpt": ("..." if start else "") + text[start:start + 260].replace("\n", " ") + ("..." if start + 260 < len(text) else "")})
        return out

    def section(self, page: str, heading: str, part: int = 1) -> dict | None:
        """The text of one section (by its heading, or part of it, or its number), in parts."""
        found = self.page(page)
        if not found:
            return None
        sections = found["sections"]
        want = heading.strip().lower()
        index = int(want) - 1 if want.isdigit() and 1 <= int(want) <= len(sections) else next(
            (i for i, s in enumerate(sections) if s["heading"].lower() == want), None)
        if index is None:
            index = next((i for i, s in enumerate(sections) if want in s["heading"].lower()), None)
        if index is None:
            return None
        text = sections[index]["text"]
        parts = max(1, math.ceil(len(text) / PART))
        part = max(1, min(int(part), parts))
        return {"page": found["title"], "section": sections[index]["heading"], "part": part, "parts": parts,
                "text": text[(part - 1) * PART:part * PART], "revision": found["revision"], "url": found["url"]}
