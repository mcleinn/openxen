"""Client for xentool's local API (`xentool serve <layout> --api`, see xentool `src/api.rs`).

xentool is the only program that talks to the keyboard modules. From it the tutor gets the
description of the keyboard, the keys as they are pressed and released, and it asks for
LED colours on top of the layout and for notes to be sounded.

`FakeXentool` has the same methods and keeps everything in memory; tests and `--demo` use
it, so the tutor can be tried without a keyboard.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Callable

import requests

Rgb = tuple[int, int, int]
Address = tuple[int, int]   # (board, key): xentool's address of a key


class XentoolError(RuntimeError):
    """xentool cannot be reached or refused a request; the message says what to do."""


def _hex(rgb: Rgb) -> str:
    return "%02X%02X%02X" % rgb


class Xentool:
    def __init__(self, base_url: str = "http://127.0.0.1:9098", timeout: float = 3.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self._local = threading.local()     # one HTTP session per thread

    def _session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
        return self._local.session

    def _call(self, method: str, path: str, json=None, params=None, timeout: float | None = None):
        try:
            r = self._session().request(method, self.base + path, json=json, params=params, timeout=timeout or self.timeout)
        except requests.RequestException as e:
            raise XentoolError(
                f"xentool is not reachable at {self.base}. Start it with the API switched on: "
                f"xentool serve <layout> --api  ({type(e).__name__})"
            ) from e
        if r.status_code != 200:
            detail = r.text[:200]
            raise XentoolError(f"xentool refused {method} {path}: {r.status_code} {detail}")
        return r.json()

    def setup(self) -> dict:
        return self._call("GET", "/api/setup")

    def held(self) -> list[Address]:
        return [tuple(a) for a in self._call("GET", "/api/keys/state")["held"]]

    def events(self, after: int | None, wait_ms: int = 0) -> dict:
        """Events numbered above `after` (see xentool `/api/events`); waits up to `wait_ms`."""
        params = {} if after is None else {"after": after, "wait_ms": wait_ms}
        return self._call("GET", "/api/events", params=params, timeout=self.timeout + wait_ms / 1000)

    def overlay(self, set: dict[Address, Rgb] | None = None, clear: list[Address] | str | None = None, dim_base: float | None = None) -> None:
        body: dict = {}
        if clear is not None:
            body["clear"] = clear if isinstance(clear, str) else [list(a) for a in clear]
        if set:
            body["set"] = [{"board": b, "key": k, "rgb": _hex(rgb)} for (b, k), rgb in set.items()]
        if dim_base is not None:
            body["dim_base"] = dim_base
        if body:
            self._call("POST", "/api/leds/overlay", json=body)

    def notes(self, on: list[tuple[Address, int, int | None]] | None = None, off: list[Address] | None = None) -> None:
        """Sound keys: `on` = (address, velocity, length in ms or None), `off` = addresses."""
        body = {
            "on": [{"board": b, "key": k, "velocity": v, **({"ms": ms} if ms is not None else {})} for (b, k), v, ms in (on or [])],
            "off": [list(a) for a in (off or [])],
        }
        self._call("POST", "/api/notes", json=body)

    def chord_names(self, edo: int, pitch_classes: list[int]) -> list[dict]:
        return self._call("POST", "/api/chords/name", json={"edo": edo, "pitch_classes": sorted(pitch_classes)})["chords"]

    def midi(self, notes: list[tuple[int, int, int, int]]) -> None:
        """Notes on a MIDI channel of their own, outside the layout: (channel 1..16, note,
        velocity, length in ms). For clicks and percussion."""
        self._call("POST", "/api/midi", json={"notes": [{"channel": c, "note": n, "velocity": v, "ms": ms} for c, n, v, ms in notes]})

    def layouts(self) -> dict:
        """`{"current": name, "available": [{"name", "edo"}], "switching", "last_error"}`."""
        return self._call("GET", "/api/layouts")

    def switch_layout(self, name: str, wait_s: float = 8.0) -> None:
        """Load another layout (and with it another tuning) and wait until it is in place."""
        self._call("POST", "/api/layout", json={"name": name})
        deadline = time.monotonic() + wait_s
        while True:
            state = self.layouts()
            if not state.get("switching"):
                if state.get("last_error"):
                    raise XentoolError(f"xentool could not load the layout {name}: {state['last_error']}")
                if state.get("current") == name:
                    return
            if time.monotonic() > deadline:
                raise XentoolError(f"xentool did not finish loading the layout {name} within {wait_s:.0f} s")
            time.sleep(0.1)


class EventPump:
    """Fetches key events from xentool on a background thread and hands each one to every
    subscriber's queue, so a waiting tool call sees a key press within milliseconds."""

    def __init__(self, client, on_setup: Callable[[], None] | None = None):
        self.client = client
        self.on_setup = on_setup
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: str | None = None   # why events are not arriving, if they are not

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="xentool-events", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def _run(self) -> None:
        after: int | None = None
        while not self._stop.is_set():
            try:
                if after is None:
                    after = self.client.events(None)["next"]
                    self.error = None
                    continue
                batch = self.client.events(after, wait_ms=2000)
                self.error = None
            except XentoolError as e:
                self.error = str(e)
                after = None
                self._stop.wait(1.0)
                continue
            after = batch["next"]
            for ev in batch["events"]:
                if ev.get("type") == "setup":
                    if self.on_setup:
                        self.on_setup()
                    continue
                with self._lock:
                    targets = list(self._subscribers)
                for q in targets:
                    q.put(ev)


class FakeXentool:
    """An in-memory xentool: holds a keyboard description, records what was asked of it,
    and lets a test (or a script) press and release keys."""

    def __init__(self, setup: dict, chord_names: Callable[[int, list[int]], list[dict]] | None = None,
                 layouts: dict[str, int] | None = None):
        self._setup = setup
        # layouts that can be switched to: name -> notes per octave
        self._layouts = dict(layouts) if layouts is not None else {f"{n}-bosanquet-sample": n for n in (12, 19, 22, 31, 41, 53)}
        self._layouts.setdefault(setup.get("layout", ""), setup.get("edo"))
        self._chord_names = chord_names
        self.overlay_state: dict[Address, Rgb] = {}
        self.dim_base: float | None = None
        self.overlay_calls = 0
        self.seen: set[tuple[Address, Rgb]] = set()     # every (key, colour) ever lit
        self.sounded: list[tuple[Address, int, int | None]] = []
        self.clicks: list[tuple[int, int, int, int]] = []      # (channel, note, velocity, ms) sent with midi()
        self.released: list[Address] = []
        self._held: set[Address] = set()
        self._events: list[dict] = []
        self._cond = threading.Condition()
        self._t0 = time.monotonic()

    # --- the Xentool interface ---

    def setup(self) -> dict:
        return self._setup

    def held(self) -> list[Address]:
        return sorted(self._held)

    def events(self, after: int | None, wait_ms: int = 0) -> dict:
        with self._cond:
            if after is None:
                return {"next": len(self._events), "missed": False, "events": []}
            if len(self._events) <= after and wait_ms:
                self._cond.wait_for(lambda: len(self._events) > after, timeout=wait_ms / 1000)
            after = min(after, len(self._events))
            return {"next": len(self._events), "missed": False, "events": list(self._events[after:])}

    def overlay(self, set: dict[Address, Rgb] | None = None, clear: list[Address] | str | None = None, dim_base: float | None = None) -> None:
        self.overlay_calls += 1
        if clear == "all":
            self.overlay_state.clear()
        elif clear:
            for a in clear:
                self.overlay_state.pop(tuple(a), None)
        for a, rgb in (set or {}).items():
            self.overlay_state[tuple(a)] = rgb
            self.seen.add((tuple(a), rgb))
        if dim_base is not None:
            self.dim_base = dim_base

    def notes(self, on=None, off=None) -> None:
        self.sounded.extend(on or [])
        self.released.extend(off or [])

    def chord_names(self, edo: int, pitch_classes: list[int]) -> list[dict]:
        return self._chord_names(edo, sorted(pitch_classes)) if self._chord_names else []

    def midi(self, notes: list[tuple[int, int, int, int]]) -> None:
        self.clicks.extend(notes)

    def layouts(self) -> dict:
        return {"current": self._setup.get("layout", ""), "switching": False, "last_error": None,
                "available": [{"name": n, "edo": e} for n, e in sorted(self._layouts.items())]}

    def switch_layout(self, name: str, wait_s: float = 8.0) -> None:
        if name not in self._layouts:
            raise XentoolError(f"xentool refused POST /api/layout: 400 no layout '{name}'")
        from .sample import sample_setup
        setup = sample_setup(self._layouts[name], tuple(self._setup.get("boards", (0,))))
        setup["layout"] = name
        self.overlay_state.clear()
        self._held.clear()
        self.set_setup(setup)

    # --- driving it ---

    def _pitch(self, address: Address) -> int:
        for k in self._setup["keys"]:
            if (k["board"], k["key"]) == address:
                return k["pitch"]
        raise KeyError(address)

    def _push(self, event: dict) -> None:
        with self._cond:
            event["seq"] = len(self._events) + 1
            self._events.append(event)
            self._cond.notify_all()

    def press(self, board: int, key: int, velocity: int = 90) -> None:
        self._held.add((board, key))
        self._push({"type": "key", "t_us": int((time.monotonic() - self._t0) * 1e6), "board": board, "key": key,
                    "kind": "on", "velocity": velocity, "pitch": self._pitch((board, key))})

    def release(self, board: int, key: int) -> None:
        self._held.discard((board, key))
        self._push({"type": "key", "t_us": int((time.monotonic() - self._t0) * 1e6), "board": board, "key": key,
                    "kind": "off", "velocity": 0, "pitch": self._pitch((board, key))})

    def set_setup(self, setup: dict) -> None:
        self._setup = setup
        self._push({"type": "setup", "boards": setup.get("boards", [])})
