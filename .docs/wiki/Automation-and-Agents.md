# Automation and agents

## Ways in

| Way | What it is |
| --- | --- |
| LISP | a dialect with 188 builtins, in the console or loaded with `appload` |
| Scripts | command lists run with `script` or `rscript` |
| Macros | recorded command lists and Python macros in an isolated process |
| Plugins | hashed folders that register commands, nodes or both |
| CLI | `formcad-engine info`, `convert`, `run`, `commands`, `perf`, `graph run`, and more; no window |
| MCP | a server on standard input and output, or HTTP at `POST /mcp` behind the token; `GET /api/automation/status` prints the lines to register it |
| Control protocol | newline JSON on a loopback port, turned on with `FORMCAD_CONTROL_PORT` |

## The trust model of the window

There are two trust classes.

1. **The window.** You, at the keyboard. You can run any command.
2. **Macros and agents.** Anything that arrives by a macro, a plugin's script, the control protocol or MCP.

The lower class is checked in two places: `backend/app/cmd/barred.py` (which commands a macro or an agent may run at all) and `backend/app/core/guard.py` (which routes a per-run macro token may reach, and whether it may read or write). Rules that matter:

- Commands that change settings, material libraries, tolerances, plugin enabling, converter paths or vault administration are barred for macros and agents.
- Every new command or route that reads or writes a file, starts a process or changes settings is classified when it lands. A route that is not classified is not callable by the lower class.
- A prompt that asks for a file says the word file, so a macro cannot answer a path prompt by accident.
- Computing jobs take lower size caps when the caller is a macro or an agent.

An audit before each release re-reads this surface; an earlier audit found a macro-to-plugin escape that was closed before release.

## Macros

Python macros run in a separate process with a scrubbed environment, a time limit, resource limits, and a guard on files, network, subprocesses and native code. Trust is per file and bound to the hash of its source: change one byte and the macro asks again. The grants (`--grant-files DIR`, `--grant-network`, `--grant-subprocess` on the CLI) are explicit and per run.

## Granted folders

A macro or agent may read and write files only inside folders it was granted. For a macro the grant is the run's own list. For agents it is the `agentFolders` setting, which only you can change in the window. Paths are resolved to their real location before the check, so a link out of a granted folder does not escape it. Output extensions are forced by the engine.

## Plugins

A plugin folder has `plugin.json` with a hash for every file. Nothing is imported at discovery. `pluginenable` stores the manifest hash; load needs the hashes to match and no code file unlisted. Seal a folder with `formcad-engine plugin seal DIR`.

## Agents over MCP

Register the server with the line from `GET /api/automation/status`. The server lists the fixed `formcad_*` tools and the `cmd_*` tools of the common drafting commands; every other command runs through `formcad_execute`, and `--tools all` lists one `cmd_*` tool per command. Each tool carries read-only, destructive and idempotent hints. `formcad_status` is the first call: it says whether the kernel and the mesher are installed and which folders are granted. Results are text plus structured content. Agents get the lower trust class, always.

`./formCAD agents install` registers the server (`./formCAD mcp`) with Claude Code, Codex, Cursor and Antigravity for the current user; `--dry-run` says what it would change. A second run changes nothing, every other entry in each program's settings is kept, and a server named `formcad` that FormCAD did not write is left alone. `./formCAD agents sync` copies `skills/` into `.claude/skills` and `.agents/skills` and writes `agents/manifest.json`; `./formCAD agents check` checks all of it. Windows has no `agents` command yet.

## The agent dock

Window, Agent Dock (Ctrl+J, Cmd+J on a Mac) opens a panel at the bottom or the right of the window with a terminal and tabs that run Claude Code, Codex, Cursor and Antigravity. Each program tab reaches this window's engine at `POST /mcp` with a token made for that tab: it is good only for `/mcp`, it is passed in the program's environment (Antigravity reads it from `.agents/mcp_config.json` in its own folder under the data folder, mode 0600), never on its command line, and it stops working when the tab closes. A plain terminal gets no token. Tabs start in the projects folder. The panel is the shared agent dock module 2.2.0 of the form family, `frontend/src/dock/`, kept byte for byte.
