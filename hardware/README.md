# hardware — module PCB (KiCad 9)

Derived from HE60 v2.1 (GPL-3.0). Planned contents:

- `kicad/openxen-m56/` — schematic + PCB (Phase 3/4)
- `fab/` — JLCPCB outputs (Phase 6)

The key field, sensors, LED cutouts, outline and holes are placed by `layout/generators/place_module.py`; MCU/USB/power are hand-placed in the top-right controller zone.
