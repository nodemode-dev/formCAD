# Electronics and routing

**Schematics.** Capture with generated symbols, hierarchical sheets, buses, electrical rule checks (`ecaderc`).

**Boards.** Layers, generated footprints, tracks, vias, pours, design rule checks (`pcbdrc`) with fabricator profiles that name their sources, a two-layer autorouter. Outputs: `gerberexport`, `drillexport`, `idfexport`, `boardstep`; `ecadsync` and `ecadpush` keep the board and the enclosure in step.

**Harnesses.** `harness`, `harnessexport`: routed through clips with bend radius checks, flattened to a formboard drawing with wire lists.

**Tubes and pipes.** `pipespec`, `piperoute`, `pipecutlist`, `pipebender`, `pipefitting`, `pipeexport`.

**Electrical schematics.** `schemdevice`, `schemwire`, `schemnumber`, `schemdraw`, `schemwirelist`, `schemexport`.

**Limits.** The autorouter is two-layer and lists nets it could not route. Rule profiles and tube specs are editable examples. See manual chapters 19 and 20.
