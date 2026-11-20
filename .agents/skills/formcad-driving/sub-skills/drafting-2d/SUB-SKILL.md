---
name: drafting-2d
description: Drafts and inspects 2D drawings in FormCAD with verified tools. Use for lines, circles, polylines, text, dimensions, layers, hatch, blocks, queries and render checks.
---

# Drafting 2D

Create: `formcad_new_document` with template `metric` or `drawing-mm-a3` (millimetres) or `inch`.

Structured tools with curated schemas: `cmd_line` (`points`, `closed`), `cmd_circle` (`center`, `radius`), `cmd_arc` (three `points`), `cmd_rectang` (`p1`, `p2`), `cmd_pline` (`vertices`), `cmd_polygon`, `cmd_text` (`point`, `text`, `height`), `cmd_mtext`, `cmd_move`, `cmd_copy`, `cmd_rotate`, `cmd_scale`, `cmd_mirror`, `cmd_offset`, `cmd_erase`, `cmd_zoom`, `cmd_setvar`. Each returns the new `handle`.

Everything else is typed: `formcad_command_line` with the whole command, for example `dimlinear 0,0 100,0 50,-10 ` (a trailing space is Enter). Commands: `dimlinear dimaligned dimangular dimradius dimdiameter qdim`, `hatch -hatch`, `layer -layer layer.new layer.set`, `block -block insert -insert`, `xref`, `trim extend fillet chamfer array`, `table`, `leader mleader`.

Inspect: `formcad_inspect` (counts, layers, extents), `formcad_query_entities` (`kind`, `layer`, `window`, `geometry` false for light output), `formcad_find_text`, `formcad_render` (PNG image), and measure tools `cmd_measuregeom`, `cmd_list`; `dist` and `id` have no tool form, so type them with `formcad_command_line`.

Recipe, plate with hole: new `metric` document, `cmd_rectang` p1 [0,0] p2 [100,60], `cmd_circle` center [20,30] radius 5, typed `dimlinear`, `formcad_query_entities` to confirm counts, `formcad_render` to look, `formcad_export` to a granted `.pdf`, `formcad_save_document` to a granted `.fcad`.
