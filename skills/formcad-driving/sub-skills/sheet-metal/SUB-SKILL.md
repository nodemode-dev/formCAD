---
name: sheet-metal
description: Builds sheet metal parts and flat patterns in FormCAD. Use for base flanges, edge flanges, hems, jogs, bend rules and K-factor, bend lists and flat DXF export.
---

# Sheet metal

Verified recipe: `formcad_new_document` template `part`; `cmd_partsketch` plane XZ; `cmd_pline` vertices [[0,0],[0,40],[60,40]]; `cmd_partsketchdone`; `cmd_smbaseflange` with `sketch`, `thickness` 2, `radius` 3, `width` 50 (the rule rides on the first feature); `cmd_smbends` lists bends (angle, radius, axis).

More: `smedgeflange smmiterflange smhem smjog smsketchbend smbendrelief smcornerrelief smconvert` (feature parameters such as `angle`, `length`, `position`, `flip`, `width_mode`, edges as persistent ids or refs). `smrule` edits the rule (`bend_method`, `k_factor`, `ba`, `bd`); `smtable` manages bend tables (ships empty); `smcheck` measures.

Flat pattern: `cmd_flatpattern` with `on` true shows it; `cmd_flatexport` with `path` (granted), `profile` bending or cutting, `version` R2018, `notes` boolean. Fixtures: `fixtures/sheetmetal/bracket.fcad`, `channel.fcad` (flat length 112.1893794959 mm).
