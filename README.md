<p align="center">
  <img src="assets/formcad_icon.png" alt="FormCAD logo" width="160" />
</p>

<h1 align="center">FormCAD</h1>

<p align="center"><b>The CAD studio of the form family: 2D drafting, parametric parts, NURBS surfaces & automation in one open desktop app.</b></p>

<p align="center">
  <img src="https://img.shields.io/badge/version-v0.11.0-f97316" alt="version v0.11.0" />
  <img src="https://img.shields.io/badge/Node.js-20.19%2B-339933?logo=nodedotjs&logoColor=white" alt="Node.js 20.19+" />
  <img src="https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white" alt="Python 3.12+" />
  <img src="https://img.shields.io/badge/license-Apache--2.0-555555" alt="license Apache-2.0" />
</p>

## What it is

FormCAD is a desktop CAD app for macOS, Linux & Windows, built in the image of its siblings formvis (image) & formmorpheus (animation). One `.fcad` project holds a full 2D drafting database w/ layouts & plotting, parametric part features on an OpenCascade kernel, NURBS curves & surfaces, & sketches w/ constraints & equations, all driven by one engine that you can also run headless, script in LISP or Python, or hand to an agent over MCP. Instead of SolidWorks, Fusion, Rhino, Grasshopper and CADcraft. The OpenCascade kernel runs as a separate program the app downloads & verifies, so the app itself stays Apache-2.0.

**Stack:** vanilla TypeScript + Vite + three.js · Python + FastAPI · OpenCascade 8 worker · Tauri 2 · **Scale:** v0.11.0, phases 0 to 30 of 43 landed (about 660 engine commands, about 185 graph nodes; drafting floor taken from a clean-room functional study, never from another product's code)

## Highlights

- **Every 2D command** draw, modify, arrays, hatch & gradient w/ islands, regions, text w/ right-to-left & Arabic shaping, 69 dimension variables w/ associativity, multileaders, tables w/ formulas
- **Drafting aids** object snaps w/ tracking, polar, ortho, isometric, grips in five modes, dynamic input, selection by window, crossing, fence & polygon
- **Blocks & references** attributes, the Block Editor, dynamic blocks, in-place editing, external references w/ relative paths, nesting & clipping
- **Layers, layouts & plotting** layer states & filters, viewports w/ their own scale & layer overrides, page setups, plot styles, PDF w/ layers & searchable text, PNG & SVG
- **Interchange** DXF R12 to R2018 checked entity by entity, SVG import, STEP AP203, AP214 & AP242 w/ semantic PMI, IGES & 3DM through the kernel, STL, OBJ, PLY, 3MF & GLB meshes, DWG through a converter you install
- **Parametric sketches** geometric & dimensional constraints, status colours, a conflict explainer that refuses over-defining dimensions, parameters w/ units & equations
- **3D on OpenCascade** solids, booleans w/ diagnostics, per-face meshes, seven display modes, a view cube, named views & construction planes
- **Parametric parts** a feature tree w/ rollback, 20 feature types, references that survive edits, configurations, design tables & mass properties
- **NURBS curves & surfaces** blend curves to G3, blend & match surfaces to G2, seam continuity badges, zebra, curvature, draft & deviation analysis, a gumball
- **Assemblies & drawings** components w/ safe file references, 13 mate kinds w/ DOF & conflict explanations, motion, explode & interference; drawing views in first or third angle w/ sections & details, dimensions that follow the model, tolerance frames, balloons, BOM tables & title blocks
- **Motion, vault & rendering** joints & motion studies w/ contact stops & dynamics, a local vault w/ branches, merges & lifecycle, path-traced renders up to 4K & storyboard videos
- **Forms, meshes & plastic parts** subdivision forms w/ creases converted to closed solids, mesh repair, reduce, remesh & mesh to solid, plastic features & wall checks from cited rules
- **Sheet metal** flanges, hems, jogs & reliefs from one rule, K-factor, allowance or deduction bends, flat patterns w/ bend notes & DXF for cutting or bending
- **The graph** a node editor w/ data trees & matching, about 185 nodes, preview & bake, loops, an optimizer, graphs run headless from the CLI, HTTP or MCP, & node plugins
- **Automation** a LISP dialect w/ 188 builtins, scripts, a macro recorder, Python macros in an isolated process, hashed plugins, a headless CLI & an MCP server for agents
- **The form family shell** the same splash & reveal, title bar, menus, Home screen, Preferences & status bar as formvis, w/ 28 shared themes & zero flash on load

## Quick Start

### Requirements

Node 20.19+ or 22.12+, Python 3.12+. Desktop builds also need Rust (`https://rustup.rs`). `./formCAD doctor` checks them. Platform note: dynamics runs use MuJoCo, which publishes no macOS Intel wheel; on an Intel Mac joints & motion studies still work & the dynamics command says it is unavailable.

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
| `FORMCAD_HOST` | the address the engine binds (default `127.0.0.1`); anything but loopback exposes the engine to the network & is not supported |
| `FORMCAD_DIST` | a built interface folder for `./formCAD serve` to serve instead of `frontend/dist` |
| `FORMCAD_CONTROL_PORT` | turns on the local control protocol on this loopback port |
| `FORMCAD_CORS_ORIGINS` | extra interface origins the engine accepts (development only) |
| `FORMCAD_KERNEL` | path to a kernel worker to use instead of the downloaded one |
| `FORMCAD_KERNEL_RELEASE` | the formCAD-binaries release to download & verify |
| `FORMCAD_FONTS` | extra font folders for text |
| `FORMCAD_LOG_LEVEL`, `FORMCAD_LOG_BYTES` | engine log level & log file size cap |
| `FORMCAD_API_DOCS` | `1` turns on the generated API pages |
| `FORMCAD_TARGET`, `FORMCAD_RUST_TOOLCHAIN` | build only: the Rust target triple & toolchain for `./build_app` |
| `FORMCAD_BUNDLES`, `FORMCAD_CARGO_TARGET` | build only: the bundle kinds to make & a separate cargo target folder for `./build_app` |
| `FORMCAD_BACKEND_PORT` | development only: the engine port the Vite dev server proxies to (default 8290) |

Set them in the shell. No `.env` is read or committed.

## Architecture

```
formCAD/
├── frontend/              the interface (vanilla TS + Vite)
│   ├── src/canvas/        the WebGL2 drafting canvas, input, snaps, grips, constraint glyphs
│   ├── src/view3d/        the three.js 3D view, display modes, view cube, picking, curve & seam layers
│   ├── src/part/          the feature tree, feature panels, configurations & materials
│   ├── src/u8/            the gumball, analysis panels, 3D snaps & the assembly panels
│   ├── src/draw/          drawing views & their annotation tools on layout sheets
│   ├── src/sheet/         sheet metal rule, panels, flat pattern display, cut list & flat DXF
│   ├── src/graph/         the graph editor: node canvas, wires, search, tree tooltips
│   ├── src/graphx/        in-node widgets, node palette, bake, optimizer, run dialogs, 3D preview
│   ├── src/p10/           interchange dialogs, PMI notes, the Form workspace, mesh tools & the plastic panel
│   ├── src/p11/           joints, motion studies, dynamics & the vault panel
│   ├── src/render/        path-traced render mode, render dialog & tiled final frames
│   ├── src/an1/           storyboards, illustration styles & video export
│   ├── src/ui/            the form family shell, panels, dialogs, output, parameters, automation
│   ├── src/io/            the engine client & event stream
│   └── src/styles/        tokens & stylesheets (tokens only, z-index from the scale)
├── backend/               the engine (FastAPI), owns every document, command & geometry
│   ├── app/doc/           the drawing database, undo journal, .fcad container
│   ├── app/cmd/           the command pipeline & every command
│   ├── app/display/       display lists for the interface
│   ├── app/interchange/   DXF, SVG, DWG & 3DM routing
│   ├── app/output/        PDF, PNG & SVG writers, plot styles
│   ├── app/lisp/          the LISP dialect
│   ├── app/automation/    CLI, MCP, control protocol, macros, plugins
│   ├── app/param/         constraints, sketches & parameters on the in-house solver
│   ├── app/solid/         solids, persistent ids & the binary scene for the 3D view
│   ├── app/part/          the part feature tree & rebuild
│   ├── app/bodies/        multibody, reference geometry, configurations, materials & mass properties
│   ├── app/nurbs3d/       NURBS curve construction, blends & continuity
│   ├── app/analysis/      zebra, curvature, draft & deviation values & colour ramps
│   ├── app/gumball/       the gumball frame & its move, rotate & scale operations
│   ├── app/meshes/        mesh entities, repair, STL & OBJ
│   ├── app/assembly/      assemblies, component references, patterns, configurations & BOM
│   ├── app/mates/         the 3D mate solver, motion, exploded views & interference
│   ├── app/views/         drawing views from hidden line removal
│   ├── app/drawann/       drawing annotation: tolerance frames, datums, balloons, BOM tables, title blocks
│   ├── app/sheetmetal/    sheet metal rule, bend list, bend maths, flat patterns & flat DXF
│   ├── app/graph/         data trees, matching, the node SDK, solver, nodes, bake, loops, optimizer, runner
│   ├── app/pmi/           semantic PMI: dimensions, tolerances & datums on faces & edges
│   ├── app/subd/          subdivision forms w/ creases & their conversion to B-rep
│   ├── app/plastic/       plastic part rules, features & checks
│   ├── app/joints/        joints, motion studies, contact sets & dynamics
│   ├── app/vault/         the local content-addressed vault, merges & lifecycle
│   ├── app/render/        appearances, environments, render settings & final-frame jobs
│   └── app/anim/          storyboards & frame sampling for video
├── kernel/                the separate OpenCascade worker program (JSON lines on stdio)
├── src-tauri/             the desktop shell (Tauri 2): splash, reveal, title bar, engine sidecar
├── setup/                 install, boot, freeze, desktop & doctor scripts behind ./formCAD
├── fixtures/              sample documents for the acceptance walk-throughs
├── docs/                  contracts other tools rely on (`ASSEMBLY_SCHEMA.md`, `GRAPH_FORMAT.md`, `NODE_SDK.md`)
├── .github/workflows/     CI: typecheck, engine boot, script checks, text lint, three-OS engine freeze, licence scan
├── build_app              the desktop build, start to finish
└── assets/                repo-level art (not wired into the build)
```

## Status

Phases 0 to 30 of the 43-phase plan have landed. v0.2.0 to v0.4.0 built the shell, the drawing database & command line, the drafting canvas, snaps & grips, every Draw & Modify command, arrays, hatch, text & dimensions. v0.5.0 added blocks, references, layers, layouts, DXF, SVG, DWG routing & plotting. v0.6.0 added LISP, scripts, macros, plugins, the CLI & MCP server, the OpenCascade worker w/ a 3D view, & parametric sketches; its audit found a macro-to-plugin escape that was closed before release, so macros & agents now run w/ less trust than the window. v0.7.0 added parametric parts (a feature tree w/ extrude, revolve, fillet, chamfer, shell, draft, patterns, mirror, sweep, loft, rib & holes, references that survive upstream edits, multibody, configurations, design tables, materials & mass properties), NURBS curves w/ blends to G3, & surfaces w/ G2 blends, seam checks & boolean diagnostics. v0.8.0 added surface analysis, the gumball, 3DM through the kernel (trimmed faces are flagged, STEP keeps them better), meshes w/ STL & OBJ, assemblies w/ mates, motion, explode & interference, & drawings from 3D w/ annotation. v0.9.0 added sheet metal (flanges, hems, jogs, reliefs, convert, flat patterns w/ DXF for cutting or bending) & the graph: a node editor w/ data trees & matching, about 185 nodes, preview & bake, loops, an optimizer, a headless runner (CLI, HTTP, MCP) & node plugins; v0.10.0 added STEP AP203, AP214 & AP242 w/ semantic PMI, IGES, 3MF, GLB & PLY w/ unit checks, subdivision form modelling converted to closed solids, a mesh workspace (repair, reduce, remesh, sections, booleans, mesh to solid) & plastic part rules w/ cited values; v0.11.0 added joints, motion studies w/ contact stops & dynamics, a local vault w/ branches & merges, path-traced rendering up to 4K & storyboards exported to video; next come machining, multi-axis & cutting, & additive (Phases 31 to 33). The Linux builds are tested here; macOS & Windows builds are configured but untested, & hardware GPU timings are owed.

## Development

Changes follow the family's rules: single-region hand edits, zero DOM flash, tokens only, no emoji, decisions & removed code in `frontend/HASHOUT_LOG.md` & `backend/HASHOUT_LOG.md`, behaviour from functional specs only. Agent rules live in `CLAUDE.md` & `AGENTS.md`. Commits are Conventional Commits as `nodemode-ai <mackin@nodemode.ai>` w/o attribution trailers.

## Contributors

- nodemode-ai · owner

## Licensing

Apache-2.0, see `LICENSE` & `NOTICE.md`. Copyright 2026 NodeAgentc, Inc.
