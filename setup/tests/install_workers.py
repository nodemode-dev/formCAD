import argparse
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
VARIABLE = {"kernel": "FORMCAD_KERNEL", "mesher": "FORMCAD_MESHER"}


def say(text: str) -> None:
    print("[formCAD] %s" % text, flush=True)


def installed_path(name: str, service) -> str | None:
    os.environ.pop(VARIABLE[name], None)
    found = service.resolve()
    return found[1] if found and found[2] == "installed" else None


def bring_up(name: str, service, minutes: float) -> str | None:
    path = installed_path(name, service)
    if path:
        say("%s already installed at %s" % (name, path))
        return path
    service.start_install()
    deadline = time.monotonic() + minutes * 60.0
    last = ""
    while time.monotonic() < deadline:
        state = service.status()
        if state["message"] != last:
            last = state["message"]
            say("%s: %s" % (name, last))
        if not state["installing"]:
            break
        time.sleep(2.0)
    path = installed_path(name, service)
    if not path:
        say("%s was not installed: %s" % (name, service.status()["message"]))
    return path


def main(argv) -> int:
    parser = argparse.ArgumentParser(description="Install the kernel and mesher workers into FORMCAD_DATA_DIR the way the app does, for the worker tests.")
    parser.add_argument("workers", nargs="*", default=["kernel", "mesher"], choices=["kernel", "mesher"])
    parser.add_argument("--env-file", help="append FORMCAD_KERNEL and FORMCAD_MESHER lines to this file")
    parser.add_argument("--minutes", type=float, default=20.0)
    args = parser.parse_args(argv)
    if not os.environ.get("FORMCAD_DATA_DIR"):
        say("set FORMCAD_DATA_DIR to the folder the workers should be installed in")
        return 2
    sys.path.insert(0, str(BACKEND))
    from app.services import kernel, mesher

    services = {"kernel": kernel, "mesher": mesher}
    lines = []
    failed = False
    for name in args.workers:
        path = bring_up(name, services[name], args.minutes)
        if path:
            lines.append("%s=%s" % (VARIABLE[name], path))
        else:
            failed = True
    kernel.stop()
    mesher.stop()
    if args.env_file and lines:
        with open(args.env_file, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    for line in lines:
        say(line)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
