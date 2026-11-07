#!/usr/bin/env python3
"""Generate the libhmk board definition ``firmware/keyboards/openxen-m56/keyboard.json``
from ``layout/module.json`` and validate it against libhmk's own schema.

The layout keymap is a plain 56-key placeholder (keycodes are irrelevant for the music
use; xentool consumes the analog stream). The mux matrix is the part that matters.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "layout" / "module.json"
PARTS = ROOT / "hardware" / "parts.json"
OUT_DIR = ROOT / "firmware" / "keyboards" / "openxen-m56"
LIBHMK = ROOT / "reference" / "repos" / "libhmk"


def main() -> int:
    s = json.loads(SPEC.read_text(encoding="utf-8"))
    sensor = json.loads(PARTS.read_text(encoding="utf-8"))["parts"]["sensor"]   # polarity belongs to the sensor part
    keys = sorted(s["keys"], key=lambda k: k["id"])
    rows: dict[int, list[dict]] = {}
    for k in keys:
        rows.setdefault(k["hex"][0], []).append(k)

    # Visual keymap for hmkconf: one entry per key, hex rows staggered by half a key.
    keymap = []
    for r in sorted(rows):
        row = []
        first = True
        for k in sorted(rows[r], key=lambda k: k["hex"][1]):
            e = {"key": k["id"]}
            if first:
                e["x"] = k["hex"][1] / 2  # doubled col / 2 = key units from the left edge
                first = False
            row.append(e)
        keymap.append(row)

    kb = {
        "name": "openxen-m56",
        "manufacturer": "openxen",
        "maintainer": "mcleinn",
        "usb": {"vid": "0x1209", "pid": "0x0000", "port": "hs"},
        "keyboard": {"num_profiles": 2, "num_layers": 2, "num_keys": 56, "num_advanced_keys": 8},
        "hardware": {"hse_value": 12000000, "driver": "at32f405xx"},
        "analog": {
            "invert_adc": bool(sensor["invert_adc"]),
            "mux": {
                "select": s["mux"]["select_pins"],
                "input": s["mux"]["input_pins"],
                "matrix": s["mux"]["libhmk_matrix"],
            },
        },
        "calibration": {"initial_rest_value": 2400, "initial_bottom_out_threshold": 650},
        "layout": {"labels": [], "keymap": keymap},
        "default_keymap": [["KC_NO"] * 56] * 2,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "keyboard.json"
    out.write_text(json.dumps(kb, indent=2), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")

    # Validate with libhmk's schema if the reference clone is present.
    schema_dir = LIBHMK / "scripts"
    if schema_dir.exists():
        sys.path.insert(0, str(schema_dir))
        try:
            from schema.keyboard import Keyboard  # type: ignore
        except Exception as e:  # pragma: no cover
            print(f"schema import failed ({e}); skipping validation")
            return 0
        try:
            Keyboard.model_validate(kb)
            print("libhmk schema: OK")
        except Exception as e:
            print("libhmk schema validation FAILED:\n", e)
            return 1
    # Matrix sanity: every key exactly once, zeros elsewhere.
    flat = [v for row in kb["analog"]["mux"]["matrix"] for v in row]
    ids = sorted(v for v in flat if v)
    assert ids == list(range(1, 57)), "matrix must contain each key id 1..56 exactly once"
    print(f"matrix: {len(kb['analog']['mux']['matrix'])} select rows x {len(kb['analog']['mux']['input'])} inputs, {len(ids)} keys")
    return 0


if __name__ == "__main__":
    sys.exit(main())
