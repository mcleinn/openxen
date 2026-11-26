"""Send sustain off, All Sound Off and All Notes Off on all 16 channels of a MIDI output
(default "loopMIDI Port"). Clears notes left hanging when xentool is stopped by force.

    python host/tools/midi_panic.py [port-name-prefix]
"""
import ctypes, sys
from ctypes import wintypes

w = ctypes.WinDLL("winmm")


class CAPS(ctypes.Structure):
    _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD), ("v", wintypes.UINT),
                ("szPname", wintypes.WCHAR * 32), ("wTechnology", wintypes.WORD),
                ("wVoices", wintypes.WORD), ("wNotes", wintypes.WORD),
                ("wChannelMask", wintypes.WORD), ("dwSupport", wintypes.DWORD)]


def main():
    prefix = sys.argv[1] if len(sys.argv) > 1 else "loopMIDI Port"
    dev = None
    for i in range(w.midiOutGetNumDevs()):
        c = CAPS()
        w.midiOutGetDevCapsW(i, ctypes.byref(c), ctypes.sizeof(c))
        if c.szPname.startswith(prefix):
            dev = i
    if dev is None:
        print(f"no MIDI output starting with '{prefix}'"); return 1
    h = wintypes.HANDLE()
    if w.midiOutOpen(ctypes.byref(h), dev, 0, 0, 0):
        print("midiOutOpen failed"); return 1
    for ch in range(16):
        for cc in (64, 120, 123):
            w.midiOutShortMsg(h, 0xB0 | ch | (cc << 8))
    w.midiOutClose(h)
    print(f"all notes off on '{prefix}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
