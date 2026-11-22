---
name: connect-and-trust
description: Registers the FormCAD MCP server, chooses headless or live mode, and explains granted folders, barred commands and result handling. Use when connecting an agent, seeing refusals, or choosing core versus all tools.
---

# Connect and trust

## Register

- Checkout: `claude mcp add formcad -- /path/to/formCAD/backend/venv/bin/python /path/to/formCAD/backend/formcad_engine.py mcp` (or `./formCAD mcp`).
- Installed app: `claude mcp add formcad -- "[install-dir]/formcad-engine" mcp`.
- `.mcp.json`: `{"mcpServers": {"formcad": {"command": "[install-dir]/formcad-engine", "args": ["mcp"]}}}` with an absolute path; Claude Desktop uses the same block in its config and needs a restart.
- `GET /api/automation/status` on a running engine returns these strings filled in.

Modes: headless (default, in-process drawings, no window); `--connect auto` or `--connect HOST:PORT` bridges to the running app so edits appear in the window (loopback only; reads `engine.port` and `session.token` from the data folder, or `FORMCAD_URL` and `FORMCAD_TOKEN`); the server lists the core tools by default (the fixed `formcad_*` tools plus the curated drafting `cmd_*` tools) and every other command stays reachable through `formcad_execute`; `--tools all` lists one tool per command, which is hundreds of schemas, so ask for it only when a client needs them listed. `--settings-dir DIR` picks a data folder (empty means throwaway). HTTP `POST /mcp` also exists behind the token guard.

## First call

Call `formcad_status` before planning. It returns the app version, `kernel` and `mesher` (each with `state` installed, installing or not installed, a `version`, a `message`, and `how` a person installs a missing one), `granted_folders`, the `settings_file` where a person grants more, and the open documents. Plan from it: without the kernel only 2D drafting, meshes and non-solid graph nodes work; without the mesher no study runs. An agent cannot install either: tell the person which button to press and stop that branch of the plan.

## Tools

The fixed `formcad_*` tools (status, documents, command line, script, execute, list_commands, inspect, query_entities, find_text, render, select, undo, redo, export, display_list, variables, graph_run, and the job tools sim_start, cam_start, job_status, job_cancel) plus `cmd_[id]` tools. A command id with a dot or a dash is written with underscores in its tool name (`layer.new` is `cmd_layer_new`); the old spelling is still accepted when called. A `cmd_` tool that is not in the list can still be called by name, or run through `formcad_execute` with the command id. Annotations mark read and destructive tools; they are advice, there is no confirmation step. Results are text plus structuredContent; `ok` false sets `isError`.

Long work is a job: `formcad_sim_start` and `formcad_cam_start` return a job id at once. Poll `formcad_job_status` every few seconds until `finished` is true, then read `result` (a study) or `results` (toolpaths). `formcad_job_cancel` stops one. Never wait inside a single call.

## Trust model

An outside agent is a lower trust class than the window.

- Granted folders: every path argument (open, save, export, graph_path, doc_path, bake_path, any `path`, `file`, `out`) must lie inside a folder in the `agentFolders` list of `automation.json` in the engine data folder. With none, all file access is refused ("outside the folders granted to this agent"). Ask the user to add a folder; never write that setting yourself and never copy files around the check.
- Barred to agents (use the window): `vaultcreate vaultstate vaultrevise vaultgc vaultlock vaultpin pluginenable aliasedit reinit appload macrosave macroplay materiallib modeltol gdtstyle docprops asmsearch analysisramp matesettings motionsettings graph gerberexport drillexport idfexport boardstep ecadsync ecadpush`. LISP is unavailable. Vault commands refuse `vault`, `author` and `force` arguments.
- A drawing view cannot point at another file (`source.doc`); put the model in the document and use a layout.
- Output extensions are forced and an existing file of another kind is never overwritten. `formcad_export` writes pdf, png, svg, dxf, dwg; saving writes fcad, dxf, dwg, dwt; 3D formats go through `cmd_export`.
- Job caps (triangles, frames, samples, time) are lower for agents and checked before work starts.

## Recovering

Read `error` and `output`; fix the cause (a missing sketch, a refused path); do not retry blindly. `formcad_undo` rolls a step back. For a failure with no message, `formcad_command_line` shows the prompt text.
