# openxen analog stream, protocol version 1

Each openxen module sends one USB HID input report per completed key scan (all 56 keys, about
4000 scans per second) on its own HID interface. The module's configuration channel (libhmk
raw HID, used by hmkconf) is unchanged and separate.

## USB

| Item | Value |
|---|---|
| Interface | HID, vendor usage page `0xFFAC`, usage `0xAC`, no report ID; input = this stream, output = LED commands (docs/led-protocol.md) |
| Report | 144 bytes, fixed layout below |
| Endpoint | interrupt IN `0x85` (OUT `0x03` for LED commands); high speed: 160-byte packets, every 125 µs microframe (one report per scan); full speed fallback: 64-byte packets every 1 ms (report spans 3 packets, at most ~330 reports/s, older scans dropped) |
| Identification | VID/PID of the module, serial number string = MCU unique ID (per module, used to assign modules to board 0..4) |

Host access: any HID API (hidapi `hid_read` on the interface with usage page `0xFFAC`). On
Windows the HID class driver polls the endpoint continuously; reports queue in the driver.

## Report layout (little endian, packed)

| Offset | Size | Field | Meaning |
|---|---|---|---|
| 0 | 2 | `magic` | `0x584F` (bytes `4F 58`, "OX") |
| 2 | 1 | `version` | 1 |
| 3 | 1 | `flags` | bit 0: values inverted (`ADC_MAX - raw`, as libhmk's matrix does for this sensor); bit 1: calibrating |
| 4 | 2 | `sequence` | +1 per completed scan, wraps at 65536. A gap means scans were lost (firmware or host) |
| 6 | 2 | `dropped` | scans the firmware could not queue since the previous report (saturating) |
| 8 | 4 | `timestamp_us` | device time at the end of the scan, µs, from the CPU cycle counter; wraps after 71.6 min |
| 12 | 1 | `num_keys` | 56 |
| 13 | 1 | `cal_first_key` | calibration below belongs to keys `cal_first_key .. +3` (mod `num_keys`) |
| 14 | 1 | `adc_bits` | 12 |
| 15 | 1 | `led_status` | LED driver state (docs/led-protocol.md): `0x01` host session active, `0x02` host timed out (LEDs off), `0x04` I2C error since the previous report |
| 16 | 112 | `values[56]` | u16 per key, key index = libhmk key = Lumatone `.ltn` key number; same domain as the calibration (rises with travel) |
| 128 | 16 | `cal[4]` | per key: u16 `rest`, u16 `bottom_out` (libhmk's running calibration) |

The calibration rotates through all keys every 14 reports (3.5 ms), so a host has a complete,
current table after 14 reports without asking for it.

## Host processing (reference: `host/oxs.py`)

1. Check `magic`/`version`; unwrap `sequence` (16 bit) and `timestamp_us` (32 bit).
2. Lost scans = sequence gap - 1 (includes `dropped`).
3. Travel of key k: `(value - rest) / (bottom_out - rest)`, clamped to 0..1. libhmk's own
   distance uses a logarithmic look-up table fitted to other sensors; openxen leaves the
   travel curve to the host, where it can be calibrated per key.
4. Velocity: differences of travel over device timestamps (not host arrival times).

## Firmware (`firmware/libhmk/`)

- `src/openxen_stream_core.c` (hardware independent, unit-tested on the PC): 8-frame ring
  between the scan interrupt (producer) and the main loop (consumer), report packing,
  microsecond clock from the cycle counter.
- `src/openxen_stream.c`: hook `analog_scan_complete_cb()` (DMA interrupt after the last mux
  channel) captures the raw values with a timestamp; `openxen_stream_task()` in the main loop
  sends the oldest frame when the endpoint is free. The report buffer is separate from
  TinyUSB's 64-byte HID buffer (libhmk's raw HID requires that size).
- `apply_openxen.py`: the edits to libhmk (4th HID interface and descriptors, scan hook,
  main loop), applied at build time by exact search/replace.
