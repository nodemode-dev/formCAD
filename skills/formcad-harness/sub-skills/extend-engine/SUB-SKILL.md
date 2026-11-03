---
name: extend-engine
description: Adds features to the FormCAD engine in the places the architecture allows. Use when adding a command, programmatic form, router, kernel method, graph node, command plugin, node plugin or file-writing feature.
---

# Extend the engine

Load `sub-skills/laws-and-logs/SUB-SKILL.md` first. Everything below follows law 6: the engine owns geometry and commands, and features land as registered modules.

## A command

1. Put it in a new module under `backend/app/cmd/commands/` (or an existing module for that area). `registry.load_modules()` imports every module in that package, so no list needs editing.
2. Register with `@command(name, aliases, group, label, description, menu, transparent, undoable, repeatable)` from `app.cmd.registry`. The generator body is the typed flow (it yields prompts), so a person can type it.
3. Register the programmatic form with `@executes(name)`: a function `(ctx, args)` that takes a dict and returns a result dict, with no prompts or dialogs. This one function is what the MCP server, the CLI `run --command` step, macros and the Python client call; the MCP tool `cmd_[name]` appears automatically.
4. Pick the `group` with care: it decides the trust class. Macros may only use groups listed in `MACRO_GROUPS` in `backend/app/cmd/barred.py`; names in `MACRO_BARRED` and `AGENT_BARRED` are refused to Python macros and outside agents. Anything that writes outside the document, edits settings, touches the vault lifecycle or runs code belongs on those lists.
5. List your command's arguments by reading them as plain keys in `args` inside the function; the MCP schema is derived from the function's code, and 17 common commands have curated schemas in `backend/app/automation/forms.py` `CURATED`. If you want a precise schema for an agent, add a curated entry there with one Edit.
6. Verify: `--selfcheck`, then `formcad-engine commands [FILTER]` to see it in the catalogue, then `formcad-engine run --new --command "name {json}"`.

## A file path argument

Any command or route that reads or writes a file must (a) pass the output name through `core/outputs.checked(path, allowed, default)` which forces the extension, refuses overwriting a different kind of file and requires an existing folder, and (b) call `barred.args_refusal` or `barred.path_refusal` so macros and outside agents are held to their granted folders. Key names `path`, `paths`, `file`, `files`, `filename`, `folder`, `dir`, `out` and anything ending `_path` or `_file` are checked automatically for agent calls. Size caps come in pairs: a window value and a lower agent and macro value, enforced before any work.

## A router

Write `backend/app/routers/[name].py` with an `APIRouter`, then add one line to `ROUTERS` in `backend/app/main.py` as `("app.routers.[name]", "/api/...")` only after the module imports cleanly, and run `--selfcheck` at once (it imports every router and prints the count). Document routes live under `/api/docs/{id}`. Routes are token guarded; a macro token can reach only `/api/docs` and `/api/commands`, and `_macro_route_ok` in `core/guard.py` lists the path segments macros are denied.

## Document state

Per-document data is a table (add the name to `TABLE_NAMES` in `backend/app/doc/tables.py`) or a header value set with `doc.set_header`. Both keep undo, redo, save and reopen working; every edit runs inside `doc.transaction` so a failing batch rolls back. Container format and autosave live in `backend/app/doc/container.py`.

## A kernel method

Add it to a `kernel/kernel_*.py` module and register it in `kernel/formcad_kernel.py`; call it from the engine through `app.services.kernel`. Units are millimetres. Test it by piping JSON lines into the worker (see `sub-skills/kernel-and-mesher/SUB-SKILL.md`). The engine never imports OCP.

## Graph nodes and plugins

- Built-in nodes live in `backend/app/graph/nodes/` and register through `app.graph.registry.register`. Node ids, guids and port names are permanent: add ports, never remove or retype them. A node is a function of its inputs and `ctx.seed`; use `random.Random(ctx.seed)`, never the clock.
- A third-party node plugin follows `docs/NODE_SDK.md`: `register(api)` calls `api.node(...)` and `api.port(...)`; ship it as a plugin folder with `plugin.json` or an entry point in the group `formcad.nodes`; seal it with `formcad-engine plugin seal [folder]`, list with `plugin list`, check with `graph io` and `graph run`. `docs/examples/node_plugin/` is a working copy-me folder.
- A command plugin uses the same loader (entry point group `formcad.plugins` or `[data]/plugins/[id]/plugin.json` with a sha256 per file); nothing imports until a person enables it, and a changed file blocks loading until re-reviewed. Plugins run inside the engine process, so say so in any user-facing text.
- The graph file format is `docs/GRAPH_FORMAT.md`; the assembly record format is `docs/ASSEMBLY_SCHEMA.md`. Contracts other tools rely on change only by adding fields.

## Finish

Run the verification tiers, log the decision in `backend/HASHOUT_LOG.md` (and the frontend log if you touched it), add the `NOTICE.md` row for any dependency, and list what you did not verify.
