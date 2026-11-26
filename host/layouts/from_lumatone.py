"""Convert Lumatone .ltn presets (the freexen ones) 1:1 into xentool openxen layouts (.otn).

openxen key indices are Lumatone key indices, so keys, channels and colours stay unchanged.
Only the two header lines xentool needs are added: `Edo=` (from the file name, "53ET-...")
and `PitchOffset=` = 2 * EDO, which reproduces freexen's pitch convention (xenAssist
server.py: pitch = (chan + 1) * edo + key; xentool: (chan - 1) * edo + key + PitchOffset).

The presets are third-party data and stay out of the repository: output goes to
build/layouts/ (gitignored).

    python host/layouts/from_lumatone.py            convert every preset
    python host/layouts/from_lumatone.py 53         only the 53ET ones
"""
import pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PRESETS = pathlib.Path(r"C:\Dev-Free\freexen\xenAssist\static\ltn")
OUT = ROOT / "build" / "layouts"


def convert(src: pathlib.Path) -> pathlib.Path:
    m = re.match(r"(\d+)ET-", src.name)
    if not m:
        raise SystemExit(f"cannot read the EDO from {src.name}")
    edo = int(m.group(1))
    text = src.read_text()
    if re.search(r"^\s*Edo\s*=", text, re.M):
        raise SystemExit(f"{src} already has an Edo line")
    out = OUT / (src.name.replace(".default.ltn", "").replace(".ltn", "") + ".otn")
    out.write_text(f"Edo={edo}\nPitchOffset={2 * edo}\n\n" + text)
    return out


def main():
    pattern = f"{sys.argv[1]}ET-*.ltn" if len(sys.argv) > 1 else "*.ltn"
    files = sorted(PRESETS.glob(pattern))
    if not files:
        raise SystemExit(f"no presets matching {pattern} in {PRESETS}")
    OUT.mkdir(parents=True, exist_ok=True)
    for f in files:
        print(f"{f.name} -> {convert(f).relative_to(ROOT)}")


if __name__ == "__main__":
    main()
