---
name: verify
description: Proves a FormCAD change with the real checks, in order, and mirrors CI. Use for doctor, selfcheck, compileall, health probe, typecheck, MCP smoke, headless CLI runs and the text lint.
---

# Verify

The owner forbids self-written tests until asked (law 10 in `CLAUDE.md`; a `TEST_PLAN.md` goes in the planning sidecar instead). Verification is therefore the set of checks that already exist, run for real, with the numbers reported.

## Tiers, cheapest first

1. Toolchain: `./formCAD doctor`. Exit 0 means no FAIL line.
2. Compile: from `backend/`, `python -m compileall -q app formcad_engine.py` (CI does the same).
3. Selfcheck: `backend/venv/bin/python backend/formcad_engine.py --selfcheck`. Read the JSON. `app` must be `ok`, `routers` is the number of mounted routers, `kernel_record` and `mesher_record` must be `ok`, `sim_solvers` counts registered solvers, and any library reading `missing: ...` means a dependency was not installed or not frozen. Run it right after adding a router line, a command module or a worker registration; other agents boot the engine from the same tree.
4. Boot and probe: boot the engine, then `scripts/health_probe.py --wait 30`.
5. Interface: from `frontend/`, `npm run typecheck` (`tsc --noEmit`), and `npm run build` for the production build. For a UI change also verify zero flash under 4x CPU and network throttling in a real browser (law 2); describe what you observed, do not claim it unrun.
6. MCP: `scripts/mcp_smoke.py --root .` from the pack root. A wrong `--root` exits 2 with the missing dispatcher path.
7. Headless CLI, through the same interpreter as the engine (`backend/venv/bin/python backend/formcad_engine.py` stands for `formcad-engine`): `info FILE`, `convert IN OUT`, `run ... --command "id {json}"`, `commands FILTER`, `graph run FILE.graph`, `plugin list`, `macro list`. Exit codes: 0 success, 1 a command failed, 2 usage; `graph run` adds 3 missing node type, 4 timeout, 5 cancelled.
8. Fixture exits: pick the fixture for the feature (see `sub-skills/fixtures-and-exits/SUB-SKILL.md`), run it through the engine and compare the stated numbers.
9. Text lint, the CI script: no U+2014 in tracked markdown and no emoji in tracked text; shell scripts parse with `bash -n` and keep mode 100755.

## What CI runs

`.github/workflows/ci.yml` has jobs for the frontend (`npm ci`, `tsc --noEmit`, `npm run build`), the backend (compile, selfcheck, boot and curl `/api/health`), scripts (shell syntax, executable bits, the em dash and emoji lint), and a three-OS engine freeze with a licence scan. Match these locally before reporting a change as verified.

## Reporting

State which tiers ran and which did not, with the literal exit codes and the selfcheck JSON fields you relied on. A tier you could not run (no browser for the throttling check, no macOS or Windows host) is reported as not run, never as passed.
