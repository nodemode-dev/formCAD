# Architecture

## The pieces

| Piece | Where | Job |
| --- | --- | --- |
| Interface | `frontend/` | vanilla TypeScript and Vite; renders engine state and dispatches commands |
| Engine | `backend/` | FastAPI; owns every document, command and geometry record |
| Kernel worker | `kernel/` | a separate OpenCascade program; talks JSON lines on stdio |
| Mesher | `mesher/` | a separate Netgen program for simulation meshes |
| Shell | `src-tauri/` | Tauri 2 desktop shell, splash, title bar, engine sidecar |
| Setup scripts | `setup/` | install, boot, freeze, desktop, doctor |

## The rules of the split

- The interface never owns geometry. It asks the engine and draws what it gets back.
- The engine never imports the B-rep libraries. Solid work is a request to the kernel worker, one JSON object per line.
- Routers are mounted in one place, the `ROUTERS` list in `backend/app/main.py`.
- Commands are registered modules under `backend/app/cmd/commands/`. A command registered once appears in the menus, the command catalogue, the CLI and the MCP tool list.
- Records for each workspace (parts, studies, setups, boards) live in the document, so undo, redo, save and reopen need no special cases.

## Why separate programs

The OpenCascade kernel and the mesher are under the LGPL. Running them as separate programs the user can replace keeps the app itself Apache-2.0. See [[Licensing-and-Data-Provenance]].

## The engine's folders (selection)

`app/doc` the drawing database and `.fcad` container · `app/cmd` the command pipeline · `app/part` the feature tree · `app/assembly` and `app/mates` assemblies · `app/sheetmetal` · `app/graph` · `app/vault` · `app/render` · `app/cam` and `app/cam3d` · `app/sim`, `app/simnl`, `app/topo`, `app/flow` · `app/gen` · `app/ecad`, `app/pcb`, `app/schem` · `app/automation` the CLI, MCP, control protocol, macros and plugins.

## Data flow of one command

Interface or script or agent sends a command and arguments, the guard decides whether this caller may run it, the runner applies it to the document inside an undo step, the engine publishes an event, and the interface patches the nodes that changed.
