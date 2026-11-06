# Custom Lekker keyboard — HE60 development handoff

Prepared: 2026-11-06. This document is the project brief for a local development model.

## Decision and objective

Use **HE60 hardware and libhmk onboard firmware** as the foundation for a custom Hall-effect keyboard. This choice is settled. Focus on adapting this platform; do not reopen the earlier search for unrelated DIY keypads.

The user owns many Wooting switches and wants a **specific non-QWERTY keyboard**. Treat this as a potentially custom physical key arrangement, not merely remapping letters. Obtain the actual layout before committing to PCB geometry. The aim is to reuse an existing acquisition system and electronics design rather than develop Hall sensing from scratch.

The user can order PCBs from **JLCPCB, potentially with assembly**, and owns a **3D printer for the case**. The intended result is editable hardware, buildable onboard firmware, manufacturing files, and printable enclosure files.

## User background and priorities

- Previously built a roughly **260-key custom Hall-effect keyboard**, using custom switches rather than Lekkers and one Teensy for all keys.
- That build suffered substantial noise. Its key count is historical context, **not a requirement for this project**.
- The user suspects separate controllers per board might have helped. This was not diagnosed or established; do not assume controller count caused or fixes the noise.
- Wooting keyboards have worked well for the user. They want comparable sensing quality and high reading speeds, with open onboard code and hardware they can modify.
- Signal quality, repeatable actuation, acquisition speed, and filtering latency take priority over cosmetic features.
- Exact switch model/generation, new key count, physical layout, and required USB output behavior have not been supplied.

## Upstream sources

| Source | URL | Purpose |
| --- | --- | --- |
| HE60 hardware | https://github.com/peppapighs/HE60 | KiCad PCB/schematic, switch footprints, plate, fabrication instructions |
| HE60 releases | https://github.com/peppapighs/HE60/releases | Released Gerber/BOM/pick-and-place packages and version notes |
| libhmk firmware | https://github.com/peppapighs/libhmk | Open onboard sensing, key processing, configuration, USB firmware |
| libhmk releases | https://github.com/peppapighs/libhmk/releases | Firmware release notes and precompiled builds |
| Web configurator | https://hmkconf.com | Upstream configuration UI |
| HE60 v2 board definition | https://github.com/peppapighs/libhmk/blob/main/keyboards/he60-v2/keyboard.json | MCU, pin/channel mapping, layout, keymap, calibration defaults |

Local source inspection during this conversation used:

- **libhmk:** `1d2b2e2101fa4509700a24152d33335ddfda8240`.
- **HE60 repository:** `501871e03edc54cc17a75ea4d55e129fea370f52`.
- Latest listed HE60 hardware release at review time: **v2.1**, release commit shown upstream as `5a29d4b`. The inspected repository HEAD above is a separate reference; do not conflate it with the release tag.

Record the exact upstream commits, hardware tag, dependencies, and tool versions used for the local project. Review changes before updating. Both repositories present GPL-3.0 licensing; retain notices and inspect the actual license files when redistributing derivatives.

## Hardware baseline and version distinction

**Start with HE60 v2.1**, retaining v2 electronics unless there is a concrete reason to change them.

- HE60 v1 used **STM32F446RE**.
- HE60 v2 changed to **Artery AT32F405** for 8 kHz USB support. AT32 is a different vendor/family; do not select STM32 firmware or assume pin/register compatibility.
- The inspected libhmk AT32 driver selects PlatformIO board `genericAT32F405RCT7`. Confirm the exact MCU ordering code/package against the selected hardware BOM before ordering.
- v2.1 adds a TC2030 debug port and is documented as compatible with v2.0 firmware and plate.
- The inspected AT32 initialization configures a **216 MHz system clock**.
- The reference uses **MT9102ET Hall sensors** and **SN74LV4051A 8:1 analog multiplexers**.
- Its v2 firmware definition specifies nine multiplexer outputs going to ADC inputs and three shared select lines. That gives 72 mux positions, mapped to 69 logical key positions in the reference definition; this is not 69 simultaneously sampled ADC channels.
- Reference select pins: `C1`, `C2`, `C3`.
- Reference ADC input pins: `A3`, `A4`, `A5`, `A6`, `A7`, `C4`, `C5`, `B0`, `B1`.
- The reference board definition uses a 12 MHz external oscillator and USB port `hs`.

The hardware README describes JLCPCB-oriented fabrication files with assembled BOM components on the PCB bottom. Component stock and assembly substitutions have **not** been checked live. Preserve exact pinouts and electrical characteristics when resolving parts.

## What the firmware review established

These findings come from static source inspection, not running or benchmarking a board.

Important files, relative to libhmk:

| File | What to inspect |
| --- | --- |
| `src/hardware/at32f405xx/analog.c` | ADC sequencing, DMA buffer/interrupt, mux advancement, settling timer, ADC calibration |
| `src/hardware/at32f405xx/board.c` | Clock, USB, bootloader and board initialization |
| `hardware/at32f405xx/board_def.h` | ADC sample-cycle defaults and supported resolution |
| `src/matrix.c` | Filtering, per-key calibration, actuation and rapid-trigger state |
| `include/matrix.h` | Filter/calibration defaults and key state |
| `include/distance.h` | ADC-to-distance lookup and normalization |
| `tools/distance_lut.py` | Distance lookup-table generation |
| `src/main.c` | Main-loop scheduling of USB, commands, matrix processing and output |
| `scripts/schema/keyboard.py` | Board-definition schema and limits |
| `scripts/make.py` | Generated build flags, channel mapping and configuration |
| `scripts/drivers.py` | MCU targets, ADC pins, flash geometry and toolchain integration |

### Acquisition sequence

1. ADC converts the configured channel sequence.
2. DMA transfers the results into a buffer.
3. DMA completion interrupt copies results to the associated keys.
4. Firmware advances the shared mux address.
5. A timer provides a settling interval for mux outputs.
6. Timer interrupt starts the next ADC conversion sequence.

The AT32 driver performs ADC calibration at startup. Its default sample-time macro is `ADC_SAMPLETIME_7_5`, with 12-bit ADC resolution enforced in the inspected board header. Board JSON supports `analog.delay`, translated to `ADC_SAMPLE_DELAY`; trace its default and actual timer timing before calculating scan rates.

This is a substantially better starting architecture than ad hoc sequential reads, but DMA itself does not prove low noise or low latency.

### Processing and caveats

- libhmk implements automatic per-key calibration, configurable actuation, rapid trigger, continuous rapid trigger, and a nonlinear distance lookup table.
- The default EMA exponent is 4: approximately `y = x/16 + 15*y_previous/16`, with integer arithmetic. It adds response delay and is applied during matrix processing.
- `matrix_scan()` runs in the main loop alongside USB and command work. ADC acquisition and matrix processing are distinct schedules. Check whether filtering processes repeated cached ADC values and how this affects time-domain behavior.
- Internal key distance is represented as **0–255** in the inspected code. A 12-bit ADC does not mean 12-bit position output or physical accuracy.
- The current board schema permits **1–256 logical keys**. Do not infer support for the user's historical 260-key design without changes. Electrical/scan limits may be lower than schema limits.
- Firmware mapping uses zero as an unused mux slot and positive one-based key IDs, converted to zero-based indices by the acquisition driver. Keep this separate from zero-based layout/keymap indices; verify against the pinned source.

**No Wooting-equivalent noise, physical resolution, scan frequency, or end-to-end latency has been verified.** Upstream advertises 8 kHz USB polling on supported AT32 hardware. Keep USB report rate, fresh per-key sampling rate, matrix-processing rate, and filtered response latency separate in all reports.

## Lekker compatibility: unresolved but essential

HE60's documented switch examples include GEON Raw HE, Gateron Magnetic Jade, and Duhuk Core HE. This review did **not** establish testing with the user's exact Wooting switch generation.

Before committing to the full custom board:

- Identify the user's switch model and generation, ideally from packaging or photos.
- Verify physical footprint, retention, magnet location/polarity, travel, and switch-to-sensor geometry.
- Check sensor operating range, idle/bottomed readings, saturation, signal span and noise with the actual switch.
- Validate distance linearization for that magnet/sensor/geometry combination; endpoint calibration alone does not establish accurate intermediate distance.

HE60 supports alternative sensors, but their polarity and calibration differ. Current documentation assumes **MT9102ET with `invert_adc: false`**. It lists GH39FKSW and DRV5055A3 as inverted alternatives. Confirm the signal direction with the actual hardware instead of blindly toggling inversion or substituting sensors.

## Adapting the physical layout

The original HE60 is a conventional 60% PCB. It is an editable reference design, **not an arbitrary-layout generator**.

1. Capture the requested physical key coordinates, switch orientations, key sizes and output assignments in one machine-readable layout specification.
2. Fork the KiCad project. Preserve the MCU/USB/power/reference circuit and acquisition topology where practical; move switch/sensor pairs and reroute for the new geometry.
3. Keep sensor orientation, magnet alignment and vertical separation controlled. Preserve local decoupling and return paths; review analog routes and digital coupling after rearrangement.
4. Create a new libhmk board directory copied from `he60-v2`. Update key count, channel mapping, layout metadata, keymap and calibration configuration. Change pins only when needed and document the reason.
5. Generate a matching plate and printable enclosure from the same layout data. Verify PCB mounts, connector access, stabilizers, switch retention, plate thickness, sensor clearance and fastener stack-up.
6. Export new fabrication files from the modified project. Upstream release files are suitable for the original board, not the rearranged layout.

The reference requires a plate attached to the PCB using eight 3.5 mm M2 standoffs and sixteen 3 mm flat-head M2 screws. Verify this stack against the selected revision and switches. Do not substitute generic MX mounting geometry without checking sensor spacing.

If key count or wiring length changes substantially, reassess sensor power demand, mux fanout, ADC scan time and interference. Do not automatically add controllers or extend analog signals over long cables.

## Suggested local workflow

### First session

Obtain these inputs together: exact switches; physical layout/key count; single board versus split/modules; desired output (ordinary keys/macros, continuous analog/gamepad, or custom protocol); desired timing targets; available programming/debug equipment; printer bed dimensions.

While awaiting those inputs, clone and pin the upstream repositories, inspect their instructions, and build the **unmodified `he60-v2` target** first. Record build results without claiming hardware verification.

Upstream documents this general build flow; adapt environment setup to the local machine:

```sh
git clone https://github.com/peppapighs/HE60.git upstream-he60
git clone https://github.com/peppapighs/libhmk.git firmware
cd firmware
# Install PlatformIO and requirements using the project's documented environment.
python setup.py -k he60-v2
pio run
```

Read the selected hardware/firmware revision's flashing instructions before use. Upstream describes DFU flashing and precompiled binaries; verify the correct target, bootloader and debug recovery path. Retain access to BOOT/reset and programming pads in the new enclosure.

### Validation before full fabrication

Use a reference board or a small electrically representative coupon to validate actual Lekkers. A coupon should preserve relevant sensor/mux/power geometry; a one-sensor test alone does not establish full-array behavior.

Measure and retain:

- Raw ADC stationary noise at rest, partial travel, and bottom-out, plus filtered noise separately.
- Mux settling and crosstalk when neighboring channels differ greatly.
- Fresh sample rate per key and full-array sweep timing.
- Matrix/filter behavior and USB reporting under realistic command/USB load.
- Repeatability, false triggers, drift and USB/power sensitivity.
- End-to-end actuation/release latency where suitable equipment is available.

Set acceptance thresholds with the user; do not invent a required 0.01 mm accuracy or claim 8 kHz sensor scans based on USB descriptors. If comparing against Wooting, use matched tests.

### Deliverables

- Versioned KiCad schematic/PCB and upstream provenance.
- Custom libhmk board definition, reproducible build instructions and firmware binary.
- Layout/channel-map documentation and validation results.
- JLCPCB Gerbers, drill files, BOM, placement files and assembly notes.
- Editable plate/case CAD plus printable STL/3MF and plate manufacturing files.
- Assembly, calibration, flashing and recovery instructions.

Run electrical/design-rule checks, inspect assembly placement and polarity, verify mechanical clearances, and review component availability before presenting a manufacturing package. The current request authorizes planning and local development; it does not request placing a paid order.

## Instruction to the development model

Continue this project with **HE60 v2.1 + libhmk**. Start by reproducing the reference firmware build and reviewing the selected hardware revision. Ask for the missing physical layout and switch details before making irreversible layout assumptions. Preserve the working acquisition architecture where possible, clearly distinguish documented claims from measured results, and prioritize resolving Lekker compatibility and noise behavior before producing the final custom fabrication package.
