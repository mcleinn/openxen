"""Prepare the mridangam sample kit for the SuperCollider patch `mridangam.scd`.

    python host/synth/mridangam_kit.py [--per-layer 3] [--layers 6]

Reads `reference/music/mridangam/MridangamDG-Full.zip`: a DrumGizmo kit of recorded mridangam
strokes (ten strokes: Thom, Num, Tha, Thi, Dhin, Dheem, Cha, Bheem, Ta, Tham; 6,977 samples,
each with a measured "power"). Private reference material, not in git.

Writes `reference/music/mridangam/kit/`: for every stroke a selection of samples spread over
its range of power (`--layers` loudness layers, `--per-layer` different takes in each, so
repeated strokes do not sound identical), and `kit.scd`, a SuperCollider literal

    (Thom: [[power, "Thom/Thom-012.wav"], ...], Num: [...], ...)

which the patch loads. The full kit would be 180 MB of buffers; the default selection is
about 180 samples.
"""

from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "reference" / "music" / "mridangam" / "MridangamDG-Full.zip"
OUT = ROOT / "reference" / "music" / "mridangam" / "kit"
# the kit's own note numbers (midimap.xml), kept so that a drum plugin and this patch agree
NOTES = {"Thom": 36, "Num": 38, "Tha": 40, "Thi": 41, "Dhin": 43, "Dheem": 45, "Cha": 47, "Bheem": 48, "Ta": 50, "Tham": 52}


def select(samples: list[tuple[float, str]], layers: int, per_layer: int) -> list[tuple[float, str]]:
    """Samples spread evenly over the stroke's range of power: `layers` groups by rank,
    from each the `per_layer` nearest to the group's middle."""
    ordered = sorted(samples)
    if len(ordered) <= layers * per_layer:
        return ordered
    chosen = []
    for layer in range(layers):
        lo, hi = len(ordered) * layer // layers, len(ordered) * (layer + 1) // layers
        group = ordered[lo:hi]
        middle = len(group) // 2
        start = max(0, min(middle - per_layer // 2, len(group) - per_layer))
        chosen.extend(group[start:start + per_layer])
    return chosen


def build(source: Path = SOURCE, out: Path = OUT, layers: int = 6, per_layer: int = 3) -> dict[str, int]:
    counts = {}
    lines = []
    with zipfile.ZipFile(source) as z:
        root = next(n for n in z.namelist() if n.endswith("drumkit.xml")).rsplit("/", 1)[0]
        for stroke in NOTES:
            xml = z.read(f"{root}/{stroke}/{stroke}.xml").decode("utf-8")
            samples = [(float(power), file) for power, file in
                       re.findall(r'<sample [^>]*power="([^"]+)"[^>]*>\s*<audiofile [^>]*file="([^"]+)"', xml)]
            chosen = select(samples, layers, per_layer)
            (out / stroke).mkdir(parents=True, exist_ok=True)
            entries = []
            for power, file in chosen:
                name = file.rsplit("/", 1)[-1]
                (out / stroke / name).write_bytes(z.read(f"{root}/{stroke}/{file}"))
                entries.append(f'[{power:g}, "{stroke}/{name}"]')
            lines.append(f"    {stroke}: [{', '.join(entries)}]")
            counts[stroke] = len(chosen)
    (out / "kit.scd").write_text("(\n" + ",\n".join(lines) + "\n)\n", encoding="utf-8")
    return counts


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--layers", type=int, default=6)
    p.add_argument("--per-layer", type=int, default=3)
    args = p.parse_args()
    result = build(layers=args.layers, per_layer=args.per_layer)
    print(", ".join(f"{k} {v}" for k, v in result.items()), f"-> {OUT}")
