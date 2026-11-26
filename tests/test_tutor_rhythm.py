"""Rhythm: the judging of taps against the times they were due (pure arithmetic), and the
rhythm tool with a scripted tapper against the click."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
from tutor import rhythm as R  # noqa: E402
from tutor.player import Player  # noqa: E402
from tutor.sample import sample_setup  # noqa: E402
from tutor.session import Tutor, TutorError  # noqa: E402
from tutor.xt import FakeXentool  # noqa: E402


def test_patterns_are_well_formed():
    for name, p in R.PATTERNS.items():
        assert p["onsets"] == sorted(set(p["onsets"])) and all(0 <= o < p["pulses"] for o in p["onsets"]), name
        assert p["pulses"] % p["beats"] == 0 or name in ("bell_12_8", "three_against_two"), name
        assert p["what"] and all(0 <= a < p["beats"] for a in p.get("accents", [])), name
    # the published ones (Wikipedia: clave, tresillo; counted in sixteenths or eighths of a 4/4 bar)
    assert R.PATTERNS["son_clave_3_2"]["onsets"] == [0, 3, 6, 10, 12] and R.PATTERNS["rumba_clave_3_2"]["onsets"] == [0, 3, 7, 10, 12]
    assert R.PATTERNS["tresillo"]["onsets"] == [0, 3, 6] and R.PATTERNS["charleston"]["onsets"] == [0, 3]
    assert R.PATTERNS["teental"]["beats"] == 16 and R.PATTERNS["rupak"]["beats"] == 7 and R.PATTERNS["jhaptal"]["beats"] == 10
    # where the taps are due: tresillo at 120 = 0, 0.75, 1.5 s in each 2-second bar
    assert R.targets(R.PATTERNS["tresillo"], 2, 10.0, 0.5) == [10.0, 10.75, 11.5, 12.0, 12.75, 13.5]


def test_offset_is_the_median_distance_from_the_click():
    clicks = [i * 0.5 for i in range(20)]
    taps = [c - 0.03 + (0.004 if i % 2 else -0.004) for i, c in enumerate(clicks)]
    offset, spread, used = R.offset_from_taps(clicks, taps)
    assert offset == pytest.approx(-0.03, abs=0.005) and spread < 0.01 and used == 16         # the first four clicks are left out
    # a stray tap and a missed click do not move it; too few taps give no answer
    offset, _, _ = R.offset_from_taps(clicks, taps[:12] + [clicks[13] + 0.2] + taps[14:])
    assert offset == pytest.approx(-0.03, abs=0.006)
    assert R.offset_from_taps(clicks, taps[:9]) is None and R.offset_from_taps(clicks[:5], taps[:5]) is None


def test_grading():
    due = [i * 0.5 for i in range(8)]
    exact = R.grade(due, [t + 0.05 for t in due], offset=0.05)
    assert exact["on it"] == 8 and exact["missed"] == exact["extra"] == 0 and exact["mean_ms"] == 0 and exact["tendency"] == "centred"
    # without the offset the same taps look late
    assert R.grade(due, [t + 0.05 for t in due])["tendency"].startswith("behind") and R.grade(due, [t + 0.05 for t in due])["close"] == 8
    # bands: 30 ms is on it for a beginner, close for an intermediate player, close for an advanced one
    assert R.grade(due, [t - 0.03 for t in due])["on it"] == 8 and R.grade(due, [t - 0.03 for t in due])["tendency"].startswith("ahead")
    assert R.grade(due, [t - 0.03 for t in due], level="intermediate")["close"] == 8
    assert R.grade(due, [t + 0.1 for t in due])["near"] == 8 and R.grade(due, [t + 0.2 for t in due])["off"] == 8
    # missed and extra taps
    some = R.grade(due, [due[0], due[1], due[1] + 0.12, due[3]])
    assert some["played"] == 3 and some["missed"] == 5 and some["extra"] == 1 and some["errors_ms"][:4] == [0, 0, None, 0]
    # slowing down shows as drift
    dragging = R.grade(due, [t + 0.02 * i for i, t in enumerate(due)])
    assert "falling behind" in dragging["drift"]
    assert "drift" not in exact


def test_grid_stats():
    onsets = [0.01, 0.26, 0.49, 0.76, 1.02, 1.24]
    stats = R.grid_stats(onsets, 0.25)
    assert stats["notes"] == 6 and abs(stats["mean_ms"]) <= 6 and stats["spread_ms"] < 20 and stats["within_close_percent"] == 100
    assert R.grid_stats([t + 0.1 for t in onsets], 0.25, offset=0.1)["mean_ms"] == stats["mean_ms"]
    assert R.grid_stats(onsets[:3], 0.25) is None


def tap_along(fake, tutor, times):
    """Tap the middle key at these seconds after the first click sounds."""
    key = tutor.keyboard.centre()

    def go():
        while not fake.clicks:
            time.sleep(0.002)
        zero = time.monotonic()
        for at in times:
            time.sleep(max(0.0, zero + at - time.monotonic()))
            fake.press(key.board, key.key)
            fake.release(key.board, key.key)

    threading.Thread(target=go, daemon=True).start()


def test_rhythm_tool_calibrates_and_judges(tmp_path):
    fake = FakeXentool(sample_setup(53, (0, 1)))
    path = tmp_path / "player.json"
    tutor = Tutor(fake, player=Player(path))
    try:
        listed = tutor.rhythm()
        assert "son_clave_3_2" in listed["patterns"] and listed["patterns"]["tresillo"]["taps_per_cycle"] == 3
        assert tutor.rhythm("status")["calibrated"] is False

        beat = 60 / 200
        tap_along(fake, tutor, [i * beat + 0.07 for i in range(20)])            # a player who is 70 ms late
        began = time.monotonic()
        cal = tutor.rhythm("calibrate", tempo_bpm=200)
        assert 5.5 < time.monotonic() - began < 8 and cal["calibrated"] and cal["taps_used"] >= 12
        assert 55 <= cal["offset_ms"] <= 110 and cal["spread_ms"] < 25                # the 70 ms plus what the route adds
        # twenty clicks on the percussion channel, the accented ones louder and on the other wood block
        assert len(fake.clicks) == 20 and {c[0] for c in fake.clicks} == {10} and not fake.sounded
        assert {(c[1], c[2]) for c in fake.clicks} == {(76, 115), (77, 75)}
        assert Player(path).offset_ms == pytest.approx(cal["offset_ms"], abs=1)       # kept for the next session

        # the same lateness is no longer an error: a tresillo played "late by the offset" is on it
        fake.clicks.clear()
        beat = 60 / 150
        tap_along(fake, tutor, [4 * beat + c * 4 * beat + o * beat / 2 + 0.07 for c in range(2) for o in (0, 3, 6)])
        out = tutor.rhythm("play", pattern="tresillo", tempo_bpm=150, cycles=2)
        assert out["due"] == 6 and out["played"] == 6 and out["missed"] == 0 and out["on it"] + out["close"] == 6
        assert abs(out["mean_ms"]) < 35 and out["tendency"] == "centred" and "not_calibrated" not in out
        assert len(fake.clicks) == 4 + 8                                             # the count-in and two bars of clicks

        # half of it left out, one tap too many
        fake.clicks.clear()
        tap_along(fake, tutor, [4 * beat + 0.07, 4 * beat + 3 * beat / 2 + 0.07, 4 * beat + 2.0 * beat + 0.07])
        out = tutor.rhythm("play", pattern="tresillo", tempo_bpm=150, cycles=2)
        assert out["played"] == 2 and out["missed"] == 4 and out["extra"] == 1 and any("missed" in w for w in out["weakest"])

        # an own pattern, and what is refused
        fake.clicks.clear()
        tap_along(fake, tutor, [3 * beat + b * beat + 0.07 for b in range(3)])
        own = tutor.rhythm("play", onsets=[0, 1, 2], pulses=3, beats=3, tempo_bpm=150, cycles=1)
        assert own["pattern"] == "own pattern" and own["played"] == 3 and len(fake.clicks) == 3 + 3
        with pytest.raises(TutorError, match="no pattern"):
            tutor.rhythm("play", pattern="nope")
        with pytest.raises(TutorError, match="own pattern needs"):
            tutor.rhythm("play", onsets=[0, 9], pulses=4, beats=4)
        with pytest.raises(TutorError, match="at most 60 s"):
            tutor.rhythm("play", pattern="teental", tempo_bpm=40, cycles=4)
        with pytest.raises(TutorError, match="level must be"):
            tutor.rhythm("play", pattern="tresillo", level="genius")
        assert tutor.rhythm("reset") == {"calibrated": False} and Player(path).offset_ms is None
    finally:
        tutor.pump.stop()


def test_mridangam_as_the_pulse_and_for_demonstrations():
    from tutor.osc import Sender, encode
    # OSC encoding: address and type tags padded to four bytes, big-endian float
    assert encode("/mridangam/stroke", "Thom", 0.5) == b"/mridangam/stroke\0\0\0,sf\0Thom\0\0\0\0" + bytes.fromhex("3f000000")
    assert encode("/x", 3)[-4:] == bytes.fromhex("00000003")

    fake = FakeXentool(sample_setup(53, (0,)))
    drum = Sender("127.0.0.1", 9)            # the discard port: nothing listens, nothing fails
    tutor = Tutor(fake, mridangam=drum)
    try:
        assert any("mridangam" in s for s in tutor.rhythm()["sounds"])
        # demo: count-in clicks, then the pattern as strokes, the first of each cycle deep
        out = tutor.rhythm("demo", pattern="tresillo", tempo_bpm=200, cycles=2, sound="mridangam")
        assert out["demonstrated"] == "tresillo" and len(fake.clicks) == 4
        strokes = [(m[1], m[2]) for m in drum.sent]
        # the first tap of a cycle deep, taps on a beat "Thi", taps between beats "Ta"
        assert [s for s, _ in strokes] == ["Thom", "Ta", "Thi"] * 2 and strokes[0][1] > strokes[1][1]
        # play: the pulse on the drum, no clicks
        fake.clicks.clear()
        drum.sent.clear()
        played = tutor.rhythm("play", pattern="tresillo", tempo_bpm=200, cycles=1, sound="mridangam")
        assert played["due"] == 3 and not fake.clicks and [m[1] for m in drum.sent] == ["Thom", "Thi", "Thi", "Thi"] * 2
        with pytest.raises(TutorError, match="sound must be"):
            tutor.rhythm("play", pattern="tresillo", sound="bongos")
    finally:
        tutor.pump.stop()
    plain = Tutor(FakeXentool(sample_setup(53, (0,))))
    try:
        assert plain.rhythm()["sounds"] == ["click"]
        with pytest.raises(TutorError, match="no mridangam is set up"):
            plain.rhythm("play", pattern="tresillo", sound="mridangam")
        # a demonstration without a drum: the pattern as clicks
        out = plain.rhythm("demo", pattern="tresillo", tempo_bpm=200, cycles=1)
        assert out["sound"] == "click" and len(plain.client.clicks) == 4 + 3
    finally:
        plain.pump.stop()


def test_an_older_xentool_gets_the_click_as_a_short_high_note():
    class Older(FakeXentool):
        def midi(self, notes):
            from tutor.xt import XentoolError
            raise XentoolError("xentool refused POST /api/midi: 404")

    fake = Older(sample_setup(53, (0,)))
    tutor = Tutor(fake)
    try:
        with pytest.raises(TutorError, match="too few to measure"):
            tutor.rhythm("calibrate", tempo_bpm=200)
        high = tutor.keyboard.range()[1]
        assert len(fake.sounded) == 20 and all(a == (high.board, high.key) and ms == 50 for a, _, ms in fake.sounded)
    finally:
        tutor.pump.stop()


def test_calibration_needs_enough_taps():
    fake = FakeXentool(sample_setup(53, (0,)))
    tutor = Tutor(fake)
    try:
        tap_along(fake, tutor, [0.0, 0.3, 0.6])
        with pytest.raises(TutorError, match="too few to measure"):
            tutor.rhythm("calibrate", tempo_bpm=200)
        assert tutor.player.offset_ms is None
    finally:
        tutor.pump.stop()
