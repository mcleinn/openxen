# openxen tutor: an MCP server for assisted playing

A language model as piano teacher: it lights keys, hears what was played and teaches chords,
inversions, progressions, fingerings and melodies in the tuning the keyboard is in. The model
runs in an agent such as Claude Code; this repository provides the tools it uses.

```
keyboard PC
┌────────────────────────────────────────────────┐
│ openxen modules ──USB── xentool serve --api    │
│                           │ 127.0.0.1:9098     │
│                           ▼                    │
│            python -m tutor  (host/tutor) ──────┼── MCP over HTTP, port 9097
│            theory, keyboard model, exercises   │   bearer token on the local network
└────────────────────────────────────────────────┘        ▲
                                                           │ MCP client: Claude Code,
                                                           │ on this PC or another one
```

- **xentool** stays the only program that talks to the modules. Its local API (xentool
  `src/api.rs`) gives the keyboard description, key presses with the physical key, an LED
  overlay above the layout colours, and notes sounded through the normal MIDI output.
- **The tutor server** does everything that needs timing: it waits for the right keys,
  judges, lights the next step. A model turn takes seconds, so one tool call runs a whole
  exercise and returns a short summary.
- **The model** chooses what to teach and explains. `.claude/skills/openxen-tutor/SKILL.md`
  tells it how the instrument works for a player and how to use the tools.

## What the model sees

One keyboard, as a player has it: keys with note names and note numbers, six neighbours per
key, the same note on several keys, chords as hand shapes. Key ids are opaque (`k319`) and
only copied from tool results. Not shown: module numbers, key positions in the hex lattice,
MIDI channels and notes.

Notes are always given both ways, because players of tunings with many notes per octave
usually use numbers: the name in ups-and-downs notation and the number, the step within the
octave counted from C = 0. Lists write `vE4 (17)`, key entries carry `note` and `number`,
intervals come with their size (`downmajor third (vM3, 17 steps)`), and the key map is
printed once by name and once by number. As input a note may be a name (`vE4`, `Eb`), a
number (`17`, any octave; `17(4)`, octave 4) or the combined form the tools write. `tests/test_tutor_server.py` checks that no tool
description or result names them.

## Starting

```
powershell -ExecutionPolicy Bypass -File host\tools\play.ps1 -Tutor        # this PC only
powershell -ExecutionPolicy Bypass -File host\tools\play.ps1 -TutorLan     # local network
```

By hand:

```
xentool serve build\layouts\53ET-bosanquet.otn --tune-supercollider --api
cd host
python -m tutor                         # http://127.0.0.1:9097/mcp
python -m tutor --host 0.0.0.0          # local network; needs OPENXEN_TUTOR_TOKEN
python -m tutor --fake 31               # no keyboard: a made-up 31-tone module
```

Dependencies: `python -m pip install -r host/tutor/requirements.txt` (Python 3.12).

**Without a keyboard** (`--fake EDO`). The server describes a made-up module and tells the
model so: the server instructions and `keyboard_info` carry a `practice_mode` note, lookups
(`keys`, `theory`, `find_shape`) work, `set_lights` says nobody sees the lights, and `demo`,
`listen` and `run_exercise` answer at once that they need the real keyboard.

**Local network.** With `--host 0.0.0.0` the server refuses to start unless
`OPENXEN_TUTOR_TOKEN` is set (any long random string). Every request must carry
`Authorization: Bearer <token>`; without it the answer is 401. Traffic is plain HTTP: use it
on a network you trust. xentool's own API always listens on 127.0.0.1 only.

**Tailscale** (`play.ps1 -TutorTailscale`). The server listens on this PC's Tailscale address
only: other machines of the tailnet reach it encrypted at
`http://<pc-name>.<tailnet>.ts.net:9097/mcp`, the local network and 127.0.0.1 do not. Same
token; `play.ps1` reads it from the user environment variable if the shell does not have it.
Windows Firewall is not in the way as long as the Tailscale interface counts as a private
network. Checked on 2026-11-25 from this PC (401 without token, MCP `initialize` with it, no
answer on the WiFi address); not yet from a second machine.

**Claude Code.** `.mcp.json` registers the server. On the keyboard PC nothing else is needed.
On another machine set two environment variables before starting Claude Code:

```
OPENXEN_TUTOR_URL=http://<keyboard-pc>:9097/mcp
OPENXEN_TUTOR_TOKEN=<the same token>
```

**How the keyboard lies in front of the player** (`--tilt`, `play.ps1 -Tilt`). The direction
names the model uses ("right", "upper right", "up") must match what the player sees.
`0` (default): key rows run level, as with a single module square on the desk, USB edge away
from the player. `lumatone`: the assembled five-module case, where the keyfield is turned
16.1° anticlockwise so that octaves run level; what was "upper right" is then "up".

## Tools

| Tool | What it does |
|---|---|
| `keyboard_info` | Tuning, range, the interval of each of the six directions, chord qualities the tuning offers, light colours, a map of all keys by note name and one by note number |
| `tuning` | The tunings (layouts) the keyboard can be switched to; with `to` (notes per octave or a layout name) switches the whole keyboard while it runs and returns the new description |
| `keys` | By key id: note, the six neighbours with intervals, the same note elsewhere. By note name: the keys that play it |
| `theory` | `chord`, `identify`, `scale`, `progression`, `tuning`; answers in note names spelled for the tuning |
| `find_shape` | The ways to play a chord or a set of notes: keys, path from the first key, reach; a finger per key with how it feels and why, and other fingerings of the same keys |
| `fingering` | Fingers for a phrase (melody, progression, mixed), chosen for the phrase as a whole; per step what the context changed and the alternatives |
| `hand` | Measure the player's hand on the keys: resting position (five keys held), widest stretches thumb-little finger and index-little finger; or a size preset; kept in `host/tutor/state/player.json` |
| `fingering_book` | The player's own fingerings per hand shape, kept between sessions; they come first in `find_shape` and `fingering` on every root |
| `library` | Teaching material as ready steps: makam pieces and chant phrase by phrase, raga outlines, practice patterns |
| `harmony` | From the tuning itself: the chords closest to a chord by the smallest movement of the voices (`neighbours`), a progression built from such moves (`path`), progressions and chord vocabularies from the Xenharmonic Wiki (`xen`). From one repertoire: which chord usually follows which (and precedes it), frequent runs, how usual each step of a given progression is, any progression as chord steps, and what the current tuning does to progressions |
| `rhythm` | A click and a pattern to tap on any key; calibrates the player's own offset once (tap along to 20 clicks), then grades each tap (on it, close, near, off, missed, extra) for a level, with tendency, steadiness, drift and the weakest taps. Also the cycles of the rhythm library (talas with their theka, mridangam lessons, usul) by name, sounded on tabla or mridangam where set up |
| `drone` | Holds the tanpura's four notes for a raga (or given notes) under everything else until stopped; names the tuning rule and where the sources disagree |
| `tuning_notes` | Search and read a local copy of the Xenharmonic Wiki: the pages of every tuning the keyboard has a layout for, notation, the chain of fifths, commas, temperaments, beginners' guides |
| `improvise` | The server keeps time: count-in, a backing (chords, roots, drone), the notes of the sounding chord lit; reports per chord what was played, the share of chord tones, what each chord started on, and one rule (only these notes, chord tones only, chord tone or guide tone first) |
| `set_lights` | Light keys by id or note with a role (`target`, `next`, `root`, `lh`, `rh`, `finger1`..`finger5`, `correct`, `wrong`) or a colour; clear single keys or all |
| `demo` | Play and light steps for the player to watch and hear |
| `played` | Everything played since the model was last told (or in the last N seconds), at once: notes in order, what was struck together, chord names, how long ago |
| `listen` | Waits for the player from now on, until they pause: same answer format |
| `run_exercise` | Wait mode: each step waits until played; right keys turn green, wrong ones red; per step result, seconds, attempts, wrong notes |
| `stop` | End a running demo, capture or exercise; lights off |

The player does not wait for the model. The server remembers every note (10 minutes, 4000
notes) whether or not a tool is waiting; `listen` and `run_exercise` count as "told", and any
other tool result carries `unheard` when notes were played that the model has not been told
about, so it calls `played` instead of asking for a repeat.

`demo` shows rhythm: a step lights and sounds for its own `beats`, `{"rest": true}` is a
silence, `repeat` loops the figure and `outline` keeps all its keys dimly lit, so an arpeggio
can be shown as it goes and slowed down with `tempo_bpm`.

`demo`, `listen` and `run_exercise` block for at most 60 s per call and report progress, so an
MCP client does not time out. An exercise that hits its time limit is continued with
`run_exercise(start_at=N)` without sending the steps again.

An exercise also returns with outcome `player paused` when the player has pressed something in
the current step, let go of every key and then played nothing for `pause_s` (default 12 s; 0
switches it off): the result lists what they played and what was expected, so the tutor
responds instead of waiting for the time limit. Searching for the first key of a step, or
holding keys, never counts as a pause.

Exercise rules (`host/tutor/engine.py`, each one tested in `tests/test_tutor_engine.py`):
a step is done when all its notes are held together and at least one was pressed during the
step, so notes shared with the previous chord may stay down; any key sounding the right note
counts unless `exact_keys`; a wrong key held with the chord blocks it until lifted; keys still
held from before are ignored; hints `always`, `after_delay` (or after a failed try), `never`.

Theory (`host/tutor/theory.py`): note and interval names from xenharmlib in ups-and-downs
notation; chords are defined by what they should sound like (4:5:6, 10:12:15, 6:7:9, ...) and
mapped to the nearest notes of the tuning, so C major is C E G in 31 notes per octave and
C vE G in 53. Chord naming of played notes also uses xentool's Scala chord list.

## Fingering

`host/tutor/fingering.py`. No fingering method is published for hexagonal keyboards in
Bosanquet layouts (research of 2026-11-26, `reference/research/fingering.md`), so the model is
built from what carries over:

- finger-pair distances (relaxed, comfortable, practical) and rule weights from piano fingering
  research (Parncutt et al. 1997 in the hand-size tables of Balliauw et al. 2017), converted to
  millimetres and applied to the real key positions (19.2 mm key pitch, tilt included);
- from the Janko keyboard and the button accordion: the thumb plays nearer to the player than
  the fingers and may lie under the hand; among several keys for a note the one that keeps the
  hand still. This follows from a resting posture of the hand, not from black-key rules;
- a phrase is fingered as a whole (trellis search): the way to play each step and its fingers
  are chosen together with its neighbours; shared notes keep their finger; legato and detached
  playing weigh hand moves differently.

Two pianists agree on 60-80 % of the fingers of a piece, so the tools return several ranked
fingerings with reasons, never one answer, and the skill tells the tutor to take the player's
own choice over the computed one.

The player's hand (`host/tutor/player.py`, tool `hand`): the resting fingertip positions are
read from five keys the relaxed hand lies on; the widest stretches thumb-little finger and
index-little finger scale the distance tables (practical limit = 0.9 of the measured stretch,
the relation between the piano tables and spans measured on 473 pianists). Until measured, an
average hand with assumed resting positions is used. The player's own fingerings (tool
`fingering_book`) are stored per hand shape in millimetres, so one entry serves the same chord
quality on every root; they always win over computed ones, also inside phrases. Both are kept
in `host/tutor/state/player.json` (not in git; `--player FILE` or `--player none`).

Still assumed: each finger's free range towards and away from the palm. Open questions for
the player: thumb under versus moving rows in scales, one finger on two keys, sliding between
neighbouring keys.

## Library

`host/tutor/library.py`, tool `library`. Research behind the choices:
`reference/research/repertoire.md`.

| Material | Source | Tuning | Licence |
|---|---|---|---|
| 2,200 Turkish makam pieces (teaching examples, seyir, folk songs, songs, instrumental forms) | SymbTr 2.4.3, `github.com/MTG/SymbTr`, `txt/` | 53, as written: step above C0 = `Koma53` - 53; the practice value, with the theory (Arel-Ezgi-Uzdilek) value kept where it differs | CC BY-NC-SA 4.0 |
| 9,045 Gregorian chants | GregoBaseCorpus v0.4, `github.com/bacor/gregobasecorpus` | any (spelled note names; exactly Pythagorean in 53) | CC0 |
| chord changes of 1,382 jazz standards | `github.com/mikeoliphant/JazzStandards` (from the iReal Pro community database) | any: chord symbols are spelled for the current tuning | none stated; private use |
| 502 older songs as lead sheets (melody and chords) | OpenEWLD, `github.com/00sapo/OpenEWLD` | any | varies by piece; private use |
| compositions in two staves ("Don't Take Five", 16 notes per octave; "Ephemeral Happiness", 17) | read from engraved scores: `host/tutor/scores/musescore_pdf.py` for MuseScore PDFs (glyph positions and vector paths; needs PyMuPDF), optical recognition for page images; JSON under `reference/music/woyten*/` | the tuning each was written for; elsewhere on the nearest notes | private use |
| Wyschnegradsky, 24 Preludes op. 22 (two pianos a quarter-tone apart) | read from Ueli Raz's free vector engraving of the Belaieff edition (`reference/music/wyschnegradsky/convert.py`); repaired once (`REPAIR.md` there): all 945 bars add up in every staff, 34 bars corrected by hand through `overrides.json`, the engraver's copying error in No. 1 bars 1, 3 and 8 corrected from the print; then checked against the engraver's own rendering and against recordings (`VERIFY.md` there): barlines that are no bars removed, grace-note accidentals read, 107 notes carry two readings (Prelude 1: all performances play the print, not the engraving); not proofread as a whole | 24; elsewhere on the nearest notes | private use (work under copyright) |
| 8 raga outlines, each with its tanpura tuning | written here from the 22-shruti model (ratios per note); the drone rule from the rhythm research (see Rhythm) | any: nearest step to each ratio, error reported | this repository |
| rhythm library: 22 Hindustani talas with theka, 40 Carnatic talas, 8 mridangam lessons, 36 usul | `reference/music/rhythm/tala.json` (research of 2026-11-26/27 from the sources in its `SOURCES.md`), converted by `python -m tutor.rhythm_build` to `build/tutor-library/rhythm.json`; tool `rhythm` | none | facts from many sources, each cycle lists its own; private use |
| tabla samples | Subodh Deolekar, "Tabla strokes dataset", Zenodo 4327350, in the bolbox selection; `host/synth/tabla_kit.py` | tabla tuned to C# | CC BY 4.0 |
| 6 practice patterns | alankar / varisai drills | any scale, any tuning | this repository |
| comma lessons | generated: twelve fifths against the start, four fifths against the pure third, eight fifths down, three major thirds against the octave, a comma pump; each with notes to play and a pair to compare, and what comes out in the tuning | any | this repository |
| cycles | generated: the major scale key after key (by fifths, fourths, whole or half steps); two-five-one key after key; the seven chords of a key by falling fifths, major and minor; dominant chains and the rhythm-changes bridge; the major-third cycle with how far it misses the octave; a spoke of the spiral; rings of fifths. Chords follow the comma policy of the jazz changes | any | this repository |
| circle of fifths | generated: a chord or arpeggio moved up a fifth and down a fourth in turn (or the other way), with what the chain of fifths does in the tuning (how many fifths close it, where twelve land, four fifths against the pure third, in 53 the third eight fifths down) | any | this repository |

The collections are third-party material: downloaded to `reference/music/` and converted to
`build/tutor-library/`, both outside git.

```
git clone --depth 1 --filter=blob:none --sparse https://github.com/MTG/SymbTr.git reference/music/symbtr
git -C reference/music/symbtr sparse-checkout set txt
curl -L -o reference/music/gregobase/gregobasecorpus-v0.4.zip https://github.com/bacor/gregobasecorpus/releases/download/v0.4/gregobasecorpus-v0.4.zip
curl -L -o reference/music/jazz/JazzStandards.json https://raw.githubusercontent.com/mikeoliphant/JazzStandards/main/JazzStandards.json
curl -L -o reference/music/jazz/OpenEWLD.zip https://github.com/00sapo/OpenEWLD/archive/refs/heads/master.zip
cd host && python -m tutor.library_build
```

Reference material is for private use and is never published with the tutor, so pieces are
included regardless of their copyright status; nothing under `reference/` or `build/` is in git.

A piece written for one tuning can be played in another on the nearest notes
(`library get ... nearest=true`): `Tuning.retuned_from` uses xenharmlib's `retune`, the same
operation for any pair of tunings, and the result states the largest deviation in cents.

A piece is cut into phrases (at rests and bar lines, at most 12 notes) and handed out one
phrase at a time as steps with note lengths, moved by whole octaves to fit the connected
keyboard. `demo` follows the lengths (`beats` per step). Levels 1-5 grade by form, length and
range. Makam pieces need the keyboard in 53; the tool says so and the tutor can switch.

### Jazz changes in a tuning

A lead-sheet symbol becomes one of the tutor's chord qualities (`library.chord_from_symbol`);
extensions beyond the seventh are left out and reported. Chords are given as a voicing: full,
shell (root, third, seventh), guide (third and seventh) or root.

Two decisions that 12 notes per octave hide (`Tutor._key_root`, `_changes_steps`; nothing is
published on jazz in 53, so these are this project's choices, tested for consistency and still to
be judged by ear):

- **Roots in a key.** In tunings that tell 9/8 from 10/9 (53, 41, 22) the tonic stays fixed and
  roots follow the key's pure scale: third, sixth and seventh degree a comma below the chain of
  fifths, flat degrees a comma above, and the minor chord on the second degree a comma low as
  well, in major and in minor. Every chord of a two-five-one then uses the same seven notes; the
  price is the fourth from the second to the fifth degree, a comma wide. `plain_roots` gives the
  chain-of-fifths roots instead. A tune without a key in its source keeps plain roots.
- **Sevenths.** A dominant chord takes the fourth of the key it leads to as its seventh (16/9),
  not the wider 9/5 the plain `dominant7` quality has. A blues (by title or 12-bar form) takes
  the harmonic seventh 4:5:6:7 where the tuning has it; `sevenths` overrides.

The improvisation course in the skill follows the order the beginner methods share (rhythm and
call-and-response, few notes over a drone, the blues, chord tones, shell voicings, the
two-five-one with guide tones, approach notes, tunes); their texts and examples are not used.
Research: `reference/research/jazz.md`.

Not included: modern microtonal compositions. For 53 none could be found as scores or MIDI,
only as audio (search of 2026-11-26); ordinary repertoire translated to 53 (pure thirds, comma
shifts) needs a translator that is not written yet.


## Harmony

`host/tutor/harmony.py`, tool `harmony`. `library_build.py` counts, over the standards that give
a key (about 900 in major, 200 in minor), how often each chord occurs, what follows and precedes
it, and the most frequent runs of three and four chords, and stores them as `harmony.json`.
Chords are degrees of the key in the twelve semitone classes the lead sheets are written in
("IIm7", "bVII7"); sixths and triads count as the seventh chord of their family. The tool spells
degrees for the current key and tuning with the comma policy of the jazz changes, adds the
textbook role of each chord (`FUNCTIONS`), and describes each step by what can be heard: the
root's move (including "a fourth that is one step wide" where the comma falls) and the number of
shared notes. `tuning` lists what follows from the tuning's arithmetic: the comma in
two-five-one, the harmonic seventh, augmented and diminished chords that do not close, the two
tritones, chord qualities beyond twelve notes.

The counts describe American popular song and jazz of about 1920 to 1970, not harmony as such.
Makam and raga are melodic systems without chord progressions and are served by the library.

### Harmony from the tuning itself

The counts know only twelve-tone chords. Three further actions of `harmony` need no repertoire
and no statistics file.

**`neighbours`** (`host/tutor/voiceleading.py`, pure functions). For a chord (root and quality,
any quality the tuning has), every chord of the tuning is a candidate: all qualities of
`theory.CHORDS` the tuning offers, of the same size (`sizes`: `same`, `triads`, `sevenths`,
`any`), on every note. Chords are sets of notes regardless of octave. The distance between two
chords is the smallest total movement that leads every voice of the first to a note of the
second and uses every note of both (`assign`: all assignments are tried, three or four voices;
when the sizes differ a voice splits or two merge); among equally cheap assignments the one
that holds the most notes wins. Distances are counted in steps of the tuning and given in cents
too. Chords with the same notes under two names appear once (`same_notes_as`), the chord's own
notes under another name never. Per neighbour: the notes that stay, each moving voice with its
size in steps and in the tuning's own words, how the root moves, and one of five kinds:

| Kind | What it is | Example from C major in 53 |
|---|---|---|
| `quality` | another quality on the same root | C neutral, C supermajor: the third moves 2 steps |
| `one_voice` | the root changes, one voice moves, the rest stay | vE minor; vA minor (G up a small whole tone) |
| `shift` | the same chord slid along | ^C major: every voice one step, a comma |
| `held` | some notes stay, several move | |
| `free` | nothing stays | vC supermajor: three voices each a comma, in contrary motion |

Ranking (`ranking="varied"`, the tool's): nearest first within each kind, and the kinds take
turns in the order `TURNS` (quality, one voice, shift, quality, one voice, held, quality, one
voice, shift, free), so that ten entries show the changed thirds, the chords sharing two notes
and the comma shifts instead of ten near-copies. Diminished and augmented chords count as twice
as far within their kind unless the starting chord is one of them (`RESTLESS_FACTOR`), which
puts E minor and A minor before the diminished chord a semitone up. `ranking="nearest"` is
distance alone. Parameters: `max_cents` (default 240: a whole tone and a little, so that the
relative minor is inside in every tuning), `roots` (`any`, `same`, `other`), `sizes`, `limit`.
The small distances are named from the tuning's fifth and thirds (`step_names`): the comma is
four fifths against the pure major third, the chromatic semitone major against minor third, the
diatonic semitone fourth against major third, the diesis three major thirds against the octave.
One step is therefore a comma in 53, 41, 22 and 29, a diesis in 31, a quarter tone in 24.

**`path`**: a progression of `length` chords from a chord back to itself (or to `to`), each move
within `max_cents`, no chord twice, optionally passing a given quality or any quality a piano
lacks (`via`). A breadth-first pass from the goal gives every chord's distance in moves; the
search then goes depth-first through the ranked neighbours and takes only chords from which the
goal is still in reach. Seed 0 takes the first such chord every time; another seed shuffles the
ten best with a generator seeded by it, so a seed always gives the same progression.

In the tool, a neighbour or path step is voiced by carrying each voice of the chord before it
(`voiced`), so held notes are the same keys; the starting chord is in root position in the
octave where it has keys, as the jazz changes are. If a carried voicing leaves the keyboard it
is moved by octaves or set in root position. A root is spelled so that held notes keep their
names (C vE G to vA C vE). Every entry has the shape of a chord step (`notes`, `label`, `root`,
`beats`) plus `kind`, `stays`, `moves`, `total_cents`.

**`xen`** (`host/tutor/xen_progressions.py`): 41 entries collected by hand from the wiki copy,
each with its page and section, the chords as the source gives them and a summary in this
project's words. A chord is a name, a root above the tonic and tones above the root, each as
pure ratios or as steps of one tuning; a root may be several sizes added up, so that three
fifths stay three fifths. Kinds: `progression`, `vocabulary` (chords to compare), `idea` (an
observation; chords, if any, only illustrate it).

| Notes per octave | Entries | Mainly from |
|---|---|---|
| 41 | 18 | Kite Giedraitis's Kite Guitar pages: translations with the comma shown, two-five-one variants, mirrored progressions, moves that keep two notes, a blues, two porcupine pumps |
| 53 | 16 | 4 of its own (triads; the thirds cycle; schismatic triads; an idea from the Orwell page), 12 carried over from 41 by their pure intervals and marked so |
| 22 | 9 | a progression resting on a suspended chord, superpyth tetrads, the porcupine pump, chord lists |
| 29 | 6 | a progression in a mode without a perfect fifth, changing the home note voice by voice |
| 31 | 6 | chord lists, the turnaround that closes, the augmented sixth as a harmonic seventh |
| 19 | 5 | chord lists, the pentatonic scale as a chord |
| 24 | 2 | triads, a major third closing to a minor third in contrary motion |
| 12 | 1 | the turnaround that closes |
| 56 | 0 | |

Not in the copy: any progression written for 53 or 31 (their pages list intervals, chord names
and scales); the page of worked comma pump examples (only the 12-tone list, with two of its
three sections empty); progressions on the temperament pages, which describe chords and roles.
The limits of the generator: its chords are the nineteen qualities of `theory.CHORDS`, so in 53
the second neutral triad, the Pythagorean triads and chords with altered fifths are not found;
a dominant seventh is the one with the wide seventh, not the key's fourth used in the jazz
changes; distance says nothing about function, so the classical resolution of a seventh chord
(root down a fifth) is far away and found only with `to`.

## Rhythm

`host/tutor/rhythm.py` (judging, pure arithmetic), tool `rhythm`. A tap is compared with the time
it was due: error = tap - target - the player's offset. The offset is measured once by tapping
along to 20 clicks (median, first four left out) and kept in the player file; it holds the delay
of keyboard, computer and sound and the few tens of milliseconds by which people tap ahead.
Bands per level in milliseconds: beginner 40 / 80 / 120, intermediate 25 / 50 / 90, advanced
15 / 35 / 70 (this project's choice, between rhythm-game windows and what a learner hears).
Reported: counts per band, missed and extra taps, mean (ahead or behind), spread, drift over the
take, the weakest taps. `improvise` reports how the notes sat on even half beats.

Built-in patterns: even notes, offbeats, Charleston, tresillo, cinquillo, son and rumba clave,
bossa, the 12/8 bell, three against two, waltz, and as a fallback the Hindustani cycles teental,
jhaptal, rupak, dadra, keherwa (tapped on every beat, accents on the claps).

**Rhythm library.** `python -m tutor.rhythm_build` (from `host/`) converts the researched
reference `reference/music/rhythm/tala.json` (third-party research, outside git; its `REPORT.md`
and `SOURCES.md` say where everything comes from) into `build/tutor-library/rhythm.json`, which
`rhythm.py` loads next to the built-in patterns. A sourced cycle replaces a built-in one of the
same name. Contents:

| Kind | Count | What a cycle carries |
|---|---|---|
| Hindustani talas | 22 | matras, vibhag with clap (tali) and wave (khali), the theka bol by bol, variants |
| Carnatic talas | 40 (the 35 suladi talas, four chapu talas, 3-beat rupaka) | beats, the angas, the hand gesture of every beat |
| mridangam lessons | 8 of the 27 solkattu lessons (those given syllable by syllable with a stroke each) | syllables and strokes; the other 19 are kept as text |
| usul (Turkish makam music) | 36 | pulses, grouping, the strokes dum, tek, te, ke with their lengths |

A cycle is a pattern with more fields: `name`, `aliases`, `tradition` (hindustani, carnatic,
makam), `kind`, `pulses`, `beats`, `onsets`, `accents`, `what`, `strokes`
(`[{at, stroke, dur, loud}]`, in pulses), `sections` (vibhag, angas or groups, with gesture),
`sources`, `confidence`, `conflict` (what the sources disagree on), `variants`. Rules of the
conversion: nothing is added to what the sources state. A matra holding several bols is split
evenly. Conflicting cycles are kept and marked: `rhythm patterns` lists every cycle under its
confidence, and every `demo` and `play` result of such a cycle carries `sources_disagree`.
Carnatic gestures that the research derived from the rules of the angas (32 of 40) are listed
as derived. The loudness of each stroke and "one click per syllable" in the lessons are this
project's choice.

`rhythm patterns` returns names and lengths by kind and confidence; with `pattern` the cycle in
full (sections with their bols or gestures, variants, sources). `find` compares names without
accents, spaces and the bracket, so the `meter` of a makam piece from the library
("Aksaksemâî (10/8)", "K. Curcuna (10/8)") finds its usul.

**What sounds** (`sound`, default `auto`; the table is `host/tutor/percussion.py`):

| Cycle | `auto` | What is played | Sourced or chosen |
|---|---|---|---|
| Hindustani tala | tabla, if set up | the theka's own bols | bols sourced; bols without a recording see Tabla below |
| mridangam lesson | mridangam, if set up | the lesson's own strokes | sourced by the lesson |
| Carnatic tala | mridangam, if set up | first beat and claps a deep stroke, other beats a light one | this project's choice: no source gives a theka |
| usul | tabla, else mridangam | dum = Ge (Thom), tek = Na (Num), te = Te, ke and ka = Ke, hek = Dha (Tham); mridangam: te, ke, ka = Thi | strokes sourced, the sound is a stand-in: no frame drum is recorded |
| a stroke the source does not name | | a click | |
| anything without its drum | click | every stroke (or beat) as a click, claps accented | |

In `play` the drum's strokes are the pulse (the count-in stays a click). `tap` says what the
player taps: `beats` (every matra), `claps` (the accents; for an usul the starts of its groups)
or `strokes`; without it a tala is tapped on every beat, a lesson and an usul on their strokes.
`variant` plays one of the other versions the sources give.

**Drone** (tool `drone`). The tanpura tuning of a raga follows the research
(`tanpura_tunings` in tala.json; rule in `library.py`, `drone_tuning`): Pa-Sa-Sa-Sa when the raga
has Pa, Ma-Sa-Sa-Sa when Pa is absent and the plain Ma present, otherwise Dha, Ni or Ga (the
sources disagree: Courtney prefers Dha, Toss Levy gives Ni, raganet Ga; Dha is used and the
result says so). A raga can override the rule (`"drone"` in `RAGAS`: Bageshri takes Ma although
it has Pa, as Toss Levy and raganet list it). `library raga` reports it under `tanpura`.

The drone sounds on an instrument of its own, `host/synth/tanpura.scd`: a SuperCollider instance
with its own sound server (port 57144; OSC on 57145: `/tanpura/start <seconds per string>
<loudness 0..1> <Hz> ...`, `/tanpura/stop`, `/tanpura/gain`, `/tanpura/ping`), apart from the
piano patch that xentool plays. The tutor sends the strings as frequencies of the current tuning
and the patch strikes them in the tanpura's order (first string, Sa, Sa, low Sa) every `pace_s`
seconds until `drone stop` or `stop`. Nothing goes through the keyboard's notes, so no key the
player presses can cut a string, and the strings need not exist as keys. The tone is a model
(a plucked string with a buzzing bridge, the idea of `xentool/supercollider/mpe_tanpura_xentool.scd`),
not a recording. Start the tutor with `--tanpura` (`play.ps1 -Tanpura` starts both). Without it
the drone falls back to held notes of the keyboard's own sound, struck by a background thread;
there a drone key the player presses is cut until its next strike, and the result says so
(`sound: "keyboard"`). Either way it holds no lock, so demos, exercises and rhythm takes run
over it.

The click is a note on MIDI channel 10 (General MIDI percussion, notes 76 and 77), sent through
xentool's `POST /api/midi`. The SuperCollider patch plays that channel as a short tick; a drum
plugin on the same MIDI port can play it instead (`~drumChannel = nil` in the patch). Layouts
use channels 1 to 5, so channel 10 is free. Timing passes USB polling, an HTTP request and
thread scheduling: about 10 ms of jitter, fine for these bands, too coarse to judge an expert.
Wait-mode exercises (`run_exercise`) have no pulse and are not timed.

Where the sources of a transcription differ on a note (the printed score and a recording), the
score file keeps both: `{"step": 48, "source": "print", "also": [{"step": 47, "source":
"recording"}]}`. The library carries them per bar, and `library get` reports them as
`two_readings` (bar, beat, hand, what each source has) in the overview and with the bar.

## Layouts for any tuning

`host/layouts/isomorphic.py` generates a Bosanquet-style layout for any number of notes per octave
from two step sizes (one key to the right, one key up-right), by default derived from the tuning's
best fifth: `python host/layouts/isomorphic.py 17` writes `build/layouts/17ET-bosanquet.otn`
(right 3, up-right 2), `16` writes `16ET-mavila.otn` (fifth of 9 steps: right 2, up-right -1, so the
key up-right is one step LOWER). With right 9 and up-right 5 it reproduces the existing 53 layout
key for key, which is the check of its geometry.

## Mridangam

`host/synth/mridangam.scd` plays recorded mridangam strokes (Thom, Num, Tha, Thi, Dhin, Dheem, Cha,
Bheem, Ta, Tham) as an instrument of its own: a second SuperCollider instance with its own sound
server (port 57140), driven by OSC (`/mridangam/stroke <name> <loudness 0..1>` on port 57141), so it
shares neither a MIDI channel nor a synth with the piano patch. `host/synth/mridangam_kit.py` selects
180 of the 6,977 samples of the DrumGizmo kit (`reference/music/mridangam/MridangamDG-Full.zip`, from
the Pi; six loudness layers, three takes each). Started by hand: `sclang host/synth/mridangam.scd`.
The tutor uses it when started with `--mridangam` (`play.ps1 -Mridangam` starts both): `rhythm`
and `improvise` take `sound: "mridangam"` for the pulse, and `rhythm demo` plays a pattern on it.

## Tabla

`host/synth/tabla.scd` is the same for the tabla: a SuperCollider instance of its own (sound
server on port 57142, OSC on 57143: `/tabla/stroke <bol> <loudness 0..1>`, `/tabla/gain`,
`/tabla/ping` answered with `/tabla/pong`). Ports in use on this machine: 57110/57120 (main
patch), 57140/57141 (mridangam), 57142/57143 (tabla), 57150/57151 (reserved by other patches).
`python host/synth/tabla_kit.py` prepares `reference/music/tabla/kit` (outside git): the 110
samples of the bolbox kit `deolekar-tabla` (eleven bols, ten takes each, with its gain per bol),
which is a selection from Subodh Deolekar's "Tabla strokes dataset" (2020, Zenodo, DOI
10.5281/zenodo.4327350, CC BY 4.0; trimmed and mixed to mono by bolbox), and `kit.scd`, the table
of which samples sound for which bol. The tutor uses the patch when started with `--tabla`
(`play.ps1 -Tabla` starts both and prepares the kit if it is missing).

How a bol is sounded (`host/tutor/percussion.py`, reported to the player as `sound_note`):

| Bol | Sound | Basis |
|---|---|---|
| Ge, Ka, Na, Tin, Tun, Ta, Ti, Te, Re, Dha, Dhun | its own recording | the kit (Tu = Tun, Ki = Ka as the kit and the research treat them) |
| Kat, Ke; Ga, Ghe; Ra; Taa | Ka; Ge; Ta; Na | the recorded bol of the same timbre class (CompMusic Tabla Solo dataset, `tabla_bol_timbre_classes`) |
| Dhin, Dhi, Dhe | Ge together with Tin, Ti, Te | **this project's choice**: the kit has no recording; a bol in "Dh" is taken as the open left-drum stroke with the right-drum stroke of the same name. The research report mentions the layering only as a suggestion |
| Din, Di; Kra | Tin; Ka | **stand-in, this project's choice**: no recording in their timbre class |
| Da, Gad, Gha, Ghaa, Kde, Ne, Tit | silent | they occur only in variants; nothing honest to play |

Every bol of the 22 main thekas has a sound. Dhi is composed as Ge + Ti by the rule, although
the research notes that sources write Dhi and Dhin for the same bol in Jhaptal and Keherwa.

## Tuning notes

`host/tutor/wiki_build.py` converts the Xenharmonic Wiki's own backup
(`reference/literature/xenwiki/pages.xml.zst`, from
`archive.org/download/XenharmonicWikiBackups/xenwiki_en_mediawiki/<date>/`; the live site refuses
automated requests) into `build/tutor-wiki/pages.json`: 144 pages, about 1,660 sections, the
latest revision of each. Selected: every page of the tunings with a layout (12, 19, 22, 24, 29,
31, 41, 53, 56: the tuning page, subpages, modes, chords, solfege, Lumatone mapping), notation,
chain of fifths, commas, the main temperaments, beginners' guides. Wikitext is reduced to plain
text, tables to one line per row. Tables the wiki computes on display (harmonics, some interval
tables) are not in the backup. `host/tutor/wiki.py` searches by section (word weights, headings
count more). Licence of the wiki: CC BY-NC-SA 4.0; private reference, not distributed. Needs
`pip install zstandard` to build.

## xentool's local API

`xentool serve <layout.otn> --api [--api-port 9098]`, openxen backend only, bound to
127.0.0.1. Backend-neutral: built from xentool's geometry and layout data, so other
keyboards xentool serves can be added without changing the tutor.

| Endpoint | |
|---|---|
| `GET /api/setup` | Geometry and layout names, tuning, connected boards, the six neighbour offsets, and per playable key: address, position in the shared hex lattice, pitch, frequency, layout colour |
| `GET /api/keys/state` | Keys held now |
| `GET /api/events?after=N&wait_ms=M` | Key presses and releases (and board changes) numbered above N; waits up to M ms for the first one |
| `POST /api/leds/overlay` | `{"clear": "all" or [[board, key]], "set": [{"board", "key", "rgb"}], "dim_base": 0..1}` |
| `POST /api/notes` | `{"on": [{"board", "key", "velocity", "ms"}], "off": [[board, key]]}` |
| `POST /api/chords/name` | `{"edo", "pitch_classes"}` → chord names per root |
| `POST /api/midi` | `{"notes": [{"channel" 1..16, "note", "velocity", "ms"}]}`: notes sent as they are on a channel of the client's choice, outside the layout (metronome clicks, percussion); released after `ms` |
| `GET /api/layouts` | `{"current", "available": [{"name", "edo"}], "switching", "last_error"}`: the layout files next to the one being served |
| `POST /api/layout` | `{"name"}`: load that layout while serving. Sounding notes are released, the synth gets the new tuning (MTS-ESP and the SuperCollider broadcast), keys their new colours, the overlay is cleared, and a `setup` event announces the new description. A file that cannot be read leaves everything as it was and sets `last_error` |

Events are fetched with a waiting request rather than a stream: xentool's HTTP library sends
streamed bodies in 8 KB chunks, which would hold single key events back.

LED overlay (xentool `src/openxen/led.rs`): each module has its layout colours and, above
them, the overlay. Layout repaints and the screensaver change only the layout colours;
clearing one overlay key shows exactly that key's layout colour again. The modules are one
keyboard: while any of them shows an overlay key, the layout colours dim and the firmware
press highlight is off on all of them (the tutor colours pressed keys itself), and the
screensaver stays off. (Until 2026-11-26 this was decided per module, so a chord lying on one
module left the others at full layout colours.)

## Call log

The tutor server records every tool call, the answer exactly as the model received it, and
every key press and release, in `build/tutor-log/<date>.jsonl` (`--log FILE` for another
place, `--no-log` for none). One JSON object per line with a timestamp: `start`, `call`
(tool and named arguments), `result` (same `id`, duration, `ok`, text) and `key`. A `call`
without `result` is a tool that never returned. Records are queued and written by a
background thread, so a tool call does not wait for the disk (measured in
`tests/test_tutor_server.py`). The file is for developers: it contains xentool's key
addresses, which the model never sees.

## Tests

`python -m pytest tests/test_tutor_*.py` (about a minute, no keyboard needed) and `cargo test` in
xentool. See `docs/testing.md` for what each file proves.

Checked by hand on 2026-11-25: the server started with a token on all interfaces answers 401
without or with a wrong token and serves an MCP client over the PC's network address; the
tutor against a running `xentool serve --api` with no module attached reports that no module
is connected and gets chord names from xentool.

**Not yet done: a run on a real module.** No module was attached when this was built. To do:
`play.ps1 -Tutor`, then from Claude Code: `keyboard_info` matches the board on the desk;
`set_lights` lights the named key and clearing restores only that key; `demo` sounds and
lights a triad; `listen` names a played major triad; `run_exercise` over I–IV–V advances only
on correct chords and reports a deliberately wrong note.

## Firmware: what assisted playing would gain

Nothing in the firmware blocks the tutor. Compared with other light-up keyboards it already
does the hard parts: a whole module is repainted in three reports and shown at once (the
Lumatone protocol sends one key per message and waits for an acknowledgement), and every
report carries the travel of all keys, so no "which keys are down" query is needed.
Candidates, by value:

1. **LED changes and sensor noise** (open bring-up item, `PROJECT_PLAN.md`): the tutor changes
   LEDs while keys are read. Measure rest noise with `host/tools/oxmon_win.py` while an
   overlay changes; firmware work only if press detection is disturbed.
2. **Per-key effects on the module** (blink or pulse for "press this next", which every
   product studied does): the IS31FL3733's auto-breath mode or a firmware timer, as a new
   command next to PIXELS. Until then the tutor shows the next key in a dimmer colour.
3. **Target-mask feedback**: the host uploads the expected keys; a pressed key shows the
   "right" or "wrong" colour locally, without the round trip through the host (an extension
   of highlight mode 1 in `openxen_led_core.c`).
4. **Stored board index** per module (today: serial → board in xentool's settings).
5. Hardware rev 2, not firmware: LEDs and switch windows face away from the player.

Each of 2–4 changes the LED protocol: `docs/led-protocol.md`, `host/oxl.py`, the firmware
host tests and xentool's encoder change together.

## Left out of version 1

Tempo-keeping (rhythm) mode, looping with tempo ramps, scores over time and a practice
journal, an event feed for the avatar, the Exquis and Wooting keyboards.

## What it was modelled on

No existing MCP server drives key LEDs or targets a microtonal or hexagonal keyboard (search
of 2026-11-25). Borrowed: the blocking "listen until the player pauses" tool from
`thias42/midi-mcp`; wait mode, listen-first and the colour conventions from light-up piano
products; chord matching as a set with wrong-key rules from Neothesia and PianoBooster. The
projects are cloned under `reference/repos/` (see `reference/SOURCES.md`).
