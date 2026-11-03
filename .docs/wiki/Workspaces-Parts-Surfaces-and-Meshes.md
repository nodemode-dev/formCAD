# Parts, surfaces and meshes

**Parts.** A feature tree with rollback on the kernel: `partsketch`, `featextrude`, `featrevolve`, `featcut`, configurations (`config`), design tables (`designtable`), materials (`material`), mass (`bodymass`).

**Sheet metal.** A rule (`smrule`), flanges (`smbaseflange`, `smedgeflange`), hems (`smhem`), flat patterns (`flatpattern`, `flatexport`). Bend tables are yours.

**Surfaces and forms.** NURBS curves and surfaces (`crv`, `srfloft`, `srfblend`), analysis (`zebra`, `curvatureanalysis`), subdivision forms (`subdbox`, `subdconvert`).

**Meshes and plastic.** Repair, reduce, remesh and mesh to solid (`meshrepair`, `meshreduce`, `meshremesh`, `meshtobrep`); plastic features and wall checks (`plasticrule`, `wallthickness`).

**Weldments and molds.** Frames and cut lists (`weldframe`, `weldcutlist`); draft, parting and cavity split (`molddraft`, `moldparting`, `moldsplit`).

**Toolbox.** Hardware generators from sizes you enter (`toolboxinsert`, `toolboximport`).

**Limits.** 3D needs the kernel worker. No standards tables ship: sizes, profiles and bend data are yours or formula-derived. See manual chapters 6 to 9, 21 and 22.
