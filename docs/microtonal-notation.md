# Writing microtonal sheet music by program

For whoever gives the tutor a function that produces sheets (an exercise, a chord, a scale as
notation). It collects what was learnt while building `host/tutor/scores/musicxml.py`, which
writes our machine-read scores back as sheet music (see "Sheets of our readings" in
[tutor.md](tutor.md)). Checked on 2026-11-27 with Verovio 6.4.1, PyMuPDF 2.1 (MuPDF 1.28.6) and music21 10.5.

Words used here: a *step* is the smallest interval of a tuning (1/31 octave in 31 notes per
octave). An *accidental* is a sign before a note (sharp, flat, arrow ...). *EDO* means "equal
division of the octave"; "31edo" is the tuning with 31 equal steps.

## 1. Which notation for which tuning

Sources: the local copy of the Xenharmonic Wiki (`build/tutor-wiki/pages.json`, read through
`host/tutor/wiki.py`; raw dump in `reference/literature/xenwiki/pages.xml.zst`), xenharmlib (the
library the tutor takes its note names from) and the three scores themselves. Nothing here is
invented by this project except where it says so.

| Notation | For | Used in this project | Source |
|---|---|---|---|
| Ups and downs (`^`, `v` before the letter, plus `#`, `b`) | any equal tuning | yes: every note name the tutor says or accepts | wiki "Kite's ups and downs notation" (rev. 2026-09-14); `host/tutor/theory.py`, `UpDownNotation(EDOTuning(n))` from xenharmlib |
| Quarter-tone signs (Stein-Zimmermann: half-sharp, sharp-and-a-half, half-flat, flat-and-a-half) | 24 | yes: the preludes in `--sounding` mode | wiki "24edo", section "Notation > Stein-Zimmermann accidentals" (rev. 2026-09-21) |
| The same four signs, one step each | 17 | yes: "Ephemeral Happiness" as printed, and its sheet | wiki "17edo", section "Notation > Quarter tone notation" (rev. 2026-09-24; in the dump, the page is not in the tutor's selection); the score ("17edo, A=441"), `reference/music/woyten/final/ephemeral_happiness.json` (`names`, `key_signatures`) |
| 12-tone letters with arrows of 25 cents and quarter-tone signs | 16 | yes: "Don't Take Five" as printed, and its sheet | the score (transcription by Stephen Weigel), `reference/music/woyten16/dont_take_five.json` (`tuning.notation`); not on the wiki's 16edo page |
| Ordinary notation, second instrument a quarter-tone lower | 24 with two pianos | yes: the preludes, default layout | Wyschnegradsky op. 22, Belaieff edition; Ueli Raz's engraving labels the part "Piano II 1/4 tiefer" |
| Sagittal | any tuning | no, only described | wiki "Sagittal notation" (rev. 2026-09-05) |
| Helmholtz-Ellis (HEJI) | just intonation | no, only described | wiki "Helmholtz-Ellis notation" (rev. 2025-12-27) |

### Ups and downs: what the tutor names notes with

The wiki's definition: "The up symbol `^` and the down symbol `v` indicate raising/lowering a note
... by one EDOstep." The letters C D E F G A B are a chain of the tuning's fifths, and a sharp is
what seven fifths minus four octaves come to (the wiki calls this number the edo's *sharpness*:
"sharp-2", "sharp-5"). So an arrow is always one step, and the size of the sharp depends on the tuning:

| Notes per octave | Fifth (steps) | Sharp or flat (steps) | Whole tone C-D (steps) | Arrow (steps) | From C upwards, as the tutor names them |
|---|---|---|---|---|---|
| 12 | 7 | 1 | 2 | (not needed) | C, C#, D |
| 17 | 10 | 2 | 3 | 1 | C, ^C, vD, D |
| 19 | 11 | 1 | 3 | (not needed) | C, C#, Db, D |
| 22 | 13 | 3 | 4 | 1 | C, ^C, B#, vD, D |
| 24 | 14 | 2 | 4 | 1 | C, ^C, C#, vD, D |
| 31 | 18 | 2 | 5 | 1 | C, ^C, C#, Db, vD, D |
| 41 | 24 | 4 | 7 | 1 | C, ^C, ^^C, Db, C#, vvD, vD, D |
| 53 | 31 | 5 | 9 | 1 | C, ^C, ^^C, vDb, Db, C#, ^C#, vvD, vD, D |

The fifth is `round(n * log2(3/2))`; sharp = 7 fifths - 4 octaves; the names in the last column
come from `Tuning(n).name(step)` in `host/tutor/theory.py`. The wiki confirms the pattern per
tuning: "17edo is sharp-2 and thus has mid intervals", "19edo is sharp-1, thus doesn't need ups and
downs", 24edo "contains 2 rings of 12edo: an up/down-ring and a plain-ring" (all from "Examples:
edos 12-24"); 31edo: "The gamut runs D, ^D/vD#, D#, Eb, ^Eb/vE, E ..."; 41edo and 53edo have
double arrows ("up, dup, downsharp, sharp ..."). In 16 notes per octave the fifth is flat and the
sharp comes out as -1 step: the wiki calls 16edo "flat-1" and gives two ways to write it (sharp
lowering the pitch, or raising it); the tutor's names follow xenharmlib there (`D#` is the step
below `D`).

On the staff the wiki puts the arrow "to the left of the note and any sharp or flat it might
have", and an arrow holds for the rest of the bar like any accidental. Its default cancelling rule
is the simplest: "any accidental or arrow cancels any previous ones. An arrow by itself implies a
natural sign."

### Quarter-tone signs for 24

The four Stein-Zimmermann signs, in the wiki's words: a half-sharp is "one half of a regular
musical sharp symbol", a sesquisharp ("sharp and a half") is the half-sharp joined to a sharp, a
half-flat is "a flat symbol mirrored horizontally", a sesquiflat is a half-flat and a flat back to
back. In 24 notes per octave each sign is a whole number of steps: half-sharp +1, sharp +2,
sesquisharp +3, half-flat -1, flat -2, sesquiflat -3. In ups and downs the same notes are `^C` (=
C half-sharp), `C#`, `^C#`; the wiki notes that Sagittal's "Evo-SZ" flavour for 24 "is identical to
Stein-Zimmerman notation". This is what `--sounding` uses for piano II of the preludes, and what
the composer's own edition for one quarter-tone piano on two staves (op. 22a) does.

### The same signs in 17: "Ephemeral Happiness"

The wiki's 17edo page: "Since a sharp raises by 2 steps, 17edo can be notated using quarter-tone
accidentals." One step is half a sharp there, as in 24, and the score uses the four quarter-tone
signs for single steps: half-sharp +1 step, sharp +2, sesquisharp +3, half-flat -1,
flat -2, sesquiflat -3 (`names` in the JSON: `t`, `#`, `#t`, `d`, `b`, `db`). The signs look like
quarter-tones but mean 70.6 cents: read them as steps, not as cents. The score has key signatures
of seven such signs (bars 1-46 and 124-190: F, C, G, D half-sharp and A, E, B half-flat; bars
47-123: F half-sharp and the other six half-flat). In ups and downs the first is simply the scale
`^C vD ...`; the tutor would say `^F` for the score's F half-sharp.

### Arrows and quarter-tone signs in 16: "Don't Take Five"

This notation is the transcriber's, not a wiki standard (the wiki's 16edo page describes other
systems: Goldsmith's circle, Armodue, mavila-based letters). It keeps the 12-tone letters and
measures everything in cents: an arrow on a natural, sharp or flat is 25 cents, a quarter-tone sign
is 50 cents. A step of 16 is 75 cents, and the JSON states the rule: step = (cents above C + 25) / 75,
so D, F, G sharp and B are plain notes and C natural does not occur. Twelve signs occur in the
file: natural, sharp, double sharp, the half/sesqui signs, and arrows on natural and sharp (up, down)
and on flat (up). Two notes of the file (bars 65 and 87) are spelled with a sign that does not land on a
step; the sheet shows the spelling.

### Two pianos a quarter-tone apart: Wyschnegradsky

Both pianos read ordinary 12-tone notation. Piano II is tuned a quarter-tone lower, so its part is
written a quarter-tone above what sounds; the reader never sees a quarter-tone sign. In our file a
step is a quarter-tone (C4 = 96): piano I has the even steps, piano II the odd ones, and the
written key of a piano II note is `(step + 1) / 2`.

### Sagittal and HEJI (not used here)

Sagittal, per the wiki, "is a musical notation system capable of notating almost any conceivable
tuning while preserving, as much as possible, the notation of harmonies across different tunings.
It uses arrow-like symbols made up of four simple components whose visual size is proportional to
their alteration". It comes in an "Evo" flavour (next to ordinary sharps and flats) and a "Revo"
flavour (replacing them). The wiki pages of 17, 22, 24, 31, 41 and 53 notes per octave each have a
Sagittal section with the chart for that tuning. This project has no Sagittal output.

HEJI, the Helmholtz-Ellis JI pitch notation, "is a musical notation system for just intonation
intervals up to the 47-limit. Based on chain-of-fifths notation with default staff notation
representing Pythagorean tuning, it adds a set of accidentals defined by formal commas to reach each
prime harmonic." It describes ratios, not steps of a tuning; this project does not use it. Note that
SMuFL's arrow glyphs named "...OneArrowUp", "...TwoArrowsUp" belong to HEJI (the arrow is a syntonic
comma there); see section 2 for why they are of little use at present.

## 2. How each sign is written in MusicXML

A note carries two things: `<alter>` (how far the pitch lies from the letter, in semitones,
decimals allowed) and `<accidental>` (which sign is printed). They are independent: the engraver
prints what `<accidental>` says and nothing if it is absent.

All signs the exporter can write (`ACCIDENTALS` in `musicxml.py`). "Drawn" is the SMuFL glyph Verovio
6.4.1 put on the page, read from its SVG (the glyph ids are SMuFL code points);
`test_verovio_draws_the_glyph_each_sign_stands_for` repeats the check.

| Our name | In note names | `<alter>` | `<accidental>` | Drawn by Verovio |
|---|---|---|---|---|
| natural | (none) | 0 | `natural` | U+E261 accidentalNatural |
| sharp | `#` | 1 | `sharp` | U+E262 accidentalSharp |
| flat | `b` | -1 | `flat` | U+E260 accidentalFlat |
| double-sharp | `x` | 2 | `double-sharp` | U+E263 accidentalDoubleSharp |
| double-flat | `bb` | -2 | `flat-flat` | U+E264 accidentalDoubleFlat |
| half-sharp | `t`, `+` | 0.5 | `quarter-sharp` | U+E282 accidentalQuarterToneSharpStein |
| half-flat | `d` | -0.5 | `quarter-flat` | U+E280 accidentalQuarterToneFlatStein |
| sesquisharp | `#t`, `#+` | 1.5 | `three-quarters-sharp` | U+E283 accidentalThreeQuarterTonesSharpStein |
| sesquiflat | `db` | -1.5 | `three-quarters-flat` | U+E281 accidentalThreeQuarterTonesFlatZimmermann |
| natural-arrow-up | `^` | 0.25 | `natural-up` | U+E272 accidentalQuarterToneSharpNaturalArrowUp |
| natural-arrow-down | `v` | -0.25 | `natural-down` | U+E273 accidentalQuarterToneFlatNaturalArrowDown |
| sharp-arrow-up | `#^` | 1.25 | `sharp-up` | U+E274 accidentalThreeQuarterTonesSharpArrowUp |
| sharp-arrow-down | `#v` | 0.75 | `sharp-down` | U+E275 accidentalQuarterToneSharpArrowDown |
| flat-arrow-up | `b^` | -0.75 | `flat-up` | U+E270 accidentalQuarterToneFlatArrowUp |
| flat-arrow-down | `bv` | -1.25 | `flat-down` | U+E271 accidentalThreeQuarterTonesFlatArrowDown |
| double-sharp-arrow-up | `x^` | 2.25 | `double-sharp-up` | **nothing** |
| double-sharp-arrow-down | `xv` | 1.75 | `double-sharp-down` | **nothing** |
| double-flat-arrow-up | `bb^` | -1.75 | `flat-flat-up` | **nothing** |
| double-flat-arrow-down | `bbv` | -2.25 | `flat-flat-down` | **nothing** |

The `<alter>` column is what the sign says in 12-tone terms with the arrow at 25 cents (the
"Don't Take Five" convention). The glyph names of the arrows speak of quarter-tones because SMuFL
files them under "Gould arrow quartertone accidentals"; the shape is what matters.

Values that did **not** render in Verovio 6.4.1, and what to do:

| Written | Result | Instead |
|---|---|---|
| `double-sharp-up`, `double-sharp-down`, `flat-flat-up`, `flat-flat-down` | no sign at all (the note looks natural) | none of our files needs them; `write_sheet` puts a warning into `score.warnings` if one occurs. Not checked with MuseScore |
| `arrow-up`, `arrow-down` (a bare arrow) | no sign | use `natural-up` / `natural-down`: an arrow by itself implies a natural anyway (wiki, see above) |
| `sharp-1` .. `sharp-5`, `flat-1` .. `flat-4` (Turkish comma signs) | no sign | not used; `slash-flat`, `slash-sharp` etc. are drawn (U+E440-E447) |
| `<accidental smufl="accidentalNaturalTwoArrowsUp">other</accidental>` and every other SMuFL name tried except one Verovio already knows | a plain **natural** sign | do not use: it prints a wrong sign. Double arrows (`^^C` in 41 and 53) have no working spelling with Verovio; see open points |

Drawn correctly besides the table: `sharp-sharp`, `natural-sharp`, `natural-flat`, `triple-sharp`,
`triple-flat`, `sori`, `koron`, `slash-quarter-sharp`, `slash-sharp`, `slash-flat`, `double-slash-flat`.

### `<alter>` in a tuning that is not a multiple of 12

`<alter>` is defined against the 12-tone pitch of the letter, in semitones. In a tuning whose
steps are not 100 or 50 cents, neither the letters nor the signs lie where 12 tones put them, so the
value has to be computed from the pitch that sounds:

```
alter = (step - step of A4) * 12 / n  -  (semitones from A4 to the letter in 12 tones)
```

This is `edo_alter(step, n, letter, octave)`. Step 0 is C0 and the letters are a chain of the
tuning's fifths, so A4 is step `4n + 3 * fifth - n` (81 in 17). Examples in 17: C half-sharp 4 is
+0.5294 (not 0.5), a plain D4 is -0.0588 (its fifth to A is 6 cents wide), A half-flat 4 is
-0.7059. Write the value with a few decimals; `<accidental>` still names the printed sign
(`quarter-sharp`), and `<key-alter>` in a key signature gets the same kind of number.

The exporter uses this for files that give only names in the tuning's own signs (17). Where the
file states the sign in 12-tone terms (16, `accidental` field) or the tuning is 24, `alter` is what
the sign says.

What programs do with a decimal `<alter>` (as tried here):

| Program | Display | Playback |
|---|---|---|
| Verovio 6.4.1 | only from `<accidental>`; a note with `<alter>1</alter>` and no `<accidental>` gets no sign | its MIDI plays the 12-tone key of the letter (C quarter-sharp sounds as C); no pitch bend. Its MEI keeps `accid.ges` only for the values it knows (0.5 becomes "su", 0.53 is dropped) |
| music21 10.5 | reads 0.5, -0.5, 1.5, -1.5 as half-sharp, half-flat, one-and-a-half-sharp/flat with the right pitch (C4 half-sharp = 60.5) | refuses the file for anything else: "incorrect accidental -0.25 for pitch A3". So it can check 12- and 24-tone output, not 16 or 17 |
| MuseScore | not installed here, not tried | not tried |

So the sheets are for reading. To hear a tuning, use the tutor's own synth, not the MusicXML.

## 3. Practical rules from building the exporter

**Durations.** Keep onsets and lengths as fractions of a quarter note (`fractions.Fraction`; a
stored 0.333333 becomes 1/3 with `limit_denominator(128)`). `<divisions>` is the least common
multiple of all denominators in the score, written once in the first bar; with elevenths and
sevenths it becomes large (18480 in two of the preludes), which no reader minded. Every voice of every bar
must add up to exactly the bar; the tests check it.

**Note values and ties.** A length that is one note value (with up to two dots) is written as such;
anything else is cut and tied. Cut first at the barline, then where a note leaves a beat group out
of its middle, then inside a group at the most even point (5/16 from the beat = quarter + sixteenth).
The beat groups are a guess when the file does not give them: 4/4 = 2 + 2, 6/8 9/8 12/8 in dotted
quarters, 3/4 one group, 5/4 = 2 + 2 + 1, everything else in quarters with the remainder last. If the
file already holds the printed note values (the Woyten files), keep them (`keep_values`); they are
what the reader compares. Rests are always cut at group boundaries.

**Ties need `<tie>` and `<tied>`,** both, on both notes. Readers pair them within a voice, so a note
tied over a barline must keep its voice number; that is why a voice keeps its number through the
whole piece here, and a bar may hold voice 2 without voice 1.

**Tuplets.** Detect them from the onsets: for the first point that is not on the binary grid, try
every stretch between two binary points and take the cheapest division (`find_tuplets`). Write
`<time-modification>` (actual, normal, normal-type) on every note of the tuplet and
`<tuplet type="start" bracket="yes"/>` / `type="stop"` on the first and last. Use
`show-number="both"` for ratios that are not the usual one (5:3, 7:6, 3:7). Nested tuplets come out
flat (five inside seven = 35 in the time of 24 or 32); correct, but not how it was printed. Two
notes in the time of three need no tuplet: dotted values say the same.

**Voices.** MusicXML wants one voice after the other, with `<backup>` (by the bar length) in
between. Put a chord into the first voice of its staff that is free at its onset, top notes first;
honour a voice the file names. Number them 1-4 for the first staff, 5-8 for the second, as
MuseScore does. Fill gaps with rests; at the end of a second voice use `<forward>` instead, or the
page fills with rests.

**Accidentals.** Work them out for your own layout: one state per line or space of a staff, valid
for all voices until the barline, starting from the key signature. Never copy "this accidental was
printed" from a source: a sheet meant for checking must show the pitch the file holds. A note tied
in from the bar before gets no sign, and the next note on its line gets one in any case.

**Key signatures in other tunings.** The originals use them ("Ephemeral Happiness": seven
quarter-tone signs). MusicXML can say this with the non-traditional key: inside `<key>`, repeat
`<key-step>`, `<key-alter>`, `<key-accidental>` for every altered letter, in the order they are
to appear. Verovio draws them on every system. What MusicXML cannot say: a "global arrow" as in
the wiki's "F# C# (v)", and where on the staff each sign sits (the engraver decides the octave).
An ordinary signature is `<fifths>`; the exporter writes that when the signs are plain sharps or
flats in the usual order.

**Bar numbers.** `<measure number="...">` takes the number you want printed (the preludes: the
engraving's numbers, after leaving out the barlines that are no bars). Verovio prints them on every
bar with `mnumInterval: 1`.

**Texts and tempo.** A text is a `<direction placement="above">` with `<words>` and a `<staff>`;
a tempo is `<metronome>` with `<beat-unit>` and `<per-minute>` (the latter may be text: "52 / 40").
To place one inside a bar, move there with `<forward>` before it and return with `<backup>`; both
Verovio and the readers follow that. Long texts are not given room: they overlap the next text if
they stand close.

**Two readings and doubtful places.** The note gets `<notehead parentheses="yes">`, and one text
per run of such notes names the other reading in the same order ("engr.: B3 C4 Db4 D4"). A doubtful
bar or place gets a bold "?" over its staff. Both are explained in the header of each sheet.

**Titles.** `<credit>` elements with `<credit-type>` title / subtitle / composer; Verovio sets them
as centred lines over the first system (all in one size, see glitches).

**Page layout that mattered** (Verovio options): `condense: "none"` (otherwise empty staves vanish
from later systems, which looks like missing music), `pageWidth`/`pageHeight` chosen from the staff
height wanted (a staff is 72 units high; `scale` cancels out), `spacingLinear: 0.5` (default 0.25
squeezes dense bars), `mnumInterval: 1`, `footer: "none"`.

**`<transpose>`.** The schema allows `<chromatic>-0.5</chromatic>` for an instrument a quarter-tone
lower, but music21 stops with "invalid literal for int()". The exporter leaves it out and says it in
the part name.

## 4. Rendering

Engraver used: **Verovio 6.4.1**, the `verovio` Python package (`python -m pip install verovio`; it
sits in the user's site-packages, nothing else was installed). No MuseScore or LilyPond is on this
machine. If a MuseScore is found (path, `Program Files`, or unpacked under `reference/tools/`),
`render_pdf` uses it instead: `MuseScore4.exe -o out.pdf in.musicxml`. That path was not run here.

Commands:

```
cd host
python -m tutor.scores.musicxml --all                       # all sheets, about 15 s
python -m tutor.scores.musicxml --all --sounding            # also the preludes with piano II at sounding pitch
python -m tutor.scores.musicxml FILE.json OUT.musicxml --pdf --prelude 16
python -m pytest ../tests/test_tutor_musicxml.py -q
```

What `render_pdf` does with Verovio: `toolkit.setOptions(VEROVIO_OPTIONS + page size)`,
`toolkit.loadData(xml)`, `toolkit.renderToSVG(page)` for each page, then PyMuPDF turns each SVG
into a PDF page (`pymupdf.open(stream=svg, filetype="svg").convert_to_pdf()`) and places it on A4.

Glitches and workarounds:

| Glitch | Workaround |
|---|---|
| PyMuPDF's SVG reader shows an empty page for Verovio's SVG (inner `<svg viewBox>`, style sheet) | `plain_svg()`: the inner `<svg>` becomes a scaled `<g>`, the style rules become attributes (lines stroked, text not, tempo bold), placeholders are removed |
| The quarter note of a metronome mark is a character of the music font, which the PDF converter does not have | `plain_svg()` draws a notehead and a stem in its place |
| Title and subtitle come in one size | `plain_svg()` enlarges the first line of the page header |
| Signs Verovio does not draw (section 2) | warning in `score.warnings`; avoid them |
| Verovio reports every tightly set system on stderr | `verovio.enableLog(verovio.LOG_OFF)` |
| No octave lines and fixed clefs: very high or low notes sit on many ledger lines | not solved |
| Many voices in one bar collide (rests on rests, brackets on brackets) | not solved; the content is right, the look is crowded (worst: Prelude IX) |
| Systems are not spread over the page height; the last system of a short piece is not stretched | left as it is |

Checking a result: render pages to PNG and look.

```python
import pymupdf
doc = pymupdf.open("prelude_01.pdf")
doc[0].get_pixmap(dpi=130).save("p1.png")                                  # a page
doc[0].get_pixmap(dpi=300, clip=pymupdf.Rect(0, 100, 300, 250)).save("x.png")   # a detail
```

And check the file itself without eyes: read the MusicXML back and compare with what went in
(`read_back` in `tests/test_tutor_musicxml.py` does it in 50 lines), and validate against the
MusicXML 4.0 schema (`musicxml.xsd` from the W3C repository with `lxml.etree.XMLSchema`; all 26
files passed on 2026-11-27).

## 5. The exporter's interface

`host/tutor/scores/musicxml.py`:

| Function | What it does |
|---|---|
| `to_musicxml(score) -> str` | a `Score` as MusicXML; problems go to `score.warnings` |
| `write_sheet(score, base, pdf=True, staff_mm=6.0) -> pages` | writes `base.musicxml` and `base.pdf` |
| `render_pdf(xml_path, pdf_path, staff_mm=6.0) -> pages` | engraves an existing MusicXML file |
| `bars_score(data, header, doubtful)` | a score file with `bars` and two staves (the Woyten format) as `Score` |
| `prelude_score(prelude, sounding=False, doubtful, updown=False)` | one prelude of `preludes.json` as `Score` on four staves; with `updown` for one player on two staves |
| `prelude_hands(prelude) -> (notes, staves)` | the staff (0 upper = right hand, 1 lower = left hand) of every note in the layout for one player; the library uses the same call |
| `choose_clefs(bars, first)`, `set_clefs(score)`, `ledger_lines(note, clef)` | a clef per bar and staff after the notes it holds |
| `write_all(source, sounding, pdf)` | all sheets (`--all`) |
| `edo_alter(step, n, letter, octave)` | `<alter>` in an equal tuning |
| `find_tuplets`, `split_values`, `note_value`, `group_bounds`, `assign_voices` | the rhythm rules of section 3, usable on their own |
| `engraver()` | which engraver would be used, as text |

The score format (dataclasses):

- `Score(title, parts, bars, events, marks=[], header=[], composer="", keep_values=False)`
- `Part(name, clefs=["G", "F"])`: one clef per staff. Staves are counted through all parts from 0.
- `Bar(number, time, start, length, key=None, repeat_start, repeat_end, ending)`: `start` and
  `length` in quarter notes; `key` is a list like `[("F", "half-sharp"), ("B", "half-flat")]`.
- `Event(staff, onset, dur, notes, voice=0, grace=False, fermata=False, staccato=False)`: a chord;
  `onset` from the start of the piece, both as `Fraction`. It may cross barlines.
- `Note(letter, octave, accidental="natural", alter=None, tie_in=False, other="", other_source="")`:
  `accidental` is a name from the table in section 2; `other` is the text of a second reading.
- `Mark(onset, staff, text, tempo=False)`: a text over a staff, or a tempo in quarters per minute.

One bar with a microtonal chord, written and engraved:

```python
import sys; sys.path.insert(0, "host")
from fractions import Fraction as F
from pathlib import Path
from tutor.scores import musicxml as mx

chord = [mx.Note("C", 4), mx.Note("E", 4, "half-flat"), mx.Note("G", 4), mx.Note("B", 4, "natural-arrow-down")]
score = mx.Score("One bar", [mx.Part("", ["G"])], [mx.Bar(1, "4/4", F(0), F(4))],
                 [mx.Event(0, F(0), F(2), chord), mx.Event(0, F(2), F(2), [mx.Note("F", 4, "sharp-arrow-up")])],
                 header=["A chord with a neutral third, written by program."])
pages = mx.write_sheet(score, Path("build/one_bar"))      # build/one_bar.musicxml and build/one_bar.pdf
print(pages, score.warnings)
```

## 6. Open points for a tutor function

- **From a tutor name to a `Note`.** The tutor's names are ups and downs (`vE4`, `^C#5`). One arrow
  maps directly: `^` = `natural-arrow-up`, `^C#` = `sharp-arrow-up`, and so on; `alter` should be
  computed with `edo_alter` from the step. This mapping is not written yet.
- **Double and triple arrows** (41 and 53: `^^C`, `vvD`) have no MusicXML value, and Verovio draws a
  natural for the SMuFL glyphs that exist. Ways out to try: MuseScore as engraver, respelling (the wiki: in 41 "half-sharps and half-flats can be used to avoid double
  arrows"), or writing the arrows as a text over the note. None is tried.
- **Which signs to show a learner.** In 17, 24 and 31 one arrow equals a half-sharp, so the same
  chord can be written with arrows or with quarter-tone signs. A decision per tuning is needed;
  arrows match what the tutor says aloud.
- **Spelling in the preludes.** The file holds key numbers only. Sharp or flat is chosen by a rule
  (`Speller`). The staff: on the four-staff proofreading sheet by pitch within each piano
  (`choose_staves`); on the sheet for one player the printed staff, which the reader
  (`reference/music/wyschnegradsky/convert.py`) now stores per note (`staff`). To look like the
  engraving it would have to store spelling and clef as well.
- **Beams.** Written per beat and per tuplet; the original's beams (across beats, across staves) are
  not kept in the files.
- **Octave lines and clef changes.** Octave lines are not written. Clefs are fixed (treble over bass)
  except on the preludes for one player, where `set_clefs` chooses them after the notes of each staff
  (see below); a change of clef stands at a barline only, never inside a bar.
- **Fingering and key colours.** MusicXML has `<technical><fingering>` per note and a `color`
  attribute on `<note>` and `<notehead>`. Neither is written yet, and whether Verovio draws them
  was not tried. Colours would let a sheet show the keyboard's key colours.
- **Playback.** No program tried here plays the decimal `<alter>` (section 2). A sheet with sound
  needs the tutor's synth beside it, or MIDI with pitch bend written by us.
- **Layout.** One page size and staff size per kind of sheet; no control over system breaks, and
  text marks do not make room for themselves.

## The preludes in ups-and-downs notation

`python -m tutor.scores.musicxml --all --updown` also writes every prelude as one quarter-tone instrument on two staves (both pianos together, as in the composer's reduction op. 22a), at sounding
pitch, each note named as xenharmlib's `UpDownNotation` names it in 24 notes per octave (`updown_note`,
through `theory.Tuning.name`): C, ^C, C#, vD, D ... An arrow is one step (a quarter-tone), a sharp two.
xenharmlib's first name uses sharps only and never more than one arrow, so the only signs needed are
`natural-up` and `natural-down` (`<alter>` 0.5 and -0.5) next to the plain sharp, all of which Verovio
draws. Files: `prelude_NN_updown.*` and `preludes_as_read_updown.pdf`. These are the names the tutor
speaks, so this is the sheet that matches a lesson.

**Which staff, which hand.** Every note stays on the staff it is printed on in the two-piano edition:
the upper staves of both pianos are the upper staff (right hand), the lower staves the lower staff
(left hand), so melody and bass stay where the composer wrote them, whatever their pitch
(`prelude_hands`; the tutor's library takes the division from the same function, so sheet and lesson
agree). The earlier rule by pitch (above F4 up, below G3 down) had moved 30 % of the notes to the
other staff. This is this project's arrangement for one player, not the composer's: where his own
two-staff version (op. 22a) is at hand (Prelude I bars 1-22, Prelude XVI bars 1-29, read from four
page images), 79 % of the notes are on the same staff as there. He redistributes: in Prelude I he
gives the note that ends each rising run to the left hand, in Prelude XVI the tenor notes under the
melody.

About 4 % of the notes have no printed staff in the file (bars typed in by hand). They are placed by
`host/tutor/scores/hands.py`, `assign_hands`, with all other notes held fixed: a search for the
cheapest division between two hands in the manner of Nakamura, Ono & Sagayama (merged-output HMM,
ISMIR 2014: each hand a chain of its own notes, solved with the Viterbi algorithm), with the pitch
proximity and no-crossing of Chew & Wu (2004) and the hand spans of the fingering model (Balliauw
et al. 2017) as costs. No pip package separates hands (`partitura` has Chew & Wu's voices only,
`music21` nothing, `pianoplayer` wants the hands given). Hidden from it a quarter of the bars at a
time, it puts 90 % of the notes of Preludes 1-10 back on their printed staff (87 % in Nos. 13-24,
which were not used to set its weights). The same module says what two hands cannot do
(`playability`): the music is for four hands, and no note is moved or left out because of that.

**Clefs.** A staff now holds what its hand plays, which may lie anywhere (the print itself often has
both staves in the treble clef and changes clef). `set_clefs` picks, per staff and bar, among treble,
bass, bass an octave lower and treble an octave higher the clefs that need the fewest ledger lines
over the whole piece, a change counting as much as six ledger lines, so a passage brings a change of
clef and a single note does not. Changes stand at barlines.

## The preludes in the composer's own spelling

`python -m tutor.scores.musicxml --all --composer` writes, for every prelude whose scale has been read from
the edition, a sheet spelled as the composer spells it (`prelude_NN_composer.*`). Each prelude is headed by
its 13-note scale ("Position Si" for the third); `reference/music/wyschnegradsky/positions.json` holds that
scale as pitch class -> name (`F#t` = F three-quarter-sharp, `Gt` = G quarter-sharp, `Ad` = A quarter-flat).
A note of the scale takes that spelling (`spelled_name`); a note outside it is spelled by rule with sharps.
The signs are the standard MusicXML `quarter-sharp`, `three-quarters-sharp`, `quarter-flat`, which Verovio
draws. Ups and downs name the same pitch differently (F three-quarter-sharp is `vG`): the composer's
spelling shows the scale degree, xenharmlib's first name does not.
