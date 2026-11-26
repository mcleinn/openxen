"""openxen tutor: an MCP server that lets a language model teach on the keyboard.

    theory.py    notes, intervals, chords and scales of the current tuning (xenharmlib)
    board.py     the keyboard as the player sees it: keys, neighbours, hand shapes
    engine.py    exercise rules (wait mode), pure logic
    xt.py        client for xentool's local API, plus an in-memory stand-in
    session.py   what each tool does, in the player's terms
    server.py    the tools as an MCP server over HTTP, with a token for the local network
    sample.py    a made-up keyboard for trying things without hardware

Start: `python -m tutor` from `host/` (see `host/tools/tutor.ps1` and `docs/tutor.md`).
"""
