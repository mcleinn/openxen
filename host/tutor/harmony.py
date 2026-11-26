"""What chord tends to follow which: counted from the chord changes of the jazz standards in
the library, and described in terms that hold in any tuning.

Chords are written relative to the key ("IIm7", "V7", "bVII7"), the degree counted in the
twelve semitone classes the lead sheets are written in. `statistics()` counts, for major and
for minor keys separately: how often each chord occurs, what follows it, what leads to it,
and the most frequent runs of three and four chords. `library_build.py` stores the result as
`harmony.json` next to the library.

The counts say what is COMMON in this repertoire (American popular song and jazz, about 1920
to 1970), not what is good; other repertoires have other habits. `FUNCTIONS` adds the textbook
reading of each chord's role, and `Tutor.harmony` adds what the current tuning does to a
progression.
"""

from __future__ import annotations

from collections import Counter

from . import library as lib

NUMERALS = ("I", "bII", "II", "bIII", "III", "IV", "#IV", "V", "bVI", "VI", "bVII", "VII")
_PITCH_CLASS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
# the tutor's chord qualities in lead-sheet shorthand; sixths and plain triads count as the seventh chord of their family
_SHORT = {"major": "maj7", "major7": "maj7", "major6": "maj7", "minor": "m", "minor6": "m", "minor-major7": "m", "minor7": "m7",
          "dominant7": "7", "dominant7sus4": "7sus", "half-diminished7": "m7b5", "diminished7": "o7", "diminished": "o7",
          "augmented": "+", "sus4": "sus", "sus2": "sus"}
SUFFIX_QUALITY = {"maj7": "major7", "m": "minor6", "m7": "minor7", "7": "dominant7", "7sus": "dominant7sus4", "m7b5": "half-diminished7",
                  "o7": "diminished7", "+": "augmented", "sus": "sus4"}

# The role of a chord in a key, as harmony textbooks describe it (function theory).
FUNCTIONS = {
    "Imaj7": "home (tonic): where phrases come to rest", "Im": "home in a minor key", "Im7": "home in a minor key, less final than Im",
    "IIm7": "prepares the dominant (subdominant function); the usual chord before V7",
    "IIm7b5": "prepares the dominant in a minor key", "II7": "the dominant of the dominant: pulls to V7",
    "IIIm7": "a lighter stand-in for home; often on the way to VI", "III7": "dominant of VI: starts a chain of dominants",
    "IVmaj7": "away from home (subdominant): opens out, often returns to I or moves on to V", "IVm7": "the minor subdominant in minor; in major a borrowed, darker colour",
    "IV7": "the fourth chord of a blues", "#IVm7b5": "a chromatic step towards V or IV; often starts a falling line",
    "#IVo7": "a passing chord between IV and V (or I with its fifth in the bass)",
    "V7": "the dominant: wants to go home", "V7sus": "a softer dominant: the fourth is held instead of the third",
    "Vm7": "the two-chord of the key a fourth up: usually followed by I7 on the way to IV",
    "VIm7": "home's relative minor: tonic function, and the start of the turnaround I VI II V", "VI7": "dominant of II: pulls to IIm7 or II7",
    "VIIm7b5": "in major the two-chord of the relative minor; leads to III7", "VIIo7": "a dominant without its root",
    "bVIImaj7": "borrowed from the minor key", "bVII7": "the backdoor dominant: reaches home from a whole step below",
    "bIIImaj7": "the relative major of a minor key; in major a borrowed colour", "bVImaj7": "the sixth degree of a minor key; in major a borrowed colour",
    "bII7": "the tritone substitute of V7: reaches home from a half step above", "bIImaj7": "the Neapolitan colour: a half step above home",
    "I7": "home turned into a dominant: leads to IV (or is the home chord of a blues)", "bVI7": "leads to V7 from a half step above",
    "bIIIo7": "a passing diminished chord between II and III",
}


def numeral(symbol: str, key: tuple[str, bool]) -> str | None:
    """A chord symbol as a degree of the key: "Dm7" in C -> "IIm7"."""
    parsed = lib.chord_from_symbol(symbol)
    if not parsed:
        return None
    root, quality, _, _ = parsed

    def pc(name: str) -> int:
        return (_PITCH_CLASS[name[0]] + name.count("#") - name.count("b")) % 12

    return NUMERALS[(pc(root) - pc(key[0])) % 12] + _SHORT.get(quality, "")


def split(roman: str) -> tuple[str, str]:
    """ "bVII7" -> ("bVII", "7")."""
    for degree in sorted(NUMERALS, key=len, reverse=True):
        if roman.startswith(degree):
            return degree, roman[len(degree):]
    raise ValueError(roman)


def statistics(tunes: list[dict]) -> dict:
    """Count chords, what follows what and frequent runs. `tunes`: pieces with "key"
    ("Gmin", "Eb") and "changes" (sections of bars of chord symbols)."""
    out: dict = {}
    for mode in ("major", "minor"):
        chords: Counter = Counter()
        following: dict[str, Counter] = {}
        preceding: dict[str, Counter] = {}
        runs: Counter = Counter()
        used = 0
        for tune in tunes:
            key = lib.parse_key(tune.get("key", ""))
            if not key or key[1] != (mode == "minor"):
                continue
            line: list[str] = []
            for section in tune.get("changes", []):
                for bar in section["bars"]:
                    for symbol in bar:
                        roman = numeral(symbol, key)
                        if roman and (not line or line[-1] != roman):      # a held chord is one chord
                            line.append(roman)
            if len(line) < 4:
                continue
            used += 1
            chords.update(line)
            for a, b in zip(line, line[1:]):
                following.setdefault(a, Counter())[b] += 1
                preceding.setdefault(b, Counter())[a] += 1
            for n in (3, 4):
                seen = set()
                for i in range(len(line) - n + 1):
                    run = tuple(line[i:i + n])
                    if len(set(run)) == n and run not in seen:              # once per tune: in how many tunes it occurs
                        seen.add(run)
                        runs[run] += 1
        total = sum(chords.values()) or 1

        def shares(counter: Counter, limit: int) -> list:
            whole = sum(counter.values()) or 1
            return [[name, round(100 * count / whole)] for name, count in counter.most_common(limit) if 100 * count / whole >= 1.5]

        common = [name for name, _ in chords.most_common(40)]
        out[mode] = {
            "tunes": used,
            "chords": [[name, round(100 * count / total, 1)] for name, count in chords.most_common(24)],
            "next": {name: shares(following.get(name, Counter()), 7) for name in common},
            "before": {name: shares(preceding.get(name, Counter()), 7) for name in common},
            "runs": [[" ".join(run), round(100 * count / max(used, 1))] for run, count in runs.most_common(40)],
        }
    return out
