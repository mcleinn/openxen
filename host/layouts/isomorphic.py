"""Generate an isomorphic (Bosanquet-style) xentool layout (.otn) for any equal tuning.

"Isomorphic": the same move on the keyfield is the same interval everywhere. Two numbers
fix the layout: `right`, the steps one key to the right, and `upper_right`, the steps one
key up and to the right. Everything else follows:

    left -right            upper_left  upper_right - right
    lower_left -upper_right            lower_right right - upper_right

Geometry (the same as the Lumatone presets converted by from_lumatone.py, proven by
reproducing 53ET-bosanquet.otn key for key, see tests/test_layouts_isomorphic.py):
key n of a module sits at (row, half-key column) = `hex` of layout/module.json (11 rows,
odd rows shifted by one half key, a neighbour to the right is 2 columns further); module
b lies 2 rows lower and 12 half keys further right than module b-1 (BOARD_SHIFT, as in
host/tutor/sample.py). From the origin key, (row, col) is reached by
n_upper_right = -(row - 4) steps up-right and n_right = (col - n_upper_right) / 2 steps
to the right, and

    pitch = origin_pitch + right * n_right + upper_right * n_upper_right.

Reference pitch: the origin is the leftmost key of the fifth row of module 0 (key 19,
lattice (4, 0)); it is the C of the 19, 22, 31 and 53 presets. By default it gets pitch
2 * EDO = C2 in xentool's numbering (pitch 0 = C0), as in 31ET-bosanquet.otn and in the
tutor's sample keyboard. 53ET-bosanquet.otn has 2 * 53 + 60 = 166 there (Lumatone note 60
on channel 1 taken as the number of steps); `--origin-pitch 166` reproduces it.

Default steps: with the fifth f = round(EDO * log2(3/2)), right = 2f - EDO (the whole
tone) and upper_right = 7f - 4*EDO (the chromatic semitone, sharp minus natural). Then
lower_right = 3*EDO - 5f is the diatonic semitone, and the scale C D E F G A B C is always
the same shape: right, right, lower-right, right, right, right, lower-right.

    17: fifth 10 -> right 3, upper_right 2, lower_right 1 (the shape of 53, 31, 19)
    16: fifth 9 (675 cents, "mavila") -> right 2, upper_right -1, lower_right 3

16 has no fifth near 3/2 (675 or 750 cents). The flat one gives the antidiatonic scale
2 2 3 2 2 2 3 (large and small steps swap roles), and seven fifths up land one step BELOW
the start, so a "sharp" lowers: the key up-right of C is one step lower than C. With
right 2 and upper_right -1 all 16 notes are there (gcd(2, 1) = 1), every scale step is a
neighbour (2 to the right, 3 lower right, 1 lower left), and the seven-note scale keeps the
fingering it has in every other Bosanquet layout. right 2 / upper_right +1 would look more
like the 12-tone layout but repeats the same notes two rows up (2 up-rights = 1 right), so
half of the keyfield is duplicates and the 3-step is no neighbour.

Colours follow 53ET-bosanquet.otn: the notes are ordered along the chain of fifths and cut
into bands of 7, 5, 7, 5 ...: F C G D A E B (the "white keys", cyan), then the five sharps,
the next seven and so on upwards, the five flats and so on downwards. If the two steps do
not come from one fifth, the colour is a hue wheel over the octave instead.

    python host/layouts/isomorphic.py 17              build/layouts/17ET-bosanquet.otn
    python host/layouts/isomorphic.py 16              build/layouts/16ET-mavila.otn
    python host/layouts/isomorphic.py 22 --right 4 --upper-right 3 --name 22ET-mine
"""

from __future__ import annotations

import argparse
import colorsys
import json
import math
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "build" / "layouts"
BOARDS = 5
BOARD_SHIFT = (2, 12)     # rows, half-key columns from one module to the next (host/tutor/sample.py)
ORIGIN = (4, 0)           # lattice position of the reference C: key 19 of module 0

# 53ET-bosanquet.otn: bands of the chain of fifths, naturals first, then alternately up and down
NATURALS = "12dfe3"
BANDS_UP = ["129300", "fffa99", "f9ff00", "ff9f57"]      # sharps, then further up
BANDS_DOWN = ["0000bf", "d882ce", "b200ae", "ff1a1a"]    # flats, then further down


def module_positions() -> dict[int, tuple[int, int]]:
    """Key index -> (row, half-key column) of one module, from layout/module.json."""
    spec = json.loads((ROOT / "layout" / "module.json").read_text(encoding="utf-8"))
    return {k["id"]: (k["hex"][0], k["hex"][1]) for k in spec["keys"]}


def lattice(boards: int = BOARDS) -> dict[tuple[int, int], tuple[int, int]]:
    """(board, key) -> (row, half-key column) in the lattice all modules share."""
    positions = module_positions()
    return {(b, k): (row + BOARD_SHIFT[0] * b, col + BOARD_SHIFT[1] * b)
            for b in range(boards) for k, (row, col) in sorted(positions.items())}


def moves(row: int, col: int) -> tuple[int, int]:
    """(keys to the right, keys up-right) that lead from the origin to (row, col)."""
    n_upper_right = -(row - ORIGIN[0])
    twice = col - ORIGIN[1] - n_upper_right
    if twice % 2:
        raise ValueError(f"({row}, {col}) is not a point of the key lattice")
    return twice // 2, n_upper_right


def default_steps(edo: int) -> tuple[int, int]:
    """(right, upper_right) of the Bosanquet layout on the tuning's best fifth."""
    fifth = round(edo * math.log2(1.5))
    return 2 * fifth - edo, 7 * fifth - 4 * edo


def default_name(edo: int, right: int, upper_right: int) -> str:
    if (right, upper_right) != default_steps(edo):
        return f"{edo}ET-isomorphic-{right}-{upper_right}"
    return f"{edo}ET-mavila" if upper_right < 0 else f"{edo}ET-bosanquet"


def pitches(edo: int, right: int, upper_right: int, origin_pitch: int | None = None,
            boards: int = BOARDS) -> dict[tuple[int, int], int]:
    """(board, key) -> pitch (steps above C0)."""
    if math.gcd(right, upper_right, edo) != 1:
        raise ValueError(f"right {right} and upper_right {upper_right} reach only every "
                         f"{math.gcd(right, upper_right, edo)}th note of {edo}")
    origin = 2 * edo if origin_pitch is None else origin_pitch
    out = {}
    for cell, (row, col) in lattice(boards).items():
        n_right, n_upper_right = moves(row, col)
        out[cell] = origin + right * n_right + upper_right * n_upper_right
    return out


def generating_fifth(edo: int, right: int, upper_right: int) -> int | None:
    """The fifth (in steps) of which `right` is two (less an octave) and `upper_right`
    seven (less four octaves), if there is one that reaches every note."""
    fifth = (upper_right - 3 * right) % edo
    fits = (2 * fifth - right) % edo == 0 and (7 * fifth - upper_right) % edo == 0
    return fifth if fits and math.gcd(fifth, edo) == 1 else None


def fifth_bands(edo: int) -> dict[int, int]:
    """Place in the chain of fifths (C = 0, G = 1, F = -1 ...) -> band: 0 for F C G D A E B,
    +1 for the five sharps, +2 for the next seven ... and -1 for the five flats, -2 ...;
    bands are added in turn above and below until all `edo` notes have one."""
    bands = {k: 0 for k in range(-1, 6)}
    high, low, level = 6, -2, 1
    while len(bands) < edo:
        size = 5 if level % 2 else 7
        for _ in range(size):
            if len(bands) < edo:
                bands[high] = level
                high += 1
        for _ in range(size):
            if len(bands) < edo:
                bands[low] = -level
                low -= 1
        level += 1
    return bands


def band_colour(band: int) -> str:
    if band == 0:
        return NATURALS
    table = BANDS_UP if band > 0 else BANDS_DOWN
    colour = table[(abs(band) - 1) % len(table)]
    dim = 0.6 ** ((abs(band) - 1) // len(table))             # further rounds of the palette get darker
    return "".join(f"{round(int(colour[i:i + 2], 16) * dim):02x}" for i in (0, 2, 4))


def colours(edo: int, right: int, upper_right: int, origin_pitch: int | None = None) -> dict[int, str]:
    """Pitch class -> RRGGBB."""
    origin = (2 * edo if origin_pitch is None else origin_pitch) % edo
    fifth = generating_fifth(edo, right, upper_right)
    if fifth is None:                                         # no chain of fifths: hue by height above C
        out = {}
        for pc in range(edo):
            r, g, b = colorsys.hsv_to_rgb(((pc - origin) % edo) / edo, 0.0 if pc == origin else 0.85, 1.0)
            out[pc] = f"{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"
        return out
    return {(origin + place * fifth) % edo: band_colour(band) for place, band in fifth_bands(edo).items()}


def render(edo: int, right: int | None = None, upper_right: int | None = None,
           origin_pitch: int | None = None, boards: int = BOARDS) -> str:
    """The text of the .otn file."""
    if right is None or upper_right is None:
        right, upper_right = default_steps(edo)
    pitch = pitches(edo, right, upper_right, origin_pitch, boards)
    colour = colours(edo, right, upper_right, origin_pitch)
    # xentool: pitch = (Chan - 1) * Edo + Key + PitchOffset, Chan >= 1 (0 switches a key off)
    offset = min(2 * edo, edo * (min(pitch.values()) // edo))
    lines = [f"Edo={edo}", f"PitchOffset={offset}", ""]
    for b in range(boards):
        lines.append(f"[Board{b}]")
        for k in sorted(key for board, key in pitch if board == b):
            octave, note = divmod(pitch[b, k] - offset, edo)
            lines += [f"Key_{k}={note}", f"Chan_{k}={octave + 1}", f"Col_{k}=ff{colour[pitch[b, k] % edo]}"]
        lines.append("")
    return "\n".join(lines)


def write(edo: int, right: int | None = None, upper_right: int | None = None,
          origin_pitch: int | None = None, name: str | None = None, out_dir: pathlib.Path = OUT) -> pathlib.Path:
    if right is None or upper_right is None:
        right, upper_right = default_steps(edo)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ((name or default_name(edo, right, upper_right)) + ".otn")
    path.write_text(render(edo, right, upper_right, origin_pitch), encoding="ascii")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Isomorphic xentool layout (.otn) for any equal tuning.")
    ap.add_argument("edo", type=int, help="steps per octave")
    ap.add_argument("--right", type=int, help="steps one key to the right (default: the whole tone)")
    ap.add_argument("--upper-right", type=int, help="steps one key up-right (default: the chromatic semitone)")
    ap.add_argument("--origin-pitch", type=int, help="pitch of key 19 of module 0 (default 2 * EDO = C2)")
    ap.add_argument("--name", help="file name without .otn")
    ap.add_argument("--out", type=pathlib.Path, default=OUT, help="directory (default build/layouts)")
    args = ap.parse_args(argv)
    right, upper_right = default_steps(args.edo)
    right = args.right if args.right is not None else right
    upper_right = args.upper_right if args.upper_right is not None else upper_right
    try:
        path = write(args.edo, right, upper_right, args.origin_pitch, args.name, args.out)
    except ValueError as e:
        raise SystemExit(str(e))
    pitch = pitches(args.edo, right, upper_right, args.origin_pitch)
    print(f"{path}: right {right}, upper_right {upper_right}, lower_right {right - upper_right}, "
          f"pitches {min(pitch.values())}..{max(pitch.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
