#!/usr/bin/env python3
"""Probe a running FormCAD engine and frontend. Standard library only.

usage: health_probe.py [--engine-port N] [--frontend-port N] [--wait SECONDS]
exit 0 when the engine answers /api/health, 1 when it does not, 2 on bad usage.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_ENGINE_PORT = 8290
DEFAULT_FRONTEND_PORT = 5290
POLL_SECONDS = 1.0
REQUEST_TIMEOUT = 3.0


def fetch(url):
    with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as reply:
        return reply.status, reply.read().decode("utf-8", "replace")


def wait_for(url, wait):
    deadline = time.monotonic() + wait
    last = "no answer"
    while True:
        try:
            return fetch(url), ""
        except (urllib.error.URLError, OSError, ValueError) as err:
            last = str(err)
        if time.monotonic() >= deadline:
            return None, last
        time.sleep(POLL_SECONDS)


def main():
    parser = argparse.ArgumentParser(description="Probe the FormCAD engine and frontend.")
    parser.add_argument("--engine-port", type=int, default=DEFAULT_ENGINE_PORT)
    parser.add_argument("--frontend-port", type=int, default=DEFAULT_FRONTEND_PORT)
    parser.add_argument("--wait", type=float, default=0.0, help="seconds to keep retrying the engine")
    opts = parser.parse_args()
    engine = "http://127.0.0.1:%d/api/health" % opts.engine_port
    got, why = wait_for(engine, opts.wait)
    if got is None:
        print("FAIL engine %s: %s" % (engine, why))
        print("hint: boot it with ./formCAD backend (or ./formCAD), then run ./formCAD doctor for port and toolchain problems")
        return 1
    status, body = got
    try:
        body = json.dumps(json.loads(body))
    except ValueError:
        pass
    print("PASS engine %s status %d %s" % (engine, status, body[:300]))
    front = "http://127.0.0.1:%d/" % opts.frontend_port
    got, why = wait_for(front, 0.0)
    print("PASS frontend %s" % front if got else "SKIP frontend %s not answering (fine for headless work): %s" % (front, why))
    return 0


if __name__ == "__main__":
    sys.exit(main())
