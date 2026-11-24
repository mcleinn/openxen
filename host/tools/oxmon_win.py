"""Read the openxen analog stream on Windows without hidapi (ctypes ReadFile on the HID path)."""
from pathlib import Path
import ctypes, subprocess, sys, time
from ctypes import wintypes
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # host/ (oxs, oxl)
import oxs

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.restype = wintypes.HANDLE
k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
k32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                         ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
HID_GUID = "{4d1e55b2-f16f-11cf-88cb-001111000030}"


def stream_paths():
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'HID\\VID_1209&PID_0000&MI_03*' } | ForEach-Object { $_.InstanceId }"],
                         capture_output=True, text=True).stdout.split()
    return ["\\\\?\\" + i.replace("\\", "#") + "#" + HID_GUID for i in out]


def live(h, buf, n):
    """Baseline 1 s, then print every key whose value moves > 60 counts, with its peak."""
    s = oxs.Stream(); base = None; acc = []; t0 = time.time(); active = {}; seen = set()
    print("measuring baseline, keep magnets away ..."); sys.stdout.flush()
    while True:
        k32.ReadFile(h, buf, oxs.REPORT_SIZE + 1, ctypes.byref(n), None)
        f = s.feed(buf.raw[1:n.value] if n.value == oxs.REPORT_SIZE + 1 else buf.raw[:n.value])
        if base is None:
            acc.append(f.values)
            if time.time() - t0 > 1.0:
                base = [sum(c) / len(c) for c in zip(*acc)]
                print("ready: move a magnet over the sensors (Ctrl+C to stop)"); sys.stdout.flush()
            continue
        for k, v in enumerate(f.values):
            d = v - base[k]
            if abs(d) > 60:
                if k not in active or abs(d) > abs(active[k]):
                    active[k] = d
            elif k in active and abs(d) < 30:
                seen.add(k)
                print(f"key {k:2d}: peak {active.pop(k):+5.0f} counts   ({len(seen)}/56 keys seen)"); sys.stdout.flush()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "live":
        paths = stream_paths()
        h = k32.CreateFileW(paths[0], 0x80000000, 3, None, 3, 0, None)
        try:
            live(h, ctypes.create_string_buffer(oxs.REPORT_SIZE + 1), wintypes.DWORD())
        except KeyboardInterrupt:
            pass
        return 0
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
    paths = stream_paths()
    if not paths:
        print("no openxen stream interface found"); return 1
    h = k32.CreateFileW(paths[0], 0x80000000, 3, None, 3, 0, None)   # GENERIC_READ, share r/w, OPEN_EXISTING
    if h in (None, wintypes.HANDLE(-1).value):
        print("CreateFile failed", ctypes.get_last_error()); return 1
    buf = ctypes.create_string_buffer(oxs.REPORT_SIZE + 1)
    n = wintypes.DWORD()
    s = oxs.Stream()
    frames = []
    t0 = time.time()
    while time.time() - t0 < seconds:
        if not k32.ReadFile(h, buf, oxs.REPORT_SIZE + 1, ctypes.byref(n), None):
            print("ReadFile failed", ctypes.get_last_error()); return 1
        raw = buf.raw[1:n.value] if n.value == oxs.REPORT_SIZE + 1 else buf.raw[:n.value]
        frames.append(s.feed(raw))
    k32.CloseHandle(h)
    dt = (frames[-1].time_us - frames[0].time_us) / 1e6
    print(f"{len(frames)} frames in {dt:.2f} s device time = {len(frames)/max(dt,1e-9):.0f} reports/s, lost {s.lost_total}, flags {frames[-1].flags:#x}")
    nk = len(frames[-1].values)
    print("key: mean (min..max)  [raw ADC]")
    line = []
    for k in range(nk):
        v = [f.values[k] for f in frames]
        line.append(f"{k:2d}:{sum(v)/len(v):6.0f} ({min(v)}..{max(v)})")
        if len(line) == 4:
            print("   ".join(line)); line = []
    if line: print("   ".join(line))
    if s.rest:
        print("calibration rest/bottom known for", len(s.rest), "keys")
    return 0


if __name__ == "__main__":
    sys.exit(main())
