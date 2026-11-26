"""The tutor's tools as an MCP server (streamable HTTP).

The server runs on the machine the keyboard is plugged into, next to `xentool serve --api`.
The MCP client (an agent such as Claude Code) may run on another machine of the local
network: it sends `Authorization: Bearer <token>` with every request. Without a token the
server only listens on this machine.

    python -m tutor                              this machine only, port 9097
    python -m tutor --host 0.0.0.0               local network; token from OPENXEN_TUTOR_TOKEN
    python -m tutor --fake 31                    no keyboard: a made-up 31-tone module
"""

from __future__ import annotations

import argparse
import hmac
import inspect
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from .board import LUMATONE_TILT_DEG, BoardError
from .calllog import CallLog
from .player import Player
from .session import PRACTICE_NOTE, Tutor, TutorError
from .theory import TheoryError
from .xt import AnyXentool, FakeXentool, Xentool, XentoolError

TOKEN_ENV = "OPENXEN_TUTOR_TOKEN"
DEFAULT_PORT = 9097
EXPECTED = (TutorError, BoardError, TheoryError, XentoolError)

INSTRUCTIONS = """\
You are teaching someone to play a hexagonal microtonal keyboard that is in front of them.
These tools are your eyes and hands on it: you can light keys, hear what was played and
look things up in the current tuning. Call keyboard_info first. Never work out key ids,
neighbours or chord notes yourself: ask keys, theory and find_shape. The player sees
lights and hears you, not key ids: speak in note names or note numbers, whichever the
player uses, and directions ("the key to the upper right of your C").
The player does not wait for you: everything they play is remembered. When they ask about
something they played, or a result says `unheard`, call played; never ask them to repeat
something only because you were not listening.
"""


def build_server(tutor: Tutor, log: CallLog | None = None) -> MCPServer:
    server = MCPServer(name="openxen-tutor", instructions=INSTRUCTIONS + (PRACTICE_NOTE + "\n" if tutor.practice else ""))

    def guard(fn, *args, **kwargs) -> str:
        """Run a tool; its result goes out as compact JSON (every token travels to the
        model and back), its expected errors as a message that says how to fix the call."""
        if log is None:
            return answer(fn, *args, **kwargs)
        given = inspect.signature(fn).bind(*args, **kwargs).arguments
        n = log.call(fn.__name__, {k: v for k, v in given.items() if k != "progress"})
        began = time.monotonic()
        try:
            text = answer(fn, *args, **kwargs)
        except BaseException as e:
            log.result(n, fn.__name__, time.monotonic() - began, False, str(e) if isinstance(e, ToolError) else repr(e))
            raise
        log.result(n, fn.__name__, time.monotonic() - began, True, text)
        return text

    def answer(fn, *args, **kwargs) -> str:
        try:
            result = fn(*args, **kwargs)
        except EXPECTED as e:
            raise ToolError(str(e)) from e
        if isinstance(result, dict) and fn.__name__ not in ("played", "listen", "run_exercise"):
            unheard = tutor.unheard()
            if unheard:
                result["unheard"] = (f"the player has played {unheard} note{'' if unheard == 1 else 's'} "
                                     f"you have not been told about; call played to hear them")
        # the key maps are easier to read as plain lines than as a JSON string
        extra = "\n\nmap:\n" + result.pop("map") if isinstance(result, dict) and "map" in result else ""
        return json.dumps(result, ensure_ascii=False, separators=(",", ":")) + extra

    async def blocking(ctx: Context | None, fn, **kwargs) -> str:
        """Run a tool that waits for the player on a worker thread; pass its progress on."""
        def progress(done: float, total: float, message: str) -> None:
            if ctx is not None:
                try:
                    anyio.from_thread.run(ctx.report_progress, done, total or None, message)
                except Exception:
                    pass    # progress is a courtesy; the client may not have asked for it

        return await anyio.to_thread.run_sync(lambda: guard(fn, progress=progress, **kwargs), abandon_on_cancel=True)

    @server.tool()
    def keyboard_info(include_map: bool = True) -> str:
        """The keyboard the player has in front of them: tuning, range, what interval each
        of the six directions is, which chord qualities the tuning offers, what the light
        colours mean, and a map of the keys by note name. Call this first in every session
        and again if modules are plugged in or removed. If the answer has `practice_mode`,
        no real keyboard is attached: read what it says before teaching."""
        return guard(tutor.keyboard_info, include_map)

    @server.tool()
    def tuning(to: str | None = None, include_map: bool = True) -> str:
        """The tuning of the whole keyboard. Without `to`: which tunings it can be switched
        to. With `to` (a layout name from that list, or a number of notes per octave such
        as "31"): switch now and get the new keyboard description, as keyboard_info gives it.
        Switch when the player asks for it, or for a demonstration when it helps the lesson:
        hearing the same chord in two tunings, or comparing its shape and fingering. Say what
        you are about to do first. Your lights go off, and every note name, number, key id,
        chord shape and fingering is different afterwards, so look them up again. After a
        demonstration switch back to the player's tuning unless they want to stay."""
        return guard(tutor.tuning, to, include_map)

    @server.tool()
    def harmony(action: str = "overview", key: str = "C", chord: str | None = None, chords: list[str] | None = None,
                limit: int = 6, voicing: str = "shell") -> str:
        """Which chord tends to follow which, counted over the chord changes of about 1,100
        jazz standards, in the current tuning. `key`: C, Eb, "G minor". action "overview";
        "next" with `chord` (a symbol such as Dm7, or a degree such as IIm7): what usually
        follows and precedes it, with its role, how the root moves and how many notes are
        shared; "common": frequent runs of three and four chords; "analyse" with `chords`:
        how usual each step of a progression is; "steps" with `chords`: any progression as
        chord steps (voicing full, shell, guide, root) for demo and improvise; "tuning":
        what this tuning does to progressions (the comma, sevenths, chords that do not
        close). The counts describe one repertoire, not a law: say "usually", and never
        call an unusual step wrong. Makam and raga have no chord progressions."""
        return guard(tutor.harmony, action, key, chord, chords, limit, voicing)

    @server.tool()
    def tuning_notes(query: str | None = None, page: str | None = None, section: str | None = None, part: int = 1, limit: int = 6) -> str:
        """What the microtonal community has written about a tuning: a local copy of the
        Xenharmonic Wiki (the pages of each tuning this keyboard offers, e.g. "53edo" and
        "31edo" with their intervals, notation, chords, scales, temperaments, history and
        music; notation; the chain of fifths; commas; beginners' guides). `query`: search,
        optionally within `page`. `page` alone: its sections. `page` with `section`: the
        text (long sections come in parts). Use it for background and for the peculiarities
        of a tuning; for the notes of a chord or a scale on this keyboard ask theory and
        keys, which know the layout. The wiki's wording is its own: put it in your words."""
        return guard(tutor.tuning_notes, query, page, section, part, limit)

    @server.tool()
    def keys(key: str | None = None, note: str | None = None, near: str | None = None) -> str:
        """Look up keys. With `key` (an id from another tool result): its note, the key in
        each of the six directions with the interval to it, and the other keys that sound
        the same note. With `note` (a name: C4, vE4, Eb; or a number: 17, 17(4); without
        an octave: every octave): the keys that play it, nearest to `near` first."""
        return guard(tutor.keys, key, note, near)

    @server.tool()
    def theory(op: str, root: str | None = None, quality: str = "major", inversion: int = 0,
               notes: list[str] | None = None, keys: list[str] | None = None, mode: str = "major",
               numerals: list[str] | None = None, sevenths: bool = False) -> str:
        """Music theory in the current tuning; answers give every note as name and number.
        op "chord": root + quality (+ inversion 0-3) -> the notes, spelled for this tuning.
        op "identify": notes (with octave) or keys -> what chord that is.
        op "scale": root + mode -> the notes and the chord on each degree (sevenths=true for seventh chords).
        op "progression": root + mode + numerals (["I","IV","V7","I"]) -> the chords.
        op "tuning": what this tuning offers compared with 12-tone."""
        return guard(tutor.theory, op, root, quality, inversion, notes, keys, mode, numerals, sevenths)

    @server.tool()
    def find_shape(root: str | None = None, quality: str = "major", inversion: int = 0,
                   notes: list[str] | None = None, near: str | None = None, hand: str = "right", limit: int = 3) -> str:
        """Where to put the fingers: the ways to play a chord (root + quality + inversion) or
        a list of notes close together, nearest to key `near` first. Each way lists its keys
        with note, the path from the first key in the six directions, and how wide the
        reach is; a finger per key for `hand` (1 thumb .. 5 little finger) with how it
        feels and why, plus other good fingerings of the same keys. For the fingers of
        several steps in a row (a melody, a progression) ask fingering instead."""
        return guard(tutor.find_shape, root, quality, inversion, notes, near, hand, limit)

    @server.tool()
    def fingering(steps: list[dict], hand: str = "right", legato: bool = True) -> str:
        """Which finger on which key for a whole phrase: a melody, a chord progression, or
        both mixed. Steps as in demo. The phrase is fingered as a whole, so the same chord
        can get different fingers depending on what comes before and after; a note two
        steps share stays on its finger where that pays. `legato` false: detached playing,
        where moving the hand costs less. Per step: the keys with their finger, how it
        feels, what the context changed, and other good fingerings of that step alone.
        This is a computed starting point for an average hand, not a rule: present it as
        a suggestion, offer the alternatives, and take the player's own choice over it."""
        return guard(tutor.fingering, steps, hand, legato)

    @server.tool()
    def library(action: str = "overview", id: str | None = None, phrase: int | None = None, phrases: int = 1,
                tradition: str | None = None, mode: str | None = None, form: str | None = None, level: int | None = None,
                text: str | None = None, limit: int = 10, name: str | None = None, root: str | None = None,
                scale: str = "major", theory_pitches: bool = False, part: str = "auto", voicing: str = "full",
                sevenths: str = "auto", plain_roots: bool = False, direction: str = "up", count: int = 12,
                rhythm: str = "half") -> str:
        """Music to teach with, ready as steps. action "overview": what there is.
        "search": pieces by tradition (makam, chant, jazz), mode (a makam such as Rast, or
        "mode 1"), form, level (1 easiest .. 5; gives that level and below) or text;
        easiest first. "get" with id: the piece and its phrases; with phrase=N (phrases=how
        many in a row): the notes as steps with their lengths, for demo, run_exercise and
        fingering. "raga" with name (and root = where Sa lies): scale, ascent, descent,
        characteristic phrase and drone on the nearest steps of this tuning; a model, say so.
        "pattern": beginner patterns (steps, doubles, threes, fours, thirds, turns) with
        name = the pattern, root and scale = a mode; or name = a raga and scale = the pattern.
        "fifths": the circle of fifths in this tuning as an exercise: root, name = chord
        quality (major, minor7, ...), voicing (full, shell, guide, root, arpeggio), direction
        up (up a fifth, down a fourth, ...) or down (the jazz cycle), count = how many
        moves (0 = the whole circle until it is home), rhythm = half, whole, charleston
        or reverse_charleston; with what the circle does in this tuning. "comma": listening
        experiments on the chain of fifths, name = twelve_fifths, third, schismatic,
        minor_third, thirds_cycle or pump (count = rounds): notes to demo and a pair to
        compare. "cycle": scales and progressions around the circle, name = scales,
        two_five_one (root = first key, scale = order of keys: fourths, fifths, whole_steps,
        half_steps, count = how many keys), diatonic, minor_diatonic, dominants, bridge
        (root = the key), major_thirds, spoke, rings; with voicing as for jazz changes.
        Jazz: tunes come as chord changes (get with phrase=N gives section N as chord steps;
        voicing full, shell = root-third-seventh, guide = third and seventh, root; sevenths
        auto, harmonic or plain; part "changes" or "melody" for lead sheets that have both).
        Makam pieces need the keyboard in 53 steps per octave. Teach one phrase at a time."""
        return guard(tutor.library, action, id, phrase, phrases, tradition, mode, form, level, text, limit, name, root, scale, theory_pitches,
                     part, voicing, sevenths, plain_roots, direction, count, rhythm)

    @server.tool()
    async def hand(ctx: Context, action: str = "status", hand: str = "right", fingers: list[int] | None = None,
                   size: str | None = None, wait_s: float = 30) -> str:
        """Measure the player's hand, so that fingerings are computed for it and not for an
        average hand. Offer this once, early, and whenever fingerings feel wrong to them.
        action "status": what is known. "rest": the player lays the relaxed `hand` on the
        keys, one finger per key, and keeps all five keys down; returns when they have been
        held still for a second (up to `wait_s`). "stretch": the player holds two keys as
        far apart as they can reach without strain, with `fingers` [1, 5] (thumb and little
        finger) or [2, 5] (index and little finger). "size": small, medium or large instead
        of measuring. "reset": back to the average hand. Explain what to do before calling."""
        return await blocking(ctx, tutor.hand, action=action, hand=hand, fingers=fingers, size=size, wait_s=wait_s)

    @server.tool()
    def fingering_book(action: str = "list", fingers: list[int] | None = None, hand: str = "right", keys: list[str] | None = None,
                       root: str | None = None, quality: str = "major", inversion: int = 0, notes: list[str] | None = None) -> str:
        """The player's own fingerings, kept between sessions. When the player settles on a
        fingering ("I play this with 1-2-4"), save it: action "save" with `fingers` (lowest
        note first) and the shape as a chord (root, quality, inversion), notes, or keys.
        It then comes first in find_shape and fingering, for the same hand shape on every
        root. "forget" removes one, "list" shows all. Never overrule an entry of this book."""
        return guard(tutor.fingering_book, action, fingers, hand, keys, root, quality, inversion, notes)

    @server.tool()
    def set_lights(lights: list[dict] | None = None, clear: list[str] | str | None = None) -> str:
        """Light keys or switch lights off. `lights`: [{"key": id} or {"note": "E4"}, plus
        "role" (target, next, root, lh, rh, finger1..finger5, correct, wrong) or "color"
        (RRGGBB)]. `clear`: "all" or a list of key ids; cleared keys show their normal
        colour again. Lights stay until cleared or until an exercise or demo starts."""
        return guard(tutor.set_lights, lights, clear)

    @server.tool()
    async def demo(ctx: Context, steps: list[dict], tempo_bpm: float = 60, beats_per_step: float = 2,
                   hand: str = "right", fingers: bool = False, repeat: int = 1, outline: bool = False) -> str:
        """Play and light steps for the player to watch and hear (listen first, then
        repeat). A step is {"chord": "C major"} (optional "inversion"), {"notes": ["C4","E4"]},
        {"note": "E4"} or {"keys": [ids]}; "beats" in a step gives it its own length, and
        {"rest": true, "beats": 1} is a silence, so an arpeggio or a rhythm is shown as it
        goes: each key lights for as long as its note lasts. A low tempo_bpm slows it down
        for practice; `repeat` plays the figure several times in a row; `outline` keeps
        the keys of the whole figure dimly lit while the sounding one is bright. Takes len(steps) * beats_per_step beats; at most
        60 seconds per call. `fingers` colours the keys by finger."""
        return await blocking(ctx, tutor.demo, steps=steps, tempo_bpm=tempo_bpm, beats_per_step=beats_per_step, hand=hand, fingers=fingers,
                              repeat=repeat, outline=outline)

    @server.tool()
    async def rhythm(ctx: Context, action: str = "patterns", pattern: str | None = None, tempo_bpm: float = 90, cycles: int = 2,
                     level: str = "beginner", onsets: list[int] | None = None, pulses: int | None = None, beats: int | None = None) -> str:
        """Rhythm practice with a click; the player taps on any key. action "patterns":
        what there is (even notes, offbeats, Charleston, tresillo, claves, bossa, three
        against two, Indian tala cycles). "calibrate": 20 clicks to tap along to; measures
        how far this player's taps lie from the click on this equipment and takes that away
        from then on. Do it once before the first take. "play": a count-in, then `cycles`
        of `pattern` (or your own: `onsets` out of `pulses` equal parts, `beats` clicks per
        cycle) at `tempo_bpm`; returns how many taps were on it, close, near, off, missed
        or extra for `level` (beginner, intermediate, advanced), whether the player is
        ahead or behind, how steady, and the weakest taps. "status", "reset". Explain the
        pattern and clap or demo it before a take; up to 60 seconds per call."""
        return await blocking(ctx, tutor.rhythm, action=action, pattern=pattern, tempo_bpm=tempo_bpm, cycles=cycles, level=level,
                              onsets=onsets, pulses=pulses, beats=beats)

    @server.tool()
    async def improvise(ctx: Context, changes: list[dict], rule: str = "free", allowed: list[str] | None = None,
                        tempo_bpm: float = 90, backing: str = "chords", count_in: int = 4, choruses: int = 1,
                        lights: bool = True, click: bool = True) -> str:
        """The player improvises while you keep time and listen. `changes`: chord steps with
        their length in beats (a section from library get, or [{"notes": [...], "beats": 4,
        "label": "C7"}]). The server counts in, sounds the `backing` (chords, roots, drone,
        none), lights the notes of the chord that is sounding (root orange), and records
        what is played against which chord. `rule` is what you asked of the player:
        "free"; "only" with `allowed` (notes that may be used, any octave); "chord_tones"
        (only notes of the current chord); "chord_tone_first" (the first note on each chord
        is one of its notes); "guide_tone_first" (it is the third or the seventh). Returns
        per chord what was played, how much of it belonged to the chord, what each chord
        started on, and whether the rule was met. Up to 150 seconds; tell the player the
        task and the tempo first. `lights` false to practise by ear; `click` false for
        no metronome on the beats (the count-in stays). The result also says how the notes
        sat on the beat (`timing`)."""
        return await blocking(ctx, tutor.improvise, changes=changes, rule=rule, allowed=allowed, tempo_bpm=tempo_bpm,
                              backing=backing, count_in=count_in, choruses=choruses, lights=lights, click=click)

    @server.tool()
    async def listen(ctx: Context, max_seconds: float = 20, stop_after_silence: float = 2.0) -> str:
        """Wait for the player to play something from now on. Returns once they have played
        and then paused for `stop_after_silence` seconds, or after `max_seconds` (at most 60):
        the notes in order, which were struck together and what chord that makes. For what
        they have already played, call played instead: it does not wait."""
        return await blocking(ctx, tutor.listen, max_seconds=max_seconds, stop_after_silence=stop_after_silence)

    @server.tool()
    def played(seconds: float | None = None) -> str:
        """What the player has played since you were last told, also while you were talking
        or another tool ran: everything is remembered, nothing is lost by not listening.
        Returns at once: the notes in order, which were struck together and what chord that
        makes, how long ago. Call this whenever the player asks about something they just
        played ("was that right?") instead of asking them to repeat it. `seconds` looks
        back that far instead (at most 600), including what you were already told."""
        return guard(tutor.played, seconds)

    @server.tool()
    async def run_exercise(ctx: Context, steps: list[dict] | None = None, hints: str = "always", hint_delay_s: float = 4.0,
                           exact_keys: bool = False, max_extra: int = 0, timeout_s: float = 45, start_at: int = 1,
                           hand: str = "right", fingers: bool = False, pause_s: float = 12.0) -> str:
        """Practise steps in order; each step waits until the player has played it. Steps as
        in demo: chords, inversions, a progression, or single notes for a melody. `hints`:
        "always" lights the keys of each step, "after_delay" only after `hint_delay_s` or a
        failed try, "never" not at all. Pressed keys turn green (right) or red (wrong).
        Any key that sounds the right note counts unless `exact_keys`. Returns per step:
        result, seconds, attempts, wrong notes. Ends after `timeout_s` (at most 60) at the
        latest: then call again with start_at as returned and no steps to continue.
        Also ends with outcome "player paused" when the player tried a step, let go of all
        keys and then played nothing for `pause_s` seconds (0 = never): the step then lists
        what they played and what was expected, so you can respond instead of waiting.
        Searching for the first key of a step is never taken as a pause."""
        return await blocking(ctx, tutor.run_exercise, steps=steps, hints=hints, hint_delay_s=hint_delay_s, exact_keys=exact_keys,
                              max_extra=max_extra, timeout_s=timeout_s, start_at=start_at, hand=hand, fingers=fingers, pause_s=pause_s)

    @server.tool()
    def stop() -> str:
        """End a running demo, listen or exercise and switch all tutor lights off."""
        return guard(tutor.stop)

    return server


class BearerToken:
    """ASGI wrapper: every HTTP request must carry `Authorization: Bearer <token>`."""

    def __init__(self, app, token: str):
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            given = dict(scope.get("headers") or []).get(b"authorization", b"")
            if not hmac.compare_digest(given, self.expected):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"text/plain"), (b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body", "body": b"missing or wrong bearer token"})
                return
        await self.app(scope, receive, send)


def build_app(tutor: Tutor, host: str, token: str | None, log: CallLog | None = None):
    """The ASGI app: the MCP endpoint at /mcp, behind the token if one is set."""
    local = host in ("127.0.0.1", "localhost", "::1")
    # Host-header checking guards browsers against DNS rebinding on localhost. Clients on
    # the local network address this machine by many names; there the token is the guard.
    security = None if local else TransportSecuritySettings(enable_dns_rebinding_protection=False)
    app = build_server(tutor, log).streamable_http_app(host=host, transport_security=security)
    return BearerToken(app, token) if token else app


def parse_tilt(text: str) -> float:
    if text.strip().lower() == "lumatone":
        return LUMATONE_TILT_DEG
    return float(text)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tutor", description="openxen tutor MCP server")
    p.add_argument("--host", default="127.0.0.1", help="address to listen on; 0.0.0.0 for the local network (needs a token)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--xentool", default="http://127.0.0.1:9098",
                   help="xentool's local API (xentool serve <layout> --api). Several, separated by commas, when more than one "
                        "xentool runs (one per kind of keyboard): the tutor uses the one that has a keyboard connected")
    p.add_argument("--tilt", type=parse_tilt, default=0.0,
                   help="how far the keyfield is turned anticlockwise in front of the player, in degrees; "
                        "'lumatone' for the assembled five-module case (%.1f)" % LUMATONE_TILT_DEG)
    p.add_argument("--fake", type=int, metavar="EDO", help="no keyboard: serve a made-up single module in this tuning")
    p.add_argument("--log", metavar="FILE", help="record of every tool call, its answer and the key presses, one JSON "
                                                 "object per line (default: build/tutor-log/<date>.jsonl in the repository)")
    p.add_argument("--no-log", action="store_true", help="keep no record of tool calls")
    p.add_argument("--player", metavar="FILE", help="the player's measured hand and own fingerings "
                                                    "(default: host/tutor/state/player.json; 'none' keeps them in memory only)")
    args = p.parse_args(argv)

    token = os.environ.get(TOKEN_ENV, "").strip() or None
    if args.host not in ("127.0.0.1", "localhost", "::1") and not token:
        print(f"refusing to listen on {args.host} without a token: set {TOKEN_ENV} first "
              f"(any long random string; the MCP client sends it as a bearer token)", file=sys.stderr)
        return 2
    if args.fake:
        from .sample import sample_setup
        client = FakeXentool(sample_setup(args.fake))
    else:
        urls = [u.strip() for u in args.xentool.split(",") if u.strip()]
        client = Xentool(urls[0]) if len(urls) == 1 else AnyXentool([Xentool(u) for u in urls])
    if (args.player or "").strip().lower() == "none" or (args.fake and not args.player):
        player = Player()
    else:
        player = Player(args.player or Path(__file__).resolve().parent / "state" / "player.json")
    tutor = Tutor(client, tilt_deg=args.tilt, practice=bool(args.fake), player=player)

    log = None
    if not args.no_log:
        path = Path(args.log) if args.log else Path(__file__).resolve().parents[2] / "build" / "tutor-log" / f"{date.today().isoformat()}.jsonl"
        log = CallLog(path)
        log.write("start", host=args.host, port=args.port, tilt_deg=args.tilt,
                  keyboard="made-up module, %d notes per octave" % args.fake if args.fake else args.xentool)
        log.follow_keys(tutor.pump)

    import uvicorn
    print(f"openxen tutor: MCP at http://{args.host}:{args.port}/mcp "
          f"({'bearer token required' if token else 'no token, this machine only'}); "
          f"keyboard from {'a made-up module' if args.fake else args.xentool}; "
          f"{'calls recorded in ' + str(log.path) if log else 'calls not recorded'}", file=sys.stderr)
    uvicorn.run(build_app(tutor, args.host, token, log), host=args.host, port=args.port, log_level="warning")
    return 0
