# hardware — module PCB (KiCad 9)

Derived from HE60 v2.1 (GPL-3.0). Everything here is generated from `layout/module.json`, `parts.json` and HE60's files by the scripts in `generators/`; regenerate rather than hand-edit until Phase 4 routing starts.

| Path | Content |
|---|---|
| `parts.json` | Every part with LCSC code, footprint, JLCPCB basic/extended status and the reason for the choice |
| `kicad/lib/openxen.pretty` | `SW_Lekker_1u`, `LED_RGB_1206R_MHT151RGBCT` |
| `kicad/lib/openxen.kicad_sym` | MT9102ET (pin-compatible with GH39FKSW) and AT32F405RxT7 symbols from HE60 |
| `kicad/openxen-m56/` | project, library tables, generated schematic |
| `generators/sexp.py`, `kicad_sch.py` | S-expression reader/writer and schematic helpers |
| `generators/gen_project.py` | symbol library + project files |
| `generators/gen_schematic.py` | the schematic (run after `gen_project.py`) |

Checks: `kicad-cli sch erc --severity-all` on the schematic (clean as of 2026-11-06, one library-version note on the crystal symbol).
