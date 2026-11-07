# Tests and the build pipeline

`python hardware/generators/build_board.py` rebuilds everything from the sources and ends
with the test suite; any failure stops the build. `python -m pytest` runs the tests alone
against the current artefacts (about 5 s).

Pipeline: project -> schematic -> ERC -> netlist -> board (key field, HE60 blocks, muxes, LED
driver, cell routing, LED sink lines, LED driver fan-out, +3.3VA plane vias, silkscreen,
planes, autorouted tracks replayed from `hardware/routes/openxen-m56.routes.json`) -> DRC ->
firmware keyboard.json -> firmware build (libhmk at the pinned commit, PlatformIO) ->
production files (Fabrication Toolkit CLI) -> tests. The autorouting itself (TraceMaker)
runs off-line on a board built with `--no-routes`; `import_routes.py --capture` stores an
accepted result, which refuses to replay once the placement has changed.

| File | What it proves |
|---|---|
| `tests/test_spec.py` | 56 keys on the 19.2 mm grid inside the outline, no M3 hole under a switch; the 7 mux groups partition the keys; libhmk matrix = groups (libhmk's `[input][channel]` order); left/right 4051 pin columns serve the left/right keys in pin order; mux bodies clear of cells, holes and controller strips; LED matrix: one (cathode group, anode line) per key, 4 x 14, 12 distinct sink lines |
| `tests/test_netlist.py` | Fresh netlist export vs spec and datasheet pin maps (kept in `tests/facts.py`, not taken from the generators): sensor cells, HEn -> exactly AM<m> pin Y<ch>, mux COM -> MUX_OUT -> the libhmk MCU input pin, select bits -> 4051 A/B/C and PC1..PC3, INH/VEE/GND low, LED anode/R/G/B -> CS/SW nets -> IS31FL3733 CS1..14 / SW1..12, I2C on PB6/PB7, SDB on PC0, ADDR pins low (address 0x50); ERC has no errors |
| `tests/test_firmware.py` | keyboard.json = spec (matrix, pins, 56 keys, keymap field libhmk reads), `invert_adc` follows the sensor part (GH39FKSW: true), libhmk schema |
| `tests/test_firmware_binary.py` | Reads `mux_input_matrix`, `mux_select_pins`, `mux_input_channels` out of the compiled `firmware.elf` and checks them against the netlist and the AT32F405 ADC channel table |
| `tests/test_stream_protocol.py` | The analog stream's firmware core (`firmware/libhmk/src/openxen_stream_core.c`) compiled for the PC (zig cc, same strict warnings) produces reports that `host/oxs.py` decodes correctly: values, timestamps, sequence numbers, the calibration rotation (complete after 14 reports), losses when the ring overflows, time and counter wrap; constants agree between header, libhmk edits, decoder and `docs/stream-protocol.md`; the built ELF contains the stream and its HID descriptor (usage page 0xFFAC, 144-byte report) |
| `tests/test_led.py` | The firmware's LED core compiled for the PC, driven with commands from the reference encoder `host/oxl.py`; its register writes are replayed into a model of the IS31FL3733 that enforces the datasheet's page-lock protocol. Checked: init sequence (normal mode, GCC 0, de-ghost pulls, exactly the 168 used channels on), every key's colour lands on the registers the netlist wires it to (gamma 2.2), the generated key map = netlist, power budget never exceeded after any single write (also while dimming), partial updates write only the change, staged frames need *show*, press highlight, host timeout and keepalive, timeout 0 = never, malformed commands rejected without effect, I2C failure re-initialises to the same state, encoder byte layout. The compiled firmware's `key_map` is checked against the netlist in `test_firmware_binary.py` |
| `tests/test_board.py` | DRC 0 errors, schematic parity 0, only known warnings; every SMD part on the bottom; K/HE/D/C/CF and muxes where the spec says; no tracks on the plane layers; planes present; track/via minimums; every LED cathode on its sink line; open connections within budget |
| `tests/test_fab.py` | BOM and pick-and-place cover every assembled part exactly once, all bottom, positions = board; all 56 cell copies share one rotation; every LCSC part exists, can be assembled and is in stock for 2 boards (database snapshot); Gerber zip has all layers; NPTH drill has 112 guide-pin, 56 LED-window and 8 M3 holes |

Bugs the tests found when they were introduced (2026-11-07): firmware `invert_adc` still
false after the sensor change; mux matrix transposed relative to libhmk; keymap under a key
libhmk ignores; a 4.7 mm NRST stub left by the HE60 block copy.

Not covered by tests (manual checks before ordering): pick-and-place rotation of the LED,
sensor, mux, MCU, LED driver, crystal and USB-C in JLCPCB's 3D preview (the toolkit's rotation
table is community data; our LED footprint has no entry); analog quality of the routing.
