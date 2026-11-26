"""Tutor MCP server (host/tutor/server.py): the tools as an MCP client sees them, progress
from a waiting tool, the bearer token, and that nothing the model reads names internals."""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from pathlib import Path

import anyio
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
pytest.importorskip("mcp.server.mcpserver", reason="the mcp package (>= 2) is not installed")
from mcp.client import Client  # noqa: E402

from tutor import server as tutor_server  # noqa: E402
from tutor.sample import sample_setup  # noqa: E402
from tutor.session import Tutor  # noqa: E402
from tutor.xt import FakeXentool  # noqa: E402

TOOLS = {"keyboard_info", "tuning", "tuning_notes", "harmony", "keys", "theory", "find_shape", "fingering", "fingering_book", "hand", "library", "improvise", "rhythm", "drone", "set_lights", "demo", "listen", "played", "run_exercise", "stop"}
# Words of the machinery below the player's view; "keyboard" is fine, "board 2" is not.
INTERNALS = re.compile(r"\b(board|boards|module index|chan|channel|edo|lattice|midi|hid|usb|address|doubled)\b", re.I)


@pytest.fixture()
def fake():
    return FakeXentool(sample_setup(31, (0, 1, 2, 3)))


@pytest.fixture()
def tutor(fake):
    t = Tutor(fake)
    yield t
    t.pump.stop()


def call(tutor: Tutor, name: str, args: dict | None = None, progress=None):
    """One tool call through an MCP client connected to the server in memory."""
    async def go():
        async with Client(tutor_server.build_server(tutor)) as client:
            return await client.call_tool(name, args or {}, progress_callback=progress)
    return anyio.run(go)


def text(result) -> str:
    return result.content[0].text


def test_tools_and_their_descriptions(tutor):
    async def go():
        async with Client(tutor_server.build_server(tutor)) as client:
            return await client.list_tools(), client.instructions
    listed, instructions = anyio.run(go)
    tools = {t.name: t for t in listed.tools}
    assert set(tools) == TOOLS
    assert "keyboard_info first" in instructions
    for name, tool in tools.items():
        assert tool.description and len(tool.description) > 60, name
        schema = json.dumps(tool.input_schema if hasattr(tool, "input_schema") else tool.inputSchema)
        for where, words in (("description", tool.description), ("schema", schema)):
            assert not INTERNALS.search(words), f"{name} {where}: {INTERNALS.search(words).group(0)}"
    assert not INTERNALS.search(instructions)


def test_results_are_compact_json(tutor):
    result = call(tutor, "theory", {"op": "chord", "root": "C", "quality": "minor"})
    assert not result.is_error
    raw = text(result)
    assert "\n" not in raw and ": " not in raw.split('"tuning"')[0]
    assert json.loads(raw)["notes"] == ["C4 (0)", "Eb4 (8)", "G4 (18)"]
    # the key map comes after the JSON as plain lines
    info = text(call(tutor, "keyboard_info"))
    head, _, key_map = info.partition("\n\nmap:\n")
    data = json.loads(head)
    assert data["keys"] == 224 and "map" not in data
    assert "C4" in key_map.split() and "the same keys by number:" in key_map
    assert len(key_map.splitlines()) == 17 + 2 + 17
    assert "map:" not in text(call(tutor, "keyboard_info", {"include_map": False}))


def test_no_internals_in_any_result(tutor, fake):
    first = json.loads(text(call(tutor, "keys", {"note": "C4"})))["keys"][0]["key"]
    outputs = [
        text(call(tutor, "keyboard_info")),
        text(call(tutor, "keys", {"key": first})),
        text(call(tutor, "theory", {"op": "tuning"})),
        text(call(tutor, "theory", {"op": "scale", "root": "D", "mode": "dorian"})),
        text(call(tutor, "find_shape", {"root": "C4", "quality": "dominant7"})),
        text(call(tutor, "set_lights", {"lights": [{"key": first, "role": "root"}]})),
        text(call(tutor, "demo", {"steps": [{"chord": "C4 major"}], "tempo_bpm": 240, "beats_per_step": 0.2})),
        text(call(tutor, "listen", {"max_seconds": 1, "stop_after_silence": 0.2})),
        text(call(tutor, "run_exercise", {"steps": [{"note": "C4"}], "timeout_s": 1})),
        text(call(tutor, "stop")),
        text(call(tutor, "harmony", {"action": "neighbours", "chord": "C harmonic7", "limit": 4})),
        text(call(tutor, "harmony", {"action": "path", "chord": "C major", "via": "xen", "max_cents": 150, "seed": 1})),
        text(call(tutor, "harmony", {"action": "xen"})),
        text(call(tutor, "harmony", {"action": "xen", "name": "orwell-functions", "key": "D"})),
    ]
    assert json.loads(outputs[-4])["neighbours"][0]["label"] == "C dominant7" and len(json.loads(outputs[-3])["steps"]) == 5
    for out in outputs:
        assert not INTERNALS.search(out), f"{INTERNALS.search(out).group(0)!r} in: {out[:200]}"
        assert '"pitch"' not in out and '"x"' not in out


def test_errors_come_back_as_tool_errors_with_advice(tutor):
    result = call(tutor, "keys", {"key": "k999"})
    assert result.is_error and "look the note up with the keys tool" in text(result)
    result = call(tutor, "theory", {"op": "chord", "root": "C", "quality": "wobbly"})
    assert result.is_error and "Available: major, minor" in text(result)
    result = call(tutor, "run_exercise", {"steps": []})
    assert result.is_error and "steps is empty" in text(result)


def test_practice_mode_says_no_real_keyboard_is_attached(fake):
    """`python -m tutor --fake`: the model must learn that nobody sees lights or presses keys."""
    practice = Tutor(fake, practice=True)
    try:
        async def go():
            async with Client(tutor_server.build_server(practice)) as client:
                return client.instructions
        instructions = anyio.run(go)
        assert "Practice mode: no real keyboard is attached" in instructions
        assert not INTERNALS.search(instructions)

        info = text(call(practice, "keyboard_info"))
        assert info.startswith('{"practice_mode":"Practice mode: no real keyboard is attached')
        # lookups still work
        assert json.loads(text(call(practice, "theory", {"op": "chord", "root": "C"})))["notes"][0] == "C4 (0)"
        first = json.loads(text(call(practice, "keys", {"note": "C4"})))["keys"][0]["key"]
        lit = json.loads(text(call(practice, "set_lights", {"lights": [{"key": first}]})))
        assert lit["count"] == 1 and "sees none of these lights" in lit["practice_mode"]

        # the tools that wait for the player answer at once instead of running out the clock
        waiting = {"demo": {"steps": [{"chord": "C4 major"}]}, "listen": {"max_seconds": 30},
                   "run_exercise": {"steps": [{"note": "C4"}], "timeout_s": 30}}
        for name, args in waiting.items():
            began = time.monotonic()
            result = call(practice, name, args)
            assert result.is_error and f"{name} needs the real keyboard" in text(result), name
            assert time.monotonic() - began < 2, name
            assert not INTERNALS.search(text(result))
        assert not call(practice, "stop").is_error
    finally:
        practice.pump.stop()


def test_call_log_records_queries_answers_and_key_presses(tutor, fake, tmp_path):
    """For reproducing a lesson: what the model asked, exactly what it was told, what was played."""
    from tutor.calllog import CallLog

    log = CallLog(tmp_path / "log" / "calls.jsonl")
    log.write("start", keyboard="test")
    log.follow_keys(tutor.pump)

    def logged(name, args=None):
        async def go():
            async with Client(tutor_server.build_server(tutor, log)) as client:
                return await client.call_tool(name, args or {})
        return anyio.run(go)

    chord = logged("theory", {"op": "chord", "root": "C", "quality": "minor"})
    bad = logged("keys", {"key": "k999"})
    c4 = fake.setup()["keys"][0]
    time.sleep(0.3)             # the event pump has taken its starting point
    fake.press(c4["board"], c4["key"])
    heard = logged("listen", {"max_seconds": 5, "stop_after_silence": 0.3})
    log.close()

    records = [json.loads(line) for line in (tmp_path / "log" / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert records[0]["kind"] == "start" and all("t" in r for r in records)
    calls = [r for r in records if r["kind"] == "call"]
    results = {r["id"]: r for r in records if r["kind"] == "result"}
    assert [c["tool"] for c in calls] == ["theory", "keys", "listen"]
    assert [c["id"] for c in calls] == sorted(results)
    # arguments by name, as the model gave them (defaults filled in by the server included)
    assert calls[0]["args"]["op"] == "chord" and calls[0]["args"]["quality"] == "minor"
    assert "progress" not in calls[2]["args"]
    # the answer is word for word what the model received
    assert results[calls[0]["id"]]["ok"] and results[calls[0]["id"]]["text"] == text(chord)
    assert not results[calls[1]["id"]]["ok"] and results[calls[1]["id"]]["text"] in text(bad)
    assert results[calls[2]["id"]]["text"] == text(heard) and results[calls[2]["id"]]["ms"] >= 300
    # a call is written before its tool runs, so a tool that hangs still shows
    order = [(r["kind"], r.get("id")) for r in records]
    assert order.index(("call", calls[2]["id"])) < order.index(("result", calls[2]["id"]))
    keys = [r for r in records if r["kind"] == "key"]
    assert keys and keys[0]["event"] == "on" and keys[0]["key"] == c4["key"]


def test_logging_does_not_wait_for_the_disk(tmp_path):
    from tutor.calllog import CallLog

    log = CallLog(tmp_path / "calls.jsonl")
    began = time.perf_counter()
    for i in range(2000):
        log.result(log.call("keys", {"note": "C4"}), "keys", 0.001, True, "x" * 2000)
    per_call = (time.perf_counter() - began) / 2000
    log.close()
    assert per_call < 0.0005, f"{per_call * 1e6:.0f} us per call"
    assert len((tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines()) == 4000


def _addresses(tutor, names):
    """xentool addresses of the first key for each note name."""
    kb = tutor.keyboard
    out = []
    for name in names:
        key = kb.keys[json.loads(text(call(tutor, "keys", {"note": name})))["keys"][0]["key"]]
        out.append((key.board, key.key))
    return out


def test_everything_played_is_remembered_until_the_model_asks(tutor, fake):
    """The player does not wait for the model: what they play while no tool is listening
    is kept, announced in the next result and handed over by `played`."""
    c, e, g, d = _addresses(tutor, ["C4", "E4", "G4", "D4"])
    assert json.loads(text(call(tutor, "played")))["played"] == []
    time.sleep(0.3)

    # a chord, then a single note, while the model is busy with something else
    for a in (c, e, g):
        fake.press(*a)
    time.sleep(0.25)
    for a in (c, e, g):
        fake.release(*a)
    time.sleep(0.25)
    fake.press(*d)
    time.sleep(0.2)

    # any other tool result says that something was played
    other = json.loads(text(call(tutor, "theory", {"op": "chord", "root": "C"})))
    assert other["unheard"].startswith("the player has played 4 notes") and "call played" in other["unheard"]

    began = time.monotonic()
    heard = json.loads(text(call(tutor, "played")))
    assert time.monotonic() - began < 1.5, "played does not wait"
    assert heard["note_count"] == 4 and len(heard["played"]) == 2
    chord, single = heard["played"]
    assert [k["note"] for k in chord["keys"]] == ["C4", "E4", "G4"] and "major" in chord["together"].lower()
    assert [k["note"] for k in single["keys"]] == ["D4"] and all("number" in k for k in single["keys"])
    assert single["at_s"] >= 0.4 and heard["last_note_s_ago"] < 3
    assert [k["note"] for k in heard["still_held"]] == ["D4"]

    # told once: the next result carries no reminder and played starts afresh
    assert "unheard" not in json.loads(text(call(tutor, "theory", {"op": "chord", "root": "C"})))
    assert json.loads(text(call(tutor, "played")))["played"] == []
    # but it can still be looked up by time
    again = json.loads(text(call(tutor, "played", {"seconds": 30})))
    assert again["note_count"] == 4
    assert call(tutor, "played", {"seconds": 5000}).is_error
    fake.release(*d)


def test_listen_and_exercises_count_as_told(tutor, fake):
    (c,) = _addresses(tutor, ["C4"])
    time.sleep(0.3)

    def player():
        time.sleep(0.4)
        fake.press(*c)
        time.sleep(0.1)
        fake.release(*c)

    threading.Thread(target=player, daemon=True).start()
    result = json.loads(text(call(tutor, "run_exercise", {"steps": [{"note": "C4"}], "timeout_s": 5})))
    assert result["steps"][0]["result"] == "ok"
    assert tutor.unheard() == 0
    assert json.loads(text(call(tutor, "played")))["played"] == []


def test_fingering_tool_fingers_a_phrase(tutor):
    steps = [{"chord": "C4 major"}, {"chord": "F4 major"}, {"chord": "G4 major"}, {"note": "E4"}, {"note": "F4"}, {"note": "G4"}]
    raw = text(call(tutor, "fingering", {"steps": steps}))
    assert not INTERNALS.search(raw) and '"pitch"' not in raw
    out = json.loads(raw)
    assert out["hand"] == "right" and out["playing"].startswith("legato") and len(out["steps"]) == 6
    for step in out["steps"]:
        fingers = [k["finger"] for k in step["keys"]]
        assert len(set(fingers)) == len(fingers) and step["fingering"]["fingers"] == "-".join(map(str, fingers))
        assert all({"note", "number", "key"} <= set(k) for k in step["keys"])
    # one hand shape, one fingering, on every root (before a melody a chord may prepare for it)
    chords = json.loads(text(call(tutor, "fingering", {"steps": steps[:3]})))
    assert len({s["fingering"]["fingers"] for s in chords["steps"]}) == 1
    # the melody moves from finger to finger
    melody = [s["keys"][0]["finger"] for s in out["steps"][3:]]
    assert len(set(melody)) == 3
    assert "starting point" in out["fingers"] and any("by_itself_also" in s for s in out["steps"])
    detached = json.loads(text(call(tutor, "fingering", {"steps": steps, "legato": False, "hand": "left"})))
    assert detached["playing"] == "detached" and detached["hand"] == "left"
    assert call(tutor, "fingering", {"steps": steps, "hand": "both"}).is_error


def test_exercise_returns_when_the_player_tried_and_then_paused(tutor, fake):
    """The player plays a wrong chord, lets go and waits: the tutor must hear about it
    instead of sitting out the time limit. Searching before the first key is no pause."""
    c, f, g = _addresses(tutor, ["C4", "F4", "G4"])
    time.sleep(0.3)

    def player():
        time.sleep(1.5)                 # looking for the keys: longer than pause_s, and no pause
        for a in (c, f, g):
            fake.press(*a)
        time.sleep(0.2)
        for a in (c, f, g):
            fake.release(*a)

    threading.Thread(target=player, daemon=True).start()
    began = time.monotonic()
    out = json.loads(text(call(tutor, "run_exercise", {"steps": [{"chord": "C4 major"}, {"chord": "F4 major"}],
                                                        "timeout_s": 20, "pause_s": 1.0})))
    took = time.monotonic() - began
    assert out["outcome"] == "player paused" and 2.5 < took < 6, took
    step = out["steps"][0]
    assert step["result"] == "tried, then paused"
    assert [n.split()[0] for n in step["played"]] == ["C4", "F4", "G4"]
    assert [n.split()[0] for n in step["expected"]] == ["C4", "E4", "G4"]
    assert step["wrong_notes"][0].startswith("F4")
    assert "Do not wait" in out["what_now"] and "start_at=1" in out["continue_with"]
    assert out["steps"][1]["result"] == "not reached"

    # keys still held are not a pause, and pause_s 0 switches it off
    def holder():
        time.sleep(0.3)
        fake.press(*c)
        time.sleep(2.0)
        fake.release(*c)

    threading.Thread(target=holder, daemon=True).start()
    out = json.loads(text(call(tutor, "run_exercise", {"steps": [{"chord": "C4 major"}], "timeout_s": 2, "pause_s": 1.0})))
    assert out["outcome"] == "time limit"
    threading.Thread(target=lambda: (time.sleep(0.2), fake.press(*f), time.sleep(0.1), fake.release(*f)), daemon=True).start()
    out = json.loads(text(call(tutor, "run_exercise", {"steps": [{"chord": "C4 major"}], "timeout_s": 2, "pause_s": 0})))
    assert out["outcome"] == "time limit"


def test_the_tuning_can_be_switched_and_everything_follows(tutor, fake):
    listed = json.loads(text(call(tutor, "tuning")))
    assert listed["current"]["notes_per_octave"] == 31
    assert {a["notes_per_octave"] for a in listed["available"]} >= {12, 19, 31, 53}
    assert not INTERNALS.search(text(call(tutor, "tuning")))

    # something is lit and something was played in the old tuning
    first = json.loads(text(call(tutor, "keys", {"note": "C4"})))["keys"][0]["key"]
    call(tutor, "set_lights", {"lights": [{"key": first}]})
    (c,) = _addresses(tutor, ["C4"])
    time.sleep(0.3)
    fake.press(*c)
    fake.release(*c)
    time.sleep(0.2)
    assert tutor.unheard() == 1 and fake.overlay_state
    assert json.loads(text(call(tutor, "theory", {"op": "chord", "root": "C"})))["notes"] == ["C4 (0)", "E4 (10)", "G4 (18)"]

    raw = text(call(tutor, "tuning", {"to": "53"}))
    head = json.loads(raw.partition("\n\nmap:\n")[0])
    assert head["switched_to"].startswith("53") and head["switched_from"] == listed["current"]["layout"]
    assert head["tuning"] == "53 equal steps per octave" and "To go back" in head["note"]
    assert "the same keys by number:" in raw and not INTERNALS.search(raw)
    # the keyboard, the theory and the fingering are those of the new tuning
    assert json.loads(text(call(tutor, "theory", {"op": "chord", "root": "C"})))["notes"] == ["C4 (0)", "vE4 (17)", "G4 (31)"]
    shape = json.loads(text(call(tutor, "find_shape", {"root": "C4"})))["ways"][0]
    assert [k["number"] for k in shape["keys"]] == [0, 17, 31] and "fingers" in shape["fingering"]
    # lights off, and what was played in the old tuning is forgotten
    assert not fake.overlay_state and tutor.unheard() == 0
    assert json.loads(text(call(tutor, "played")))["played"] == []

    # by name, back again; switching to the current tuning changes nothing
    back = json.loads(text(call(tutor, "tuning", {"to": head["switched_from"], "include_map": False})))
    assert back["tuning"] == "31 equal steps per octave"
    assert "already" in json.loads(text(call(tutor, "tuning", {"to": "31"})))
    bad = call(tutor, "tuning", {"to": "72"})
    assert bad.is_error and "Available (name, notes per octave)" in text(bad) and "53" in text(bad)

    # not in the middle of an exercise
    running = threading.Thread(target=lambda: call(tutor, "run_exercise", {"steps": [{"note": "C4"}], "timeout_s": 3, "pause_s": 0}), daemon=True)
    running.start()
    time.sleep(1.0)
    busy = call(tutor, "tuning", {"to": "53"})
    assert busy.is_error and "still running" in text(busy)
    call(tutor, "stop")
    running.join(timeout=10)


def test_the_players_own_fingering_takes_precedence_and_is_kept(fake, tmp_path):
    from tutor.player import Player

    path = tmp_path / "state" / "player.json"
    tutor = Tutor(fake, player=Player(path))
    try:
        way = json.loads(text(call(tutor, "find_shape", {"root": "C4", "limit": 1})))["ways"][0]
        computed = way["fingering"]["fingers"]
        mine = [1, 3, 5] if computed != "1-3-5" else [1, 2, 4]
        assert json.loads(text(call(tutor, "fingering_book")))["own_fingerings"] == []

        saved = json.loads(text(call(tutor, "fingering_book", {"action": "save", "root": "C4", "fingers": mine})))
        assert saved["saved"]["for"] == "major" and saved["saved"]["fingers"] == "-".join(map(str, mine))
        # first in find_shape, marked as theirs, with the computed one still offered
        way = json.loads(text(call(tutor, "find_shape", {"root": "C4", "limit": 1})))["ways"][0]
        assert [k["finger"] for k in way["keys"]] == mine and "yours" in way["fingering"]
        assert computed in [o["fingers"] for o in way["other_fingerings"]]
        # the same hand shape on another root, and inside a phrase
        assert [k["finger"] for k in json.loads(text(call(tutor, "find_shape", {"root": "F4", "limit": 1})))["ways"][0]["keys"]] == mine
        steps = json.loads(text(call(tutor, "fingering", {"steps": [{"chord": "C4 major"}, {"chord": "G4 major"}]})))["steps"]
        assert all([k["finger"] for k in s["keys"]] == mine and "yours" in s["fingering"] for s in steps)
        # another quality is not affected
        minor = json.loads(text(call(tutor, "find_shape", {"root": "C4", "quality": "minor", "limit": 1})))["ways"][0]
        assert "yours" not in minor["fingering"]
        assert json.loads(text(call(tutor, "fingering_book")))["own_fingerings"] == [
            {"hand": "right", "for": "major", "fingers": "-".join(map(str, mine)), "keys": 3}]
        # nonsense is refused with what to give
        bad = call(tutor, "fingering_book", {"action": "save", "root": "C4", "fingers": [1, 1, 2]})
        assert bad.is_error and "none twice" in text(bad)
    finally:
        tutor.pump.stop()

    # kept between sessions
    again = Tutor(fake, player=Player(path))
    try:
        assert [k["finger"] for k in json.loads(text(call(again, "find_shape", {"root": "C4", "limit": 1})))["ways"][0]["keys"]] == mine
        assert json.loads(text(call(again, "fingering_book", {"action": "forget", "root": "C4"})))["forgotten"]
        assert "yours" not in json.loads(text(call(again, "find_shape", {"root": "C4", "limit": 1})))["ways"][0]["fingering"]
    finally:
        again.pump.stop()


def test_the_hand_is_measured_on_the_keys(fake, tmp_path):
    from tutor import fingering as F
    from tutor.player import Player

    tutor = Tutor(fake, player=Player(tmp_path / "player.json"))
    try:
        kb = tutor.keyboard
        assert "average hand" in json.loads(text(call(tutor, "hand")))["measured"]

        # five keys under a relaxed right hand: the thumb on a nearer row to the left
        start = kb.keys[json.loads(text(call(tutor, "keys", {"note": "C4"})))["keys"][0]["key"]]
        thumb = kb.neighbours(kb.neighbours(start)["lower_left"])["lower_left"]
        fingers = [start]
        for _ in range(3):
            fingers.append(kb.neighbours(fingers[-1])["right"])
        print_keys = [thumb] + fingers
        assert all(print_keys)

        def lay(keys, after=0.3):
            def go():
                time.sleep(after)
                for k in keys:
                    fake.press(k.board, k.key)
            threading.Thread(target=go, daemon=True).start()

        lay(print_keys)
        out = json.loads(text(call(tutor, "hand", {"action": "rest", "wait_s": 10})))
        assert out["done"] == "rest" and "resting hand" in out["measured"] and "nearer than" in out["resting_thumb"]
        rest = dict(tutor.hand_model.rest)
        assert rest[3] == (0.0, 0.0) and rest[1][1] < -25 and rest[1][0] < rest[2][0] < 0 < rest[4][0] < rest[5][0]
        assert rest[4][0] == pytest.approx(19.2, abs=0.2)
        for k in print_keys:
            fake.release(k.board, k.key)

        # a stretch: two keys held; the practical limit follows the measurement
        far = fingers[0]
        for _ in range(9):
            far = kb.neighbours(far)["right"]
        lay([fingers[0], far])
        out = json.loads(text(call(tutor, "hand", {"action": "stretch", "fingers": [1, 5], "wait_s": 10})))
        assert out["thumb_to_little_finger_mm"] == round(9 * 19.2)
        assert tutor.hand_model.span(1, 5)[5] == pytest.approx(9 * 19.2 * F.SPAN_TO_PRACTICAL, rel=0.01)
        assert tutor.hand_model.span(3, 4) == F.default_hand().span(3, 4)
        fake.release(fingers[0].board, fingers[0].key)
        fake.release(far.board, far.key)

        # not five keys: says so instead of guessing
        lay(print_keys[:3])
        short = call(tutor, "hand", {"action": "rest", "wait_s": 3})
        assert short.is_error and "3 are held now" in text(short)
        assert call(tutor, "hand", {"action": "stretch", "fingers": [3, 4]}).is_error
        assert json.loads(text(call(tutor, "hand", {"action": "reset"})))["measured"].startswith("nothing yet")
        assert dict(tutor.hand_model.rest) == dict(F.default_hand().rest)
    finally:
        tutor.pump.stop()


def test_a_chord_comes_with_its_root_and_the_finger_colours(tutor, fake):
    """What the teacher must be able to say when a chord is new: the root, and each finger by its light."""
    out = json.loads(text(call(tutor, "find_shape", {"root": "F4", "quality": "major", "inversion": 1, "limit": 1})))
    keys = out["ways"][0]["keys"]
    assert out["root"].startswith("F") and "root" in out["say"]
    assert [k.get("role") for k in keys] == [None, None, "root"]          # first inversion: the root is on top
    colours = {1: "white", 2: "yellow", 3: "green", 4: "cyan", 5: "magenta"}
    assert all(k["finger_light"] == colours[k["finger"]] for k in keys)
    demo = json.loads(text(call(tutor, "demo", {"steps": [{"chord": "C4 major"}], "tempo_bpm": 240, "beats_per_step": 0.5})))
    assert demo["played"][0]["keys"][0]["role"] == "root" and "orange" in demo["lights"] and "say" in demo
    root = tutor.keyboard.key(demo["played"][0]["keys"][0]["key"])
    assert ((root.board, root.key), (255, 140, 0)) in fake.seen
    lit = json.loads(text(call(tutor, "demo", {"steps": [{"chord": "C4 major"}], "tempo_bpm": 240, "beats_per_step": 0.5, "fingers": True})))
    assert "finger_light" in lit["lights"]
    # single notes have no root and need no such reminder
    assert "say" not in json.loads(text(call(tutor, "demo", {"steps": [{"note": "C4"}], "tempo_bpm": 240, "beats_per_step": 0.5})))


def test_library_tool_names_no_internals(tutor):
    outputs = [text(call(tutor, "library")),
               text(call(tutor, "library", {"action": "raga", "name": "Yaman", "root": "C4"})),
               text(call(tutor, "library", {"action": "pattern", "name": "threes", "root": "C4", "scale": "major"})),
               text(call(tutor, "library", {"action": "search", "tradition": "chant", "level": 1, "limit": 2}))]
    for out in outputs:
        assert not INTERNALS.search(out), f"{INTERNALS.search(out).group(0)!r} in: {out[:200]}"
    assert call(tutor, "library", {"action": "nope"}).is_error


def test_a_real_keyboard_is_not_called_practice(tutor):
    assert "practice_mode" not in text(call(tutor, "keyboard_info"))
    async def go():
        async with Client(tutor_server.build_server(tutor)) as client:
            return client.instructions
    assert "Practice mode" not in anyio.run(go)


def test_exercise_over_mcp_reports_progress(tutor, fake):
    shape = json.loads(text(call(tutor, "find_shape", {"root": "C4", "quality": "major", "limit": 1})))
    c = [tutor.keyboard.key(k["key"]) for k in shape["ways"][0]["keys"]]
    e4 = c[1]

    def player():
        time.sleep(0.4)
        for k in c:
            fake.press(k.board, k.key)
        time.sleep(0.2)
        for k in c:
            fake.release(k.board, k.key)
        time.sleep(0.2)
        fake.press(e4.board, e4.key)
        fake.release(e4.board, e4.key)

    seen = []

    async def progress(done, total, message):
        seen.append((done, total, message))

    threading.Thread(target=player, daemon=True).start()
    result = call(tutor, "run_exercise", {"steps": [{"chord": "C4 major"}, {"note": "E4"}], "timeout_s": 15}, progress)
    out = json.loads(text(result))
    assert out["outcome"] == "finished" and out["completed"] == "2 of 2 steps"
    assert seen == [(1, 2, "C major: done"), (2, 2, "E4: done")]
    assert fake.overlay_state == {}


def run_asgi(app, headers: list[tuple[bytes, bytes]]) -> tuple[int, bytes]:
    """One GET through an ASGI app; returns (status, body)."""
    sent = []

    async def go():
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        await app({"type": "http", "method": "GET", "path": "/mcp", "headers": headers}, receive, send)

    anyio.run(go)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    return status, b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")


def test_bearer_token_guards_every_request():
    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"through"})

    app = tutor_server.BearerToken(inner, "s3cret-token")
    assert run_asgi(app, [(b"authorization", b"Bearer s3cret-token")]) == (200, b"through")
    for headers in ([], [(b"authorization", b"Bearer wrong")], [(b"authorization", b"s3cret-token")], [(b"authorization", b"Bearer s3cret-token ")]):
        status, body = run_asgi(app, headers)
        assert status == 401 and b"through" not in body


def test_app_is_wrapped_only_when_a_token_is_set(tutor):
    assert isinstance(tutor_server.build_app(tutor, "0.0.0.0", "tok"), tutor_server.BearerToken)
    assert not isinstance(tutor_server.build_app(tutor, "127.0.0.1", None), tutor_server.BearerToken)


def test_will_not_listen_on_the_network_without_a_token(monkeypatch, capsys):
    monkeypatch.delenv(tutor_server.TOKEN_ENV, raising=False)
    assert tutor_server.main(["--host", "0.0.0.0", "--fake", "31"]) == 2
    assert tutor_server.TOKEN_ENV in capsys.readouterr().err
    monkeypatch.setenv(tutor_server.TOKEN_ENV, "   ")
    assert tutor_server.main(["--host", "192.168.1.20", "--fake", "31"]) == 2


def test_tilt_option():
    assert tutor_server.parse_tilt("lumatone") == pytest.approx(16.1, abs=0.05)
    assert tutor_server.parse_tilt("-5.5") == -5.5
