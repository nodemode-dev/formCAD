---
name: simulation-and-generative
description: Runs FormCAD simulation, topology and generative studies and flow estimates. Use for static, modal, thermal, buckling, nonlinear, optimization and result reports.
---

# Simulation and generative

Needs the kernel and the mesher. Commands: `simstudy` (type, body, material, loads, fixtures, maxh, name), `simmaterial` (library id or cited values), `simload`, `simfixture`, `simcontact`, `simcontrol`, `simrun` (`study`, `mode` run or mesh), `simprobe`, `simreport` (`study`, `path`, `format`). Topology `toposhape toporun topoapply`; generative `genrun genapply`. Open `fixtures/sim/cantilever.fcad` to copy the record shapes: 200 by 10 by 10 steel, 100 N gives 1.6000 mm and 203.85 Hz.

Rules: materials carry a source, enter values yourself only when the user gave them; check the study result before reporting; size refusals mean a coarser `maxh`; reports go to granted folders.
