#!/usr/bin/env python3
"""List the live FormCAD MCP tools with their required and known arguments. Standard library only.

usage: list_tools.py [--root DIR | --command PROGRAM [ARG ...]] [--filter TEXT] [--core] [--json]
Starts the server (default: ROOT/formCAD mcp --settings-dir ''), runs initialize and tools/list and prints one
line per tool: name, a read/write/destructive tag from the annotations, required arguments, argument names.
Use it instead of trusting any written tool list: the catalogue grows every release.
exit 0 listed, 1 the server answered badly, 2 it could not be started.
"""
import argparse
import json
import os
import subprocess
import sys
import threading

REPLY_TIMEOUT = 90.0


def exchange(proc, message):
    proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()
    box = []
    reader = threading.Thread(target=lambda: box.append(proc.stdout.readline()), daemon=True)
    reader.start()
    reader.join(REPLY_TIMEOUT)
    if not box or not box[0]:
        raise RuntimeError("no reply to %s" % message["method"])
    return json.loads(box[0])


def tag(annotations):
    if annotations.get("readOnlyHint"):
        return "read"
    return "destructive" if annotations.get("destructiveHint") else "write"


def main():
    parser = argparse.ArgumentParser(description="List the live FormCAD MCP tools.")
    parser.add_argument("--root", default=os.getcwd(), help="the FormCAD checkout")
    parser.add_argument("--command", nargs="+", help="a full server command, for example an installed formcad-engine mcp")
    parser.add_argument("--filter", default="", help="keep tools whose name contains this text")
    parser.add_argument("--core", action="store_true", help="ask for the core toolset only")
    parser.add_argument("--json", action="store_true", help="print the raw tool list as JSON")
    opts = parser.parse_args()
    if opts.command:
        command = list(opts.command)
    else:
        launcher = os.path.join(opts.root, "formCAD")
        if not os.path.isfile(launcher):
            print("no formCAD dispatcher at %s; pass --root or --command" % launcher)
            return 2
        command = [launcher, "mcp", "--settings-dir", ""]
    if opts.core:
        command += ["--tools", "core"]
    try:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except OSError as err:
        print("cannot start %s: %s" % (command[0], err))
        return 2
    try:
        exchange(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}}})
        tools = exchange(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})["result"]["tools"]
    except (RuntimeError, KeyError, ValueError) as err:
        print("the server answered badly: %s" % err)
        return 1
    finally:
        try:
            proc.stdin.close()
            proc.wait(10)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()
    tools = [t for t in tools if opts.filter in t["name"]]
    if opts.json:
        print(json.dumps(tools, indent=2))
        return 0
    for tool in tools:
        schema = tool.get("inputSchema", {})
        props = [p for p in schema.get("properties", {}) if p != "document"]
        print("%s [%s] required=%s args=%s" % (tool["name"], tag(tool.get("annotations", {})), ",".join(schema.get("required", [])) or "-", ",".join(props) or "-"))
    print("%d tools" % len(tools))
    return 0


if __name__ == "__main__":
    sys.exit(main())
