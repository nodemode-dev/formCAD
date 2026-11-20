---
name: formcad-harness
description: "Use when asked to run, install, build, test, freeze, debug or extend the FormCAD repo (formCAD, formcad-engine, .fcad). Installs, boots, verifies, freezes and extends a FormCAD checkout as a developer agent: the ./formCAD dispatcher and setup scripts, ports 5290 and 8290, the engine --selfcheck, the OpenCascade kernel worker and Netgen mesher programs, frozen engine builds, fixtures and their exit numbers, the CLAUDE.md laws (SEDO hand edits, zero DOM flash, tokens only, HASHOUT logs), and the command, router, kernel and plugin extension points. Not for drawing or modelling inside FormCAD through MCP or the CLI; that is the formcad-driving skill."
license: Apache-2.0
metadata:
  product: FormCAD
  pack-version: "0.19.1"
  audience: developer agent
---

# FormCAD harness

FormCAD is a Tauri 2 desktop CAD app: a vanilla TypeScript and Vite interface in `frontend/`, a Python and FastAPI engine in `backend/` that owns every document, command and piece of geometry, a Tauri shell in `src-tauri/`, and two separate worker programs, the OpenCascade kernel in `kernel/` and the Netgen mesher in `mesher/`. This pack is the operating manual for an agent that works on the checkout itself. It teaches the order of operations, the checks that prove a change, and the rules that the owner enforces on every change.

The pack never repeats what the code can tell you. Command names, routes and tool names are read from the tree (`backend/app/cmd/commands/`, `backend/app/main.py`, `backend/app/automation/mcp.py`); when this pack and the tree disagree, the tree wins and the pack needs a fix.

## Route first, then load one sub-skill

| The task is about | Load |
| --- | --- |
| A fresh clone, installing, booting, ports, environment variables, the data folder, the token guard | `sub-skills/install-and-boot/SUB-SKILL.md` |
| Proving a change: doctor, selfcheck, typecheck, health probe, MCP smoke, headless CLI, CI parity | `sub-skills/verify/SUB-SKILL.md` |
| 3D features refused, the kernel worker, the mesher, simulation studies that cannot mesh, licence files | `sub-skills/kernel-and-mesher/SUB-SKILL.md` |
| Freezing the engine or workers, the desktop build, the `release/` folder and what must never be pushed | `sub-skills/freeze-and-ship/SUB-SKILL.md` |
| Before editing anything: the laws, SEDO, HASHOUT logs, version sites, commits, licences, clean room | `sub-skills/laws-and-logs/SUB-SKILL.md` |
| Adding or changing a command, router, kernel method, graph node, command plugin or node plugin | `sub-skills/extend-engine/SUB-SKILL.md` |
| Which fixture proves which feature and what its exit numbers are | `sub-skills/fixtures-and-exits/SUB-SKILL.md` |

For any task that edits files, load `laws-and-logs` as well as the specialist. It is short and its rules are not negotiable.

## The first five minutes in a checkout

Run these from the repository root, in this order, and stop at the first failure.

1. `./formCAD doctor` prints ok, warn or FAIL for node (22 or newer), npm, Python (3.12 or newer), the engine, kernel and mesher venvs, Rust, webkit2gtk (Linux) and ports 5290 and 8290. Exit 0 means no FAIL line.
2. `./formCAD version` prints the version from `frontend/src/version.ts` and the short commit.
3. `backend/venv/bin/python backend/formcad_engine.py --selfcheck` prints one JSON object (library versions, router count, `kernel_record`, `mesher_record`, `sim_solvers`). It exits 0 only when both worker records read as ok. On Windows the interpreter is `backend\venv\Scripts\python.exe`.
4. `./formCAD` boots the engine on 127.0.0.1:8290 and Vite on 127.0.0.1:5290. `python3 skills/formcad-harness/scripts/health_probe.py --wait 30` confirms the engine answers `GET /api/health`.
5. `python3 skills/formcad-harness/scripts/mcp_smoke.py --root .` starts the MCP server on stdio, draws one line, undoes it and exits 0.

A missing kernel or mesher venv is a warning, not a failure: the app still runs its 2D features, and `./formCAD install-kernel` and `./formCAD install-mesher` add the workers.

## Hard stops

These come from `CLAUDE.md` and are checked by the owner's audits. Read `sub-skills/laws-and-logs/SUB-SKILL.md` for the reasoning.

- Edit tracked files only with single-region hand edits made with the editing tool. Never `sed`, `awk`, `patch`, `git apply`, codemods or edit scripts on tracked files. New files are written whole.
- The engine never imports OCP or build123d. Geometry that needs OpenCascade goes to the kernel worker over JSON lines.
- No new dependency without a `NOTICE.md` row first. GPL and AGPL never enter a distributed build. No code from formcompiler or formportal.
- Write no tests of your own unless the owner asks; verification is the checks in `sub-skills/verify/SUB-SKILL.md` and the fixture exits.
- Nothing is pushed or published from here. The `release/` folder is prepared in the tree; the owner pushes.
- No emoji anywhere and no U+2014 in markdown.

## Scripts in this pack

Run them, do not read them into context.

| Script | Purpose |
| --- | --- |
| `scripts/health_probe.py` | Polls the engine and frontend ports; exit 0 when `/api/health` answers, with a hint when it does not. |
| `scripts/mcp_smoke.py` | Boots `./formCAD mcp` with a throwaway settings folder, lists tools, draws and undoes a line; exit 0 on success, 2 when the dispatcher path is wrong. |

## Reference

`references/ports-and-env.md` holds the port table, every `FORMCAD_*` variable with who reads it, and the file names the engine writes into its data folder. Load it when you need an exact variable or a path.

## Evaluations

`evals/evals.json` holds the evaluations and the should-trigger and should-not-trigger phrasings for this pack. Re-run them after any change to a description or a routing table.
