# Reference firmware build (Phase 0)

Unmodified upstream libhmk target `he60-v2`, built 2026-11-06 to prove the toolchain. No hardware was flashed or verified.

| Item | Value |
|---|---|
| libhmk commit | `1d2b2e2101fa4509700a24152d33335ddfda8240` (clone at `reference/repos/libhmk`) |
| Command | `python setup.py -k he60-v2` then `pio run` (PlatformIO Core 6.1.19) |
| Platform | `arterytekat32` from `https://github.com/ArteryTek/platform-arterytekat32.git`; board `genericAT32F405RCT7`; framework `at32firmlib` (package `AT32F402_405_Firmware_Library`) |
| Toolchain | `toolchain-gccarmnoneeabi` (installed by PlatformIO); also installed: `tool-dfuutil` (dfu-util 0.11), `tool-openocd-at32` |
| Result | SUCCESS in 179 s; Flash 34128 B of 262144 (13.0 %), RAM 14068 B of 104448 (13.5 %) |
| Artefacts | `.pio/build/he60-v2/firmware.{bin,elf,hex}` inside the reference clone (not committed); `firmware.bin` carries a DFU suffix |

Notes
- PlatformIO reported a newer core (6.2.0); not upgraded, keep 6.1.19 pinned until the project build is stable.
- `python setup.py` needs pydantic ≥ 2.11 (system Python 3.12 has 2.13.4).
- Flashing path for later: AT32 factory DFU bootloader (BOOT button) with `dfu-util` or WebUSB DFU; SWD recovery via TC2030 + ST-LINK/V2 through `tool-openocd-at32`.
