---
name: interchange-and-electronics
description: Exchanges STEP, IGES, 3MF, GLB, STL and PMI, and drives electronics, harness and pipe design in FormCAD. Use for import, export, unit warnings, boards, schematics and routing.
---

# Interchange and electronics

Files: `cmd_import` (`path`, `unit`, `options`) and `cmd_export` (`path`, `unit`, `version`, `options`) take STEP AP203, AP214, AP242, IGES, 3MF, GLB, PLY, STL, OBJ, 3DM, DXF; read the unit mismatch warning and report what was dropped. PMI: `pmidim pmidatum pmitol pmiedit pmidelete`. Paths must be granted. Fixtures in `fixtures/interchange/`.

Electronics (document template `ecad`): `schemdraw schemdevice schemwire schemnumber schemwirelist`, the board lives in the pcb routes, and `ecadsync` is window only. Outputs `gerberexport drillexport idfexport boardstep` are barred to agents. Harness `harness harnessexport`; pipes `pipespec piperoute pipefitting pipebender pipecutlist pipeexport`. Fixtures: `ecad/board.fcad`, `route/harness.fcad`.
