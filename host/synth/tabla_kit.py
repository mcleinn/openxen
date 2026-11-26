"""Prepare the tabla sample kit for the SuperCollider patch `tabla.scd`.

    python host/synth/tabla_kit.py [--kit DIR] [--tala FILE] [--out DIR]

Reads (private reference material, not in git):
  - `reference/music/rhythm/downloads/repos/bolbox/kits/deolekar-tabla/`: 110 mono WAV, eleven
    bols with ten takes each, and `kit.json` with a gain per bol. Made by the bolbox project
    from Subodh Deolekar's "Tabla strokes dataset" (2020, Zenodo, DOI 10.5281/zenodo.4327350,
    CC BY 4.0): takes selected, trimmed, mixed down to mono; see its LICENSE.txt, copied along.
  - `reference/music/rhythm/tala.json`: the thekas, for the list of bols that must sound, and
    the timbre classes that say which bols sound alike.

Writes `reference/music/tabla/kit/`: the samples, the licence, and `kit.scd`, a SuperCollider
literal the patch loads:

    (samples: (ge: [17.1, ["ge_rr1.wav", ...]], ...),      gain in dB as in kit.json, the takes
     bols: (dha: [\\dha], dhin: [\\ge, \\tin], ...))         bol -> the samples struck together

How a bol without a recording of its own is sounded is decided in `host/tutor/percussion.py`
(the same table the tutor reports to the player): another bol of its timbre class, or, for
Dhin, Dhi and the like, the left and the right drum's strokes together. That composition is
this project's choice, not a statement of the sources.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "host"))
from tutor import percussion  # noqa: E402
from tutor.rhythm_build import convert  # noqa: E402

KIT = ROOT / "reference" / "music" / "rhythm" / "downloads" / "repos" / "bolbox" / "kits" / "deolekar-tabla"
TALA = ROOT / "reference" / "music" / "rhythm" / "tala.json"
OUT = ROOT / "reference" / "music" / "tabla" / "kit"


def samples_of(kit: dict) -> dict[str, tuple[float, list[str]]]:
    """bol -> (gain in dB, its takes), from the kit's strokes and recorded composites."""
    found = {}
    for group in ("strokes", "composites"):
        for name, entry in kit.get(group, {}).items():
            if entry.get("samples"):
                found[name] = (float(entry.get("gain_db", 0.0)), list(entry["samples"]))
            elif entry.get("alias_of") and percussion.TABLA_SPELLINGS.get(name) != entry["alias_of"]:
                raise ValueError(f"the kit plays {name} with {entry['alias_of']}; percussion.TABLA_SPELLINGS does not say so")
    return found


def bol_table(tala: dict) -> tuple[dict[str, list[str]], list[str]]:
    """Every bol of the thekas (and those the tutor uses for usul and for a plain pulse)
    -> the samples struck together; and the bols that stay silent."""
    library = convert(tala)
    classes = tala.get("tabla_bol_timbre_classes", {})
    table = {bol: how["samples"] for bol, how in library["tabla_bols"].items()}
    extra = set(percussion.USUL_ON_TABLA.values()) | set(percussion.GENERIC["tabla"]) | set(percussion.PULSE["tabla"]) \
        | {s.capitalize() for s in percussion.TABLA_SAMPLES}
    for bol in sorted(extra):
        how = percussion.tabla_bol(bol, classes)
        if how:
            table.setdefault(bol, how["samples"])
    return table, library["silent_bols"]


def kit_scd(samples: dict[str, tuple[float, list[str]]], bols: dict[str, list[str]]) -> str:
    sample_lines = [f"        {name}: [{gain:g}, [{', '.join(json.dumps(f) for f in files)}]]" for name, (gain, files) in samples.items()]
    keyed: dict[str, list[str]] = {}
    for bol, parts in bols.items():
        keyed.setdefault(percussion._plain(bol), parts)        # the patch compares in lower case
    bol_lines = [f"        {name}: [{', '.join(chr(92) + p for p in parts)}]" for name, parts in sorted(keyed.items())
                 if name.isascii() and name.isalpha()]
    return "(\n    samples: (\n" + ",\n".join(sample_lines) + "\n    ),\n    bols: (\n" + ",\n".join(bol_lines) + "\n    )\n)\n"


def build(kit_dir: Path = KIT, tala_file: Path = TALA, out: Path = OUT) -> dict:
    kit = json.loads((kit_dir / "kit.json").read_text(encoding="utf-8"))
    samples = samples_of(kit)
    if set(samples) != set(percussion.TABLA_SAMPLES):
        raise ValueError(f"the kit has {sorted(samples)}, percussion.TABLA_SAMPLES expects {sorted(percussion.TABLA_SAMPLES)}")
    bols, silent = bol_table(json.loads(Path(tala_file).read_text(encoding="utf-8")))
    out.mkdir(parents=True, exist_ok=True)
    copied = 0
    for _, files in samples.values():
        for name in files:
            shutil.copyfile(kit_dir / name, out / name)
            copied += 1
    for name in ("LICENSE.txt",):
        if (kit_dir / name).exists():
            shutil.copyfile(kit_dir / name, out / name)
    (out / "kit.scd").write_text(kit_scd(samples, bols), encoding="utf-8")
    return {"samples": copied, "bols": len(bols), "silent": silent}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--kit", type=Path, default=KIT)
    p.add_argument("--tala", type=Path, default=TALA)
    p.add_argument("--out", type=Path, default=OUT)
    args = p.parse_args()
    result = build(args.kit, args.tala, args.out)
    print(f"{result['samples']} samples, {result['bols']} bols -> {args.out}" +
          (f"; no sound for: {', '.join(result['silent'])}" if result["silent"] else ""))
