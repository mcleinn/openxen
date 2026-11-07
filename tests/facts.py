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

# IS31FL3733 QFN-48 (Lumissil rev. G, "Pin configuration", p. 3): pin number -> datasheet name.
# The KiCad symbol calls pin 35 RSET (datasheet R_EXT); pin 49 is the exposed thermal pad.
IS31FL3733_PIN = {
    1: "NC", 2: "SW1", 3: "SW2", 4: "SW3", 5: "PGND", 6: "SW4", 7: "SW5", 8: "SW6", 9: "SW7",
    10: "SW8", 11: "SW9", 12: "PGND", 13: "SW10", 14: "SW11", 15: "SW12",
    16: "CS1", 17: "CS2", 18: "CS3", 19: "CS4", 20: "PVCC", 21: "CS5", 22: "CS6", 23: "CS7",
    24: "CS8", 25: "CS9", 26: "CS10", 27: "CS11", 28: "CS12", 29: "PVCC", 30: "CS13", 31: "CS14",
    32: "CS15", 33: "CS16", 34: "AGND", 35: "R_EXT", 36: "NC", 37: "AVCC", 38: "DVCC", 39: "VIO",
    40: "SYNC", 41: "SDA", 42: "SCL", 43: "ADDR1", 44: "ADDR2", 45: "INTB", 46: "SDB",
    47: "IICRST", 48: "GND",
}
# Supplies: PVCC/AVCC/DVCC from 5 V (2.7-5.5 V); VIO = the MCU's logic high (datasheet note 3)
IS31FL3733_SUPPLY = {"PVCC": "+5V", "AVCC": "+5V", "DVCC": "+5V", "VIO": "+3.3V",
                     "PGND": "GND", "AGND": "GND", "GND": "GND"}

# MHT151RGBCT (Meihua LDDS-0002116 rev. 6, p. 2): LED pins 1 = common anode, 2 = blue,
# 3 = green, 4 = red. Package BOTTOM view (terminal side): 1 top-left, 2 bottom-left,
# 4 top-right, 3 bottom-right. Reverse mount: the LED sits on B.Cu with its lens in the hole,
# so the bottom-side viewer sees this bottom view, and the library drawing (= what a B.Cu
# footprint looks like from below) must show it. The datasheet's "Recommended Solder Pad"
# drawing is the lens-side view (mirrored); copying it literally was the rev-1 review finding.
# Our footprint numbers its pads like KiCad's LED_ARGB symbol (2 = R, 4 = B), so the test
# checks the geometry: neighbours of the anode pad, and the handedness.
MHT151_NEIGHBOUR_OF_ANODE = {"near": "B", "across": "R", "diagonal": "G"}
# z of (anode->blue) x (anode->red) in the library drawing (x right, y down): bottom view
# 1 TL, 2 BL, 4 TR gives (0, +) x (+, 0) < 0
MHT151_HANDEDNESS_LIBRARY = -1

# Module supply budget (worst case, datasheet maxima)
SENSOR_ICC_MAX_MA = 9.0          # GH39FKSW ICC max
MCU_MISC_MA = 60.0               # AT32F405 + muxes + LED driver logic (estimate, generous)
PTC_HOLD_DERATING = 0.8          # polyfuse hold current at ~50 C board temperature
