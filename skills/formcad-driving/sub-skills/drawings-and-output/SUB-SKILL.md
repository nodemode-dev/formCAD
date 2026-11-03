---
name: drawings-and-output
description: Produces drawing views, annotation, BOM tables, toolbox parts, inspection reports and PDF output in FormCAD. Use for layouts, views, sections, balloons, title blocks and plotting.
---

# Drawings and output

Verified recipe: `formcad_open_document` a granted `.fcad` part or assembly (the model stays in the same document; a view cannot reference another file for an agent); `cmd_viewbase` with `direction` front, `scale` 0.5, `position` [100,100] and `layout` Layout1 (layout is required); `cmd_viewprojected` with `parent` V1 and `rel` right; `cmd_viewsection` with `parent`, `kind` full, `line` and `letter`; `cmd_bomtable`; `formcad_export` with `path` ending `.pdf` and `layout` Layout1. Views report `state.status`; changed models mark views stale, refresh with `cmd_viewupdate`.

More: `viewdetail viewaux viewbroken viewcrop viewedit viewdelete viewprojection`, annotation `balloon autoballoon titleblock gdtframe datumsym finishmark centermark viewdim`, tables `table table.setcell tableexport`, `bomexport`, plot `plot pagesetup exportpdf pngout svgout publish`.

Toolbox and inspection (new): `toolboxinsert toolboximport inspection inspectionexport mbdview`; sizes are user entered or imported from the user's own CSV, never shipped. Weld cut tables: `weldcuttable weldcutupdate`.
