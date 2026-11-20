---
name: graph-and-headless
description: Runs FormCAD node graphs, scripts and the headless CLI. Use for formcad_graph_run, graph run or optimize, convert, run steps, macros and plugins.
---

# Graph and headless

CLI (`formcad-engine`, or `backend/venv/bin/python backend/formcad_engine.py` in a checkout): `info FILE`, `convert IN OUT` (by extension pdf png svg dxf dwg fcad, `--in-place` to overwrite), `run [FILE...]` with ordered steps `--new --sample NAME --script TEXT --script-file F --command "id {json}" --save PATH --export PATH`, `commands [FILTER]`, `mcp`, `perf`, `sample NAME OUT`, `plugin seal|list`, `macro list`, `graph run|io|optimize`. Exit 0 success, 1 a step failed, 2 usage; graph run adds 3 missing node, 4 timeout, 5 cancelled. `--settings-dir ''` is a throwaway data folder.

Graphs: `graph io FILE.graph` prints inputs and outputs (facade.graph: columns, rows, reach, attr_x, attr_z, max_open, gap, panel_limit in; open_area, panel_count, fitness out). `graph run FILE.graph --in columns=8 --out json --bake OUT.fcad --doc BASE.fcad --seed N --timeout SEC --strict`. `graph optimize FILE.graph --gene NODE --fitness NODE:PORT --maximise --method evolution|annealing --budget N --write OUT.graph`. MCP: `formcad_graph_run` with `graph_path` or inline `graph`, `inputs`, `bake_path`; paths must be in granted folders. In a document: `graphrun graphbake graphimport graphexport`.

Python macros run in an isolated process (`run --python-macro F --grant-files DIR`); agents cannot run or save macros. Docs: `docs/GRAPH_FORMAT.md`, `docs/NODE_SDK.md`.
