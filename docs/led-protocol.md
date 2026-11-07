# openxen LEDs: host commands and firmware behaviour

The host (xentool) owns the colours; the module owns timing, highlight, gamma and power.
Commands go to the same HID interface as the analog stream (usage page `0xFFAC`) as 64-byte
output reports (no report ID, zero padded). Reference encoder: `host/oxl.py`.

## Commands

| Byte 0 | Name | Layout | Effect |
|---|---|---|---|
| `0x10` | PIXELS | `[1]` flags (bit 0 = show), `[2]` first key, `[3]` count 1..20, `[4..]` count × R, G, B | colours into the staging frame; with *show*, the staging frame becomes visible (a full frame = 3 reports, keys 0–19, 20–39, 40–55, show on the last, so no half-updated frames) |
| `0x11` | CONFIG | `[1]` brightness 0..255, `[2]` highlight mode (0 off, 1 replace), `[3..5]` highlight R, G, B, `[6..7]` host timeout ms (u16 LE, 0 = never), `[8..9]` LED power budget mA (u16 LE, capped at 600) | |
| `0x12` | KEEPALIVE | — | keeps the host session alive |

Every accepted command refreshes the host session. Malformed commands (unknown code, too
short, key range outside 0..55, count > 20, highlight mode > 1) are rejected and change
nothing.

Colours are plain sRGB 8-bit values; the firmware applies gamma 2.2 once (freexen applied it
twice: host and firmware).

## Firmware behaviour

- **Start-up**: LEDs off, budget 100 mA, timeout 2 s, highlight off, until the first command.
- **Highlight**: with mode 1, a pressed key (libhmk's actuation) shows the highlight colour
  instead of its frame colour, locally and without USB traffic.
- **Host timeout**: no command for longer than the timeout → all LEDs off ("defined fallback";
  the Wooting and Exquis keep the host's colours forever). Any command restores the frame.
- **Power budget**: the IS31FL3733's global current (GCC) is computed from the frame actually
  shown so the estimated LED current stays within the budget:
  `I = 3.5 mA × GCC/255 × ΣPWM/256` (42 mA peak per channel at REXT 20 kΩ, 1/12 scan duty).
  Full white at GCC 255 is ~590 mA; the default 100 mA keeps a module within a 500 mA port
  together with the sensors (~390 mA). Raise the budget only on a powered hub (the InLine hub
  supplies 2 A per port). When the current goes down, GCC is lowered before PWM rises; when it
  goes up, PWM is written first, so no intermediate state exceeds the budget.
- **Register traffic**: only changed PWM bytes are written (runs of up to 16 bytes); a full
  frame is 12 transfers. I2C runs at ~385 kHz from the main loop, one byte per loop pass
  (never waiting), so LED updates cannot stall scanning or USB.
- **Status**: the analog stream report's byte 15 carries `0x01` host session active,
  `0x02` host timed out (LEDs off), `0x04` I2C error since the previous report (the driver is
  re-initialised automatically after 50 ms).

## IS31FL3733 details used

- Address 0x50 (ADDR1 = ADDR2 = GND). Page select: write 0xC5 to 0xFE (unlock), then the page
  to 0xFD. Page 0: LED on/off (bit per channel), page 1: PWM, register `SW × 16 + CS`
  (0-based), page 3: configuration (0x01 = normal operation), GCC, SW pull-up / CS
  pull-down (32 kΩ de-ghosting, bench-tunable).
- Key → lines: generated from `layout/module.json` into
  `firmware/keyboards/openxen-m56/openxen_led_map.h`; tests check it against the netlist.
- Not used yet: open/short detection (needs I2C reads; planned for bring-up diagnostics),
  auto-breath, SYNC.
