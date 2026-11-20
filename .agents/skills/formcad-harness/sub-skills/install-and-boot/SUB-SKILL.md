---
name: install-and-boot
description: Installs, boots and diagnoses a FormCAD checkout through the ./formCAD dispatcher and setup scripts. Use for a fresh clone, install, doctor, boot, ports, environment variables, the data folder and the token guard.
---

# Install and boot

## Prerequisites

`./formCAD doctor` is the authority; its rules live in `setup/doctor` and `setup/lib.sh`. Today: Node 22 or newer with npm, Python 3.12 or newer, and for desktop builds Rust (`https://rustup.rs`) plus `libwebkit2gtk-4.1-dev` on Linux. The README states a looser Node range; follow the doctor. On an Intel Mac there is no MuJoCo wheel, so dynamics reports itself unavailable while joints and motion studies still work.

## Install order

| Command | Effect |
| --- | --- |
| `chmod +x formCAD formCAD_oc_install build_app` | One time, on macOS and Linux. |
| `./formCAD install` | Same as `./formCAD_oc_install`: engine venv (`backend/venv`), then the kernel dev venv, the mesher dev venv, then frontend packages. |
| `./formCAD install --lite` | Skips the kernel and mesher venvs. 2D features work without them. |
| `./formCAD install-kernel` | Creates `kernel/venv` from `kernel/requirements_kernel.txt`. Retry it alone if the first run failed. |
| `./formCAD install-mesher` | Creates `mesher/venv` from `mesher/requirements_mesher.txt`. Simulation studies need it. |
| `./formCAD install-desktop` | Installs PyInstaller and checks the Rust and Tauri toolchain. |

Windows uses the `.bat` twins: `formCAD_oc_install.bat`, `formCAD.bat`, `build_app.bat`. Kernel and mesher install failures print a message and do not abort the install; read the line, then rerun the single install command.

## Boot

| Command | Starts |
| --- | --- |
| `./formCAD` (also `boot`, `dev`) | Engine on 8290 and Vite on 5290 together; Ctrl-C stops both. |
| `./formCAD backend` | Engine only, `uvicorn app.main:app --reload`, host from `FORMCAD_HOST`, port from `FORMCAD_PORT`. |
| `./formCAD frontend` | Vite only. |
| `./formCAD build` then `./formCAD serve` | Production build of the interface into `frontend/dist`, served by the engine on 8290. |
| `./formCAD desktop dev` | The Tauri shell with the engine as a sidecar. |
| `./formCAD mcp` | The MCP server on stdio (see the formcad-driving pack). |

After booting, `python3 skills/formcad-harness/scripts/health_probe.py --wait 30` waits for `GET /api/health`. A busy port is reported by the doctor as a warning; choose another with `FORMCAD_PORT` and `FORMCAD_BACKEND_PORT` instead of killing the owner of the port.

## Data folder and trust

The engine keeps its state in `FORMCAD_DATA_DIR` (or the platform folder, or beside the app with `FORMCAD_PORTABLE=1`). For a throwaway run use a temporary `FORMCAD_DATA_DIR`, or the CLI flag `--settings-dir ''` that gives the headless CLI and MCP server a throwaway folder. Never point a test run at the owner's real data folder.

`references/ports-and-env.md` in the pack root lists every variable, the files in the data folder and the guard rules. Read it when a probe gets 401 or 403, or when you need the token file.

## Common failures

- `backend venv missing, run ./formCAD install`: the dispatcher sources `backend/venv`; run the install.
- Doctor says node is too old: install Node 22; do not edit `setup/lib.sh` to lower the bar.
- Interface loads but nothing works: the engine is not on 8290, or the Vite proxy points elsewhere (`FORMCAD_BACKEND_PORT`).
- 3D commands answer with a kernel message: see `sub-skills/kernel-and-mesher/SUB-SKILL.md`.
