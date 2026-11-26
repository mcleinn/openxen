"""A record of what the tutor model asked and what it was told, for reproducing a lesson.

One JSON object per line:

    {"t": "...", "kind": "start", ...}                      server start: tuning, options
    {"t": "...", "kind": "call", "id": 7, "tool": "keys", "args": {"note": "C4"}}
    {"t": "...", "kind": "result", "id": 7, "tool": "keys", "ms": 3.1, "ok": true, "text": "..."}
    {"t": "...", "kind": "key", ...}                        a key press or release, as xentool reports it

`text` is exactly what the model received (the error message if `ok` is false). A `call`
without a `result` is a tool that never returned.

A tool call only puts the record on a queue; a background thread formats and writes it, so
logging costs a tool call some microseconds and never waits for the disk. This is a
developer's file: unlike tool results it contains xentool's key addresses.
"""

from __future__ import annotations

import itertools
import json
import queue
import threading
from datetime import datetime
from pathlib import Path

_STOP = object()


class CallLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._q: queue.SimpleQueue = queue.SimpleQueue()
        self._ids = itertools.count(1)
        self._key_queues: list[tuple[object, queue.Queue]] = []
        self._thread = threading.Thread(target=self._run, name="tutor-call-log", daemon=True)
        self._thread.start()

    def write(self, kind: str, **fields) -> None:
        """Queue one record; returns at once."""
        self._q.put({"t": datetime.now().isoformat(timespec="milliseconds"), "kind": kind, **fields})

    def call(self, tool: str, args: dict) -> int:
        n = next(self._ids)
        self.write("call", id=n, tool=tool, args=args)
        return n

    def result(self, n: int, tool: str, seconds: float, ok: bool, text: str) -> None:
        self.write("result", id=n, tool=tool, ms=round(seconds * 1000, 1), ok=ok, text=text)

    def follow_keys(self, pump) -> None:
        """Also record every key press and release the event pump delivers."""
        q = pump.subscribe()
        self._key_queues.append((pump, q))

        def run() -> None:
            while True:
                ev = q.get()
                if ev is _STOP:
                    return
                self.write("key", event=ev.get("kind"), **{k: v for k, v in ev.items() if k not in ("kind", "type")})

        threading.Thread(target=run, name="tutor-key-log", daemon=True).start()

    def close(self) -> None:
        """Write what is queued and stop (for tests and a clean shutdown)."""
        for pump, q in self._key_queues:
            pump.unsubscribe(q)
            q.put(_STOP)
        self._key_queues.clear()
        self._q.put(_STOP)
        self._thread.join(timeout=5)

    def _run(self) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            while True:
                record = self._q.get()
                if record is _STOP:
                    return
                try:
                    f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")
                    if self._q.empty():
                        f.flush()
                except Exception:
                    pass    # the log must never take the server down
