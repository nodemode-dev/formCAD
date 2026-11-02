# formCAD

![version](https://img.shields.io/badge/version-0.1.0-f97316) ![license](https://img.shields.io/badge/license-Apache--2.0-3a7bff) ![stage](https://img.shields.io/badge/stage-planning-717072)

Parametric solids, NURBS surfaces, 2D drafting and visual programming in one open desktop app. Instead of SolidWorks, Rhino, Grasshopper and CADcraft.

Part of the NodeMode form family: built for macOS, Windows and Linux by formcompiler, installed and connected to agents through formportal.

## Status

Planning. The research and the development plan are done and waiting for review; no application code exists yet. The plan lives in the planning sidecar that ships beside each repo version.

## What it will do

| Workspace | Covers |
| --- | --- |
| Drafting | 2D drawing and editing, annotation, dimensions, blocks, layouts, plotting, DXF |
| Part | sketches with constraints, features, multibody parts, configurations, mass properties |
| Assembly | components, mates, exploded views, interference, bills of materials |
| Surface | NURBS curves and surfaces, continuity tools, analysis, SubD and meshes |
| Drawing | sheets generated from 3D, sections, details, GD&T, title blocks |
| Graph | node-based visual programming with data trees, loops and optimization |

## Stack

| Layer | Choice |
| --- | --- |
| Shell | Tauri 2 |
| Interface | vanilla TypeScript, Vite, three.js |
| Engine | Python 3.12, FastAPI, sidecar process |
| Geometry | OpenCascade through OCP, build123d, manifold3d |

## License

Apache-2.0. See `LICENSE` and `NOTICE.md`.

Copyright 2026 NodeAgentc, Inc.
