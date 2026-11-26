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
| `harmony` | Which chord usually follows which (and precedes it), frequent runs, how usual each step of a given progression is, any progression as chord steps, and what the current tuning does to progressions |
| `rhythm` | A click and a pattern to tap on any key; calibrates the player's own offset once (tap along to 20 clicks), then grades each tap (on it, close, near, off, missed, extra) for a level, with tendency, steadiness, drift and the weakest taps |
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
| 8 raga outlines | written here from the 22-shruti model (ratios per note) | any: nearest step to each ratio, error reported | this repository |
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

## Rhythm

`host/tutor/rhythm.py` (judging, pure arithmetic), tool `rhythm`. A tap is compared with the time
it was due: error = tap - target - the player's offset. The offset is measured once by tapping
along to 20 clicks (median, first four left out) and kept in the player file; it holds the delay
of keyboard, computer and sound and the few tens of milliseconds by which people tap ahead.
Bands per level in milliseconds: beginner 40 / 80 / 120, intermediate 25 / 50 / 90, advanced
15 / 35 / 70 (this project's choice, between rhythm-game windows and what a learner hears).
Reported: counts per band, missed and extra taps, mean (ahead or behind), spread, drift over the
take, the weakest taps. `improvise` reports how the notes sat on even half beats.

Patterns: even notes, offbeats, Charleston, tresillo, cinquillo, son and rumba clave, bossa, the
12/8 bell, three against two, waltz, and the Hindustani cycles teental, jhaptal, rupak, dadra,
keherwa (tapped on every beat, accents on the claps). Turkish usul are left out until their
stroke patterns are checked against a book: the sources found disagree.

The click is a note on MIDI channel 10 (General MIDI percussion, notes 76 and 77), sent through
xentool's `POST /api/midi`. The SuperCollider patch plays that channel as a short tick; a drum
plugin on the same MIDI port can play it instead (`~drumChannel = nil` in the patch). Layouts
use channels 1 to 5, so channel 10 is free. Timing passes USB polling, an HTTP request and
thread scheduling: about 10 ms of jitter, fine for these bands, too coarse to judge an expert.
Wait-mode exercises (`run_exercise`) have no pulse and are not timed.

## Mridangam

`host/synth/mridangam.scd` plays recorded mridangam strokes (Thom, Num, Tha, Thi, Dhin, Dheem, Cha,
Bheem, Ta, Tham) as an instrument of its own: a second SuperCollider instance with its own sound
server (port 57140), driven by OSC (`/mridangam/stroke <name> <loudness 0..1>` on port 57141), so it
shares neither a MIDI channel nor a synth with the piano patch. `host/synth/mridangam_kit.py` selects
180 of the 6,977 samples of the DrumGizmo kit (`reference/music/mridangam/MridangamDG-Full.zip`, from
the Pi; six loudness layers, three takes each). Started by hand: `sclang host/synth/mridangam.scd`.
Not yet connected to the tutor's `rhythm` and `improvise` tools.

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

`python -m pytest tests/test_tutor_*.py` (about 25 s, no keyboard needed) and `cargo test` in
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
