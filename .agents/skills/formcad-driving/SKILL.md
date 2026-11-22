---
name: formcad-driving
description: "Operates FormCAD through its MCP server (formcad-engine mcp) and headless CLI to draft, model parts, build sheet metal, assemble, draw, run graphs, simulate, manufacture and exchange files. Use when asked to draw, model, dimension, mate, export or check a design in FormCAD, register the formcad MCP server, grant folders to an agent, or run a .graph or .fcad headless. Covers the granted-folder trust model, the command catalogue by workspace and recipes with verified tool names. Not for changing FormCAD source code, installing or freezing it (formcad-harness)."
license: Apache-2.0
metadata:
  product: FormCAD
  pack-version: "0.23.0"
  audience: operating agent
---

# Driving FormCAD

FormCAD is a CAD engine with one document model: 2D drafting, parametric parts, sheet metal, assemblies, drawings, graphs, simulation, manufacture and electronics all live in `.fcad` files and are driven by the same commands. An agent reaches them through the MCP server or the CLI. This pack gives the order of operations and the traps; tool names and arguments come from the live server.

## Route first

| Task | Load |
| --- | --- |
| Register the server, the first call (`formcad_status`), modes, granted folders, jobs, results, what is barred | `sub-skills/connect-and-trust/SUB-SKILL.md` |
| Working from a tab of the agent dock, beside a person in the open window | `sub-skills/agent-dock/SUB-SKILL.md` |
| A picture, a rendered image, a turntable, a video, an exploded view | `sub-skills/render-and-animation/SUB-SKILL.md` |
| Versions, branches, check in and out, diff, merge, comments, where-used | `sub-skills/vault/SUB-SKILL.md` |
| 2D drawing, layers, dimensions, hatch, blocks, queries | `sub-skills/drafting-2d/SUB-SKILL.md` |
| Parts, sketches, features, surfaces, forms, meshes, plastic, weldments, molds | `sub-skills/parts-and-surfaces/SUB-SKILL.md` |
| Sheet metal and flat patterns | `sub-skills/sheet-metal/SUB-SKILL.md` |
| Assemblies, mates, joints, motion, vault | `sub-skills/assemblies-and-motion/SUB-SKILL.md` |
| Drawing views, annotation, BOM, plotting, PDF, toolbox, inspection | `sub-skills/drawings-and-output/SUB-SKILL.md` |
| Graphs, headless runs, the CLI, scripts | `sub-skills/graph-and-headless/SUB-SKILL.md` |
| Simulation, topology, generative, flow | `sub-skills/simulation-and-generative/SUB-SKILL.md` |
| CAM, cutting, nesting, slicing | `sub-skills/manufacture/SUB-SKILL.md` |
| STEP, IGES, 3MF, GLB, PMI, electronics, harness, pipes | `sub-skills/interchange-and-electronics/SUB-SKILL.md` |

## Core loop

0. `formcad_status` first: it says whether the 3D kernel and the mesher are installed and which folders are granted. Plan only what it allows.
1. Discover: `formcad_list_commands` (with a filter), or run `scripts/list_tools.py --filter [text]` for required and known arguments. Never invent a tool or argument; `references/command-catalogue.md` lists every command by group but the live list wins.
2. Create or open a document with `formcad_new_document` and an explicit `template` (`metric`, `part`, `assembly`, `drawing-mm-a3`, `surface`, `form`, `graph`, `ecad`; a bare call is not metric).
3. Act with `cmd_[id]` tools (structured arguments, no prompts; a dot or dash in the id is an underscore in the tool name), with `formcad_execute` for any command the tool list does not show, or with `formcad_command_line` (typed like a person; spaces act as Enter). Studies and toolpaths run as jobs: `formcad_sim_start` or `formcad_cam_start`, then poll `formcad_job_status`.
4. Check every result: `ok`, `error`, `output`. A part feature returns a `state` with status ok or error; read it before the next step.
5. Verify by measurement: `formcad_inspect`, `formcad_query_entities`, `formcad_render`, `cmd_bodymass`, check commands. Edits are undoable with `formcad_undo`.
6. Save and export only inside granted folders.

## Traps

- A `cmd_` tool whose schema lists only `inputs` has hidden argument names: if it fails with an internal error, type it with `formcad_command_line`.
- Feature parameters go at top level (for example `depth1`, `thickness`) or in `params`; scanned names in tool schemas are hints.
- Refusals are by design (folders, barred commands, size caps lower for agents). Report them; do not hunt for a way around.
- Units follow the document template; state them in every plan.

## Scripts and reference

`scripts/list_tools.py` starts the server and prints tools with required arguments (exit 2 when the dispatcher path is wrong). `references/command-catalogue.md` is the generated command list by registry group. `evals/evals.json` holds evaluations and trigger phrasings.
