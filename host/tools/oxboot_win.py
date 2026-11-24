"""Send libhmk COMMAND_BOOTLOADER (id 2) to the raw HID interface (MI_02) of an openxen module."""
import ctypes, subprocess, sys
from ctypes import wintypes
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.restype = wintypes.HANDLE
k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
k32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
ids = subprocess.run(["powershell", "-NoProfile", "-Command",
    r"Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'HID\VID_1209&PID_0000&MI_02*' } | ForEach-Object { $_.InstanceId }"],
    capture_output=True, text=True).stdout.split()
if not ids: sys.exit("no openxen config interface found")
path = chr(92)*2 + "?" + chr(92) + ids[0].replace("\\", "#") + "#{4d1e55b2-f16f-11cf-88cb-001111000030}"
h = k32.CreateFileW(path, 0xC0000000, 3, None, 3, 0, None)
if h in (None, wintypes.HANDLE(-1).value): sys.exit(f"CreateFile failed {ctypes.get_last_error()}")
data = b"\x00" + bytes([2]) + bytes(63)      # report ID 0, command_id = COMMAND_BOOTLOADER
n = wintypes.DWORD()
ok = k32.WriteFile(h, data, len(data), ctypes.byref(n), None)
print("bootloader command sent" if ok else f"WriteFile failed {ctypes.get_last_error()}")
