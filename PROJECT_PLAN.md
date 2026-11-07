# openxen — Project Plan

Version 0.1, 2026-11-06. Living document; update the "Decisions" and "Open questions" sections as they change.

## 1. Context

openxen is the third iteration of a velocity-sensitive microtonal hex keyboard:

| Iteration | What | Outcome |
|---|---|---|
| freexen (`C:\Dev-Free\freexen`, `C:\Dev-Free\hexkeys`) | 5 identical Lumatone-shaped 56-key modules, 3D-printed void switches, 2 addressable LEDs per key, one Teensy 4.1 scanning 280 keys over a two-level mux tree with DAC offset + digipot gain, separate control boards (EasyEDA) | Switch printing tedious; switches melted from LED heat; analog noise; LED data integrity over 560-LED chain; 5 V/20 A LED supply and wide traces next to sensor lines; separate controller added noise. Case (wood, CNC-cut from `xenCase/*.dxf`) and 5 module cutouts still exist. |
| xentool (`C:\Dev-Free\xentool`) | Rust host: 1 kHz analog polling → velocity, aftertouch, MTS-ESP, HUD, LED painting, for Wooting 60HE and Exquis | Works well; layout locked to those devices. |
| openxen (this) | 5 identical module PCBs with Wooting Lekker Tikken switches, one MCU per module, USB to the host, analog depth streamed to xentool | — |

Owned parts: 360 Lekker Tikken Medium switches (4×90; 280 needed, 80 spare), Linear70 and Linear100 spring packs for experimentation, lube kit. Tools: KiCad 9.0.7 (with bundled Python + pcbnew), OpenSCAD nightly, PlatformIO 6.1.19, Rust/cargo, Python 3.12, Bambu A1 mini (small bed), ST-LINK/V2 (official, plus possibly clones), InLine 35396C self-powered 10-port USB hub (2 A/port). dfu-util 0.11 and AT32 OpenOCD installed via PlatformIO. Larger prints/CNC go to a service.

Upstream base (handoff decision, confirmed): HE60 v2.1 hardware (`github.com/peppapighs/HE60`, HEAD 501871e, tag v2.1, KiCad 9 format 20241229, 2-layer, AT32F405RCT7, MT9102ET sensors, SN74LV4051A 8:1 muxes, XC6206 3.3 V + TLV75733 3.3 VA LDOs, USBLC6 ESD, TC2030 SWD) and libhmk firmware (`github.com/peppapighs/libhmk`, HEAD 1d2b2e2, 2026-10-11). Both GPL-3.0 → openxen hardware and firmware stay GPL-3.0.

## 2. Decisions (as of 2026-11-06)

1. **Module geometry = freexen module**, unchanged outline (124.84 × 211.2 mm stepped Lumatone shape, 46-vertex polygon, 9.6 mm notches / 17.28 mm tabs, R1.5 fillets in the case DXF), 56 keys in rows 2-5-6-6-6-6-6-6-6-5-2 at 19.2 mm pitch, 9.6 mm stagger, 8 M3 holes at x 19.2/105.6, y 19.2/76.8/134.4/192.0 (relative to top-left). Fits the existing wood case. 5 identical PCBs (JLCPCB 5-pack).
2. **One AT32F405 per module**, each module its own USB device. No analog signal leaves the PCB. Host stitches modules (xentool already does this for multiple Wootings/Exquis).
3. **Controller location**: top-right housing-free strip (~78 × 21 mm, where the old IDC header/terminal block sat). Fallback: bottom-left mirror strip, or AT32F405CCU7 QFN-48 between keys. Case may be modified if needed.
4. **USB**: USB-C receptacle on each module; existing hub connects the 5 modules: **InLine 35396C** industrial 10-port USB 3.2 Gen 1 hub, aluminium/DIN-rail, external 20 V / 3 A PSU (60 W), max 5 V / 2 A per port, no PD (https://distrinode.co.za/inline-35396c-interface-hub-usb-3-2-gen-1-3-1-gen-1-type-b-5000-mbit-s-black). Per-port 2 A and ~12 A aggregate at 5 V cover 5 modules at ~0.9 A each with margin; 5 spare ports for Exquis/Wooting. Modules must enumerate as USB 2.0 HS devices (AT32 HS PHY) — fine on a USB 3 hub.
5. **All components on the bottom side** (Wooting 60HE recipe, confirmed from the teardown photos in `C:\Dev-Free\macrolev\ref\Wooting-60HE`): sensors, muxes, MCU, USB-C and **reverse-mount RGB LEDs in PCB cutouts** → single-sided JLCPCB assembly. Top side has only switches and the plate.
6. **LEDs**: **variant B chosen for rev 1 (user decision 2026-11-06)** — matrix driver **IS31FL3733** (C506251; 12 SW sinks × 16 CS sources; the IS31FL3741A is not stocked by JLCPCB). Common-anode **MHT151RGBCT** reverse-mount 1206 RGB (C409782): anode → CS line (14 used), cathodes → the 3 SW lines of its group; 4 groups = 4 vertical stripes of 14 keys, so CS lines run horizontally and SW lines vertically. No series resistors (datasheet Fig. 2). Peak 42 mA/channel at REXT 20 k, 1/12 duty. Reasons: hardware current cap (≈0.37 A / ≈1.9 W per module at full white vs 2.0 A / 10 W for a chain), no idle current, isolated LED failures, smooth dimming; variant A is the same LED family that failed in freexen. Routing: unit cell + row/column buses scripted, Freerouting as comparison, human review. Both variants documented below for reference:
   - **A — addressable chain** (SK6812MINI-E reverse-mount, one data line, SPI+DMA): least routing; 56 free-running PWM sources; ~0.6 mA idle each; needs a 3.3→5 V data buffer. Rev-1 default *unless* the coupon test (§7, gate G2) shows LED coupling into the sensors.
   - **B — matrix driver** (IS31FL3743B or AW20216S + plain reverse-mount RGB, Wooting-style with per-row resistors): quieter, hard current cap, no idle current; ~29 matrix lines through the hex field; extended part with thin stock.
   - One LED per key (not two), brightness capped in firmware.
7. **Host protocol**: firmware streams per-key depth (0–255) at ≥1 kHz over a vendor HID interface; xentool gets a native `openxen` backend. Layout files: Lumatone `.ltn` (xentool already has `LTN_BOARD0..4_TUPLES` = exactly this keyfield). Onboard USB-MIDI is a later option.
8. **Plate**: FR4 plate ordered as a bare 2-layer PCB with the same outline (as HE60's `plate/plate.kicad_pcb`), 1.5 mm, 14 mm cutouts. Replaces the printed `module-top.stl`. Keycaps from `xenKeycap` (MX cross stem fits Lekker).
9. **Sensor**: **GH39FKSW** (C266230; HE60-listed alternative, SOT-23 pinout identical to MT9102ET: 1 VDD, 2 OUT, 3 GND; 1.8 mV/Gs, 6 mA, `invert_adc: true`). MT9102ET is not in JLCPCB's catalogue (2026-11-06).

## 3. System architecture

```
[Lekker Tikken ×56] ─magnet─> [MT9102ET ×56] ─> [7× 74LV4051 8:1] ─> AT32F405 ADC (7 ch) + 3 select
                                                                     │ DMA + TMR6 settle (libhmk driver)
                                                                     ├─ raw HID: analog stream (56 B/report, 1 kHz)
                                                                     ├─ raw HID: config/commands (libhmk protocol)
                                                                     ├─ LED driver (A: SPI-DMA WS2812 / B: SPI to IS31FL3743B)
                                                                     └─ USB HS (8 kHz capable) ──> USB-C ──> Waveshare hub ──> PC/Pi
PC/Pi: xentool `serve layout.ltn` (new openxen backend) → velocity/aftertouch/MTS-ESP/MIDI/HUD, LED colours back to modules
```

Scan budget per module (libhmk defaults): 8 mux steps × (7 conversions + 20 µs settle) ≈ 250 µs full refresh ≈ 4 kHz fresh samples per key; xentool polls at 1 kHz. (Unverified until measured on hardware.)

## 4. Unit cell (to be verified with a switch in hand — gate G1)

Sourced (2026-11-06), switch centre = (0,0), +y = south (KiCad convention), all on the **bottom** layer:

| Item | Value | Source |
|---|---|---|
| Guide-pin holes | 2× NPTH Ø1.75 at (±5.08, 0); no centre-post hole, no pin pads | macrolev `SW_MX_Lekker_1u.kicad_mod` (built for Lekker) and HE60 `MX-1U.kicad_mod` — identical |
| Plate cutout | 14.0 × 14.0 mm, R≈0.5 corners; 1.5 mm plate 3.5 mm above PCB | same footprints (Eco2 outline), `module_top.dxf`, HE60 build guide |
| Hall sensor | SOT-23 at (0, 0), rotation so the die sits under the magnet axis | HE60 PCB: every sensor at dx=dy=0 from its switch; Wooting 60HE photo `W60HE-16.jpg` (sensor centred between the guide holes) |
| LED | reverse-mount in a cutout ≈3.3 × 3.2 mm centred at (0, −4.7…−5.08) = MX LED position, north | `W60HE-16.jpg` scaled by the 10.16 mm hole pitch; MX standard LED position (0, −5.08) |
| Magnet | in the stem, centred, facing the PCB; Tikken bottom closed | Lekker V1 photo `lekker-switch.png`; Wooting product page; PC Gamer factory walkthrough |
| Polarity | north-pole-down (same as Lekker V2 and Gateron Jade); HE60 reads Jade with MT9102ET and `invert_adc: false` → same setting | Notebookcheck (Tikken = V2 orientation), MonsGeek (Jade = N-down), HE60 README (Jade supported) |
| Magnet strength | unknown vs Jade; libhmk auto-calibrates rest/bottom-out, so only the swing size is at risk | Wooting blog: Gateron-made Lekkers use a stronger magnet to bridge a larger gap |
| Filtering | 100 nF at each sensor + 4.7 nF to GND at the sensor output (HE60); series R optional (DRV5055 app note) | HE60 schematic (69× 4.7n, 83× 100n), DRV5055 datasheet |

Confirmed by the user's photos `docs/input/lekker-1.jpg` (top) and `lekker-2.jpg` (bottom), 2026-11-06: MX cross stem; LED lens on the north edge, reaching the housing bottom (reverse-mount LED below it works); bottom fully closed with a raised round boss over the centred magnet; two round plastic guide pins at ±5.08 mm; no centre post; no metal pins; marking "A02". **Gate G1 closed.** Polarity taken as N-down from sources; `invert_adc` is the fallback.

Bench checks for the user (gate G1), with sources:
1. Bottom of a Tikken: confirm two side pins at ±5.08 mm, no centre post, centred magnet window, lens position (north/south). Compare with HE60 `HE60/lib/HE60.pretty/MX-1U.kicad_mod` and `W60HE-16.jpg`.
2. Polarity: compass or a known north-down switch (Gateron Jade) bottom-to-bottom → both repel = same orientation. Notebookcheck states Tikken = Lekker V2 orientation: https://www.notebookcheck.net/A-world-first-and-near-perfect-thocky-Hall-effect-switch-Wooting-Lekker-Tikken-vs-Lekker-V2-switch-hands-on-test.1156046.0.html
3. Spring/force: Medium 42→54 gf, 22 mm spring: https://wooting.io/product/wooting-lekker-tikken-medium-switch

## 5. Workstreams and gates

| Phase | Deliverable | Who does what | Gate |
|---|---|---|---|
| 0. Setup ✅ 2026-11-06 | Git repo (origin `github.com/mcleinn/openxen`), skeleton, `docs/provenance.md`, AT32 PlatformIO platform installed, unmodified `he60-v2` built (`docs/reference-build.md`) | AI | build passes ✅ |
| 1. Switch verification | G1 checklist above + photos/measurements in `docs/switch-verification.md` | User measures, AI records | **G1**: geometry + polarity known |
| 2. Layout spec ✅ 2026-11-06 | `layout/module.json` built from freexen PCB + xentool key order (`layout/generators/`): keys match plate cutouts ≤0.13 mm, holes ≤0.09 mm (one DXF hole 1.04 mm off, PCB keeps grid); `module_preview.png`; `firmware/keyboards/openxen-m56/keyboard.json` validated against libhmk schema; `place_module.py` creates/updates a KiCad board (self-test rendered, 288 footprints). Open: real SK6812MINI-E reverse-mount footprint (pads outside a ~3.7×3.0 cutout, confirm from the datasheet drawing) | AI; user reviews preview | ✅ (plate match 0.13 mm instead of the 0.05 target — freexen row 2 has a 19.16 mm pitch error; nominal grid kept) |
| 3. Schematic ✅ 2026-11-06 | `hardware/kicad/openxen-m56/openxen-m56.kicad_sch` generated by `hardware/generators/gen_schematic.py`: HE60 controller block copied verbatim (fuse upsized to 1 A), 56 sensor cells + 7 mux cells cloned from HE60's cells, IS31FL3733 LED sheet from the datasheet's RGB application circuit; every part carries an `LCSC Part #` (`hardware/parts.json`, checked against the JLCPCB database of 2026-11-06, basic parts preferred). ERC: 0 errors, 1 harmless library-version warning. Parts changed vs HE60 because JLCPCB does not stock them: sensor MT9102ET → **GH39FKSW** (same pinout, HE60-listed, `invert_adc: true`), LED driver IS31FL3741A → **IS31FL3733** (12 SW × 16 CS; QMK-supported). LED: **MHT151RGBCT** reverse-mount 1206 RGB (marbastlib footprint geometry, datasheet-confirmed). Footprints: `hardware/kicad/lib/openxen.pretty` | AI; user reviews renders | ERC clean ✅ |
| 4. PCB 🔄 (2026-11-07) | 4-layer: F.Cu LED lines (referenced to GND), In1 GND plane, In2 +3.3 VA plane, B.Cu parts, cells and analog. `build_board.py` rebuilds everything deterministically: key field, HE60 controller blocks with their routing, muxes in 7 compact 8-key clusters (farthest key 39 mm, channels ordered by pin column), LED driver, all 56 cells routed, the 12 LED sink lines scripted (`route_led_sw.py`), +3.3VA plane vias, silkscreen, planes. Net classes carry the widths. DFT: TP1-16. Status: DRC 0 errors, parity 0, 39 consistency tests green (`docs/testing.md`). Open: 14 LED anode lines, sensor-to-mux fan-in, controller/driver connections -> TraceMaker (Freerouting failed on this board: >330 open, routed through planes and cells) | AI scripts + DRC loop + renders; user reviews analog | **G2**: DRC clean, analog review done, LED variant chosen ✅ (B) |
| 5. Plate + case | Keep the freexen case (photos `docs/input/case-1.jpg`, `case-2.jpg`): 3 wood layers — top 20 mm (optional, hex openings), middle 20 mm (module pockets, modules tilted, interlocking), bottom 10 mm; each module on its own floor plate; per-module metal plate with 14 mm cutouts on 8 standoffs; connector bay at the top-right of each pocket. **Plates: all five CNC metal plates exist and measure exactly 1.5 mm (2026-11-06) → reused unchanged.** Stack-up: PCB top → plate underside = 3.5 mm standoffs (M3, PCB holes are M3), plate top at 5.0 mm (MX standard, same as HE60). Switch is captured between PCB and plate; clips engage at 1.5 mm. No FR4 plate needed. Adjust floor-plate thickness so Lekker + hex keycap height matches the old stack. USB-C on the module's top-right strip exits into the existing bay. Keycap batch from `xenKeycap` | AI generates plate/DXF from spec; user measures stack, prints/orders | plate thickness + standoff height confirmed; keycap top height matches old stack |
| 6. Fab package 🔄 dry run ✅ 2026-11-07 | `hardware/fab/make_fab.py` runs the Fabrication Toolkit CLI on a copy of the board: Gerber/drill zip, BOM (LCSC numbers), positions. Tested: complete, bottom-only, positions = board, stock for 2 boards, 9 extended parts. Manual check left: rotations in JLCPCB's preview. **Order 5 PCBs, assemble 2** once routed | AI prepares; user orders | user approval before paying |
| 7. Firmware 🔄 board + analog stream build ✅ 2026-11-07 | `firmware/keyboards/openxen-m56/keyboard.json` (generated) and the openxen changes (`firmware/libhmk/`, applied by exact search/replace) build against libhmk 1d2b2e2 via `firmware/build_firmware.py` (32.5 KB flash, 13.9 KB RAM). **Analog stream** (`docs/stream-protocol.md`): own HID interface, one 144-byte report per scan with µs device timestamp, sequence number, 56 raw 12-bit values and a rotating calibration slice; reference decoder `host/oxs.py`; tested on the PC and in the ELF. Open: IS31FL3733 LED driver + host commands, then the xentool reader | AI | builds ✅; bench test on rev 1 |
| 8. xentool backend | `src/openxen/`: HID enumeration (5 modules → board index by serial), 1 kHz reader, `.ltn` layout, reuse Wooting velocity/aftertouch code, LED painting, HUD | AI | plays MIDI from 1 module |
| 9. Validation | Noise (raw/filtered, rest/mid/bottom), mux settling/crosstalk, per-key sample rate, LED-on vs LED-off noise, drift, USB load, end-to-end latency; acceptance thresholds agreed with user | AI tooling + user bench | **G3**: thresholds met → build remaining modules |
| 10. Production | Remaining 3 modules assembled, 5-module case integration, docs (assembly, flashing, calibration, recovery) | both | done |

## 6. Power budget per module (5 V, from research; verify on hardware)

| Load | Current |
|---|---|
| 56 × MT9102ET @ ~6 mA | ≈ 340 mA |
| MCU + muxes + misc | ≈ 50 mA |
| RGB at 20 % white, 1 LED/key | ≈ 400 mA |
| Addressable idle (variant A) | ≈ 35 mA |
| **Total** | **≈ 0.8–0.9 A** per module, ≈ 4.3 A for five |

→ Covered by the InLine 35396C hub (2 A/port, 60 W PSU). Brightness cap in firmware still mandatory (a module must also work on a plain 500 mA port for bench use: LEDs off or dim until the host enables them). Lower-current sensors (AH49HZ3 ~2 mA) remain an option.

## 7. AI / human division of labour

- AI (reliable): everything that is text or script — layout spec, placement/track replication with `pcbnew` (KiCad 9 bundled Python; SWIG API deprecated but works in 9.x), ERC/DRC loops (`kicad-cli ... --exit-code-violations`), SVG/PNG renders to inspect, BOM/LCSC stock, fab exports, firmware, xentool, docs, test tooling.
- Human (required): unit-cell placement and routing, analog/USB/power routing review, Eeschema structural edits, datasheet pin checks, bench measurements, ordering.
- Guard rails: git commit before every scripted board write and diff the S-expression; never trust AI-generated pinouts/footprints without datasheet check; DRC exit code 0 does not mean clean unless `--exit-code-violations` is set; code-first EDA tools (atopile, tscircuit, Zener, Flux) cannot import HE60 and are out.

## 8. Risks and open questions

- Tikken magnet-to-sensor gap (closed bottom) → smaller ADC swing; calibrate on rev 1. (G1/G3)
- LED PWM coupling into sensors (variant A). (G2/G3)
- AT32F405RCT7 and IS31FL3743B availability at JLCPCB. (Phase 6)
- ~~Hub PSU rating vs 4.3 A~~ — resolved: InLine 35396C, 2 A/port, 60 W. (§6)
- libhmk 256-key schema is irrelevant per module (56) but hmkconf expects a keyboard; keep the HID keyboard interface for configurator compatibility.
- Case: USB-C exit positions, hub bay, R1.5 fillets in the PCB outline, DXF hole at (20.24, 192) vs PCB 19.2.

## 9. Repository layout

```
openxen/
  PROJECT_PLAN.md, HE60_development_handoff.md
  docs/            OUR documents: provenance.md, switch-verification.md, validation/
  reference/       THIRD-PARTY material only (see reference/SOURCES.md)  — created 2026-11-06
    repos/         HE60, libhmk, hmkconf, Zellia80-HE, Lucca-58HE, Plink, kicad-kbplacer,
                   Fabrication-Toolkit, wooting-analog-sdk, void_switch_kicad, macrolev
    datasheets/    AT32F405, 74LV4051A, CD74HC4067, DRV5055, IS31FL3743A/B, IS31FL3741A,
                   SK6812MINI-E, AHCT1G125, TLV757P, kicad-cli manual (+ list of manual downloads)
    images/        Wooting 60HE teardown photos, Lekker V1 exploded view, MX drawings
    web/           saved product/teardown/compat pages, QMK LED driver sources
  layout/          module.json (source of truth), generators/ (python)        — Phase 2
  hardware/        kicad/openxen-m56/ (HE60-derived), plate/, fab/            — Phase 3–6
  firmware/        libhmk fork, keyboards/openxen-m56/                        — Phase 7
  host/            notes for the xentool backend (code lives in C:\Dev-Free\xentool)
  case/            DXF/STL deltas vs freexen/xenCase                           — Phase 5
```

Programming/debug: normal flashing via the AT32 factory DFU bootloader (BOOT button, as HE60/libhmk). SWD recovery via the TC2030 pad with the user's ST-LINK/V2 (works on AT32F405 Cortex-M4 through OpenOCD's AT32 support; Artery's own AT-Link/ICP is the vendor path). Install dfu-util / WebUSB DFU in Phase 0.

## 10. Immediate next steps

1. User: gate G1 bench checks (§4).
2. AI: Phase 0 (repo, pins, AT32 toolchain, reference build) and Phase 2 layout spec + generators, both independent of G1.
3. Together: unit-cell drawing (sensor, LED cutout, holes, caps) → first Eeschema/PCB session.
