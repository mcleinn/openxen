#!/usr/bin/env python3
"""Build libhmk for the openxen-m56 board (system Python + PlatformIO).

    python firmware/build_firmware.py [--clean]

Works in build/fw/libhmk, a local clone of reference/repos/libhmk checked out at the pinned
commit, so the reference clone stays pristine and our own sources stay in firmware/:
  1. clone / reset build/fw/libhmk to LIBHMK_COMMIT
  2. copy firmware/keyboards/openxen-m56 into its keyboards/ and apply firmware/libhmk/apply_openxen.py
     (analog stream sources + exact search/replace edits)
  3. python setup.py -k openxen-m56  (writes platformio.ini)
  4. pio run  ->  build/fw/libhmk/.pio/build/openxen-m56/firmware.{elf,bin}
  5. copy firmware.bin / .elf / the size report to build/fw/
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "reference" / "repos" / "libhmk"
WORK = ROOT / "build" / "fw" / "libhmk"
OUT = ROOT / "build" / "fw"
BOARD = "openxen-m56"
LIBHMK_COMMIT = "1d2b2e2101fa4509700a24152d33335ddfda8240"
PIO = Path.home() / ".platformio" / "penv" / "Scripts" / "pio.exe"


def run(cmd: list[str], cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    print("$", " ".join(cmd))
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, env=env)
    if r.returncode != 0:
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit(f"failed: {' '.join(cmd[:3])}")
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true", help="delete the work clone first")
    args = ap.parse_args()
    if args.clean and WORK.exists():
        shutil.rmtree(WORK, onerror=lambda f, p, e: (os.chmod(p, 0o700), f(p)))
    if not (WORK / ".git").exists():
        WORK.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--quiet", "--no-hardlinks", str(REF), str(WORK)], ROOT)
    run(["git", "checkout", "--quiet", "--force", LIBHMK_COMMIT], WORK)
    run(["git", "clean", "-fdq", "-e", ".pio", "-e", "lib"], WORK)        # keep PlatformIO's caches
    shutil.copytree(ROOT / "firmware" / "keyboards" / BOARD, WORK / "keyboards" / BOARD, dirs_exist_ok=True)
    run([sys.executable, str(ROOT / "firmware" / "libhmk" / "apply_openxen.py"), str(WORK)], ROOT)   # analog stream
    run([sys.executable, "setup.py", "-k", BOARD], WORK)
    t0 = time.time()
    r = run([str(PIO), "run", "-e", BOARD], WORK)
    size = [l for l in r.stdout.splitlines() if l.startswith(("RAM:", "Flash:"))]
    built = WORK / ".pio" / "build" / BOARD
    OUT.mkdir(parents=True, exist_ok=True)
    for f in ("firmware.bin", "firmware.elf"):
        shutil.copy(built / f, OUT / f)
    (OUT / "size.txt").write_text("\n".join(size) + "\n", encoding="utf-8")
    print(f"built {BOARD} in {time.time() - t0:.0f} s:", *size, sep="\n  ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
