"""Which recorded stroke sounds for which syllable of a rhythmic cycle.

Three instruments can sound a cycle: the tabla patch (`host/synth/tabla.scd`, for Hindustani
thekas), the mridangam patch (`host/synth/mridangam.scd`, for Carnatic lessons) and the click.
What the sources state and what is this project's choice are kept apart here:

Sourced
  - the bols of each theka and the strokes of each lesson and usul (`rhythm_build.py`, from
    `reference/music/rhythm/tala.json`);
  - which tabla bols sound alike: the 18 timbre classes of the CompMusic Tabla Solo dataset
    (`tabla_bol_timbre_classes` in tala.json);
  - which samples exist: the kit made from Subodh Deolekar's "Tabla strokes dataset"
    (Zenodo 4327350, CC BY 4.0), eleven bols.

This project's choice (not sourced; labelled wherever it reaches the player)
  - a bol starting with "Dh" that has no recording of its own is played as the open left-drum
    stroke Ge together with the right-drum stroke of the same name without the h
    (Dhin = Ge + Tin, Dhi = Ge + Ti);
  - STAND_INS: bols of a timbre class of which the kit has no recording at all;
  - the usul strokes dum, tek, ... on tabla or mridangam (no frame drum or kudum is recorded);
  - the strokes that mark a pattern which has none of its own (GENERIC), and the loudness of
    every stroke.
"""

from __future__ import annotations

import unicodedata

# the kit's samples (kit.json of bolbox/kits/deolekar-tabla: nine strokes and two composites)
TABLA_SAMPLES = ("ge", "ka", "na", "tin", "tun", "ta", "ti", "te", "re", "dha", "dhun")
# the same bol written differently: tala.json treats Tu/Tun/Toon as spellings; kit.json plays ki with ka
TABLA_SPELLINGS = {"tu": "tun", "toon": "tun", "ki": "ka"}
# timbre classes without any recording in the kit -> the sample that stands in, and why
STAND_INS = {
    "DIN": ("tin", "the kit has no Din; Tin stands in (the sample set's notes call its nearest stroke 'din/tin-like')"),
    "KDA": ("ka", "the kit has no Kra; the closed left-drum stroke Ka stands in"),
}
BAYAN_OPEN = "ge"

MRIDANGAM_STROKES = ("Thom", "Num", "Tha", "Thi", "Dhin", "Dheem", "Cha", "Bheem", "Ta", "Tham")

# Usul strokes on the two drums: stand-ins, this project's choice. The glossary in tala.json:
# dum = strong low stroke; tek = weak high stroke; te, ke, ka = short strokes; ta = the hands
# lift, a light touch; hek = both hands together.
USUL_ON_TABLA = {"dum": "Ge", "tek": "Na", "te": "Te", "ke": "Ke", "ka": "Ke", "ta": "Na", "hek": "Dha"}
USUL_ON_MRIDANGAM = {"dum": "Thom", "tek": "Num", "te": "Thi", "ke": "Thi", "ka": "Thi", "ta": "Num", "hek": "Tham"}
USUL_NOTE = ("the usul is sounded on {drum} as a stand-in (no recorded frame drum): dum = {dum}, the low open stroke, "
             "tek = {tek}, a rim stroke; this is this project's choice")

# A pattern without strokes of its own: (first tap of the cycle, tap on a beat, tap between beats),
# and the pulse (accented, plain).
GENERIC = {"mridangam": ("Thom", "Thi", "Ta"), "tabla": ("Dha", "Na", "Te")}
PULSE = {"mridangam": ("Thom", "Thi"), "tabla": ("Dha", "Te")}
ADDRESS = {"mridangam": "/mridangam/stroke", "tabla": "/tabla/stroke"}
# the drum of a tradition, in order of preference
DRUMS = {"hindustani": ("tabla",), "carnatic": ("mridangam",), "makam": ("tabla", "mridangam")}


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def _collapse(text: str) -> str:
    """Long vowels written double: Dhaa -> Dha."""
    out = ""
    for c in text:
        if not (out and c == out[-1] and c in "aeiou"):
            out += c
    return out


def tabla_bol(bol: str, classes: dict[str, list[str]]) -> dict | None:
    """How a bol is sounded with the kit: {"samples": [...], "how": recorded | same timbre
    class | composed | stand-in, "note": ...}, or None if nothing honest can be said."""
    n = _plain(bol)
    if n in TABLA_SAMPLES:
        return {"samples": [n], "how": "recorded"}
    if n in TABLA_SPELLINGS:
        return {"samples": [TABLA_SPELLINGS[n]], "how": "recorded", "note": f"written {TABLA_SPELLINGS[n].capitalize()} in the kit"}
    group = next((name for name, members in classes.items() if not name.startswith("_") and n.upper() in members), None)
    if group:
        for member in classes[group]:
            m = TABLA_SPELLINGS.get(member.lower(), member.lower())
            if m in TABLA_SAMPLES:
                return {"samples": [m], "how": "same timbre class",
                        "note": f"the kit has no {bol}; {m.capitalize()} is in the same timbre class (CompMusic)"}
    if not group and _collapse(n) != n:
        return tabla_bol(_collapse(n), classes)
    if n.startswith("dh") and len(n) > 2:
        dayan = tabla_bol("t" + n[2:], classes)
        if dayan and dayan["how"] != "composed":
            return {"samples": [BAYAN_OPEN, *dayan["samples"]], "how": "composed",
                    "note": f"no recording of {bol}: Ge and {dayan['samples'][0].capitalize()} are struck together (this project's choice)"}
    if group in STAND_INS:
        sample, why = STAND_INS[group]
        return {"samples": [sample], "how": "stand-in", "note": why + " (this project's choice)"}
    return None


def tabla_bols(bols, classes: dict[str, list[str]]) -> tuple[dict[str, dict], list[str]]:
    """The table for a set of bols, and the bols that have no sound."""
    table, silent = {}, []
    for bol in sorted(set(bols)):
        found = tabla_bol(bol, classes)
        if found:
            table[bol] = found
        else:
            silent.append(bol)
    return table, silent


def drum_for(tradition: str | None, available: set[str]) -> str:
    """The drum of a tradition if it is set up, else the click."""
    return next((d for d in DRUMS.get(tradition or "", ()) if d in available), "click")


def stroke_on(drum: str, tradition: str | None, stroke: str | None) -> str | None:
    """The name to send to `drum` for a cycle's own stroke; None = this drum does not
    have it (the caller sounds a click instead)."""
    if not stroke:
        return None
    if tradition == "hindustani" and drum == "tabla":
        return stroke
    if tradition == "carnatic" and drum == "mridangam":
        return stroke if stroke in MRIDANGAM_STROKES else None
    if tradition == "makam":
        return (USUL_ON_TABLA if drum == "tabla" else USUL_ON_MRIDANGAM).get(stroke.lower())
    return None


def plays_own_strokes(drum: str, tradition: str | None) -> bool:
    return drum in DRUMS.get(tradition or "", ())
