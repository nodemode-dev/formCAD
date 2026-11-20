#!/usr/bin/env python3
"""Smoke test the FormCAD MCP server over stdio. Standard library only.

usage: mcp_smoke.py [--root DIR] [--timeout SECONDS]
Starts "./formCAD mcp --settings-dir ''" (a throwaway settings folder), runs initialize, tools/list,
formcad_new_document, formcad_command_line with a LINE, formcad_inspect and formcad_undo, then closes stdin.
exit 0 all steps passed, 1 a step failed, 2 the server could not be started.
"""
import argparse
import json
import os
import subprocess
import sys
import threading

DEFAULT_TIMEOUT = 60.0
MIN_TOOLS = 20
LINE_TEXT = "line 0,0 10,10 "


class Session:
    def __init__(self, command, timeout):
        self.timeout = timeout
        self.next_id = 0
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def rpc(self, method, params=None):
        self.next_id += 1
        message = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}}
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()
        box = []
        reader = threading.Thread(target=lambda: box.append(self.proc.stdout.readline()), daemon=True)
        reader.start()
        reader.join(self.timeout)
        if not box or not box[0]:
            raise RuntimeError("no reply to %s within %.0f s" % (method, self.timeout))
        return json.loads(box[0])

    def call(self, name, arguments=None):
        reply = self.rpc("tools/call", {"name": name, "arguments": arguments or {}})
        if "error" in reply:
            raise RuntimeError("%s: %s" % (name, reply["error"].get("message")))
        result = reply["result"]
        if result.get("isError"):
            raise RuntimeError("%s refused: %s" % (name, json.dumps(result.get("structuredContent"))[:300]))
        return result["structuredContent"]

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(10)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()


def main():
    parser = argparse.ArgumentParser(description="Smoke test the FormCAD MCP server over stdio.")
    parser.add_argument("--root", default=os.getcwd(), help="the FormCAD checkout (holds the formCAD dispatcher)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    opts = parser.parse_args()
    launcher = os.path.join(opts.root, "formCAD")
    if not os.path.isfile(launcher):
        print("FAIL no formCAD dispatcher at %s; pass --root with the checkout folder" % launcher)
        return 2
    try:
        session = Session([launcher, "mcp", "--settings-dir", ""], opts.timeout)
    except OSError as err:
        print("FAIL cannot start %s: %s" % (launcher, err))
        return 2
    steps = []
    try:
        info = session.rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {}})["result"]
        steps.append(("initialize", info["serverInfo"]["name"] == "formcad", "server %s" % info["serverInfo"].get("version")))
        count = len(session.rpc("tools/list")["result"]["tools"])
        steps.append(("tools/list", count >= MIN_TOOLS, "%d tools" % count))
        session.call("formcad_new_document")
        steps.append(("formcad_new_document", True, "drawing created"))
        session.call("formcad_command_line", {"text": LINE_TEXT})
        entities = session.call("formcad_inspect")["entities"]
        steps.append(("line drawn", entities == 1, "%s entities" % entities))
        session.call("formcad_undo")
        steps.append(("formcad_undo", session.call("formcad_inspect")["entities"] == 0, "back to 0"))
    except (RuntimeError, KeyError, ValueError, OSError) as err:
        steps.append(("step failed", False, str(err)))
        tail = session.proc.stderr.read(2000) if session.proc.poll() is not None else ""
        if tail:
            print(tail)
    finally:
        session.close()
    bad = 0
    for name, ok, note in steps:
        print("%s %s: %s" % ("PASS" if ok else "FAIL", name, note))
        bad += 0 if ok else 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
