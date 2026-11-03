---
name: fixtures-and-exits
description: Maps FormCAD fixtures to the feature each one proves and the exit numbers to reproduce. Use when choosing a fixture, reproducing a phase exit, checking a regression, or reading fixtures/README.md.
---

# Fixtures and exits

`fixtures/` holds data files, not tests. Each phase of the build ended with an exit: a fixture the engine produces or reads, with numbers measured through the real engine. When you change a feature, open its fixture, redo the exit and compare. `fixtures/README.md` is the full description of each file (what it holds, how it was made, the measured values); read the section for your fixture there before running it, because the numbers below are only the headline.

How to run an exit: open the file through the engine (`formcad-engine info FILE` or `run FILE --command "id {json}"`, or `POST /api/docs/open {"path": ...}` against a booted engine), run the command or route the README names, and compare. Part, assembly and simulation fixtures need the kernel worker, and simulation also needs the mesher. Work on a copy when the exit saves; several fixtures have a `.bak` beside them left by the engine.

| Area | Fixture | Headline exit |
| --- | --- | --- |
| 2D drafting | `draw-all-part1.fcad`, `draw-all-part2.fcad`, `text.fcad`, `hatch.fcad`, `modify-part1.fcad`, `modify-part2.fcad`, `dimensions.fcad`, `leaders-tables.fcad` | One result per command and option; the display route builds an item for every object. |
| DXF | `dxf/survival-r12.dxf` to `dxf/survival-r2018.dxf` | Checked entity by entity (see `dxf/SURVIVAL.md`). |
| Scripting | `scripts/`, `macros/plate.py`, `macros/typed.py`, `lisp/bolt-pattern.lsp` | Macros draw and edit in an open document. |
| Parts | `part-core.fcad` | 13 features all `ok`; changing `plate_w` to 140, 100 and 120 keeps them ok, also after save and reopen. |
| Bodies | `part-adv.fcad` | `GET /api/docs/{id}/bodies/exitcheck` passes within 1e-6 relative on eight bodies. |
| Surfaces | `surface.fcad` | `SEAMCHECK` reports G2 at both seams after reopen. |
| Assemblies | `assembly.fcad` (parts in `assembly/`), `mechanism.fcad` | Four pins patterned on the base holes; sixteen mates on the mechanism. |
| Drawings | `drawing-views.fcad`, `mechanism-drawing.fcad` | Six views at 1:2; a 92 mm edge measures 46.0 mm on paper. |
| Sheet metal | `sheetmetal/channel.fcad`, `sheetmetal/bracket.fcad`, `sheet.fcad` | Channel flat pattern 112.1893794959 mm by 100 mm; the bracket rebuilds seven features. |
| Graph | `graph/facade.graph` with `graph/facade-base.fcad`, `graph/plate-holes.graph` | Headless run and bake give 40 panels, total volume 1230780242.474323 mm3, same as in the editor. |
| Interchange | `interchange/` | `part-pmi.fcad` and `assembly-colours.fcad` round-trip through STEP and 3MF with mass properties kept within the stated tolerance. |
| Forms and meshes | `form.fcad`, `mesh/scan-box-hole.stl`, `plastic/housing.fcad` | Cage converts to a watertight B-rep; the scan repairs to a closed body; the housing checks report its cited rules. |
| Joints and vault | `linkage.fcad`, `vault/part.fcad` with branches A and B | Four-bar matches the closed form to 2.4e-10 rad and stops at 1.0979 s on contact; the merge reports exactly one conflict, `params.depth1` of `F2`. |
| Render and video | `render/scene.fcad`, `mechanism-storyboard.fcad` | A 3840 by 2160 PNG through the headless path; an exploded video of the mechanism. |
| Manufacture | `cam/pocket-part.fcad`, `cam/five-axis.fcad`, `cam/sheet-set/`, `additive/part.fcad` | Posted G-code that simulates gouge-free; a 5-axis path without collision; nested cutting code; a sliced plate with layer count and filament length. |
| Simulation | `sim/cantilever.fcad`, `sim/nonlinear.fcad`, `sim/topo-bracket.fcad`, `sim/pipe.fcad` | Cantilever deflection 1.6000 mm and first frequency 203.85 Hz within 2 percent; topology result removes 55 percent of the mass under 85 MPa; pipe pressure drop 1.5996 Pa against Hagen-Poiseuille 1.6002 Pa. |
| Electronics and routing | `ecad/board-schematic.fcad`, `ecad/board.fcad`, `ecad/board-linked.fcad` with `ecad/enclosure.fcad`, `route/harness.fcad`, `route/piping.fcad`, `route/schematic.fcad` | Board routes 7 of 7 nets with 0 DRC errors; the harness flattens to a formboard layout with a wire list. |

Fixtures for later phases (weldments, mold, toolbox) land in `fixtures/weld/`, `fixtures/mold/` and `fixtures/toolbox/`; list the folder before assuming a fixture is absent.

## Rules for fixtures

- A fixture is written by the engine through its own commands or routes, never hand edited (several are binary containers). Add a new one with one `fixtures/README.md` row, one Edit.
- Keep the README row factual: what it holds, how it was made, the measured numbers. A number you did not measure is not written.
- Do not commit a fixture that embeds third-party data without its source and licence recorded.
