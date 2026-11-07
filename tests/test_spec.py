"""layout/module.json: key field, mux groups and LED matrix are complete and consistent."""
from __future__ import annotations

import math

import pytest

from facts import MUX_CAP_DX, MUX_DY


def inside(poly, x, y) -> bool:
    c = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def test_keys_complete_and_on_grid(spec):
    ids = sorted(k["id"] for k in spec["keys"])
    assert ids == list(range(56))
    for k in spec["keys"]:
        assert abs(k["x"] / 9.6 - round(k["x"] / 9.6)) < 1e-6 and abs(k["y"] / 19.2 - 0.5 - round(k["y"] / 19.2 - 0.5)) < 1e-6
        assert inside(spec["outline"]["vertices"], k["x"], k["y"])
    pos = {(k["x"], k["y"]) for k in spec["keys"]}
    assert len(pos) == 56


def test_keys_clear_of_mounting_holes(spec):
    """No M3 hole (r 1.6) under a switch: the 14 mm plate cutout / housing square must clear
    the hole by >= 0.5 mm (freexen's holes sit 9.6 mm from the nearest key centre -> 1.0 mm)."""
    for h in spec["holes"]:
        for k in spec["keys"]:
            dx, dy = abs(k["x"] - h["x"]), abs(k["y"] - h["y"])
            assert not (dx < 7.0 + h["d"] / 2 + 0.5 and dy < 7.0 + h["d"] / 2 + 0.5), (k["id"], h)


def test_mux_groups_partition_keys(spec, keys):
    groups = spec["mux"]["groups"]
    assert [g["index"] for g in groups] == list(range(7))
    seen = []
    for g in groups:
        assert len(g["keys"]) == 8                       # index in the list = channel
        for ch, kid in enumerate(g["keys"]):
            assert keys[kid]["mux"] == g["index"] and keys[kid]["mux_channel"] == ch
        seen += g["keys"]
    assert sorted(seen) == list(range(56))


def test_libhmk_matrix_matches_groups(spec):
    m = spec["mux"]["libhmk_matrix"]
    assert len(m) == 8 and all(len(r) == 7 for r in m)
    for g in spec["mux"]["groups"]:
        for ch, kid in enumerate(g["keys"]):
            assert m[ch][g["index"]] == kid + 1


def test_mux_channels_follow_pin_columns(spec, keys):
    """Left pin column (Y4..Y7) serves the left keys, ordered like the pins top to bottom
    (Y5, Y7, Y6, Y4); right column (Y0..Y3) the right keys (Y3, Y0, Y1, Y2). Fan-in tracks
    then never have to cross at the mux."""
    for g in spec["mux"]["groups"]:
        ks = {ch: keys[kid] for ch, kid in enumerate(g["keys"])}
        left = [ks[c] for c in (5, 7, 6, 4)]
        right = [ks[c] for c in (3, 0, 1, 2)]
        assert max(k["x"] for k in left) <= min(k["x"] for k in right), g["index"]
        for side in (left, right):
            assert [k["y"] for k in side] == sorted(k["y"] for k in side), g["index"]


def test_mux_groups_are_compact(spec, keys):
    for g in spec["mux"]["groups"]:
        mx, my = g["pos"]
        far = max(math.hypot(keys[k]["x"] - mx, keys[k]["y"] - my) for k in g["keys"])
        assert far < 40.0, (g["index"], far)


def test_mux_positions_free(spec, keys):
    """Mux body (+-3.7 x +-2.7) and its cap must sit inside the board, outside every key cell
    and away from mounting holes and the controller / LED driver strips."""
    poly = spec["outline"]["vertices"]
    for g in spec["mux"]["groups"]:
        mx, my = g["pos"]
        host = keys[g["host_key"]]
        assert g["host_key"] in g["keys"]
        assert (mx, my) == (host["x"], pytest.approx(host["y"] + MUX_DY))
        corners = [(mx + dx, my + dy) for dx in (-3.7, MUX_CAP_DX + 0.6) for dy in (-2.7, 2.7)]
        assert all(inside(poly, x, y) for x, y in corners), g["index"]
        for k in spec["keys"]:                           # cell zone: x +-6.3, y -6.6..+1.9
            for x, y in corners + [(mx, my)]:
                assert not (abs(x - k["x"]) < 6.3 and -6.6 < y - k["y"] < 1.9), (g["index"], k["id"])
        for h in spec["holes"]:
            assert math.hypot(mx - h["x"], my - h["y"]) > 6.0
        for z in spec["controller_zones"]:
            assert not (z["x0"] - 4 < mx < z["x1"] + 4 and z["y0"] - 3 < my < z["y1"] + 3), (g["index"], z["name"])


def test_led_matrix(spec, keys):
    L = spec["led"]
    assert L["driver"] == "IS31FL3733"
    pairs = {(L["key_group"][str(k)], L["key_cs"][str(k)]) for k in keys}
    assert len(pairs) == 56                               # every LED has its own (cathode group, anode line)
    assert sorted({g for g, _ in pairs}) == [0, 1, 2, 3]
    assert sorted({c for _, c in pairs}) == list(range(14)) and L["cs_used"] == 14
    sw = [L["sw_lines"][str(g)][c] for g in range(4) for c in "RGB"]
    assert sorted(sw) == list(range(12))
    # groups are vertical stripes of three key columns around x_m = 19.2 + 28.8 g
    for k in keys.values():
        g = L["key_group"][str(k["id"])]
        assert abs(k["x"] - (19.2 + 28.8 * g)) <= 9.6 + 1e-6, k["id"]
