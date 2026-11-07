"""Datasheet facts the tests check the design against (kept separate from the generators on
purpose: a generator bug must not be able to "agree with itself")."""

# SN74LV4051A (TI SCLS408, pin configuration, D/PW package)
MUX_Y_PIN = {0: "13", 1: "14", 2: "15", 3: "12", 4: "1", 5: "5", 6: "2", 7: "4"}
MUX_COM_PIN = "3"
MUX_SELECT_PIN = {0: "11", 1: "10", 2: "9"}        # A = S0, B = S1, C = S2
MUX_INH_PIN, MUX_VEE_PIN, MUX_GND_PIN, MUX_VCC_PIN = "6", "7", "8", "16"

# Hall sensor SOT-23 (GH39FKSW = MT9102ET pinout): 1 VDD, 2 OUT, 3 GND
SENSOR_PIN = {"VDD": "1", "OUT": "2", "GND": "3"}

# KiCad Device:LED_ARGB pin numbering used on the board: 1 = anode, 2 = R, 3 = G, 4 = B cathode
LED_PIN = {"A": "1", "R": "2", "G": "3", "B": "4"}

# Unit cell, relative to the key centre (mm, y down), bottom side
LED_OFFSET = (0.0, -5.08)
CAP_OFFSET = {"C": (-3.3, 0.0), "CF": (3.3, 0.0)}
GUIDE_HOLES = [(-5.08, 0.0), (5.08, 0.0)]
GUIDE_HOLE_D = 1.75
LED_HOLE_D = 2.1

# Mux placement rule (place_rest.py / build_spec.py)
MUX_DY = 7.0
MUX_CAP_DX = 5.4

# JLCPCB standard capabilities used as hard limits (4-layer, 1 oz)
MIN_TRACK = 0.2           # our own floor (JLC allows 0.09); 0.2 needed at the LED driver's 0.4 mm-pitch QFN
MIN_VIA_DRILL = 0.3
MIN_VIA_D = 0.5
