# Provenance

Pinned upstream sources and tool versions used by this project. Update this file whenever a pin or tool changes; review upstream diffs before moving a pin.

## Upstream code (cloned under `reference/repos/`, not committed here)

| Project | URL | Pinned commit | Date | License | Role |
|---|---|---|---|---|---|
| HE60 | https://github.com/peppapighs/HE60 | `501871e03edc54cc17a75ea4d55e129fea370f52` (tag v2.1 is the hardware release; HEAD only changes the README link) | 2026-07-05 | GPL-3.0 | Hardware base: MCU/USB/power/mux/sensor circuit, MX footprints, plate project |
| libhmk | https://github.com/peppapighs/libhmk | `1d2b2e2101fa4509700a24152d33335ddfda8240` | 2026-10-11 | GPL-3.0 | Firmware base: AT32F405 driver, analog acquisition, calibration, raw-HID protocol |
| hmkconf | https://github.com/peppapighs/hmkconf | `22884ba` | 2026-07-19 | (see repo) | Configurator; reference for the raw-HID command usage |
| macrolev | https://github.com/heiso/macrolev | `5e56c0b` | 2025-08-25 | (see repo) | Lekker switch footprint (`SW_MX_Lekker_1u`) used to confirm the unit cell |

Other clones (Zellia80-HE, Lucca-58HE, Plink, kicad-kbplacer, Fabrication-Toolkit, wooting-analog-sdk, void_switch_kicad) are reading references only; see `reference/SOURCES.md`.

## Copied into this repository (GPL-3.0, from HE60 501871e)

- `hardware/kicad/lib/openxen.kicad_sym`: symbols `MT9102ET` and `AT32F405RxT7` extracted from `HE60.kicad_sch` by `hardware/generators/gen_project.py`.
- The controller block of `openxen-m56.kicad_sch` (USB-C, ESD, fuse, LDOs, MCU, crystal, buttons, TC2030, JST) is HE60's schematic region below its key matrix, copied item by item by `gen_schematic.py`; sensor and mux cells are HE60's HE1 / AM2 cells cloned.
- Footprint `SW_Lekker_1u` geometry = HE60 `MX-1U` = macrolev `SW_MX_Lekker_1u`; `LED_RGB_1206R_MHT151RGBCT` = marbastlib `LED_MX_1206R` geometry (datasheet-confirmed).

## Our own prior work (local, read as input)

| Source | Used for |
|---|---|
| `C:\Dev-Free\freexen\xenIO\void_switch_keyboard.kicad_pcb` (2025-02-07) | Module outline polygon, 56 key centres, 8 mounting holes |
| `C:\Dev-Free\freexen\xenCase\module_top.dxf` | Existing 1.5 mm CNC plates: 14 mm cutouts and holes (cross-check) |
| `C:\Dev-Free\xentool\src\geometry.rs` (`LTN_BOARD0_TUPLES`) | Key numbering and hex coordinates (Lumatone `.ltn` order) |

## Tools (this machine, 2026-11-06)

| Tool | Version | Notes |
|---|---|---|
| KiCad | 9.0.7 (file format 20241229) | `kicad-cli` and bundled Python 3.11.5 with `pcbnew` at `C:\Program Files\KiCad\9.0\bin` |
| PlatformIO Core | 6.1.19 | `~/.platformio/penv/Scripts/pio.exe`; AT32 platform from `https://github.com/ArteryTek/platform-arterytekat32.git` (installed on first build) |
| Python (system) | 3.12.10 | pydantic 2.13.4 (libhmk schema), numpy, matplotlib, PIL, pypdf |
| Rust | cargo at `~/.cargo/bin` | xentool backend (Phase 8) |
| OpenSCAD | nightly | keycaps/case parts |
| Java (portable) | Temurin 25.0.5 JRE under `reference/tools/jre25/` (also 21 under `jre/`) | runs Freerouting; no admin install |
| Freerouting | 2.5.0 jar under `reference/tools/` (needs Java 25) | cell comparison run (`freeroute_cell.py`) and the whole-board leftover-net pass (`freeroute_board.py`, `--router.fanout.enabled=false`); cells, controller blocks and planes are scripted, not autorouted |
| Freerouting host | user's Linux VM "linuxvm" (Ubuntu 24.04, 4 cores, 54 GB), Temurin 25 JRE + the jar in the user's home, reached over SSH | `freeroute_board.py --remote`; the 8 GB PC cannot hold a whole-board run |
| Fabrication Toolkit | `reference/repos/Fabrication-Toolkit` at 7f627b6, run through its CLI by `hardware/fab/make_fab.py` | JLCPCB Gerbers/BOM/positions, rotation table `transformations.csv` |
| TraceMaker | v0.12.1 Linux release binary (GPL-3.0, github.com/DingoOz/TraceMaker) on the VM, user-installed | autorouter trial for the non-scripted nets |
| 7-Zip | `C:\Program Files-Zip` | split-archive extraction (jlcparts database) |
| jlcparts database | `reference/jlcparts/cache.sqlite3`, snapshot 2026-11-06 | JLCPCB stock / basic-extended lookups |

## Reference firmware build log

See `docs/reference-build.md` (written by Phase 0 once the unmodified `he60-v2` target has been built).
