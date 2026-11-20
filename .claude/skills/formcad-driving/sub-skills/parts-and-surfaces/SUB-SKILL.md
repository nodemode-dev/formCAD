---
name: parts-and-surfaces
description: Models parametric parts, surfaces, forms, meshes, plastic features, weldments and mold splits in FormCAD. Use for sketches, features, fillets, parameters, configurations, mass properties and analysis.
---

# Parts and surfaces

3D needs the kernel worker; a kernel message means it is missing (formcad-harness).

## Verified part recipe

1. `formcad_new_document` template `part`.
2. `cmd_partsketch` with `plane` XY, XZ or YZ (returns the sketch id; it is entered).
3. Draw into the sketch with `formcad_command_line` or `cmd_rectang`, `cmd_circle`, `cmd_pline`.
4. `cmd_partsketchdone`.
5. `cmd_featextrude` with `sketch` (name, for example Sketch1) and `depth1`; also `cmd_featcut`, `cmd_featrevolve`, `cmd_featrevolvecut`, `cmd_featadd` (`type` for fillet, chamfer, shell, draft, pattern, mirror and others).
6. `cmd_features` lists the tree with each feature state; `cmd_featedit`, `cmd_featsuppress`, `cmd_featrollback`, `cmd_featrebuild` change it.
7. Verify: `cmd_bodymass` (volume, area, centre) or `cmd_massprop` with a `handle`. A 40 by 20 by 10 extrude reports 8000 mm3.

Parameters and constraints: `cmd_parameters`, `cmd_sketch`, `cmd_geomconstraint`, `cmd_dimconstraint`, `cmd_sketchstatus`; constrain before extruding and read the status. Variants: `cmd_config`, `cmd_designtable`, `cmd_material`.

Analysis: `draftanalysis zebra curvatureanalysis wallthickness seamcheck deviation analyzeshapes`.

Other families (read schemas with list_tools.py): surfaces `srfloft srfsweep srfblend srfmatch srfpatch srftrim srfjoin`; curves `crv crvblend crvinterp`; forms `subdbox subdcylinder subdconvert subdcrease`; meshes `meshrepair meshreduce meshremesh meshtobrep`; plastic `plasticrib plasticboss plasticlip plasticgroove plasticcheck plasticrule`; weldments `weldframe weldmember weldjoint weldendcap weldgusset weldcutlist`; molds `molddraft moldparting moldblock moldsplit moldsettings moldclear`. Weld and mold schemas are new; they may list only `inputs`.
