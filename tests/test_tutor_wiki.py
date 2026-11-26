"""The tuning notes: wikitext reduced to readable text, the selection of pages, the search,
and the tool, on a small backup in the wiki's format."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
from tutor import wiki_build as wb  # noqa: E402
from tutor.sample import sample_setup  # noqa: E402
from tutor.session import Tutor, TutorError  # noqa: E402
from tutor.wiki import Wiki  # noqa: E402
from tutor.xt import FakeXentool  # noqa: E402

PAGE = """{{Infobox ET}}
{{Wikipedia| 53 equal temperament }}
53edo is an excellent [[5-limit]] system, first noted by {{w|Isaac Newton}}<ref>[https://example.org Some paper]</ref>.
Its step is the "[[Holdrian comma]]".

== Theory ==
'''Bold''' and ''italic'' text with a [[Pythagorean comma|comma]] link and [https://example.org an outside link].<!-- hidden -->

=== Prime harmonics ===
{{Harmonics in equal|53|columns=11}}

== Intervals ==
{| class="wikitable center-all"
|-
! #
! Cents
! colspan="3" | [[Ups and downs notation]]
|-
| 0
| 0.0
| P1 || unison
|-
| 17
| 384.91
| vM3 || downmajor 3rd
|}

== Relationship to 12edo ==
53edo's circle of 53 fifths can be bent into a 12-spoked "spiral of fifths".
* a list item
{{Lumatone EDO mapping|n=53|start=2|xstep=9|ystep=-5}}
"""


def backup(path: Path, pages: dict[str, list[tuple[str, str]]]) -> Path:
    import zstandard
    xml = ['<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">']
    for title, revisions in pages.items():
        xml.append(f"<page><title>{title}</title>")
        for stamp, text in revisions:
            safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            xml.append(f"<revision><timestamp>{stamp}</timestamp><text>{safe}</text></revision>")
        xml.append("</page>")
    xml.append("</mediawiki>")
    path.write_bytes(zstandard.ZstdCompressor().compress("\n".join(xml).encode("utf-8")))
    return path


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    pytest.importorskip("zstandard")
    root = tmp_path_factory.mktemp("wiki")
    source = backup(root / "pages.xml.zst", {
        "53edo": [("2020-01-01T00:00:00Z", "an old revision about nothing"), ("2026-10-03T10:00:00Z", PAGE)],
        "53-EDO": [("2021-01-01T00:00:00Z", "#REDIRECT [[53edo]]")],
        "Circle of fifths": [("2022-01-01T00:00:00Z", "#REDIRECT [[Chain of fifths]]")],
        "Chain of fifths": [("2025-05-05T00:00:00Z", "Fifths stacked up and down, octave-reduced.\n\n== In edos ==\nThe chain closes into a circle.")],
        "31edo/Music": [("2025-01-01T00:00:00Z", "== Pieces ==\n* A piece in 31")],
        "Lumatone mapping for 31edo": [("2025-01-01T00:00:00Z", "{{Lumatone EDO mapping|n=31|start=-2|xstep=5|ystep=-2}}")],
        "72edo": [("2025-01-01T00:00:00Z", "not a tuning of this keyboard")],
        "User:Somebody/53edo thoughts": [("2025-01-01T00:00:00Z", "a user page")],
        "Unrelated page": [("2025-01-01T00:00:00Z", "nothing")],
    })
    out = root / "out"
    assert wb.build(source, out) == 4
    return out / "pages.json"


def test_wikitext_becomes_readable_text():
    parts = wb.sections(PAGE)
    assert [p["heading"] for p in parts] == ["Introduction", "Theory", "Theory > Prime harmonics", "Intervals", "Relationship to 12edo"]
    intro = parts[0]["text"]
    assert "excellent 5-limit system, first noted by Isaac Newton." in intro and "Holdrian comma" in intro
    assert "[[" not in intro and "<ref" not in intro and "example.org" not in intro
    assert parts[1]["text"] == "Bold and italic text with a comma link and an outside link."
    assert "the wiki computes" in parts[2]["text"]
    # a table: one line per row, cells separated, attributes dropped
    assert parts[3]["text"].splitlines() == ["# | Cents | Ups and downs notation", "0 | 0.0 | P1 | unison", "17 | 384.91 | vM3 | downmajor 3rd"]
    assert "- a list item" in parts[4]["text"] and "Lumatone layout parameters: n=53 start=2 xstep=9 ystep=-5" in parts[4]["text"]


def test_selection_latest_revision_and_redirects(built):
    wiki = Wiki(built)
    assert wiki.titles() == ["31edo/Music", "53edo", "Chain of fifths", "Lumatone mapping for 31edo"]      # not 72edo, not the user page
    page = wiki.page("53edo")
    assert page["revision"] == "2026-10-03" and "old revision" not in page["sections"][0]["text"]
    assert wiki.page("53-EDO")["title"] == "53edo" and wiki.page("circle of fifths")["title"] == "Chain of fifths"
    assert wiki.page("72edo") is None
    assert wb.wanted("53edo") and wb.wanted("31edo modes") and wb.wanted("Lumatone mapping for 53edo (part 2)")
    assert not wb.wanted("72edo") and not wb.wanted("User:X/53edo") and not wb.wanted("153edo")


def test_search_and_sections(built):
    wiki = Wiki(built)
    hits = wiki.search("spiral of fifths")
    assert hits[0]["page"] == "53edo" and hits[0]["section"] == "Relationship to 12edo" and "spiral of fifths" in hits[0]["excerpt"]
    assert wiki.search("chain closes circle")[0]["page"] == "Chain of fifths"
    assert wiki.search("downmajor", page="53edo")[0]["section"] == "Intervals"
    assert wiki.search("zzzz") == [] and wiki.search("the of") == []
    text = wiki.section("53edo", "intervals")
    assert text["parts"] == 1 and text["text"].startswith("# | Cents") and text["url"].endswith("/53edo")
    assert wiki.section("53edo", "4")["section"] == "Intervals" and wiki.section("53edo", "nope") is None
    assert not Wiki(built.parent / "missing.json").available


def test_tuning_notes_tool(built):
    tutor = Tutor(FakeXentool(sample_setup(53, (0, 1))), wiki=Wiki(built))
    try:
        over = tutor.tuning_notes()
        assert over["pages"] == 4 and over["for_the_current_tuning"] == ["53edo"] and "Chain of fifths" in over["also"]
        found = tutor.tuning_notes(query="spiral of fifths")
        assert found["hits"][0]["page"] == "53edo" and "Xenharmonic Wiki" in found["source"]
        sections = tutor.tuning_notes(page="53edo")["sections"]
        assert [s["section"] for s in sections][:2] == ["Introduction", "Theory"]
        text = tutor.tuning_notes(page="53edo", section="Relationship to 12edo")
        assert "12-spoked" in text["text"] and text["revision"] == "2026-10-03"
        with pytest.raises(TutorError, match="no page 'meantone'"):
            tutor.tuning_notes(page="meantone")
        with pytest.raises(TutorError, match="Similar: 31edo/Music"):
            tutor.tuning_notes(page="31edo")
        with pytest.raises(TutorError, match="no section"):
            tutor.tuning_notes(page="53edo", section="nope")
        missing = Tutor(FakeXentool(sample_setup(53, (0,))), wiki=Wiki(built.parent / "missing.json"))
        try:
            with pytest.raises(TutorError, match="not installed"):
                missing.tuning_notes()
        finally:
            missing.pump.stop()
    finally:
        tutor.pump.stop()


def test_the_real_notes_if_they_are_installed():
    wiki = Wiki()
    if not wiki.available:
        pytest.skip("build/tutor-wiki not built")
    assert len(wiki.titles()) > 100 and {"53edo", "31edo", "Chain of fifths", "Meantone"} <= set(wiki.titles())
    assert "53edo" in [h["page"] for h in wiki.search("53edo spiral of fifths")[:3]]
    assert "Holdrian" in wiki.section("53edo", "Theory")["text"]
