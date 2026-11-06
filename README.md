# openxen

Custom Hall-effect microtonal hex keyboard: five identical 56-key Lumatone-shaped modules with Wooting Lekker Tikken switches, one AT32F405 per module, analog key depth streamed to [xentool](https://github.com/mcleinn/xentool).

Successor of [freexen](https://github.com/mcleinn/freexen) (DIY printed switches, one Teensy) and of the Wooting/Exquis software-only approach.

- `PROJECT_PLAN.md` — the plan, decisions and gates (read this first)
- `docs/` — our documents (provenance, verification notes, user inputs)
- `layout/` — machine-readable module specification and the generators built on it
- `hardware/` — KiCad project for the module PCB (derived from HE60, GPL-3.0)
- `firmware/` — libhmk-derived firmware for the module (GPL-3.0)
- `host/` — notes for the xentool backend
- `case/` — deltas against the freexen case
- `reference/` — third-party clones, datasheets and photos; **not part of the repository** (see `.gitignore`)

Hardware and firmware derived from [peppapighs/HE60](https://github.com/peppapighs/HE60) and [peppapighs/libhmk](https://github.com/peppapighs/libhmk) are licensed GPL-3.0; see `docs/provenance.md` for pinned commits.
