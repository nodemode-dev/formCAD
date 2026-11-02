# formCAD

![version](https://img.shields.io/badge/version-0.5.0-f97316) ![license](https://img.shields.io/badge/license-Apache--2.0-3a7bff) ![stage](https://img.shields.io/badge/stage-early%20build-717072)

FormCAD: parametric solids, NURBS and SubD surfaces, 2D drafting, manufacturing, simulation and visual programming in one open desktop app. Instead of SolidWorks, Fusion, Rhino, Grasshopper and CADcraft.

Part of the NodeMode form family: built for macOS, Windows and Linux by formcompiler, installed and connected to agents through formportal.

## Status

Early build. 2D drafting runs: every Draw and Modify command, arrays, hatches, regions, text, dimensions, leaders and tables, with snaps, tracking, selection, grips, the Properties palette and the style managers; blocks with attributes, the Block Editor, external references, layers, layouts and viewports; DXF open and save, SVG import, DWG through a converter you install; plotting to PDF, PNG and SVG. Automation, scripting and the 3D viewport arrive next. The plan lives in the planning sidecar that ships beside each repo version.

## Quick start

```
./formCAD_oc_install     # engine venv and interface packages
./formCAD install-kernel # optional: the OpenCascade worker for 3D, in kernel/venv
./formCAD                # engine on 127.0.0.1:8290, interface on 127.0.0.1:5290
./build_app              # desktop app for this machine
```

On Windows use `formCAD_oc_install.bat`, `formCAD.bat` and `build_app.bat`.

| Service | Address |
| --- | --- |
| Interface (dev) | http://127.0.0.1:5290 |
| Interface (preview) | http://127.0.0.1:5291 |
| Engine (dev) | http://127.0.0.1:8290 (the desktop app picks a free port) |

The engine accepts only loopback requests carrying its per-start token. The 3D kernel is a separate program: in the desktop app it downloads on first use from the formCAD-binaries releases and every file is checked against a SHA-256 record before it is installed.

## Layout

| Folder | Holds |
| --- | --- |
| `frontend/` | interface: vanilla TypeScript and Vite |
| `backend/` | engine: FastAPI, the drawing database, commands, system variables |
| `kernel/` | the separate OpenCascade worker program |
| `src-tauri/` | desktop shell |
| `setup/` | install, boot, freeze and build scripts |
| `fixtures/` | sample documents used for acceptance walk-throughs |

## What it will do

| Workspace | Covers |
| --- | --- |
| Drafting | 2D drawing and editing, annotation, dimensions, blocks, layouts, plotting, DXF |
| Part | sketches with constraints, features, multibody parts, configurations, mass properties |
| Assembly | components, mates, exploded views, interference, bills of materials |
| Surface | NURBS curves and surfaces, continuity tools, analysis, SubD and meshes |
| Drawing | sheets generated from 3D, sections, details, GD&T, title blocks |
| Graph | node-based visual programming with data trees, loops and optimization |
| Form | SubD and T-spline-style freeform modeling |
| Manufacture | milling, turning, multi-axis, cutting and nesting toolpaths, additive slicing |
| Simulate | stress, modal, thermal, buckling, nonlinear, flow, molding, generative design |
| Render | path-traced rendering, animation and exploded storyboards |
| Electronics | schematics, boards, routing and harnesses |

## Stack

| Layer | Choice |
| --- | --- |
| Shell | Tauri 2 |
| Interface | vanilla TypeScript, Vite, three.js |
| Engine | Python 3.12, FastAPI, sidecar process |
| Geometry | own exact 2D geometry in the engine; OpenCascade through OCP and build123d in a separate worker program |

## License

Apache-2.0. See `LICENSE` and `NOTICE.md`.

Copyright 2026 NodeAgentc, Inc.
