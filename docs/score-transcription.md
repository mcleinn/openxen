# Getting a printed score into the tutor's library

How the transcribed pieces in the library were made, which method fits which kind of source, and
what went wrong along the way. Written after transcribing two pieces by Woyten and Wyschnegradsky's
24 Preludes op. 22. The scores themselves, the scans and the recordings are private reference
material under `reference/music/` and are not in this repository; this page describes the method.

Related: [tutor.md](tutor.md) (library, grades, sheets), [microtonal-notation.md](microtonal-notation.md)
(writing sheets by program), [testing.md](testing.md).

## First: what kind of source is it?

Open the file and look before choosing a method. The three kinds need entirely different work.

| Source | How to tell | Method | Used for |
| --- | --- | --- | --- |
| PDF exported from a notation program | Zooming stays sharp; `pymupdf` finds text in a music font (`page.get_text("dict")`) and vector paths | Read the glyphs and paths directly: exact, no recognition | "Don't Take Five"; Ueli Raz's engraving of the preludes |
| PDF or images of a clean modern engraving, as pixels | Zooming gets blurry; no text layer | Optical recognition (`homr`), then repair what it cannot know | "Ephemeral Happiness" |
| Scan of a printed book, dense or hand-engraved | As above, but smaller, skewed, smeared | Read by eye from enlarged crops, bar by bar, against an existing draft | The composer's edition of the preludes (Belaieff 418) |

Before any of this, make sure of two things:

- **It is the right edition.** The preludes exist as a two-piano edition (four staves, ordinary
  notation, second piano a quarter-tone low) and as the composer's edition for one quarter-tone
  instrument (two staves, quarter-tone signs). Only the second says which hand plays what. Read the
  title page; a day of work went into the wrong one.
- **It is the document, not a preview.** Document sites show reduced page images to visitors (here:
  904 px for a double spread) and hand out the full file only to a logged-in account. At preview size
  a quarter-tone sign is a few pixels. Ask the owner for the downloaded file.

## Method 1: a PDF from a notation program

`host/tutor/scores/musescore_pdf.py` (general, with tests) and, for the preludes,
`reference/music/wyschnegradsky/convert.py`.

- Noteheads, accidentals, rests, flags, dots, clefs and time-signature digits are characters of the
  music font (SMuFL code points) at exact positions; staff lines, stems, ledger lines, beams, barlines,
  ties and octave lines are vector paths.
- Pitch = staff position from the notehead's height against the staff lines, the clef, the accidental
  (with the bar-long rule) and octave lines. Rhythm = head type, flags or beams, dots, tuplets.
- Check with numbers the PDF itself gives: every bar adds up to its time signature in every staff;
  counts of noteheads, accidentals and rests per page match what was read.

What went wrong, so look for it:

- A slur starting on a note followed by the same written pitch was taken for a tie (the second note
  is lost, the first too long).
- Two heads on one staff position on a forked stem (clusters) both got the same accidental.
- Notes after a clef change inside a bar came out half a beat early or in the wrong octave.
- A time signature announced at the end of a system was counted as a bar of silence.
- Accidentals on grace notes were ignored, although they hold for the rest of the bar.
- Tempo marks inside a bar were all put on the barline.
- Bars with more than two voices on a staff: onsets can be wrong inside the bar without failing the
  bar-sum check.

## Method 2: optical recognition

`homr` (pip) reads notes, rhythm and bars from page images of a clean engraving. It knows nothing of
microtonal accidentals. For "Ephemeral Happiness" these were recovered by searching the page images
for the seven sign shapes with templates cut from the score itself, checking contact sheets of the
found signs by eye, and then verifying against the recording (below). Rhythm inside a bar is only as
good as the recogniser: bar sums catch some errors, not a wrong duration that still fills the bar.

## Method 3: reading a scan by eye

Used for the composer's edition of the preludes. No recognition tool was used: each system was
cropped and enlarged (8 to 20 times) with `pymupdf` and read, bar by bar, against the draft from
method 1. The working instructions are `reference/music/wyschnegradsky/PROOF_BRIEF.md`; the rules that
mattered:

- Write down what a bar shows **before** looking at the draft's notes for that bar. Otherwise one
  reads what one expects.
- Measure, do not judge: line or space is decided by the notehead's height against the staff lines.
- Never guess. What cannot be read is listed and left as it is; the piece is then graded
  "partly checked" with those bars named.
- Dense chords and clusters are the limit of a scan of about 880 px per page: head count, outline and
  signs as a set can be compared, single heads cannot.
- One correction file per piece (`overrides.d/NN.json`), produced by a script, applied by the converter
  after reading: the result stays reproducible, and several pieces can be worked on at once.

## A copy of a score is not the score

The draft of the preludes was read from a volunteer's engraving of the two-piano edition. Read against
the printed editions, that engraving turned out to have a whole staff a semitone low through four
preludes, octave lines left out or added, missing ties, a missing voice, and wrong rhythms: in one
prelude 117 of 542 notes. Our reading of the engraving was almost exact; the engraving was wrong.
Treat any secondary copy as a draft and name its source on every piece.

## Checking against a recording

Scripts in `reference/music/woyten/work/` and `reference/music/wyschnegradsky/verify/`: a constant-Q
analysis with one bin per step of the tuning, alignment of score and audio, and a verdict per note
(confirmed, masked by another note's overtone, undecided, contradicted).

- It is a check, not a proof. Measure how sharp it is by planting errors on purpose: here a pitch one
  step off was flagged outright about half the time and passed as confirmed 4 % of the time; an octave
  error or a moved onset passed 16 to 18 % of the time. It does not hear note lengths or ties.
- A machine rendering of the same engraving checks the reading, not the music. A real performance
  checks the music, more bluntly (rubato, pedal).
- It missed what mattered most: an octave line left out over 24 notes in a prelude it had rated best.
  Only reading against the print found that.

## Where sources differ

Do not pick silently. A note keeps both readings:
`{"step": 48, "source": "print", "also": [{"step": 47, "source": "recording"}]}`. The library hands
them to the tutor per bar (`two_readings`) and the proofreading sheet prints the other reading above
the staff. Source names in use: `print` (two-piano edition), `print22a` (the composer's two-staff
edition), `engraving` (the volunteer's copy), `recording`.

A confirmed error (wrong against the authority) is corrected at once and reported afterwards.

## Music for two instruments, played on one

The two pianos a quarter-tone apart were the composer's way to get quarter-tones from ordinary
instruments. For one microtonal keyboard both are merged at sounding pitch. Which hand plays a note is
taken from the composer's own two-staff edition where it has been read (`"hand"` on the note), else
from the staff the note is printed on; never from pitch height, and never from which piano it was on.
The tutor does not get the two-piano layout at all; it survives only in the four-staff proofreading
sheet, for comparing with the source.

## Expression marks

Dynamics, hairpins, tempo words, pedal, accents, fermatas and slurs are part of the transcription
(`"marks"` in `preludes.json`; format in `convert.py`'s docstring, method and counts in `MARKS.md` of
the reference folder). Two ways in, as for the notes:

- **Automatically from the vector PDF** (all 24 preludes): dynamics are glyphs of a text font, hairpins
  pairs of slanted lines, accents, staccato dots, tenuto lines and fermatas glyphs at a note, slurs the
  curves that are not ties, and the engraver's pedal is a small extra staff ("CC 64 Sustain": high note
  = down, low note = up). A mark gets the time of the note column nearest in x and the staff it stands
  at. This reads what the engraver wrote, per piano, and he wrote for playback: no tempo or expression
  words at all (his ritardandi are metronome marks), "crescendo - - -" as hairpins, pedal only where
  he needed it.
- **By eye from the authoritative edition** (Prelude III so far): every bar's automatic marks are
  cleared and the edition's entered with the override operation `marks` (add, change, delete, clear),
  from a script, like the note corrections. Of the 46 marks the two-staff edition prints in Prelude
  III the engraving has 32; the 14 others are the four tempo words, "simile", two hairpins, the one
  accent, three dynamics missing and three at another level. The engraving has 103 more marks that
  the two-staff edition does not print (staccato, tenuto, accents, slurs and each piano's own
  dynamics of the two-piano version).

Not carried: trill lines and octave lines (they are in the notes), arpeggio signs, fingering,
the metronome mark as a mark (it is in `tempi`), and the text of the preface.

## Grades

Every transcribed piece says how far it was checked (`checked` in the library, see tutor.md):
"well checked" only when every note was read against the authoritative edition; "partly checked"
otherwise, with the doubtful bars named. The tutor warns the player once and names a recording.

## Proofreading with a sheet of our own reading

`python -m tutor.scores.musicxml --all --updown` (from `host/`) engraves what our files hold. Laid
beside the original it shows errors at a glance that no numeric check found (a missed octave line, a
slur read as a tie). Make this sheet early.

## Cost

Reading one prelude (about 500 notes) by eye against the scan took a helper about half an hour and on
the order of half a million tokens; the 24 preludes about three hours of wall time in four parallel
batches. Reading a notation-program PDF costs minutes for a whole cycle. Check for such a file first.
