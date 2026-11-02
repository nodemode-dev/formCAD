<p align="center">
  <img src="assets/formcad_icon.png" alt="FormCAD logo" width="160" />
</p>

<h1 align="center">FormCAD</h1>

<p align="center"><b>The CAD studio of the form family: 2D drafting, parametric parts, NURBS surfaces & automation in one open desktop app.</b></p>

<p align="center">
  <img src="https://img.shields.io/badge/version-v0.6.0-f97316" alt="version v0.6.0" />
  <img src="https://img.shields.io/badge/Node.js-20.19%2B-339933?logo=nodedotjs&logoColor=white" alt="Node.js 20.19+" />
  <img src="https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white" alt="Python 3.12+" />
  <img src="https://img.shields.io/badge/license-Apache--2.0-555555" alt="license Apache-2.0" />
</p>

## What it is

FormCAD is a desktop CAD app for macOS, Linux & Windows, built in the image of its siblings formvis (image) & formmorpheus (animation). One `.fcad` project holds a full 2D drafting database w/ layouts & plotting, parametric part features on an OpenCascade kernel, NURBS curves & surfaces, & sketches w/ constraints & equations, all driven by one engine that you can also run headless, script in LISP or Python, or hand to an agent over MCP. Instead of SolidWorks, Fusion, Rhino, Grasshopper and CADcraft. The OpenCascade kernel runs as a separate program the app downloads & verifies, so the app itself stays Apache-2.0.

**Stack:** vanilla TypeScript + Vite + three.js · Python + FastAPI · OpenCascade 8 worker · Tauri 2 · **Scale:** v0.6.0, phases 0 to 15 of 43 landed, 16 to 18 in progress (about 500 engine commands; drafting floor taken from a clean-room functional study, never from another product's code)

## Highlights

- **Every 2D command** draw, modify, arrays, hatch & gradient w/ islands, regions, text w/ right-to-left & Arabic shaping, 69 dimension variables w/ associativity, multileaders, tables w/ formulas
- **Drafting aids** object snaps w/ tracking, polar, ortho, isometric, grips in five modes, dynamic input, selection by window, crossing, fence & polygon
- **Blocks & references** attributes, the Block Editor, dynamic blocks, in-place editing, external references w/ relative paths, nesting & clipping
- **Layers, layouts & plotting** layer states & filters, viewports w/ their own scale & layer overrides, page setups, plot styles, PDF w/ layers & searchable text, PNG & SVG
- **Interchange** DXF R12 to R2018 checked entity by entity, SVG import, STEP & IGES through the kernel, DWG through a converter you install
- **Parametric sketches** geometric & dimensional constraints, status colours, a conflict explainer that refuses over-defining dimensions, parameters w/ units & equations
- **3D on OpenCascade** solids, booleans w/ diagnostics, per-face meshes, seven display modes, a view cube, named views & construction planes
- **Automation** a LISP dialect w/ 188 builtins, scripts, a macro recorder, Python macros in an isolated process, hashed plugins, a headless CLI & an MCP server for agents
- **The form family shell** the same splash & reveal, title bar, menus, Home screen, Preferences & status bar as formvis, w/ 28 shared themes & zero flash on load

## Quick Start

### Requirements

Node 20.19+ or 22.12+, Python 3.12+. Desktop builds also need Rust (`https://rustup.rs`). `./formCAD doctor` checks them.

### macOS & Linux

```shell
chmod +x formCAD_oc_install formCAD build_app
./formCAD_oc_install          # engine venv & interface packages
./formCAD install-kernel      # optional: the OpenCascade worker for 3D, in kernel/venv
./formCAD                     # engine & interface together
```

Desktop app:

```shell
./formCAD desktop dev
./build_app
```

### Windows

```shell
formCAD_oc_install.bat
formCAD.bat
build_app.bat
```

### Ports

| Service | URL | Notes |
|---|---|---|
| Frontend | http://127.0.0.1:5290 | Vite dev server, `server.host` false, strict port |
| Preview | http://127.0.0.1:5291 | `vite preview` of the built interface |
| Backend | http://127.0.0.1:8290 | FastAPI engine, loopback only, per-start token & Origin check; the desktop app picks a free port |

## Configuration

| Variable | Purpose |
|---|---|
| `FORMCAD_DATA_DIR` | where the engine keeps settings, sessions, autosaves & the kernel (default: the platform's app data folder) |
| `FORMCAD_LIBRARY_DIR` | a different folder for the drawing library |
| `FORMCAD_PORTABLE` | `1` keeps all data beside the app |
| `FORMCAD_PORT` | the engine port (desktop app: 0, a free port) |
| `FORMCAD_CONTROL_PORT` | turns on the local control protocol on this loopback port |
| `FORMCAD_CORS_ORIGINS` | extra interface origins the engine accepts (development only) |
| `FORMCAD_KERNEL` | path to a kernel worker to use instead of the downloaded one |
| `FORMCAD_KERNEL_RELEASE` | the formCAD-binaries release to download & verify |
| `FORMCAD_FONTS` | extra font folders for text |
| `FORMCAD_LOG_LEVEL`, `FORMCAD_LOG_BYTES` | engine log level & log file size cap |
| `FORMCAD_API_DOCS` | `1` turns on the generated API pages |
| `FORMCAD_TARGET`, `FORMCAD_RUST_TOOLCHAIN` | build only: the Rust target triple & toolchain for `./build_app` |

Set them in the shell. No `.env` is read or committed.

## Architecture

```
formCAD/
├── frontend/              the interface (vanilla TS + Vite)
│   ├── src/canvas/        the WebGL2 drafting canvas, input, snaps, grips, constraint glyphs
│   ├── src/view3d/        the three.js 3D view, display modes, view cube, picking
│   ├── src/ui/            the form family shell, panels, dialogs, output, parameters, automation
│   ├── src/io/            the engine client & event stream
│   └── src/styles/        tokens & stylesheets (tokens only, z-index from the scale)
├── backend/               the engine (FastAPI), owns every document, command & geometry
│   ├── app/doc/           the drawing database, undo journal, .fcad container
│   ├── app/cmd/           the command pipeline & every command
│   ├── app/display/       display lists for the interface
│   ├── app/interchange/   DXF, SVG & DWG routing
│   ├── app/output/        PDF, PNG & SVG writers, plot styles
│   ├── app/lisp/          the LISP dialect
│   ├── app/automation/    CLI, MCP, control protocol, macros, plugins
│   ├── app/param/         constraints, sketches & parameters on the in-house solver
│   ├── app/solid/         solids, persistent ids & the binary scene for the 3D view
│   └── app/part/          the part feature tree & rebuild
├── kernel/                the separate OpenCascade worker program (JSON lines on stdio)
├── src-tauri/             the desktop shell (Tauri 2): splash, reveal, title bar, engine sidecar
├── setup/                 install, boot, freeze, desktop & doctor scripts behind ./formCAD
├── fixtures/              sample documents for the acceptance walk-throughs
├── .github/workflows/     CI: typecheck, engine boot, script checks, text lint, three-OS engine freeze, licence scan
├── build_app              the desktop build, start to finish
└── assets/                repo-level art (not wired into the build)
```

## Status

Phases 0 to 15 of the 43-phase plan have landed. v0.2.0 to v0.4.0 built the shell, the drawing database & command line, the drafting canvas, snaps & grips, every Draw & Modify command, arrays, hatch, text & dimensions. v0.5.0 added blocks, references, layers, layouts, DXF, SVG, DWG routing & plotting. v0.6.0 added LISP, scripts, macros, plugins, the CLI & MCP server, the OpenCascade worker w/ a 3D view, & parametric sketches; its audit found a macro-to-plugin escape that was closed before release, so macros & agents now run w/ less trust than the window. Phases 16 to 18 (part features, NURBS curves & surfaces) are being built for v0.7.0. The Linux builds are tested here; macOS & Windows builds are configured but untested, & hardware GPU timings are owed.

## Development

Changes follow the family's rules: single-region hand edits, zero DOM flash, tokens only, no emoji, decisions & removed code in `frontend/HASHOUT_LOG.md` & `backend/HASHOUT_LOG.md`, behaviour from functional specs only. Agent rules live in `CLAUDE.md` & `AGENTS.md`. Commits are Conventional Commits as `nodemode-ai <mackin@nodemode.ai>` w/o attribution trailers.

## Contributors

- nodemode-ai · owner

## Licensing

Apache-2.0, see `LICENSE` & `NOTICE.md`. Copyright 2026 NodeAgentc, Inc.
