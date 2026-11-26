"""Chord progressions and chord vocabularies that microtonal musicians have written down for
particular tunings, collected from the local copy of the Xenharmonic Wiki (en.xen.wiki,
CC BY-NC-SA 4.0; pages as built by `wiki_build.py`, read in November 2026).

Each entry names its wiki page and section. The chords are the source's; the sentences in
"shows" are this project's summary, not quotations. Nothing is added to a source: where a page
gives only a list of chords, the entry is a vocabulary, and where it gives only an observation,
an idea without chords.

An entry:
  id, name
  kind      "progression" (chords in order), "vocabulary" (chords to know, in no order) or
            "idea" (an observation; chords, if any, only illustrate it)
  tunings   the notes per octave the source writes it for
  also      further tunings it carries over to by its pure intervals (this project's reading;
            results say so). Only given where the entry's point survives the move.
  chords    "name | root | tones": root and tones are sizes above the tonic and above the
            root. A size is a pure ratio (5/4), a number of steps of the tuning (13; only in
            entries for a single tuning), or several of these added up ("3/2 3/2 3/2" as a
            root: three fifths up). Ratios become the tuning's nearest step, each on its own,
            so three stacked fifths stay three fifths.
  shows     what it demonstrates
  source    (page, section) in the wiki copy

`resolve` turns an entry into roots and tones in steps of a tuning.
"""

from __future__ import annotations

import math

# chord types of the Kite Guitar pages (41 notes per octave) by the pure intervals they stand for
_DOWN, _UPMIN, _DOWNMIN = "5/4 3/2", "6/5 3/2", "7/6 3/2"
_DOWN7, _UPMIN7, _DOWNMIN7 = "5/4 3/2 7/4", "6/5 3/2 9/5", "7/6 3/2 7/4"
_DOWNMAJ7, _UP7, _UPMIN6, _DOWN_UP7 = "5/4 3/2 15/8", "9/7 3/2 9/5", "6/5 3/2 12/7", "5/4 3/2 9/5"
_KITE = "Kite Guitar"
_KITE_X = "Kite Guitar Exercises and Techniques by Kite Giedraitis"
_KITE_T = "Kite Guitar translations by Kite Giedraitis"
_TRANSLATING = "Translating songs to 41-equal"

ENTRIES: list[dict] = [
    # --- 41 notes per octave: Kite Giedraitis's Kite Guitar pages ---
    {"id": "kite-four-chords", "name": "One, five, six, four with pure chords", "kind": "progression", "tunings": (41,), "also": (53,),
     "chords": (f"Iv | 1/1 | {_DOWN}", f"Vv | 3/2 | {_DOWN}", f"vVI^m | 5/3 | {_UPMIN}", f"IVv | 4/3 | {_DOWN}"),
     "shows": "The usual translation of the four-chord song: every chord pure, the minor chord on the sixth degree a comma below "
              "its plain name so that it shares two notes with the home chord. Nothing has to shift.",
     "source": (_KITE, _TRANSLATING)},
    {"id": "kite-gu-pump", "name": "Turnaround with the comma shown (one, six, two, five)", "kind": "progression", "tunings": (41,), "also": (53,),
     "chords": (f"Iv | 1/1 | {_DOWN}", f"VI^m | 3/2 3/2 3/2 | {_UPMIN}", f"II^m | 3/2 3/2 | {_UPMIN}", f"Vv7 | 3/2 | {_DOWN7}", f"Iv | 1/1 | {_DOWN}"),
     "shows": "A progression that would drift by a comma if every common note were held. Here the roots six, two, five move by pure "
              "fifths and the price is paid at once: from the first chord to the second the root moves by a plain major sixth, and the "
              "home note and its third each reappear one step higher.",
     "source": (_KITE, _TRANSLATING)},
    {"id": "kite-ru-pump", "name": "One, four, five as harmonic seventh chords", "kind": "progression", "tunings": (41,), "also": (53,),
     "chords": (f"Iv7 | 1/1 | {_DOWN7}", f"IVv7 | 4/3 | {_DOWN7}", f"Vv7 | 3/2 | {_DOWN7}", f"Iv7 | 1/1 | {_DOWN7}"),
     "shows": "Three harmonic seventh chords a fourth and a fifth apart do not agree on the fourth degree of the scale: it is the root "
              "of the four chord and, one step lower, the seventh of the five chord. The shift lies between those two chords.",
     "source": (_KITE, _TRANSLATING)},
    {"id": "kite-two-five-one-strong", "name": "Two, five, one with a dominant that pulls", "kind": "progression", "tunings": (41,), "also": (53,),
     "chords": (f"II^m7 | 3/2 3/2 | {_UPMIN7}", f"V^7 | 3/2 | {_UP7}", f"IvM7 | 1/1 | {_DOWNMAJ7}"),
     "shows": "The harmonic seventh chord is smoother than the major seventh chord it should resolve to, so the cadence feels unfinished. "
              "A dominant with the wide (supermajor) third and the wide minor seventh is rougher, shares two notes with the two chord "
              "and makes the arrival a release.",
     "source": (_KITE, _TRANSLATING)},
    {"id": "kite-two-five-one-soft", "name": "Two, five, one to a plain triad", "kind": "progression", "tunings": (41,), "also": (53,),
     "chords": (f"IIvm7 | 3/2 3/2 | {_DOWNMIN7}", f"Vv7 | 3/2 | {_DOWN7}", f"Iv | 1/1 | {_DOWN}"),
     "shows": "When the home chord has no seventh, the harmonic seventh chord works as its dominant. The subminor seventh chord on the "
              "second degree is tied to it more closely than the ordinary minor one.",
     "source": (_KITE, _TRANSLATING)},
    {"id": "kite-andalusian", "name": "Falling minor cadence (A minor, G, F, E7)", "kind": "progression", "tunings": (41,), "also": (53,),
     "chords": (f"I^m | 1/1 | {_UPMIN}", f"^bVIIv | 9/5 | {_DOWN}", f"^bVIv | 8/5 | {_DOWN}", f"Vv^7 | 3/2 | {_DOWN_UP7}"),
     "shows": "For music from before the twentieth century the harmonic seventh sounds too relaxed and out of style on the dominant. "
              "Here the last chord keeps a pure major third and takes the wide minor seventh instead, and no note has to shift.",
     "source": (_KITE, _TRANSLATING)},
    {"id": "kite-mirrored-cadence", "name": "Five-one and its mirror image", "kind": "progression", "tunings": (41,), "also": (53,),
     "chords": (f"Vv7 | 3/2 | {_DOWN7}", f"Iv | 1/1 | {_DOWN}", f"IV^m6 | 4/3 | {_UPMIN6}", f"I^m | 1/1 | {_UPMIN}"),
     "shows": "Turning the harmonic seventh chord and its resolution upside down gives a minor chord with a wide sixth on the fourth "
              "degree resolving to the minor home chord. Both have a narrow tritone closing inwards to a third, three voices moving by "
              "seconds and one voice staying.",
     "source": (_KITE_X, "Motivating Example")},
    {"id": "kite-mirrored-progression", "name": "A progression and its mirror image", "kind": "progression", "tunings": (41,), "also": (53,),
     "chords": (f"Iv | 1/1 | {_DOWN}", f"vVI^m | 5/3 | {_UPMIN}", f"IVv | 4/3 | {_DOWN}", f"Vv | 3/2 | {_DOWN}",
                f"I^m | 1/1 | {_UPMIN}", f"^bIIIv | 6/5 | {_DOWN}", f"V^m | 3/2 | {_UPMIN}", f"IV^m | 4/3 | {_UPMIN}"),
     "shows": "The first four chords are a familiar progression. The last four are the same turned upside down: every interval of the "
              "bass line inverted, pure major chords exchanged for pure minor ones. A way to find new progressions from known ones.",
     "source": (_KITE_X, "Rotating a Chord Progression")},
    {"id": "kite-upminor7-moves", "name": "Moves from a minor seventh chord that keep two notes", "kind": "progression", "tunings": (41,), "also": (53,),
     "chords": (f"I^m7 | 1/1 | {_UPMIN7}", f"IV^m7 | 4/3 | {_UPMIN7}", f"I^m7 | 1/1 | {_UPMIN7}", f"^bVIv7 | 8/5 | {_DOWN7}",
                f"I^m7 | 1/1 | {_UPMIN7}", f"^VIvm7 | 12/7 | {_DOWNMIN7}", f"I^m7 | 1/1 | {_UPMIN7}", f"^bIIIvm7 | 6/5 | {_DOWNMIN7}"),
     "shows": "Four chords the source lists as sharing two notes with a pure minor seventh chord, each played after the home chord "
              "(the alternation is this project's way to audition them). The roots move by intervals that are not on the chain of "
              "fifths; harmonic seventh and subminor chords answer the minor one. The source calls two of them weird but cool.",
     "source": (_KITE_X, "Interesting Root Movements")},
    {"id": "kite-barbershop-fourths", "name": "Barbershop chain of harmonic sevenths", "kind": "progression", "tunings": (41,), "also": (53,),
     "chords": (f"Iv | 1/1 | {_DOWN}", f"VIv7 | 3/2 3/2 3/2 | {_DOWN7}", f"IIv7 | 3/2 3/2 | {_DOWN7}", f"Vv7 | 3/2 | {_DOWN7}", f"Iv | 1/1 | {_DOWN}"),
     "shows": "Six, two, five, one with every seventh chord tuned as a harmonic seventh and every root a pure fourth from the next. The "
              "third and fifth of the scale belong to both of the first two chords but not at the same pitch: one goes up a step and the "
              "other down a step, rather than one of them moving two.",
     "source": (_KITE_T, "Please Don't Sell My Daddy No More Wine (Tom Lane)")},
    {"id": "kite-i-will", "name": "A comma pump in two bars (I Will)", "kind": "progression", "tunings": (41,), "also": (53,),
     "chords": (f"Iv | 1/1 | {_DOWN}", f"vVI^m7 | 5/3 | {_UPMIN7}", f"IIvm7 | 3/2 3/2 | {_DOWNMIN7}", f"Vv7 | 3/2 | {_DOWN7}", f"Iv | 1/1 | {_DOWN}"),
     "shows": "The turnaround at speed. The comma is taken in the middle: the root moves from the low sixth degree to the plain second "
              "by a fourth that is one step wide. Keeping the six chord low ties it to the home chord, so that the four chords feel like two.",
     "source": (_KITE_T, "I Will (The Beatles)")},
    {"id": "kite-blues-turnaround", "name": "Blues turnaround with pure chords (Stormy Monday, bars 7 to 12)", "kind": "progression", "tunings": (41,), "also": (53,),
     "chords": (f"Iv7 | 1/1 | {_DOWN7}", f"vII^m7 | 10/9 | {_UPMIN7}", f"vIII^m7 | 5/4 | {_UPMIN7}", f"vbIII^m7 | 7/6 | {_UPMIN7}",
                f"vII^m7 | 10/9 | {_UPMIN7}", f"IV^m7 | 4/3 | {_UPMIN7}", f"Iv7 | 1/1 | {_DOWN7}", f"IVv7 | 4/3 | {_DOWN7}", f"Iv7 | 1/1 | {_DOWN7}"),
     "shows": "The harmonic seventh chord as the home chord of a blues, with minor seventh chords walking up from the second degree and "
              "back down. Their roots are the low second and third of the pure scale and a subminor third.",
     "source": (_KITE_T, "Stormy Monday (T-Bone Walker, Bobby Bland, Allman Brothers)")},
    {"id": "kite-porcupine-pump", "name": "Porcupine pump carried over to 41", "kind": "progression", "tunings": (41,),
     "chords": (f"IvM7 | 1/1 | {_DOWNMAJ7}", f"I^m7 | 1/1 | {_UPMIN7}", f"^bVIIvM7 | 9/5 | {_DOWNMAJ7}", f"^bVII^m7 | 9/5 | {_UPMIN7}",
                f"vVIvM7 | 5/3 | {_DOWNMAJ7}", f"vVI^m7 | 5/3 | {_UPMIN7}", f"VvM7 | 3/2 | {_DOWNMAJ7}", f"Vv7 | 3/2 | {_DOWN7}"),
     "shows": "The same chord names as the 22-note original, read in 41. The three falling root moves are no longer equal (six, five and "
              "six steps) and one common note between the fourth and fifth chord moves up a step: the bass line is less regular, the "
              "chords are purer.",
     "source": (_KITE_T, "Porcupine Pump (Mike Battaglia, microtonal)")},
    {"id": "kite-mizarian", "name": "Ending of the Mizarian Porcupine Overture in 41", "kind": "progression", "tunings": (41,),
     "chords": ("Iv | 0 | 13 24", "vIII^m | 13 | 11 24", "vVIv | 30 | 13 24", "^Iv | 1 | 13 24", "^IVv | 18 | 13 24", "VIv | 31 | 13 24",
                "IIv | 7 | 13 24", "V^m | 24 | 11 24", "Vv | 24 | 13 24", "Iv | 0 | 13 24"),
     "shows": "A famous passage (Herman Miller) written for a tuning in which three small whole tones make a fourth. In 41 they do not, "
              "so one tied note has to move down a step in the second bar; the chord passes quickly and the shift is hard to hear.",
     "source": (_KITE_T, "Mizarian Porcupine Overture (Herman Miller, microtonal)")},

    # --- 22 notes per octave ---
    {"id": "porcupine-pump-22", "name": "Porcupine pump (Mike Battaglia)", "kind": "progression", "tunings": (22,),
     "chords": ("IvM7 | 0 | 7 13 20", "I^m7 | 0 | 6 13 19", "^bVIIvM7 | 19 | 7 13 20", "^bVII^m7 | 19 | 6 13 19",
                "vVIvM7 | 16 | 7 13 20", "vVI^m7 | 16 | 6 13 19", "VvM7 | 13 | 7 13 20", "Vv,7 | 13 | 7 13 18"),
     "shows": "Major seventh turns into minor seventh on the same root, then the root falls three steps, three times, and lands on the "
              "fifth degree. That only closes where three equal small whole tones make a fourth, as here; on a piano it cannot be played.",
     "source": (_KITE_T, "Porcupine Pump (Mike Battaglia, microtonal)")},
    {"id": "superpyth-quartal", "name": "A progression that rests on a fourth chord", "kind": "progression", "tunings": (22,),
     "chords": ("Csus4 | 0 | 9 13", "E Orwell diminished | 8 | 5 10", "Fsus4 | 9 | 9 13", "G supermajor | 13 | 8 13"),
     "shows": "In the scale built from this tuning's wide fifths, chords of fourths rest better than chords of thirds, so home is a "
              "suspended chord. The supermajor triad on the fifth degree is tense enough to be the dominant without a seventh, and the "
              "chord on the wide third slides a small semitone into the suspended chord on the fourth: a false arrival.",
     "source": ("22edo/Unque's compositional approach", "Example: Chord Progression in C Ionian (Superpyth)")},
    {"id": "superpyth-tetrads", "name": "Subminor and supermajor chords with a pull", "kind": "progression", "tunings": (22,),
     "chords": ("IV subminor seventh | 4/3 | 7/6 3/2 7/4", "V supermajor with sixth | 3/2 | 9/7 3/2 12/7", "I supermajor with second | 1/1 | 9/8 9/7 3/2"),
     "shows": "The page names these chords and where each wants to go: the subminor seventh chord on the fourth degree has a low sixth "
              "of the key that falls to the fifth, the supermajor chord with its sixth on the fifth degree has a high leading note, and "
              "the supermajor triad with an added second is one of the resting chords. The order four, five, one is the textbook one.",
     "source": ("Superpyth", "Chords and harmony")},
    {"id": "superpyth-eleventh", "name": "A sharper suspension", "kind": "progression", "tunings": (22,),
     "chords": ("I with second and high fourth | 1/1 | 9/8 11/8 3/2", "I supermajor with second | 1/1 | 9/8 9/7 3/2"),
     "shows": "Like a suspended fourth resolving to the third, with more tension: the note between fourth and tritone falls to the "
              "supermajor third.",
     "source": ("Superpyth", "Chords and harmony")},
    {"id": "22-resting-chords", "name": "Other chords to come home to", "kind": "vocabulary", "tunings": (22,),
     "chords": ("5:6:7 triad | 0 | 6 11", "supermajor triad 14:18:21 | 0 | 8 13", "subminor triad 6:7:9 | 0 | 5 13", "Orwell tetrad | 0 | 5 10 15"),
     "shows": "One composer's view: the minor third here is wide of pure, so the ordinary major and minor triads are not the natural "
              "resting chords. Candidates instead: a triad spanning exactly half an octave, the supermajor triad with its subminor "
              "partner, and a stack of three equal subminor thirds.",
     "source": ("22edo/Eliora's approach", "Base chord into which everything resolves")},
    {"id": "22-triads", "name": "Triads and seventh chords of 22", "kind": "vocabulary", "tunings": (22,),
     "chords": ("downmajor 4:5:6 | 0 | 7 13", "upminor 10:12:15 | 0 | 6 13", "major (supermajor) 14:18:21 | 0 | 8 13", "minor (subminor) 6:7:9 | 0 | 5 13",
                "upminor down-five (magical) | 0 | 6 12", "diminished | 0 | 5 10", "augmented | 0 | 8 16",
                "harmonic seventh | 0 | 7 13 18", "subminor seventh | 0 | 5 13 18", "upminor sixth | 0 | 6 13 17", "dominant seventh (supermajor third, subminor seventh) | 0 | 8 13 18"),
     "shows": "Four kinds of third give four triads with a perfect fifth. The plain names major and minor belong to the wide and the "
              "narrow one here; the pure-sounding ones are downmajor and upminor.",
     "source": ("22edo chords", "Triads")},
    {"id": "22-tendencies", "name": "Which intervals want to move", "kind": "idea", "tunings": (22,), "chords": (),
     "shows": "Roots still like to move by fifths. There are two leading notes: one step (very tense) and two steps (milder, good as a "
              "dissonant chord note). Half an octave wants to open or close to a fifth or fourth; a subminor third tends to open to a "
              "major third and a supermajor third to close to a minor third, the voices moving in contrary motion.",
     "source": ("22edo/Unque's compositional approach", "Elements of Functional Harmony")},

    # --- 29 notes per octave ---
    {"id": "vivecan-29", "name": "A key without a perfect fifth", "kind": "progression", "tunings": (29,),
     "chords": ("C upminor up-five | 0 | 8 18", "^F upminor down-five | 13 | 8 16", "D upminor down-five | 5 | 8 16", "vA with second and up-fourth | 21 | 5 13"),
     "shows": "A mode whose home chord has a fifth one step wide while most other degrees have one a step narrow. Each chord shares "
              "two notes with the next, and in the last one a whole tone opens outwards to the wide fifth of the home chord, which makes "
              "that fifth sound like the place of rest.",
     "source": ("29edo/Unque's compositional approach", "Example: Progression in C Vivecan")},
    {"id": "reroot-29-thirds", "name": "Changing the home note one voice at a time", "kind": "progression", "tunings": (29,),
     "chords": ("C downmajor | 0 | 9 17", "vE upminor | 9 | 8 17", "G downmajor | 17 | 9 17"),
     "shows": "From the home chord to the chord a fifth higher without a new note: first one voice moves, giving the minor chord both "
              "have in common, then another. All three chords are of the same family, so the change is smooth.",
     "source": ("29edo/Unque's compositional approach", "Re-Rooting a Mode")},
    {"id": "reroot-29-sus", "name": "The same change through a suspended chord", "kind": "progression", "tunings": (29,),
     "chords": ("C downmajor | 0 | 9 17", "C sus2 | 0 | 5 17", "G downmajor | 17 | 9 17"),
     "shows": "The voices move in the other order. The middle chord is the suspended chord of the new home, so the arrival is heard as "
              "a resolution: more expressive, less blended.",
     "source": ("29edo/Unque's compositional approach", "Re-Rooting a Mode")},
    {"id": "29-quartal", "name": "Chords of fourths as a bridge", "kind": "vocabulary", "tunings": (29,),
     "chords": ("C4 (two fourths) | 0 | 12 24", "C sus4 | 0 | 12 17", "C sus2 | 0 | 5 17"),
     "shows": "Unresolved but calm. The source uses them between a dominant and the home chord to soften the arrival, and says where "
              "each resolves: two fourths on C to F major or Bb minor, C sus4 to C major or F minor, C sus2 to G major or C minor.",
     "source": ("29edo/Unque's compositional approach", "Quartal Inversions")},
    {"id": "29-triads", "name": "Six triads with a perfect fifth", "kind": "vocabulary", "tunings": (29,),
     "chords": ("arto | 0 | 6 17", "minor | 0 | 7 17", "upminor | 0 | 8 17", "downmajor | 0 | 9 17", "major | 0 | 10 17", "tendo | 0 | 11 17"),
     "shows": "Thirds one step apart from very narrow to very wide. Plain major and minor are the ones of the chain of fifths; "
              "downmajor and upminor are nearest to the pure thirds.",
     "source": ("29edo/Unque's compositional approach", "Tertian Triads")},
    {"id": "29-leading-notes", "name": "Three sizes of leading note", "kind": "idea", "tunings": (29,), "chords": (),
     "shows": "One step acts like another version of the same note, three steps like an ordinary small melodic step; two steps pull "
              "hardest. Intervals halfway between the usual ones resolve by contrary motion, each voice moving three steps: two notes "
              "eleven steps apart open to a fifth, two notes six steps apart open to a fourth or close to a unison.",
     "source": ("29edo/Unque's compositional approach", "Elements of Functional Harmony")},

    # --- 24 notes per octave ---
    {"id": "24-contrary-thirds", "name": "Major third to minor third in contrary motion", "kind": "progression", "tunings": (24,),
     "chords": ("major third | 0 | 8", "minor third | 1 | 6"),
     "shows": "Both voices move a quarter tone, one up and one down: strictly contrary motion from a major to a minor third, which no "
              "smaller tuning with good thirds allows. In the same way any succession of two intervals of the piano can be reached.",
     "source": ("24edo", "Counterpoint")},
    {"id": "24-triads", "name": "Five triads and the neutral chords", "kind": "vocabulary", "tunings": (24,),
     "chords": ("inframinor (downminor) | 0 | 5 14", "minor | 0 | 6 14", "neutral | 0 | 7 14", "major | 0 | 8 14", "ultramajor (upmajor) | 0 | 9 14",
                "fourth split in two | 0 | 5 10"),
     "shows": "Three new triads next to major and minor. The source finds that the new ones lack the force to sound resolved alone and "
              "suggests seventh chords in their place, for example the neutral triad with a neutral seventh. The page gives steps only "
              "for the neutral triad and the split fourth; the others follow from its chord names.",
     "source": ("24edo", "Chord types")},

    # --- 31 notes per octave and other meantone tunings ---
    {"id": "meantone-turnaround", "name": "The turnaround that closes", "kind": "progression", "tunings": (12, 19, 31),
     "chords": ("I | 1/1 | 5/4 3/2", "vi | 5/3 | 6/5 3/2", "ii | 3/2 3/2 | 6/5 3/2", "V | 3/2 | 5/4 3/2", "I | 1/1 | 5/4 3/2"),
     "shows": "One, six, two, five, one returns to the note it started from only where four fifths make a major third. That is the "
              "defining property of these tunings, and the reason the progression is so familiar; elsewhere the root comes back a comma "
              "low or a note has to shift (library action comma, name pump).",
     "source": ("81/80", "Comma pumps")},
    {"id": "31-chords", "name": "Triads and seventh chords of 31", "kind": "vocabulary", "tunings": (31,),
     "chords": ("downminor (subminor) 6:7:9 | 0 | 7 18", "minor | 0 | 8 18", "mid (neutral) 18:22:27 | 0 | 9 18", "major | 0 | 10 18", "upmajor (supermajor) 14:18:21 | 0 | 11 18",
                "harmonic seventh 4:5:6:7 | 0 | 10 18 25", "subharmonic seventh 7:6:5:4 | 0 | 7 15 25", "minor with up-sixth 12:10:8:7 | 0 | 8 18 24"),
     "shows": "Five thirds one step apart under the same fifth. Of the seventh chords the page singles out the harmonic seventh "
              "chord, its mirror image built downwards, and the minor chord with a wide sixth.",
     "source": ("31edo chord names", "Ups and downs notation")},
    {"id": "31-tetrads", "name": "Seventh chords on the subminor and neutral triads", "kind": "vocabulary", "tunings": (31,),
     "chords": ("subminor seventh 12:14:18:21 | 0 | 7 18 25", "neutral seventh 18:22:27:33 | 0 | 9 18 27", "undecimal tetrad 6:7:9:11 | 0 | 7 18 27",
                "supermajor seventh 14:18:21:27 | 0 | 11 18 29"),
     "shows": "From a long list of chords of this tuning: the seventh chords that continue each new triad with a seventh of its own "
              "kind, and the subminor triad with a neutral seventh.",
     "source": ("List of 31edo chords", "Tetrads")},
    {"id": "31-augmented-sixth", "name": "The augmented sixth chord is a harmonic seventh", "kind": "idea", "tunings": (31,),
     "chords": ("bVI with augmented sixth | 8/5 | 5/4 3/2 225/128",),
     "shows": "The chord on the flat sixth degree with an augmented sixth (the German sixth of classical harmony) is tuned exactly like "
              "a harmonic seventh chord here, which a piano cannot show: there it is one more dominant seventh.",
     "source": ("Dominant seventh chord", "In just intonation")},

    # --- several tunings ---
    {"id": "thirds-cycle", "name": "Three major thirds down (Giant Steps)", "kind": "progression", "tunings": (19, 31, 41, 53),
     "chords": ("start | 1/1 | 5/4 3/2", "a major third lower | 8/5 | 5/4 3/2", "two major thirds lower | 8/5 8/5 | 5/4 3/2",
                "three major thirds lower | 8/5 8/5 8/5 | 5/4 3/2"),
     "shows": "B, G, Eb and then Cb. On a piano the fourth chord is the first again. Where three pure major thirds fall short of an "
              "octave it is a small step higher: Cb, not B. The source's point is that the tune still works if the two are simply allowed to differ, as long as "
              "nothing drifts from one chorus to the next.",
     "source": ("12edo comma pump examples", "Augmented (128/125) comma pumps")},
    {"id": "garibaldi-thirds", "name": "Cold, sweet and sour triads", "kind": "vocabulary", "tunings": (41, 53),
     "chords": ("major of the chain of fifths | 1/1 | 81/64 3/2", "sweet major (third a comma lower) | 1/1 | 5/4 3/2", "sour major (third a comma higher) | 1/1 | 9/7 3/2",
                "minor of the chain of fifths | 1/1 | 32/27 3/2", "sweet minor (third a comma higher) | 1/1 | 6/5 3/2", "sour minor (third a comma lower) | 1/1 | 7/6 3/2"),
     "shows": "Where fifths are pure, the triads spelled with plain note names sound cold and metallic. Moving the third one step "
              "inwards gives the warm pure chords, one step outwards the sharper, more active supermajor and subminor ones.",
     "source": ("Garibaldi", "Chords and harmony")},
    {"id": "magic-functions", "name": "Dominant a major third away", "kind": "idea", "tunings": (19, 22, 41),
     "chords": ("tonic | 1/1 | 5/4 3/2", "subdominant: a major third below | 8/5 | 5/4 3/2", "dominant: a major third above | 5/4 | 5/4 3/2", "tonic | 1/1 | 5/4 3/2"),
     "shows": "In scales built from a chain of major thirds the major third takes over the fifth's role: the page calls the chord a "
              "major third above the home chord its dominant and the one a major third below its subdominant, and the augmented triad "
              "the counterpart of the suspended chord. The page names the roles; the order played here is the textbook cadence.",
     "source": ("Magic", "Chords and harmony")},
    {"id": "orwell-functions", "name": "Dominant a subminor third away", "kind": "idea", "tunings": (22, 31, 53),
     "chords": ("tonic | 1/1 | 7/6 3/2", "subdominant: a subminor third below | 12/7 | 7/6 3/2", "dominant: a subminor third above | 7/6 | 7/6 3/2", "tonic | 1/1 | 7/6 3/2"),
     "shows": "In scales built from a chain of subminor thirds, harmony can rest on the subminor triad, and the chords a subminor third "
              "above and below take the roles of dominant and subdominant. The page names the roles; the order played here is the "
              "textbook cadence.",
     "source": ("Orwell", "Chords and harmony")},

    # --- chord vocabularies of single tunings ---
    {"id": "53-triads", "name": "Six triads between subminor and supermajor", "kind": "vocabulary", "tunings": (53,),
     "chords": ("downminor 6:7:9 | 0 | 12 31", "upminor 10:12:15 | 0 | 14 31", "dupminor 18:22:27 | 0 | 15 31", "dudmajor 22:27:33 | 0 | 16 31",
                "downmajor 4:5:6 | 0 | 17 31", "upmajor 14:18:21 | 0 | 19 31"),
     "shows": "The thirds a chord can take here, step by step. There are two neutral ones, a lower and a higher; the tutor's own "
              "neutral chord is the lower.",
     "source": ("53edo", "Interval quality and chord names in color notation")},
    {"id": "41-triads", "name": "Five triads between subminor and supermajor", "kind": "vocabulary", "tunings": (41,),
     "chords": ("downminor 6:7:9 | 0 | 9 24", "upminor 10:12:15 | 0 | 11 24", "mid 18:22:27 | 0 | 12 24", "downmajor 4:5:6 | 0 | 13 24", "upmajor 14:18:21 | 0 | 15 24"),
     "shows": "The thirds a chord can take here. Plain major and minor (14 and 10 steps) are left out by the source: Kite Giedraitis "
              "advises against plain thirds in chords.",
     "source": ("41edo", "Interval quality and chord names in color notation")},
    {"id": "19-chords", "name": "Four triads and the harmonic seventh", "kind": "vocabulary", "tunings": (19,),
     "chords": ("subminor | 0 | 4 11", "minor | 0 | 5 11", "major | 0 | 6 11", "supermajor | 0 | 7 11", "harmonic diminished | 0 | 5 9", "augmented | 0 | 6 12",
                "harmonic seventh | 0 | 6 11 15", "subminor seventh | 0 | 4 11 15", "supermajor seventh | 0 | 7 11 18", "minor with sharp sixth | 0 | 5 11 15"),
     "shows": "Four main triads instead of two. The interval of fifteen steps serves both as the harmonic seventh above a major triad "
              "and as the wide sixth above a minor one.",
     "source": ("19edo chords", "Triads")},
    {"id": "19-pentatonic", "name": "The pentatonic scale as a chord", "kind": "idea", "tunings": (19,), "chords": (),
     "shows": "The seven-note scale sounds duller here than on a piano and the five-note scale more expressive. One suggestion is to "
              "treat a pentatonic scale as one large chord and to move between the pentatonic scales inside a twelve-note scale as a "
              "chord progression. Seventh chords, not triads, are proposed as the basic sonority.",
     "source": ("19edo", "As a means of extending harmony")},
]

# What was looked for in the wiki copy and not found (November 2026); the tool says so.
MISSING = (
    "No page of the copy gives a chord progression written for 53 or for 31 notes per octave: their pages list intervals, chord names "
    "and scales. For 53 only the chords carried over from the 41-note guitar pages apply.",
    "Nothing for 56 notes per octave.",
    "The pages on comma pumps explain the idea and list pieces; the page with the worked examples for these tunings is not in the copy.",
    "The pages on single temperaments describe chords and their roles, rarely a progression.",
)


class ProgressionError(ValueError):
    pass


def _size(text: str, edo: int) -> int:
    """One or more sizes added up: ratios become the tuning's nearest step, integers are steps."""
    total = 0
    for part in text.split():
        if "/" in part:
            a, b = part.split("/")
            total += round(edo * math.log2(int(a) / int(b)))
        else:
            total += int(part)
    return total


def for_tuning(edo: int) -> list[dict]:
    """The entries that apply to a tuning, those written for it first."""
    own = [e for e in ENTRIES if edo in e["tunings"]]
    return own + [e for e in ENTRIES if edo in e.get("also", ())]


def entry(name: str) -> dict:
    wanted = name.strip().lower()
    for e in ENTRIES:
        if e["id"] == wanted or e["name"].lower() == wanted:
            return e
    near = [e["id"] for e in ENTRIES if wanted in e["id"] or wanted in e["name"].lower()]
    if len(near) == 1:
        return entry(near[0])
    raise ProgressionError(f"no entry '{name}'" + (f"; similar: {', '.join(near)}" if near else ""))


def resolve(e: dict, edo: int) -> list[tuple[str, int, tuple[int, ...]]]:
    """The chords of an entry in a tuning: (name as the source writes it, root in steps above
    the tonic, tones in steps above the root)."""
    if edo not in e["tunings"] and edo not in e.get("also", ()):
        raise ProgressionError(f"'{e['id']}' is written for {' and '.join(str(n) for n in e['tunings'])} notes per octave")
    out = []
    for chord in e["chords"]:
        name, root, tones = (part.strip() for part in chord.split("|"))
        out.append((name, _size(root, edo) % edo, tuple(_size(t, edo) for t in tones.split())))
    return out
