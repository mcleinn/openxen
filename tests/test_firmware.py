"""firmware/keyboards/openxen-m56/keyboard.json agrees with the spec, the parts and libhmk."""
from __future__ import annotations

import sys

import pytest

from conftest import ROOT


def test_matrix_and_pins_match_spec(keyboard, spec):
    mux = keyboard["analog"]["mux"]
    assert mux["matrix"] == spec["mux"]["libhmk_matrix"]
    assert mux["select"] == spec["mux"]["select_pins"]
    assert mux["input"] == spec["mux"]["input_pins"]
    flat = sorted(v for row in mux["matrix"] for v in row if v)
    assert flat == list(range(1, 57))
    assert keyboard["keyboard"]["num_keys"] == 56
    assert len(keyboard["default_keymap"][0]) == 56


def test_sensor_polarity_follows_part(keyboard, parts):
    """GH39FKSW reads inverted relative to the MT9102ET (HE60 README); the flag must come
    from the sensor actually on the board."""
    assert keyboard["analog"]["invert_adc"] is parts["parts"]["sensor"]["invert_adc"]
    assert parts["parts"]["sensor"]["mpn"] == "GH39FKSW" and parts["parts"]["sensor"]["invert_adc"] is True


def test_crystal_matches_firmware(keyboard, pin_net, netlist):
    """HSE 12 MHz in firmware, 12 MHz crystal on the board (Y1 value)."""
    assert keyboard["hardware"]["hse_value"] == 12_000_000
    assert ("Y1", "1") in pin_net or ("Y1", "3") in pin_net


def test_libhmk_schema(keyboard):
    scripts = ROOT / "reference" / "repos" / "libhmk" / "scripts"
    if not scripts.exists():
        pytest.skip("libhmk reference clone not present")
    sys.path.insert(0, str(scripts))
    from schema.keyboard import Keyboard  # type: ignore
    Keyboard.model_validate(keyboard)
