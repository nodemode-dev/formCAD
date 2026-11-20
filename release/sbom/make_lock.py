#!/usr/bin/env python3
import importlib.metadata as md
import sys

SKIP = {"pip", "setuptools", "wheel", "pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "packaging", "pefile", "pywin32-ctypes", "macholib"}


def main():
    target = sys.argv[1]
    rows = {}
    for dist in md.distributions():
        name = dist.metadata["Name"]
        if name and name.lower().replace("_", "-") not in SKIP:
            rows[name.lower().replace("_", "-")] = f"{name}=={dist.version}"
    with open(target, "w", encoding="utf-8", newline="\n") as out:
        out.write("# pins of the installed build environment, no hashes; CI replaces this with pip-compile --generate-hashes output\n")
        for key in sorted(rows):
            out.write(rows[key] + "\n")
    print(f"wrote {len(rows)} pins to {target}")


if __name__ == "__main__":
    main()
