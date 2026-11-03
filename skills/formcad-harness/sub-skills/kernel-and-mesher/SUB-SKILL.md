---
name: kernel-and-mesher
description: Explains and repairs the FormCAD OpenCascade kernel worker and Netgen mesher programs. Use when 3D features are refused, a kernel or mesher is not found, a download fails verification, or a simulation study cannot mesh.
---

# Kernel worker and mesher

## The rule that shapes everything

The engine never imports OCP or build123d. All OpenCascade work goes to `formcad-kernel`, a separate program in `kernel/` that the engine starts as a child process and talks to in JSON lines on stdin and stdout: `{"id", "method", "params"}` in, `{"id", "result"}` or `{"id", "error": {"message"}}` out. Kernel units are millimetres; the engine converts at its boundary. The mesher (`mesher/formcad_mesher.py`, program `formcad-mesher`) follows the same protocol and exists separately because the Netgen build it needs (`netgen-occt` 7.8.1) must not share a process with OCP 8.0.1. Both are shipped as separate, replaceable, unpatched programs so the app stays Apache-2.0 and the LGPL libraries stay relinkable.

Worker method tables live in `kernel/README.md` and `mesher/README.md`; method code lives in the `kernel/kernel_*.py` modules, registered in `kernel/formcad_kernel.py`. Without a kernel the app still runs every 2D feature; part, surface, assembly and 3D commands answer with a kernel message.

## How the engine finds a worker

`backend/app/services/kernel.py` `resolve()` tries, in order:

1. `FORMCAD_KERNEL`: a `.py` script (run with the venv python beside it) or an executable. Source label `dev` or `env`.
2. An installed release under `[data folder]/kernel/[release]/`, choosing `FORMCAD_KERNEL_RELEASE` or else the last release folder. Label `installed`.
3. The repository script `kernel/formcad_kernel.py` with `kernel/venv`. Label `dev`.

`backend/app/services/mesher.py` mirrors this with `FORMCAD_MESHER`, `FORMCAD_MESHER_RELEASE` and `mesher/venv`.

## Inspect and repair

| Need | Do |
| --- | --- |
| Is the kernel running | `GET /api/kernel/status` returns `available`, `version`, `installing`, `progress`, `message`. |
| Start the download | `POST /api/kernel/install` (the app does this from its banner). |
| Dev install | `./formCAD install-kernel`, `./formCAD install-mesher`; then `backend/venv/bin/python backend/formcad_engine.py --selfcheck` and read `kernel_record`, `mesher_record`. |
| Talk to a worker by hand | `printf '{"id":1,"method":"hello","params":{}}\n{"id":2,"method":"shutdown","params":{}}\n' | kernel/venv/bin/python kernel/formcad_kernel.py` should print a `result` on the first line. |
| Mesher selfcheck | `mesher/venv/bin/python mesher/formcad_mesher.py --selfcheck` imports `netgen.meshing` and `netgen.occ` and prints versions. |

## Verification of downloads

The desktop app downloads each worker release from formCAD-binaries and verifies every file against `backend/app/data/kernel-licence.json` (and `mesher-licence.json`). In the checkout those records carry a null `release` and an empty `files` list until the owner publishes a release; the record schema is `release/formCAD-binaries/records/SCHEMA.md`. A hash mismatch is a refusal, never a warning to skip. Do not edit a record to make a download pass, and never commit worker binaries.

## Failure patterns

- Kernel message on a 3D command: no worker resolved. Check `FORMCAD_KERNEL`, the data folder, then `kernel/venv`.
- Worker starts then dies: run the `hello` line by hand to see its stderr (the engine discards it).
- Simulation studies refuse to mesh: the mesher venv is missing; install it, or set `FORMCAD_MESHER`.
- Size refusals from the mesher (element estimate against the agent cap) are by design; use a coarser `maxh`.
