# layout — module specification and generators

`module.json` is the single source of truth for the openxen module geometry: outline, mounting holes, the 56 key centres in Lumatone (`.ltn`) order, the per-key unit cell (switch, Hall sensor, LED cutout, passives), the controller zones and the mux assignment. Everything downstream (KiCad placement, libhmk board definition, plate checks, xentool geometry) is generated from it; never edit generated files by hand.

| Script | Reads | Writes |
|---|---|---|
| `generators/extract_freexen.py` | freexen `xenIO` board + `module_top.dxf` (local, read-only) | `source/freexen_extract.json` |
| `generators/build_spec.py` | `source/freexen_extract.json`, xentool key order | `module.json` |
| `generators/render_preview.py` | `module.json` | `module_preview.png` |
| `../firmware/generators/gen_keyboard_json.py` | `module.json` | `../firmware/keyboards/openxen-m56/keyboard.json` |
| `generators/place_module.py` | `module.json` + a KiCad board | places/creates footprints, outline and holes in the board |

Run from the repository root with the system Python 3.12 (`place_module.py` needs KiCad's bundled Python, see its header).
