"""openxen LED bring-up test on Windows (ctypes, no hidapi).

    python oxled_win.py rgb        all keys red, green, blue, white (low brightness), 3 s each
    python oxled_win.py chase      one key after another in white, key number printed
    python oxled_win.py key N      key N red/green/blue in turn
"""
from pathlib import Path
import ctypes, sys, time
from ctypes import wintypes
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # host/ (oxs, oxl)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import oxl, oxs
from oxmon_win import stream_paths, k32

k32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
                          ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
LEVEL = 60          # sRGB 0..255, firmware applies gamma: 60 is dim
BUDGET_MA = 100


class Module:
    def __init__(self):
        p = stream_paths()
        if not p:
            raise SystemExit("no openxen module found")
        self.h = k32.CreateFileW(p[0], 0xC0000000, 3, None, 3, 0, None)   # read + write
        if self.h in (None, wintypes.HANDLE(-1).value):
            raise SystemExit(f"CreateFile failed {ctypes.get_last_error()}")
        self.buf = ctypes.create_string_buffer(oxs.REPORT_SIZE + 1)

    def send(self, report: bytes):
        data = b"\x00" + report            # report ID 0 + 64 bytes
        n = wintypes.DWORD()
        if not k32.WriteFile(self.h, data, len(data), ctypes.byref(n), None):
            raise SystemExit(f"WriteFile failed {ctypes.get_last_error()}")

    def show(self, colours):
        for r in oxl.frame(colours):
            self.send(r)

    def status(self):
        n = wintypes.DWORD()
        for _ in range(3):                 # skip queued reports
            k32.ReadFile(self.h, self.buf, oxs.REPORT_SIZE + 1, ctypes.byref(n), None)
        r = oxs.parse(self.buf.raw[1:n.value])
        flags = []
        if r.led_status & oxl.STATUS_HOST: flags.append("host session")
        if r.led_status & oxl.STATUS_TIMEOUT: flags.append("TIMED OUT")
        if r.led_status & oxl.STATUS_I2C_ERROR: flags.append("I2C ERROR")
        return ", ".join(flags) or "none"

    def hold(self, colours, seconds):
        t = time.time()
        while time.time() - t < seconds:   # resend inside the 2 s host timeout
            self.show(colours)
            time.sleep(0.4)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "rgb"
    m = Module()
    m.send(oxl.config(255, None, 2000, BUDGET_MA))
    off = [(0, 0, 0)] * oxl.KEYS
    try:
        if mode == "rgb":
            for name, c in (("red", (LEVEL, 0, 0)), ("green", (0, LEVEL, 0)), ("blue", (0, 0, LEVEL)), ("white", (LEVEL,) * 3)):
                print(f"all keys {name} ...", end=" ", flush=True)
                m.hold([c] * oxl.KEYS, 3)
                print("status:", m.status())
        elif mode == "chase":
            for k in range(oxl.KEYS):
                cols = list(off); cols[k] = (LEVEL * 2,) * 3
                print(f"key {k:2d} (HE{k}/D{k})", flush=True)
                m.hold(cols, 0.8)
            print("status:", m.status())
        elif mode == "key":
            k = int(sys.argv[2])
            for name, c in (("red", (LEVEL * 2, 0, 0)), ("green", (0, LEVEL * 2, 0)), ("blue", (0, 0, LEVEL * 2))):
                cols = list(off); cols[k] = c
                print(f"key {k} {name}", flush=True)
                m.hold(cols, 2)
        m.show(off)
    except KeyboardInterrupt:
        m.show(off)
    return 0


if __name__ == "__main__":
    sys.exit(main())
