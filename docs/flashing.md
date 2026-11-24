# Flashing the openxen-m56 module

The AT32F405 has a factory USB DFU bootloader in ROM. Normal flashing needs only the module's
USB-C cable and a PC. SWD (ST-LINK + TC2030) is for recovery only.

## Buttons (bottom side, near mux AM0)

| Button | Function |
|---|---|
| SW2 | BOOT: pulls BOOT0 high, the MCU starts the DFU bootloader instead of the firmware |
| SW1 | RESET (NRST) |

Flash before the module goes into the case; afterwards the firmware can enter the bootloader by
command from the configurator.

## Normal flashing over USB (DFU)

1. USB-C cable from the module straight to the PC (not through the hub the first time).
2. Enter DFU mode, either way:
   - hold BOOT (SW2) while plugging in the cable, then release, or
   - cable connected: hold BOOT, tap RESET (SW1), release BOOT.
3. Windows, once: Zadig (zadig.akeo.ie), Options > List All Devices, select the AT32 DFU device
   (USB ID should be 2E3C:DF11; check what Zadig shows), install WinUSB. dfu-util and WebUSB need it.
4. Check:
   ```
   %USERPROFILE%\.platformio\packages\tool-dfuutil\bin\dfu-util.exe -l
   ```
   lists the device with an "Internal Flash" entry at 0x08000000 (this alone proves MCU, crystal
   and USB path).
5. Flash, one of:
   - dfu-util (installed with PlatformIO):
     ```
     dfu-util.exe -d 2e3c:df11 -a 0 -s 0x08000000:leave -D C:\Dev-Free\openxen\build\fw\libhmk\.pio\build\openxen-m56\firmware.bin
     ```
     `:leave` starts the firmware after flashing; a warning about the DFU suffix is harmless.
   - PlatformIO: `pio run -e openxen-m56 -t upload` in `build\fw\libhmk` (environment set to DFU).
   - WebUSB DFU in Chrome (libhmk's recommendation): https://devanlai.github.io/webdfu/dfu-util/
     (connect, pick the flash entry, choose `firmware.bin`, Download).
   - Artery ISP Programmer (Artery's Windows GUI tool).
6. Unplug/replug or press RESET: the module enumerates as the openxen HID device.

The firmware is built by `python firmware/build_firmware.py` (also part of `build_board.py`).

## Updating without the BOOT button

Once openxen firmware runs, it enters the bootloader by command (libhmk `COMMAND_BOOTLOADER`,
id 2, on the configuration interface MI_02). Tested on board 1, 2026-11-24:

```
python host\tools\oxboot_win.py
dfu-util.exe -d 2e3c:df11 -a 0 -s 0x08000000:leave -D C:\Dev-Free\openxen\build\fw\libhmk\.pio\build\openxen-m56\firmware.bin
```

The button (or SWD) is only needed when the firmware does not start or USB does not come up.
Both SW2 and J3 face the floor plate in the case; take that module out (or drill a small access
hole at about 76 mm from the left and 36.5 mm from the top edge, component side up, USB-C at top).
Alternatively map libhmk's `SP_BOOT` keycode to a key combination.

The WinUSB driver (Zadig, "DFU in FS Mode", 2E3C:DF11) is installed once per PC.

## Bring-up tools (Windows, no extra packages)

| Tool | Does |
|---|---|
| `python host\tools\oxmon_win.py [seconds]` | reads the analog stream: report rate, lost reports, mean/min/max per key |
| `python host\tools\oxmon_win.py live` | magnet test: prints every key that moves, counts keys seen (target 56/56) |
| `python host\tools\oxled_win.py rgb` | all keys red, green, blue, white (dim), prints driver status (I2C errors) |
| `python host\tools\oxled_win.py chase` / `key N` | one key after another / one key in R, G, B |
| `python host\tools\oxboot_win.py` | sends the bootloader command |

## Recovery over SWD

Chain: ST-LINK/V2 (20-pin 2.54 mm) -> 20-to-10-pin adapter (ZERO / DollaTek, use its 1.27 mm
header) -> Tag-Connect **TC2030-CTX, Normal Orientation** (legged: the legs click into J3's four
big holes, so it holds by itself) -> J3. Not "LEMTA" (Atmel-ICE only); not TC2050-ARM2010 (2.54 mm,
for TC2050 cables). Check the adapter once with a multimeter: 20-pin 1/7/9/13/15 -> 10-pin
1/2/4/6/10, GND (20-pin 4) -> 10-pin 3/5/9. TC2030-CTX mapping (datasheet): pad 1 VCC, 2 SWDIO,
3 nRESET, 4 SWCLK, 5 GND, 6 SWO = J3. Software: OpenOCD with Artery support (PlatformIO package
`tool-openocd-at32`, target `at32f405xx.cfg`); ST-LINK with AT32F405 not yet tested.

| TC2030 pad (J3) | Signal | ST-LINK/V2 20-pin |
|---|---|---|
| 1 | VCC 3.3 V (reference only) | 1 (VAPP/VTref) |
| 2 | SWDIO | 7 |
| 3 | NRST | 15 |
| 4 | SWCLK | 9 |
| 5 | GND | 4 (any even pin 4-20) |
| 6 | SWO (optional) | 13 |

Power the module over USB during SWD (the ST-LINK does not supply it), then:

```
openocd -f interface/stlink.cfg -f target/at32f405xx.cfg -c "program C:/Dev-Free/openxen/build/fw/libhmk/.pio/build/openxen-m56/firmware.elf verify reset exit"
```
