---
name: manufacture
description: Generates toolpaths, cutting plans, nests and 3D-print slices in FormCAD. Use for CAM setups, tools, operations, posts, G-code, turning, probing and slicing.
---

# Manufacture

CAM: `camsetup` (stock, WCS), `camtool`, `camop`, `camgenerate`, `camtime`, `cammachine`, `camexport` (`setup`, `ops`, `post`, `out`), `camturnprofile`, `camprobe`, `camprocess`, `camnest`, `camnestexport`. Posts: LinuxCNC and grbl; Marlin for printing. Additive: `slice`, `orientstudy`, `arrangeplate`, `additiveexport`. Tool feeds are typed by the user, no vendor data ships. Fixtures: `fixtures/cam/pocket-part.fcad`, `five-axis.fcad`, `sheet-set/`, `additive/part.fcad`.

Cost, DFM, design check and sustainability are not commands and have no MCP tools: `list_tools.py --filter cost` finds nothing, and that is correct. They are engine routes under `/api/docs/[id]/costing/` (`profile`, `estimate`, `dfm`, `dfm/rules`, `rules`, `check`, `emissions`, `sustainability`, `export`), reachable from the window panels "Cost and DFM" and "Design check" or by an operator calling the engine with the session token. Macros may read them but never write; `export` is barred for macros. Rates, DFM thresholds, user rules (at most 100) and emission factors live in the document header, so edits are undoable and saved. No rate or factor ships unsourced: the profile starts empty or user typed, and every number in an estimate names where it came from. An agent should tell the user to run these in the window and read the result back from the saved report, not assume a tool exists.

Order: setup, tools, operations, generate, read time and any gouge or collision report, then export to a granted path. State machine limits honestly.
