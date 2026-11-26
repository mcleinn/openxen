"""A made-up keyboard description, in the shape xentool's `/api/setup` returns: openxen
modules with a Bosanquet layout (whole tones to the right, like the Lumatone presets).
For tests and for `python -m tutor --fake`, where no keyboard is attached.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOARD_SHIFT = (2, 12)   # each module sits two rows lower and twelve half-keys further right
DIRECTIONS = {
    "left": [0, -2], "right": [0, 2], "upper_left": [-1, -1], "upper_right": [-1, 1],
    "lower_left": [1, -1], "lower_right": [1, 1],
}


def module_positions() -> dict[int, tuple[int, int]]:
    """Key index -> (row, half-key column) of one module, from `layout/module.json`."""
    spec = json.loads((ROOT / "layout" / "module.json").read_text(encoding="utf-8"))
    return {k["id"]: (k["hex"][0], k["hex"][1]) for k in spec["keys"]}


def sample_setup(edo: int = 31, boards: tuple[int, ...] = (0,)) -> dict:
    """Bosanquet layout: one key to the right is a whole tone up, one key to the upper
    right a chromatic semitone up; the leftmost key of the fifth row of module 0 is C2."""
    fifth = round(edo * 0.5849625007211562)     # log2(3/2)
    right = 2 * fifth - edo                     # whole tone
    upper_right = 7 * fifth - 4 * edo           # chromatic semitone
    positions = module_positions()
    c0_hz = 16.351597831287414
    keys = []
    for b in sorted(boards):
        for key, (row, col) in sorted(positions.items()):
            x, y = row + BOARD_SHIFT[0] * b, col + BOARD_SHIFT[1] * b
            # (x, y) = n_right * (0, 2) + n_upper_right * (-1, 1), counted from (4, 0)
            n_upper_right = -(x - 4)
            n_right = (y - n_upper_right) // 2
            pitch = 2 * edo + right * n_right + upper_right * n_upper_right
            keys.append({
                "board": b, "key": key, "x": x, "y": y, "pitch": pitch,
                "hz": c0_hz * 2 ** (pitch / edo), "color": "3050A0",
            })
    return {
        "backend": "sample", "geometry": "lumatone", "layout": f"{edo}-bosanquet-sample", "edo": edo,
        "boards": sorted(boards), "directions": DIRECTIONS, "keys": keys,
    }
