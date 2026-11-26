# host

The program that plays the modules is xentool (`C:\Dev-Free\xentool`, backend `src/openxen/`).
This folder holds what belongs to openxen itself:

- `oxs.py`, `oxl.py`: reference decoder and encoder for the analog stream and the LED
  commands (`docs/stream-protocol.md`, `docs/led-protocol.md`); the firmware tests use them.
- `tools/`: bring-up tools (stream monitor, LED tests, bootloader) and `play.ps1`, which
  starts a playing session.
- `layouts/`: converter from Lumatone `.ltn` presets to xentool `.otn` layouts.
- `tutor/`: the tutor MCP server, a language model as piano teacher (`docs/tutor.md`).
