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

Register the server with the line from `GET /api/automation/status`. Tools are named `formcad_*` plus one `cmd_<id>` per command that takes arguments, each with read-only, destructive and idempotent hints. Results are text plus structured content. Agents get the lower trust class, always.
