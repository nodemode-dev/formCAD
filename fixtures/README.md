# Fixtures

Sample data for manual checks and demos. These are data files, not tests.

## bracket.step and solids.fcad

`bracket.step` is an L bracket made by the kernel worker through the engine's own commands in a millimetre drawing: a closed polyline profile (60 mm and 50 mm legs, 12 mm thick, an inner corner rounded with an 8 mm arc) extruded 40 mm, then two 8 mm holes subtracted through the bottom leg. One solid named `L bracket`, 11 faces, 27 edges, volume 46383.0 mm3, colour 0.62 0.66 0.72, written through EXPORT. Open it with OPEN or IMPORT. `solids.fcad` holds the same bracket plus a box with a vertical hole, a sphere, a cone, a torus and the union of two overlapping boxes (6 solids), with the stored shapes and cached meshes in `parts/` and `cache/`; it also holds the profile polyline of the bracket.

## doc-basic.fcad

A metric drawing (template `drawing-mm-a3`, limits 420 x 297, layouts sized A3) created by the running engine through its command line API, then saved with `POST /api/docs/{id}/save`.

| Content | Count | Layer |
| --- | --- | --- |
| Layers | `0`, `Defpoints`, `Walls` (colour 1), `Dims` (colour 3) | |
| Lines | 5: a closed 200 x 100 rectangle from 20,20 plus one diagonal | `Walls` |
| Circles | 2: centre 120,70 radius 25 and centre 300,70 diameter 40 | `Dims` |
| Arcs | 2: three point arc 260,20 / 300,40 / 340,20 and centre-start-end arc about 300,150 | `Dims` |
| Polylines | 2: an open four point zigzag from 20,200 and a closed rectangle from 240,200 | `Dims` |

Total 11 objects. Open it with File > Open (browser: type the absolute path; desktop: pick the file), or `POST /api/docs/open {"path": "..."}`. The manifest records `kind: drawing`.

## lines-100k.fcad

A metric drawing (`drawing-mm-a3`) holding 100,000 random lines (seed 20261102, lengths 3 to 60 inside 4200 x 2970) on seven layers: `Walls`, `Dims`, `Hidden`, `Centre`, `Notes`, `Paths`, `Grid`, each with its own colour, linetype and lineweight; about 30 percent carry their own linetype and linetype scale, 30 percent their own lineweight and 10 percent an index colour. Created by the engine's document service (one transaction, no undo steps) and saved through `service.save`. It measures the display list build and the `/api/docs/{id}/display` payload.

## text-codes.fcad

A metric drawing for the text pipeline: one multiline text that uses every inline code (font, height, width factor, oblique, tracking, index and RGB colour, underline, overline, strike, stacked fractions in all three separators and the three tolerance alignments, paragraph indents, tab stops of each kind, centre, right, justified and distributed paragraphs, space before and after, escapes, percent codes), a two column multiline text, an exact line spacing text, nine attachment points, and single line text in all fifteen justifications plus width factor, oblique, rotation, backwards, upside down and an outline font style (`Sans`, font `arial.ttf`, which falls back to the stroke font where Arial is not installed). Red points mark the alignment and insertion points. Open either file like doc-basic.

## snaps.fcad

A metric drawing (`drawing-mm-a3`) made by the running engine through typed commands, one result of each kind the object snaps need, 16 objects on layer `0`: two crossing lines (20,20 to 120,20 and 70,0 to 70,60, intersection 70,20), two lines whose extensions meet at 90,70 (20,70 to 60,70 and 90,50 to 90,90, apparent intersection and extension), circles at 200,60 r30 and 260,60 r20 (centre, quadrant, tangent, perpendicular), a three point arc 20,120 / 50,150 / 80,120, an ellipse centred 150,150 (major 40, minor 20), an open polyline with an arc segment from 20,200, a rectangle 140,200 to 200,250 (geometric centre 170,225), a hexagon polygon at 300,200 r30, a fit spline through 240,110 / 270,150 / 300,110 / 330,150, a point at 380,30, a ray from 350,100 through 380,130, an xline through 360,250 and 400,260 and a donut at 380,200 (10 inner, 20 outer). Text and block insertions are not in it because the engine has no text or block command yet (insertion snap is untested).

## draw-all-part1.fcad

A metric drawing (`drawing-mm-a3`) with one result of every Draw command in part 1 and every option of each, made by driving the real prompt sequences through the engine's input route (typed text and canvas payloads), each cell checked, undone and redone before saving. Each result sits in its own 70 mm cell, nine cells per row, on layer `0`; the helper lines and circles that the pick based commands need stay in their cells.

| Command | Results |
| --- | --- |
| LINE | segments, Close, Undo |
| XLINE | base and through, Hor, Ver, Ang, Ang Reference, Bisect, Offset by distance (both sides), Offset Through |
| RAY | two rays from one start |
| PLINE | lines, Close, Width taper, Halfwidth, Length, Undo, Arc endpoint, Second pt, Angle (endpoint, CEnter, Radius), CEnter (endpoint, Angle, chord Length), Direction, Radius (endpoint, Angle), Line switch, CLose, arc Width |
| POLYGON | inscribed and circumscribed by point, inscribed and circumscribed with a typed radius, Edge |
| RECTANG | corners, Fillet, Chamfer, Width, Elevation, Thickness, CEnter, Area, Dimensions, Rotation |
| CIRCLE | Center Radius, Diameter, 2P, 3P, Center Diameter, Ttr (two lines, line and circle), Ttt (three lines) |
| ARC | 3 Points, Start Center End, Start Center Angle, Start Center Length, Start End Angle, Start End Direction, Start End Radius, Center Start End, Center Start Angle, Center Start Length, Start End Center, Continue, and the nine menu commands arc.sce to arc.csl |
| ELLIPSE | axis end, tall axis, centre, Rotation, Arc by angles, Arc Parameter, Arc Included angle, Isocircle top, right and left |
| DONUT | ring, solid disc, two rings |
| SOLID | quadrilateral, triangle, chained pair |

113 objects: 15 lines, 13 xlines, 2 rays, 39 polylines (polygons, rectangles, donuts, pline), 9 circles, 21 arcs, 10 ellipses, 4 solids. The display route builds an item for every one of them.

## draw-all-part2.fcad

A metric drawing (`drawing-mm-a3`) with one result of every Draw command in part 2 and every option of each, made by driving the real prompt sequences through the engine's input route (typed text and canvas pick payloads). Each result sits in its own 80 mm cell, nine cells per row, on layer `0`; the helper lines, circles, polylines and blocks (`TICK`, `BRKSYM`) that the pick based commands need stay in their cells. Every cell that creates objects was undone and redone before saving. LIMITS ends at 0,0 to 760,500 and PTYPE ends at PDMODE 35 (circle around a cross) with PDSIZE 2.5; multiline styles `TRI` and `FANCY` (plus `STANDARD`) are in the style table.

| Command | Results |
| --- | --- |
| POINT | single point, multiple point (three) |
| SPLINE | fit with Chord, Square root and Uniform knots, Close, start and end Tangency, toLerance, repeated point (kink), Object (open polyline converted), control vertices degree 3, degree 5, CV Close |
| DIVIDE | line, arc, circle, ellipse, arc with an aligned block |
| MEASURE | line, arc, spline, circle with an aligned block |
| HELIX | defaults, cone with Turns and tWist CW, Diameter with turn Height, Axis endpoint |
| REVCLOUD | rectangular, polygonal, freehand, Object circle, Object with Reverse, calligraphy style with arc length 8 |
| WIPEOUT | points, Polyline with Erase No, Polyline with Erase Yes (over parallel lines) |
| 3DPOLY | open with z values, Close |
| CENTERMARK | circle and arc |
| CENTERLINE | two converging lines |
| BREAKLINE | built-in symbol, Size and Extension with a picked location, custom block symbol |
| MLINE | Top, Zero, Bottom, Close, negative scale with Undo, a style with caps, joints, fill and four coloured elements (MLSTYLE New) |
| MLEDIT | CC, OC, MC, CT, OT, MT, CJ, AV, DV, CS, CA, WA, one pair of multilines each |

174 model space objects: 50 points, 38 lines, 25 multilines, 12 splines, 12 block references, 11 polylines (revision clouds and break-lines), 8 arcs, 8 circles, 4 helices, 3 wipeouts, 2 3D polylines, 1 ellipse. The display route builds an item for every one of them.

## text.fcad

A metric drawing (`drawing-mm-a3`) made through the engine's input route, one result per text command and option, 51 objects (39 single line text, 12 multiline text) and 9 text styles (`Standard`, `Sans` outline font, `Slant`, `Wide`, `Back`, `Up`, `Tall` vertical, `Fixed` height 6, `Note` annotative). Cells of 120 mm: the 13 TEXT justifications (Left, Center, Right, Middle, TL to BR), Align, Fit, rotation 30, a three line DTEXT plus an Enter continuation, a 90 degree two line text; one text per style (outline font with kerning, oblique, width factor, backwards, upside down, vertical, fixed height); mixed English and Hebrew in both paragraph directions, an Arabic word, lam alef and a phrase, Thai marks and sara am, a stroke style falling back to a system font for Arabic and Hebrew; MTEXT with Width, Justify, Height, Rotation, Line spacing (Exactly), static and dynamic Columns, Style, inline codes, bullet, number, lower and upper lists, mixed scripts with Thai wrapping, and one made through `POST /api/docs/{id}/mtext`; TEXTEDIT in Single and Multiple mode. Hebrew, Arabic and Thai cells need an installed font with those scripts (DejaVu Sans, Loma or similar); `Sans` needs DejaVu Sans, otherwise it falls back to the stroke font.

## hatch.fcad

A metric drawing (`drawing-mm-a3`) with one result of every hatch, gradient, boundary and region command and option, made through the engine's programmatic command forms. 79 cells of 130 x 110 mm, eight per row, filled left to right then downward from 0,0; boundaries and results stay in their own cell.

| Cells | Results |
| --- | --- |
| 1 to 23 | one hatch per built-in pattern (SOLID, ANSI31 to ANSI38, LINE, NET, NET3, DOTS, DASH, BRICK, SQUARE, CROSS, EARTH, GRASS, HONEY, ZIGZAG, AR-CONC, AR-SAND) on a rectangle with a circular island, scale 1 |
| 24 to 35 | the ten gradient names (angle 0 and 30, centred and not), a one colour gradient with tint, and a solid fill with transparency 40 |
| 36 to 41 | nested islands (rectangle in rectangle in rectangle with a circle) under Normal, Outer and Ignore, then picks inside the second and third level, and a solid pick inside the circle |
| 42 to 50 | separate hatches against one hatch, hatch by selected objects, gap tolerance closing a 5 unit gap, an associative hatch after STRETCH, an island erased, retained boundary as polyline and as region, a user pattern loaded from inline text |
| 51 to 60 | origin modes (bottom left, bottom right, top right, top left, center), an origin point, scale and angle, annotative, draw order back and front |
| 61 to 65 | BOUNDARY as polylines and as a region (source in the first cell, result moved one cell right), REGION from a line and arc, circle, closed polyline, ellipse and closed spline |
| 66 to 74 | UNION, SUBTRACT and INTERSECT on two overlapping rectangles, two overlapping circles, and a rectangle crossed by a circle |
| 75 to 79 | HATCHEDIT results: pattern, scale, angle and style; gradient from a pattern; separate hatches; remove boundary; add object |

228 model space objects: 67 hatches, 90 polylines, 39 circles, 16 lines, 16 regions. The display route builds an item with prims for every hatch (710 `tri` prims, 9,465 `pl` prims, 6.3 MB). The hatch fixture was rendered to an image and checked by eye; solid and gradient fills were checked with antialiasing off for seams. The user pattern `FORMCAD_WAVES` travels inside its hatch, so the file displays without the pattern file.

## arrays-groups-props.fcad

A metric drawing (`drawing-mm-a3`) made by driving the real commands through the engine (typed prompt sequences, canvas payloads and programmatic forms), then saved with `POST /api/docs/{id}/save`. Cells are 220 x 140 mm, six per row, each labelled by a text object on layer `0`; arrays are on layer `Arrays`, groups on `Groups`, property results on `Props`.

| Row | Content |
| --- | --- |
| 0 | ARRAYRECT 4 x 3, two levels with row elevation, axis angle 30, negative spacings, separate copies (associative off), typed COUnt and Spacing then ARRAYEDIT of columns |
| 1 | ARRAYPOLAR 8 full circle, 6 items over 270, 4 items over -90 (clockwise), rotate off, 3 rings, typed Items and Fill angle |
| 2 | ARRAYPATH on an open line, a closed circle with align, fixed spacing 22, separate copies, an arc path |
| 3 | -ARRAY rectangular and polar (copies), ARRAYEDIT source edit saved by ARRAYCLOSE, replacement of two items, per-item overrides (one recoloured, one hidden), ARRAY through its type menu |
| 4 | GROUP unnamed, named with description, typed Name and Description, GROUPEDIT add, remove and rename, -GROUP order and not selectable, UNGROUP |
| 5 | CHPROP (colour, linetype, scale, lineweight, true colour, transparency, thickness), CHANGE (line end, circle through a point, elevation), MATCHPROP (all and only colour and lineweight), inline LINETYPE load, FIND replace `Room` with `Hall`, RENAME of a layer |

132 model space objects: 19 associative arrays (`assoc_array`; 6 polar, 4 path, the rest rectangular), 5 groups (`*A1`, `Walls`, `Roof`, `Edited`, `Ordered`) and loose objects. Reopened from disk the display route builds an item for every object and each array regenerates its items. Rendered to an image and checked by eye.

## leaders-tables.fcad

A metric drawing (`metric` template, ISO-25 dimension style) made through the engine's input route and the programmatic forms: 58 model space objects (30 multileaders, 9 leaders, 9 tables, 8 multiline texts, 1 block reference, 1 dimension) plus the block `TAG` (an 8 mm square with a diagonal). Two table styles (`Standard`, `Report`), three multileader styles (`Standard`, `Detail` with a dot arrowhead and larger sizes, `Annotated` annotative), 18 annotation scales (the 17 metric ones plus `1:25`) and `CANNOSCALE` 1:2. Rows from the top: LEADER at y 0, MLEADER at -100, MLEADEREDIT at -200, MLEADERALIGN at -300, MLEADERCOLLECT at -420, styles and annotative objects at -500, tables at -650, broken and linked tables at -800. The linked table reads `leaders-tables-parts.csv` from this folder (an absolute path is stored, so use DATALINKUPDATE only where the file sits there).

| Cell | Results |
| --- | --- |
| LEADER | straight with hook and two lines of text, Format Spline, Format None (no arrowhead) with text, annotation None, Block with scale 1.5 and rotation 45, Copy of a multiline text, Undo of a point, shallow last segment without hook |
| MLEADER | leader first, landing first, content first, leader type None, content None, landing No, spline with four points, first angle 45, left dogleg, block content with Center extents and with Insertion point, back to multiline text |
| MLEADEREDIT | one multileader with two leaders added and one removed |
| MLEADERALIGN | project onto a line, Specify spacing 20, make segments Parallel, Distribute between two points |
| MLEADERCOLLECT | Horizontal row, Vertical column, Wrap at width 20 (three block multileaders each) |
| MLEADERSTYLE | `Detail` made through the typed option loop, `Annotated` made programmatically |
| Annotative | a multileader at scales 1:2 and 1:4 with its 1:4 position moved, text with 1:2 and 1:4 and its 1:4 position moved, a dimension at 1:2 and 1:4 |
| TABLE | typed columns, rows and insertion point; formulas (product, SUM, equation, cell), decimal and percent formats, fill, alignment; merged 2x2 and a merge then unmerge; row and column insertion; outside borders, hidden inside lines, row cell style, own text height, column width and row height; table style `Report` with a user cell style; breaks right with repeated top rows, down with repeated bottom row and spacing; CSV data link |

## modify-part1.fcad

A metric drawing with one result of every Modify part 1 command and option, made by driving the real prompt sequences through the engine input route (typed text and canvas pick, point and selection payloads, the real token guard). 60 cells of 200 x 200 mm, ten per row, going downward from the origin, each with a text label above it; every cell was undone and redone (the whole document compared object by object) before saving. Cells in order: ERASE (selection), OOPS, MOVE (base and second point, Displacement), COPY (several copies, Array, Array Fit), ROTATE (angle, Copy, Reference), SCALE (factor, Copy, Reference), MIRROR (keep and erase source), STRETCH (crossing window, crossing polygon), OFFSET (distance on a line and a circle, Through, Multiple, closed polyline with an arc, ellipse, spline), TRIM (line against an arc, Standard mode with cutting edges, circle, polyline with an arc, ellipse, spline, Fence, Crossing, Edge Extend, shift-select), EXTEND (line, arc, polyline, elliptical arc, spline, Fence), BREAK (two points, First point), BREAKATPOINT (line, arc), BREAK (circle, closed polyline), JOIN (collinear lines, lines to a polyline, arcs, close an arc, splines, elliptical arcs), LENGTHEN (delta with Angle, percent, total with Angle, dynamic, spline), ALIGN (one pair, two pairs, scale), REVERSE. 196 model space objects (68 lines, 60 labels, 26 circles, 19 polylines, 12 arcs, 7 splines, 4 ellipses); reopened from disk the display route builds an item for each. Rendered to an image and checked by eye.

## modify-part2.fcad

A metric drawing with one result of every Modify part 2 command and option, made by driving the real prompt sequences through the engine input route (typed text and canvas pick, point and selection payloads). 79 cells of 100 x 90 mm, eight per row, going downward from the origin, each with a text label; every cell was undone and redone (state compared object by object) before saving. Cells: FILLET (perpendicular, 60 degree corner, extension of short lines, No trim, shift-select corner, line and circle, circle and circle, arc and line, ellipse and line, spline and line, Polyline, two segments of one polyline, segments with one between, polyline end with a line, Multiple with Undo), CHAMFER (distances, length and angle, No trim, shift-select, Polyline, polyline segments, polyline end with a line, Multiple), BLEND (tangent, smooth, polyline to spline), EXPLODE (wide polyline, multiline text, multiline, block rotated and scaled, mirrored, non-uniform, array, region, helix, 3D polyline, dimension block), PEDIT (Close, Open, Width, Join, Fit, Spline, Decurve, Ltype gen, Reverse, convert line, convert arc, vertex Move, Insert, Straighten, Break, Tangent, Width, Multiple), SPLINEDIT (Close, Reverse, fit data Add, Delete, Kink, Move, Tangents, toLerance, Purge, vertex Add, Elevate order, Weight, Delete, Move, convert to Polyline, Join, Close then Open), NCOPY, MOCORO, FLATTEN, ARRAYPATH.SIMPLE (count, spacing, closed path), CHSPACE (a circle and a line moved to `Layout1` through its viewport, so they are not in the model grid). 285 model space objects (88 lines, 83 labels, 42 polylines, 23 arcs, 23 circles, 22 splines, 3 ellipses, 1 block reference) and 3 in `Layout1`; the display route builds an item for each. Blocks `FX1`, `FX2` and `*DIMFX` are in the block table.

## dimensions.fcad

A metric drawing (`drawing-mm-a3`, ISO-25 current) with one result of every dimension command and option and of every dimension variable group, made by driving the real prompt sequences through the engine input route (typed text, canvas pick and point payloads, programmatic forms for the style cells). 175 cells of 140 x 110 mm, ten per row, going upward from 20,20; every cell was undone and redone (the whole document state compared) before saving. Reopening gives the same 206 dimensions and 282 objects, and the display route builds an item for each. Cells in order: DIMLINEAR (horizontal, vertical by location, Horizontal, Vertical, Rotated, select object on a line and on a circle, Mtext, Text, Angle), DIMALIGNED (points, object), DIM, DIMCONTINUE (chain, Undo), DIMBASELINE (stack, Select base dimension), DIMRADIUS (text outside, inside, Mtext, on an arc), DIMDIAMETER (inside, outside), DIMJOGGED (halfway and picked jog), DIMCENTER (circle, arc), DIMANGULAR (two lines, Quadrant, arc, circle, three point), DIMARC (whole, Partial), DIMORDINATE (inferred X and Y, Xdatum, Ydatum), QDIM (Continuous, Staggered, Baseline, Ordinate, vertical Continuous, Y datum, datumPoint, Edit, Radius, Diameter), DIMEDIT (New, Rotate, Home, Oblique), DIMTEDIT (moved text, Left, Right, Center, Angle, Home), DIMOVERRIDE (set, Clear overrides), DIMSTYLE update, DIMSPACE (Auto, value, 0), DIMBREAK (Auto, Manual, picked object, Remove, Multiple), DIMJOGLINE (default, picked, Remove), DIMINSPECT (Round, Angular, None, Remove), DIMDISASSOCIATE, DIMREASSOCIATE, DIMREGEN, and four associativity cells (line end moved by a grip, STRETCH, MOVE, object erased). The variable cells use named styles saved with DIMSTYLE: DIMDEC, DIMZIN, DIMRND, DIMDSEP, DIMPOST, DIMLFAC, DIMLUNIT 1 to 6 with DIMFRAC 0 to 2, tolerance deviation, symmetric and top and bottom justified (DIMTOL, DIMTP, DIMTM, DIMTDEC, DIMTFAC, DIMTOLJ), limits (DIMLIM), alternate units (DIMALT, DIMALTF, DIMALTD, DIMAPOST, DIMALTRND, DIMALTU), DIMATFIT 0 to 3 with long and short text, DIMTIX, DIMSOXD, DIMTOFL, DIMSCALE, DIMTAD 0 to 4, DIMTVP, DIMJUST 0 to 4, DIMTIH and DIMTOH, negative DIMGAP, DIMTFILL 1 and 2, colours, lineweights and linetypes of the three parts, DIMTSZ with DIMDLE, DIMSE1 and 2, DIMSD1 and 2, DIMFXLON and DIMFXL, DIMEXO and DIMEXE, DIMASZ, DIMTXT, DIMTMOVE 1 and 2 with DIMLDRBLK, DIMAUNIT 1 to 4 with DIMADEC and DIMAZIN, DIMARCSYM 0 to 2, DIMCEN positive and negative, DIMJOGANG, all 20 standard arrowheads and separate first and second arrowheads. Dimension kinds present: linear 160, aligned 3, radius 7, diameter 4, jogged 3, centre mark 4, angular 2, three point angular 8, arc length 5, ordinate 10. Dimensions carry no anonymous block; the display route builds their geometry from the definition points and the style.

## layers-views.fcad

A metric drawing made through the layer manager routes, the layer tools, VIEW and the tiled viewport options: 12 layers with every property set differently (colour index and true colour, linetype, lineweight snapped to 0.53, transparency, plot off, locked, off, frozen, new viewport freeze, descriptions, one renamed with `Rev-A`), a line and a circle on nine of them (18 model space objects, 14 shown because `E-LIGHT` is off and `S-GRID` is frozen), four layer filters (property `Architecture` on `A-*`, property `Not plotted`, group `Review set`, nested property `Arch glazing` under `Architecture`), layer states `Plan v1`, `Lighting` (edited to add `X-NOTE`) and `Plan` (re-imported from an exported file), three named views (`Overall` and `Entrance` with layer snapshots, `Detail` as a window without one), and a three tile `*Active` viewport configuration (3 Right) whose tiles hold different views plus the saved configurations `Review` and `Stacked`. Each of the 33 fixture steps was undone and redone and the whole document state compared before saving; reopened from disk the layer, state, filter, view and viewport tables are identical and the layer manager listing gives the same usage counts.

## sheet.fcad

The Phase 10 exit sheet, built through the command routes: model space holds a closed 4000 x 2000 mm polyline, a circle of radius 500 at its centre and a centre line; the A3 landscape layout `Layout1` (420 x 297 mm, 5 mm margins) holds a paper border, the block `TITLEBLOCK` (180 x 40 mm frame with four attributes TITLE, DRAWNO, SCALE and DATE, filled with `SITE PLAN`, `A3-001`, `1:50`, `2026-11-02`) and one viewport at 1:50 centred on model point 2000,1000. Reopened from disk the layout display gives the polyline as 80 x 40 mm and the circle as radius 10 mm on paper, scale 1:50, and the title block with four attribute texts. K1's `blocks.fcad` did not exist yet, so the title block was built here with the block and attribute commands.

## blocks.fcad

A metric drawing made through the real command routes (typed prompts, canvas pick and selection payloads, programmatic forms, the grip route), one result per block and attribute command and option, each step undone and redone in the driver; 31 model space objects (15 block references, 9 lines, 6 texts, 1 table) and 11 blocks. `TITLEBLOCK` is the title block definition other fixtures reuse: a 60 x 24 frame with the attributes `TITLE`, `DRAWN`, `DATE`, `SCALE`, `SHEET` (in that order, then `REV` added by ATTDEF with a block and propagated by ATTSYNC); three references show interactive attribute prompts, programmatic values, scale 0.5 with rotation 90, ATTEDIT, -ATTEDIT (find and replace, colour) and BATTMAN edits. Other blocks: `SQUARE` (base at centre; plain, scaled and rotated, 2 x 3 array, exploded, base override), `RETAINED`, `ANNOT` (annotative, not explodable), `REDEF` (redefined), `NESTED`, `ATTMODES` (one attribute per mode: invisible, constant, verify, preset, lock position, annotative, multiple lines, plus Center, MC and BR justification, one attribute moved by its grip), `OLDMARK` replaced by `NEWMARK` (BLOCKREPLACE), `WBLOCKED` (WBLOCK then INSERT of the file), and `UNUSED_BLOCK` for PURGE. A BURST title block (its attributes became text), BASE (5,5) and a DATAEXTRACTION table are included; the CSV output was written to a temporary folder.

## xrefs/

External reference fixture, three `.fcad` drawings attached by relative path. `xrefs/host.fcad` holds a frame, one text line and three XATTACH references to `refs/plan.fcad` (at 0,0; at 400,0 scale 1.5 rotated 90; at 0,150 clipped by an XCLIP rectangle). `refs/plan.fcad` has walls, a door block and its own attachment of `refs/details/detail.fcad` (stored as `details/detail.fcad`, relative to the plan), so the host lists `plan` and the nested `plan|detail` as Loaded. The host carries a layer override for `plan|WALLS` (colour 5) that survives XREF Reload. Built through the real command routes; open `host.fcad` and run XREF to see the manager list. Moving the folder keeps the links; the `.bak` files are not shipped.

## sketch.fcad

Phase 15 fixture: sketch `Bracket` on plane XY, an L-shaped bracket profile (six lines, two holes) that reaches fully defined with zero degrees of freedom. Five named parameters (`width` 60, `height` 40, `thickness` 8, `hole_d` 6 in millimetres, and the equation `hole_offset = thickness * 1.5`), nine named dimensions (`base_w`, `flange_h`, `base_t`, `flange_t`, `hole_dia`, `h1_x`, `h1_y`, `h2_x`, `h2_y` driven by expressions over the parameters), six coincident joints, three horizontal and three vertical relations, one fix and one equal. Built through the constraint and sketch routes. Open it, run SKETCHSTATUS for `Bracket`, change `width` in PARAMETERS to see the profile and the holes follow, or add `DCALIGNED` on the base line with a different value to see it refused with the conflicting constraints named.

## plot/

PDFs of `sheet.fcad` made by the plot engine: `sheet-layout1.pdf` (layout `Layout1`, A3 landscape, one 1:50 viewport) and `sheet-model-1to50.pdf` (model space at 1:50 on A3). `NOTE.md` records the measurement: the 4000 mm polyline edge is 80.000 mm on the page in both files.

## dxf/

One DXF per version family, `survival-r12.dxf`, `-r2000`, `-r2004`, `-r2007`, `-r2010`, `-r2013` and `-r2018`, each written from the same 1730 object drawing (every `.fcad` fixture above except lines-100k merged with a block, attribute, layer, view, user coordinate system, layout and viewport drawing). `SURVIVAL.md` records the save then reopen result entity by entity. R2007 and later reopen equal apart from three benign defaults listed there; R2000 and R2004 lose true colour, transparency and attribute position lock; R12 keeps the geometry that R12 can hold and counts the rest.

## scripts/

Script, alias and macro fixtures. `plate.scr` draws a 200 x 120 mounting plate with two holes and a centre line, then edits it (COPY, MOVE through `@pick`, ERASE through a crossing `@box`, OFFSET, TEXT, a DELAY and a LISP line); run it with SCRIPT on a `drawing-mm-a3` drawing. `plate.fcad` is that script's result saved and reopened. `shop.fcalias` is a command alias file in FormCAD's own `ALIAS, *COMMAND` format with an unknown target, an alias that shadows a command name and an external program line, so loading it prints three warnings and loads seven aliases. `bracket-sketch.scr` and `bracket-sketch.py` are one recorded session (rectangle, two circles, a line, a crossing selection and a MOVE) saved by the macro recorder as a script and as a Python macro; both replay to the same four objects.

## macros/

Python macros for the `formcad` client module (`backend/app/data/sdk/formcad.py`). `plate.py` draws a 120 x 80 plate with four holes, a centre line and a text, then edits it (MOVE, SCALE, COPY, ERASE, select, UNDO, REDO) and asserts the geometry numerically, so the exit status is the check; `typed.py` uses the recorder style (`doc.send`, `doc.script`, a programmatic form, undo and redo). Run one with `formcad-engine run --new --python-macro fixtures/macros/plate.py --save out.fcad`, or trust it in the macro list of the preferences and run it against the open drawing. Both run in a separate scrubbed `python -I` process with a timeout and memory limits and no network.

## lisp/

`bolt-pattern.lsp` is a parametric bolt-hole routine: `bolt-pattern` draws N circles on a pitch circle through `command`, puts them on layer BOLTS with `entmod`, moves the set and rotates it about the moved centre; `c:boltdemo` runs 6 holes of diameter 8 on a 60 pitch circle at (100,100), moved by (50,20) and rotated 15 degrees, and `bolt-centres` lists the hole centres through `ssget` and `entget` (expected: (150 + 30 cos(60 i + 15), 120 + 30 sin(60 i + 15)) for i = 0 to 5). Load it with APPLOAD (or put the folder in the LISP support folders and use `(load "bolt-pattern")`), type BOLTDEMO; one U takes back the whole routine. `bolt-pattern.fcad` is the result saved and reopened.

## curves.fcad

A metric drawing with three `nurbscurve` entities made through the curve commands: an interpolated degree 3 curve through five 3D points (CRVINTERP), a degree 3 control point curve (CRV), and the G2 blend between the end of the first and the start of the second (CRVBLEND, shape factor 1). CRVCONT reports G2 from the kernel for both joins. Saved through `POST /api/docs/{id}/save`; reopened poles, knots and samples match exactly. `GET /api/docs/{id}/curves` lists them.

## part-adv.fcad

Phase 17 exit (bodies and data), millimetres. Eight solid bodies, each with its closed-form volume, centre of mass and mass stored in the body's `source.expect`; `GET /api/docs/{id}/bodies/exitcheck` compares the kernel's mass properties with them and passes within 1e-6 relative (measured worst: 4e-11). Bodies: Swept tube (annulus R10 r7 swept along a quarter arc of radius 50, 304 stainless), Lofted block (rectangle 40 x 20 at z=0 to rectangle 16 x 24 at z=30 with centres offset (5, 3), 6061), Counterbored plate (60 x 40 x 20 with a diameter 8 hole and a diameter 14 x 6 counterbore at (20, 12), Ti-6Al-4V), Frustum (cone radii 12 and 5, height 20), Torus (R30 r5), Hollow cylinder (made with Combine subtract), and Split block in two pieces (made with Split Body at x=205). The reference geometry table holds nine items (planes by face, offset, three points and angle; axes by two points and by two planes; points by coordinates and face centre; the coordinate system Plate corner), the parameters L and W, and the configurations Default, Heavy and Light (values and per-body materials). Open it, call `POST /bodies/massprops` with `cs: "Plate corner"` for inertia about that system.

## shape features (no fixture file yet)

The sweep, loft, boundary solid, rib and hole features were checked on scratch documents only, each saved and reopened without a status change: a tube (annulus r 10 and 8 swept 100, volume pi(100-64)100), a loft between a 20 and a 10 square 40 apart (prismatoid 9333.33), a six-patch boundary cube of 1000, a rib of 80 x 20 x 6 in a box cavity, and two counterbored holes. P4F owns `part-adv.fcad`; these can be rebuilt from the feature parameters above.

## part-core.fcad

Phase 16 exit (feature tree), millimetres. A part document of 13 features: sketch Base (100 x 60 rectangle with the driving dimensions `plate_w` and `plate_d`), Plate extrude 20, sketch on the plate top, Boss extrude 15 (circle r12), Boss draft 3 degrees, Shell 1 mm opened at the boss top, a pocket sketch and Pocket (8 deep), a hole sketch and through Hole, a circular Holes pattern of 4, Corners fillet r4 on the four vertical plate edges and Chamfer 0.3 on the boss rim. Every reference is a named key (`F2:cap:end`, `e(F4:cap:end|F4:side:h...)`), so `PUT /parameters/plate_w` with another expression rebuilds the whole chain with every feature `ok` and no reference lost (checked at 140, 100 and 120, and after save and reopen with a cold cache). Measured here: full build of 13 features 570 ms, edit of the root dimension about 650 ms (sketch 0.1 ms, extrudes 1 to 30 ms, the dress-up and pattern features 50 to 130 ms each), edit of the last feature about 120 ms.

## surface.fcad

Phase 18 exit (surfaces), millimetres, document tolerances set with MODELTOL to 0.001 mm and 0.001 rad. Three surface bodies: `Surface A` and `Surface B` (cubic lofts through three curves, 100 mm wide, spanning y 0 to 50 and y 100 to 150) and `Blend A-B`, made with SRFBLEND at G2 on both ends (Hermite construction after the filling attempt, influence 0.6). SEAMCHECK on the saved and reopened file reports G2 at both seams: seam A gap 1.5e-13 mm, normal angle 3.7e-8 rad, curvature gap 3.3e-9; seam B gap 5.6e-13 mm, angle 1.5e-7 rad, curvature gap 2.0e-8, all under the tolerances (1e-3 mm, 1e-3 rad, 1.4e-4 to 1.5e-4 relative to curvature). The blend body stores its construction report under `source.report`.

## analysis.fcad

Z1 exit (gumball and analysis), millimetres. A sphere of radius 20, a cylinder of radius 10, a cubic loft surface, a circle and a cubic curve, a custom `diverging` colour ramp (stops and limits -0.1 to 0.1) stored in the document header, a ZEBRA display and a curvature comb on the circle. Saved and reopened: the ramp comes back unchanged and CURVATUREANALYSIS gaussian on the sphere reads 1/R^2 = 0.0025 within 0.1 percent.

## assembly.fcad

AS1 model fixture (assembly document kind, schema 1), millimetres, with its files in `assembly/`, every reference stored relative (`assembly/base.fcad`). Components: `Base` (the part-core plate with part number BP-100, 6061, and a part configuration `Wide` of plate_w 140; fixed), `Pin` (DP-300, 304 stainless, radius 3 height 28) patterned by the feature pattern on the Base's `F10` hole feature (four pins, one in each hole at (25,30), (75,30), (50,5), (50,55), checked on the reopened file), and `Clamp` (sub-assembly clamp.fcad, CL-500: two rods RD-410 and a linear pattern of two caps CP-020) repeated twice by a circular pattern of 180 degrees about (50,30). Configurations `Default`, `Light` (clamp suppressed) and `Wide base` (Base uses its Wide configuration, clamp suppressed). Flat BOM: BP-100 x1, DP-300 x4, RD-410 x4, CP-020 x4 with find numbers 1 to 5 stored. Opened cold, all five components read `loaded`; `GET /api/docs/{id}/scene` draws 13 bodies from the cached part meshes.

## z2-3dm-mesh.fcad

Z2 fixture, millimetres. Opened from a 3DM file written from `surface.fcad`: the untrimmed surfaces `Surface A`, `Surface B` and `Blend A-B` (one face each, read back within 3.2e-13 mm of the originals). Added after the open: mesh objects `Box mesh` (12 triangles, closed, volume 24000) and `Sphere mesh` (3664 triangles, closed) made by MESHFROMSOLID on layer `Meshes`; mesh `soup`, read from a binary STL cube with two faces missing and two triangles reversed, then welded and unified, so it still has 4 naked edges in 1 loop (MESHFILL closes it, volume 1000); and a rational cubic curve `Curve` on layer `Curves3dm`. Reopened, all three mesh summaries are equal to the saved ones, the scene route draws them, and EXPORT to 3DM writes all seven objects with the largest read-back deviation 3.98e-13 mm.

## drawing-views.fcad

DR1 fixture (drawing views), millimetres, third angle. `part-core` on sheet `Layout1` as six views at 1:2: `V1` FRONT base, `V3` TOP projected above it (cut by one zigzag break, so type `broken`), `V4` RIGHT projected beside it, `V2` ISO base, `V5` full section A-A (hatched cut faces), and `V6` detail B at 2:1 of a circle in the front view. A 92 mm edge measures 46.0 mm on paper at 1:2. Reopened, all six views read `ok` with their cache intact; changing `plate_w` marks them stale or rebuilds them (auto), about 0.5 s for the six.

## mechanism-drawing.fcad

DR2 fixture (Phase 21 exit, drawing annotation), millimetres, third angle, A3 `Layout1`. The mechanism assembly drawn as five views at 1:2 (`V1` front, `V2` top, `V3` right, `V4` iso, `V5` full section A-A with hatch), three dimensions that follow view edges (260 and 100 mm model size read at 1:2, a diameter), eleven centre marks, one geometric tolerance frame (position, diameter zone, M, datums A B) with datum symbol A, a surface finish mark, eight balloons, a parts list table and a filled title block. `plot/mechanism-drawing.pdf` is the sheet from the plot engine and `dxf/mechanism-drawing-r2018.dxf` the R2018 export; reopened, the dimensions, annotations, table and title block attributes survive and the views come back as plain geometry. The parts list shows part numbers MECH-001 to MECH-010, descriptions and materials from the part files in `mechanism/`.

## mechanism.fcad

AS2 fixture (Phase 20 exit, mates and motion), millimetres, with its ten part files in `mechanism/` (`base`, `gear`, `pinion`, `crank`, `rod`, `slider`, `pin_gear`, `pin_pinion`, `pin_crank`, `pin_slider`). A gear and pinion pair drives a crank, a rod and a slider along a guide. Sixteen mates: pins locked to the base, hinges as concentric plus coincident, gear ratio 0.5 reversed between gear and pinion, the crank locked to the gear, the rod hinged on the crank pin and the slider pin, the slider on the base top and the guide wall, and `crank angle`, a signed angle about z that is the one input (status `fully`, 0 degrees of freedom). Driving it from 0 to 350 degrees moves the slider between x 55 and 105 mm, matching the hand crank-slider formula to 2e-8, with zero interference at 36 sampled positions and a minimum clearance of 0.1 mm at the pin fits. The exploded view `Service` has five steps along z (slider group 60, rod 45, crank group 30, gear and pinion 15, pins 70).

## graph/matching_corpus.json

GC1 fixture (Phase 23 exit, graph data). The 47 golden matching cases M01 to M47 of research R21: id, source tag, operation, mode, inputs with access, optional flag and modifiers, principal override, expected output tree, expected warnings and a note, with trees in the `{0;1}:[a,b]` notation. The operations ADD, ADD3, PAIR, LJOIN, ADDSUM, ADDCNT, TCOUNT and DUP2 are defined in the file header. Numbers compare with absolute tolerance 1e-9. Each case is fed to `app.graph.match.run` and all 47 reproduce.

## graph/tree_ops_corpus.json

GC1 fixture (Phase 23 exit, graph data). The 37 structure cases of research R21 section 1.8: T01 to T18 (flatten, graft, simplify, flip matrix, flip tree, trim, shift paths), S01 (path order), PM1 to PM8 (path mapper) and P01 to P09 (parameter modifier order). A case with an `error` expects an empty tree and that error code; `warnings` lists expected path mapper warnings. All 37 reproduce through `app.graph.tree` and `app.graph.modifiers`.

## sheetmetal/channel.fcad

SM2 fixture (Phase 22 exit, flat pattern), millimetres. A U channel as one extruded solid (aluminium 6061): thickness 2, inside radius 3, K 0.44, outside web 60, outside flanges 30 each, depth 100, two 90 degree bends; the sheet rule rides in the `SHEETFLAT` header (`on` true). The flat pattern computed from the B-rep is 112.1893794959 mm long by 100 mm (the R20 value 112.189379 from BA 6.09469 and BD 3.90531, difference below 1e-13 mm), bend line centres at x 28.04734487 and 84.14203462, both bends the same direction. `channel-cutting.dxf` (layer `CUT`, one closed polyline) and `channel-bending.dxf` (layers `OUTER`, `BEND_UP` or `BEND_DOWN` on a CENTER linetype, `BEND_NOTE`) are the two flat exports, R2018, `$INSUNITS` mm.

## graph/plate-holes.fcad

GR2 fixture (Phase 24, node graph geometry and bake), millimetres, with the same graph as `plate-holes.graph`. Graph `Plate with bolt holes`: a 100 by 60 by 20 box, one cylinder of radius 4 turned into a ring of four by the polar array, the difference of the two (volume 115978.7614 mm3, the box minus four holes), a tagged copy (`attr.set`: name `Plate`, layer `Plates`, colour #3a7bd5), the mass node and the mid height section (five curves of total length 420.5310 mm). Baked from the nodes `tag` and `sec`: one solid body named `Plate` on layer `Plates` and five NURBS curves, all carrying the provenance `G1/<node>/<port>/<path>/<index>` in `FORMCAD_GRAPH` extended data. Reopened, the graph solves to the same volume and the baked objects keep name, layer and colour.

## sheetmetal/bracket.fcad

SM1 fixture (Phase 22, sheet metal features), millimetres. Part with seven features: sketch `Profile` (an L, 40 up and 60 along), `Base Flange` (open profile, thickness 2, inside radius 3, K 0.44, width 50, one bend of 90 degrees), sketch `JogLine` on the flat top face, `Jog` (offset 12, two bends, the far side moves up), `Far Flange` (edge flange 20 long on the far end, 30 wide centred, material inside, rect relief at both sides), `Leg Flange` (edge flange 15 long on the free end of the standing leg, 40 wide centred, with relief) and `Hem` (closed, 8 long, on the side edge of the first flat). Six recorded bends (`F2.1`, `F4.1`, `F4.2`, `F5.1`, `F6.1`, `F7.1`); rule on `Base Flange`. Reopened with a cold cache all features rebuild; `GET /sheetmetal/verify` measures thickness at sampled points of every skin face (deviation below 1e-9 mm) and every bend face is a cylinder of radius 3 or 5 (0.1 or 2.1 for the hem); editing the base flange thickness to 3 and to 1.5 rebuilds all seven features with the same result.

## graph/facade-base.fcad and graph/facade.graph

GR3 fixtures (Phase 24 exit), millimetres. The document holds one box body 9000 by 300 by 4500 on layer `WALL` and an empty layer `FACADE`. The graph reads the wall with a document object node, takes its extents from the vertices, lays out a grid of panels (sliders `columns` 8 and `rows` 5), cuts a square opening in each panel whose side falls off with the distance to an attractor point (`attr_x`, `attr_z`, `reach`, `max_open`, `gap`), and tags the cut panels as `Panel` on layer `FACADE` in colour #2f6fed. Named outputs `open_area`, `panel_count` and `fitness` (open area with a penalty above `panel_limit` panels). Imported and baked in the engine (`GRAPHBAKE`) and run with `formcad-engine graph run fixtures/graph/facade.graph --doc fixtures/graph/facade-base.fcad --bake OUT.fcad`, both give 40 solid bodies with the same total volume (1230780242.474323 mm3), bounding box, per-body properties and shape hash. Optimizer: maximising `fitness` over all seven sliders (population 40, 40 generations, seed 7) finds 29895122.67 mm2 of open area with 4 columns and 2 rows.

## interchange/

X2 fixtures (Phase 25 exit F1, 3D interchange), millimetres. `part-pmi.fcad`: a 40 by 30 by 10 plate with a 12 mm hole and nine PMI items (datums A on the bottom and B on a side, a 10 mm thickness distance with plus-minus 0.1, a diameter 12 with +0.02/-0.01, a radius 6, a 90 degree angle, a 20 mm hole-to-side distance, flatness 0.05 on the top, and a position tolerance 0.2 with diameter zone, M and datums A, B). `assembly-colours.fcad`: four bodies in two assemblies (`Machine` holds the red 10 by 20 by 30 `Block` and the blue `Pin` r 5 h 40 at x 100; `Base` holds the green `Plate` with a hole and the freeform loft `Vase`), layers `PARTS`, `BASE`, `FREEFORM`, colours kept. Written by the engine from these two documents: `part-pmi.step` (AP242, 9 of 9 PMI items written and read back), `part-pmi-inch.step` (same in inches), `part-pmi.3mf`, `.glb`, `.ply`, `.iges` (IGES carries no semantic PMI and reports the 9 items as dropped); `assembly-colours-ap203.step`, `-ap214.step`, `-ap242.step`, `-inch.step`, `.3mf`, `.iges`; `assembly-clamp.step` is `assembly.fcad` (the AS1 assembly document, 13 component instances with nested clamps) written as an assembly. Round trip of the four STEP variants: total volume relative error 0 (millimetres) and 8.4e-13 (inch), analytic solids at most 2.0e-12, the freeform solid 7.6e-14, centroids within 1.6e-13 of the body diagonal, names, colours, layers and assembly paths equal, pin to block offset equal to 1e-9. 3MF: every object a closed oriented manifold, mesh volume within 0.06 per cent of the B-rep volume (linear deflection 0.01 mm, angular 0.1 rad), re-read volume equal to the written mesh to 6.4e-12; the same file written in inches scales by 25.4 on import into a millimetre document with the unit warning. The `.step` files are written by the engine, not by hand; the kernel-written input `source-asm.step` of the scratch run is not shipped.

## plastic/housing.fcad

PL1 fixture (Phase 27 exit F4, plastic rules), millimetres. A 60 by 40 by 20 housing, ten features: sketch `Profile`, `Block` (20), `Draft 1` (1 degree on three outer walls), `Draft 0.3` (0.3 degree on the fourth), `Shell` (2.5 mm inward, top open), then the plastic features `Rib` (1.5 mm, 60 percent of the wall, height 4.5), `Snap hook` (beam 12, root 1.2, undercut 1.5, strain 1.875 percent), `Boss` (screw 2.5, outside diameter 5.5 = 2.2 x, height 8), `Lip` on the rim face and `Groove` on the bottom face (both from the rule: width and height W/3, groove +0.15 wide and +0.2 deep, 3 degree sidewalls). The plastic rule is ABS with a nominal wall of 2.5 mm. `POST /api/docs/{id}/plastic/checks` on the reopened file reports 1 error (snap hook strain 1.875 against the permissible 1.82 percent), draft 0.30 against 0.50 degree on exactly the two faces of the 0.3 degree wall, the rib at 60 percent of the wall as a slight sink note, no boss or rib error, 31 sharp inside edges, wall 1.37 to 2.77 mm (median 2.5, sphere method, 1250 samples) and a main wall variation of 11 percent (varies with the sample set). Undo, redo, save and reopen leave the rule and all ten features intact.

## mesh/

MW1 fixtures (Phase 27 exit F3, mesh workspace), millimetres. `scan-box-hole.stl` is a scanned-style binary STL of a 24 by 16 by 10 block with a 6 mm hole through the 10 mm height (48-gon, volume 3558.06 mm3; the true cylinder gives 3557.26). The base mesh is a remeshed edge-0.7 triangulation (7712 triangles); defects were injected with a fixed seed (20261103) by a scratch script that is not shipped: Gaussian vertex noise sigma 0.02 mm, a flipped patch of 60 triangles, three holes (one triangle, a 6-gon around a valence-6 vertex, a 20-gon), 200 vertices duplicated 3e-6 mm away with half of their triangles moved to the copy, 10 isolated zero-area triangles, 5 duplicate triangles and two spikes (a triangle apex pulled 12 mm through the opposite wall, another 26 mm). Raw file: 7678 triangles, 1625 naked edges in 287 loops, 15 non-manifold edges, 28 mismatched edges, 55 pieces, 40 self-intersecting pairs (most from the 3e-6 cracks, 8 after the weld from the two spikes). `scan-box-hole.fcad` is the same mesh imported as a `meshbody`. `scan-box-hole-solid.fcad` is the result of the exit run through the real engine: MESHREPAIR (weld 0.0001, fill 32, resolve intersections: 200 vertices merged, 10 degenerate and 5 duplicate triangles removed, 60 flipped, 3 holes filled with 23 triangles, 9 triangles of the two spikes removed and 4 holes refilled, closed with 0 naked and 0 non-manifold edges and 0 self-intersections, volume 3559.76), MESHREDUCE to 20 percent (7682 to 1536 triangles, largest deviation 0.065 mm, rms 0.013, still closed), MESHREMESH to 1.0 mm (3966 triangles, mean edge 1.007, deviation 0.10 from the reduced mesh, volume 3563.30), MESHTOBREP with flat merging at tolerance 0.08 (191 faces, 81 of them merged flat regions, valid closed solid, 0 free edges, volume 3563.57, 7.7e-5 from the mesh); the faceted conversion of the same mesh gives 3966 faces, 0 free edges, volume equal to the mesh to 3e-16, 3 s. The solid sits next to the mesh in the document. The faceted volume is 0.15 percent above the 48-gon block (noise).

## form.fcad

SD1 fixture (Phase 26 exit F2, form modelling), millimetres, document kind `form`. `Housing`: a 60 by 40 by 24 box cage (6 by 4 by 3 faces) with mirror symmetry in x and y, edited with the commands: the 20 outer edges of the base crease-weighted 10 (sharp), the middle of the top raised by 8 with a soft selection of radius 22 (smooth falloff, 23 vertices moved, the mirrored copies followed), one edge ring cut around the waist, the outer edges of the top that stayed at height 24 semi-sharp at weight 2; final cage 130 vertices, 128 faces, 8 extraordinary vertices, 28 crease edges, counterpart error 0. `Housing solid` is `SUBDCONVERT` of it at level 2: 2048 patches (1732 exact B-spline, 316 matched-boundary at extraordinary vertices and creases), one valid closed solid, 0 free edges, volume 61728.8257 mm3 (the mass properties route gives the same), largest gap between neighbouring patches 1.1e-14 mm, largest distance to the level 5 subdivision 0.0188 mm (0.024 percent of the bounding diagonal), largest normal jump across a shared edge 14.7 degrees (G0 around the extraordinary vertices and creases, 0 on the regular faces). `Ring`: the 12 by 8 torus cage, major 20, minor 6 (converts at level 1 to 384 exact patches; the same cage at major 3 and minor 1 gives the 43.945 volume of the R22 prototype), `Sheet`: an open 4 by 3 plane (converts to a shell and says it is not closed, never a solid), `Ball`: a quadball of radius 15 with 2 spans. Written by the running engine and reopened: the cages are bit for bit equal after save, reopen and save as, the solid volume is equal, and converting again gives the same volume.

## vault/

DM1 fixtures (Phase 29 exit, local vault), millimetres, document kind `part`. `part.fcad` is the part-core plate (13 features, 4 sketches). `part-branch-a.fcad` and `part-branch-b.fcad` are two edits of it made through the running engine's feature routes and saved, each rebuilt (all 13 features ok): A sets `F2` (Plate) `depth1` 20 to 24 and `F12` (Corners) `radius` 4 to 3; B sets `F4` (Boss) `depth1` 15 to 18, `F2` `depth1` 20 to 30 and `F13` (Chamfer) `distance` 0.3 to 0.4. Check `part.fcad` into a vault, put A and B on two branches from it and merge B into A: the report has exactly one conflict, field `params.depth1` of `table:features:F2` with base 20, ours 24, theirs 30; the other three edits (`F12`, `F4`, `F13`) merge without a choice, and the derived feature states and solid body never conflict. Choosing a value and completing gives a two-parent version that opens, rebuilds all 13 features ok and carries the chosen `F2` depth with A's `F12` and B's `F4` and `F13`. Every `.fcad` in this folder tree (68 files) checks in and comes back byte-identical.

## linkage.fcad

JM1 fixture (Phase 28 exit, joints and motion), millimetres, with five part files in `linkage/` (`base`, `crank`, `coupler`, `rocker`, `bracket`, each one box). A planar four-bar crank-rocker (ground 100, crank 30, coupler 90, rocker 70, so shortest plus longest is 130 against 160, a Grashof crank-rocker) on three layers 1 mm apart in z, built with four as-built revolute joints about z at the pivots (`M1` base to crank, `M2` crank to coupler, `M3` coupler to rocker, `M4` base to rocker); the crank starts at 60 degrees. Status under with 1 degree of freedom (20 rows, rank 17, three redundant rows from the planar loop). `bracket` is a fixed block whose face lies in the plane through the rocker pivot at 130 degrees, the stop. Contact set `K1` holds the pair rocker and bracket (touch gap 0.01 mm); motion study `S1` "Crank turn" keys joint `M1` rz from 0 to 330 degrees over 4 s at 30 frames per second, contact mode stop. Measured through the engine: the crank swept over 361 positions agrees with the closed-form rocker angle to 2.4e-10 rad (coupler pivot to 1.4e-8 mm); the study stops at 1.0979 s (crank turned 90.578 degrees, 150.578 absolute) when the rocker comes within 0.004 mm of the bracket (an independent interference check at that pose reports no overlap and a distance of 0.0040005 mm), the analytic crank angle for that gap is 90.57813 degrees (difference 6e-6 degrees); a MuJoCo run of the same linkage with the crank servo-driven matches the closed form to 0.09 mm over 1 s. The same numbers hold for a slider-crank (crank 30, rod 90): 361 positions to 7.7e-9 mm kinematic and 0.21 mm dynamic.

## render/scene.fcad

RN1 fixture (Phase 30 exit part one, render), millimetres. An assembly of three components (`Base`, a `Pin` pattern, a `Clamp` sub-assembly pattern) whose part files are copies of the `assembly/` ones in `render/parts/` (`base`, `pin`, `rod`, `cap`, `clamp`), referenced by relative path, 13 bodies. The `render` table holds: environment `studio_small_08` at 1k (Poly Haven, CC0), yaw 30 degrees, a light grey floor, 8 samples, 4 bounces, 4 glass bounces, 4 by 4 tiles per sample, smoothing on, neutral tone mapping, output 3840 by 2160; appearances `Aluminium, polished` on the base (`i:C1`), `Brass, satin` on the four pins, `Plastic, glossy blue` on the four rods and `Glass, clear` on the four caps; one image decal `hazard` (a 96 by 48 PNG of diagonal stripes, 26 by 13 mm) on the top face of the base at 78, 30, 20. The base top is at z 20 there, not at the 35 mm of the bounding box. Measured through the engine as a headless job (`POST /api/docs/{id}/renderjobs`, `backend: headless`, Chromium 1243 from Playwright, ANGLE on Mesa llvmpipe, a two-core machine shared with other work): a 3840 by 2160 RGBA PNG of 22,572,198 bytes, 8 samples in 16 scissor tiles each, render time 328.2 s, wall time 336.9 s from job start to file; the shader compile and the first sample are inside that time. The image is not stored here; a 720 by 405 reduction is in the handoff screens folder.

## render/mechanism-exploded.mp4 and mechanism-storyboard.fcad

AN1 fixtures (Phase 30 exit part two, animation). `mechanism-storyboard.fcad` is `mechanism.fcad` (same folder, so the component paths still resolve) with one storyboard, `Exploded`, 1280 by 720 at 30 fps, style shaded, frames from the viewport: `Hold` 1 s, `Explode` 4 s (the `Service` explode view from 0 to 5 steps, camera framed on the assembled pose at the start and on the exploded pose at the end, 35 degree orbit), `Hold exploded` 1 s, `Collapse` 2.4 s, `Run mechanism` 3 s (drive of mate M16, the crank angle, from 0 to 180 degrees, linear). 342 frames, 11.4 s. `render/mechanism-exploded.mp4` is that storyboard exported through the interface (WebCodecs H.264, codec string avc1.64001f, muxed by Mediabunny into MP4 with the index up front): 342 frames, 11.4 s, 863,443 bytes, plays in Chromium 1243 and Chrome for Testing 153.


## additive/

AM1 fixture (Phase 33 exit), millimetres. `part.fcad` is one solid, 70 by 30 by 23 mm and 22316.5 mm3: a 3 mm plate, two 10 by 30 pillars 14 mm apart carrying a 3 mm beam (a 14 mm bridge, with a 5 mm hole through the beam), and a mushroom (post radius 3, a cone to radius 11 over 6 mm, a cap) that overhangs at about 37 degrees from horizontal. It holds profile `Standard 0.2 gyroid 20` (standard preset) and plate `Part plate` (one item, placed by the arranger) with a stored `last` summary. Sliced through the engine: 114 layers, 5194.4 mm of 1.75 mm filament, about 1h 28m 49s (estimate), 4509 mm3 of support under the mushroom, one bridge layer (the beam), no support under the beam. Reopened, the plate is not stale and re-slicing gives the same hash.

## cam/pocket-part.fcad

CAM1 fixture (Phase 31 exit), millimetres. One part: a 100 by 80 by 20 mm block with a 60 by 36 mm pocket 8 mm deep (island of diameter 12 in the middle) and four 6 mm through holes 10 mm from the corners. It holds three tools (T1 6 mm flat, T2 3 mm flat, T3 6 mm drill, with cutting data for `6061 aluminium` typed in by hand, not from a source), setup `S1` (stock from the model, WCS slot 1 at the stock top corner) and six operations: face, adaptive clearing, pocket walls, rest machining with T2, peck drilling of the model's holes, outline contour. `pocket-part.ngc` is its LinuxCNC post (8185 lines); reopening the file and exporting gives the same bytes.

CAM2 edited it for the simulation exit (v0.12.0): the setup stock has 0.5 mm above the model and the WCS origin is custom at the model top (the original stock equalled the model, so the face pass cut 0.5 mm into the part, which the simulation reported as a gouge); the pocket operation used arc tolerance 0 because the arc fitting of CAM1 produced an arc through the island centre that left the pocket (found by the same simulation); I13 fixed the fit (an arc must stay within the tolerance of the chords between its points) and restored arc tolerance 0.01, and `pocket-part.ngc` was posted again (12600 lines, 1723 arc words). Simulated at cell 0.2 mm: 0 gouge cells, minimum distance to the model 0.0 mm (vertical), 22650.9 mm3 removed of 164000, 917 s cycle time with acceleration (801 s by length over feed), no collisions.

## cam/five-axis.fcad

CAM2 fixture (Phase 32 exit), millimetres. A 100 by 80 by 15 mm block with a cone frustum on it (base diameter 60, top diameter 40, 30 high, centred), tools T1 10 mm flat (holder profile typed in) and T2 6 mm ball, setup `S1` with machine `mill5`, stock from the model plus 3 mm on the sides and top, WCS custom at the centre of the block top (on the C axis), and three operations: `O1` 3D adaptive roughing (stock to leave 0.5), `O2` swarf along the cone wall (rails are the base and top circles, 72 points each, stock to leave 0.1), `O3` flowline finishing of a flat strip with the ball tilted 10 degrees and leading 5 degrees. Machine `mill5_table_table`. The rails are typed into the operation geometry as WCS points.

## cam/sheet-set/

CAM3 fixture (Phase 32 exit), millimetres. `sheet-set.fcad` holds a sheet metal channel (flat pattern) and five closed outlines (a plate, an L, a disc, a slot bar, a gusset) with nest `N1` (31 part instances on 500 by 400 mm sheets, kerf 1.5, gap 2, margin 5, two sheets) and cutting processes `P1` laser, `P2` plasma, `P3` waterjet. The six files `sheet-set-{laser,plasma,waterjet}-{1,2}` are the cutting code of the two sheets through the posts `cut_grbl_laser`, `cut_linuxcnc_plasma` and `cut_linuxcnc_waterjet`.

## sim/cantilever.fcad

FE1 fixture (Phase 34 exit), millimetres. One solid box, 200 by 10 by 10 mm (body handle 256), and three studies on it with their stored results: `S1` linear static (100 N total on the face x = 200 acting along -z, face x = 0 fixed), `S2` modal (four modes), `S3` buckling (reference load 1 N along -x on the face x = 200). Material `M1` is steel typed in by hand from the R25 benchmark definition (E 200 GPa, nu 0.3, rho 7850 kg/m3, k 50 W/m/K, alpha 12e-6 1/K), its source field names the definition; `M2` is the cited library aluminium 6061-T6 and is not used by a study. Mesh controls: element size 5 mm, second-order tetrahedra, 762 elements and 5265 unknowns. Run through the engine: tip deflection 1.5951 mm against 1.6000 mm (-0.30 percent), first frequency 204.22 Hz against 203.85 Hz (+0.18 percent), buckling load 10298.7 N against 10280.8 N (+0.17 percent). Reopened, every study is `solved`, the results display and probe, and the reports write.

## sim/nonlinear.fcad

FE2 fixture (Phase 35 exit, nonlinear), millimetres. One solid box, 200 by 10 by 10 mm, with steel typed in by hand (no source, the benchmark definition) and four studies with stored results: `S1` nonlinear static with J2 plasticity, a 300 N tip bend (max displacement 5.343 mm, max von Mises 252.5 MPa, maximum plastic strain 0.00125 over 13 percent of the elements, 19 Newton iterations), `S2` nonlinear static with a rigid stop at the tip (elastic model, max displacement 0.8007 mm, 32 iterations), `S3` explicit dynamic axial impact on a rigid wall (581 steps of 2.24e-7 s, contact impulse 0.3116 N s against 0.3140 N s, peak force 4265 N), `S4` fatigue on the linear static stress (minimum life 1.38e8 repeats, Goodman). No S-N data ships with the program, so the S-N curve of `S4` is typed in. Reopened, all four studies are `solved`, display their stress field, and a fresh run of each gives the same numbers.

## sim/topo-bracket.fcad

TO1 fixture (Phase 35 exit, topology), millimetres. An L bracket (wall 12 by 18 by 42, arm 60 by 18 by 12, one solid body), aluminium 6061-T6 from the library (yield 276 MPa), 700 N down on the arm end face, fixed wall back, and topology study `S1` with its stored result: remove 55 percent of the mass, stress limit 85 MPa, mirror plane y, a preserved boss cylinder, 3000 target cells (grid 20 by 6 by 14, cell 3 mm), 100 iterations. Result: mass 0.05240 to 0.02358 kg (55.0 percent removed), peak von Mises 53.6 to 80.9 MPa, within the limit; a smoothed closed mesh body (outcome of TOPOAPPLY, 4920 triangles) is stored in the file. Reopened, the result displays and a fresh TOPORUN gives the same numbers.

## sim/pipe.fcad

CF1 fixture (Phase 36 exit, flow), millimetres. A straight round passage, diameter 10 mm and length 100 mm, with a flow inlet (0.05 m/s) on one end and a zero pressure outlet on the other; fluid typed in (water, density 1000, viscosity 0.001 Pa s, no table ships). Study `S1` is type `flow` on formCAD's own Stokes solver (second-order curved tetrahedra at 2.5 mm, 1701 elements, 11443 unknowns, Reynolds number 501). Run through the engine on a fresh start: pressure drop 1.5996 Pa against the Hagen-Poiseuille 1.6002 Pa (-0.04 percent, the exit asks 5 percent), 3.7 s. Reopened, the result displays and a re-run gives the same number.

## route/harness.fcad

RT1 fixture (Phase 39 exit, harness), millimetres. An assembly of four components (`Chassis A` and `Chassis B` 300 mm apart, `Sensor`, `Bracket`; part files `chassis.fcad`, `sensor.fcad`, `bracket.fcad` are copies of the assembly fixtures) carrying a harness: connectors J1 (10 pins), J2 (8) and J3 (3, the sensor), clips K1 and K2 on the bracket, a splice SP1 and a waypoint, three segments, nine 20 AWG wires and one shielded 2-core cable. Routed and flattened to the layout `Formboard` (A2) with a wire list, from-to, connector pin and segment table. Pin counts differ from the contract text (8, 6, 3) because nine wires and a two-core cable need more pins on the chassis connectors.

## ecad/board-schematic.fcad

EL1 fixture (Phase 38, schematic side; the board layout and outputs are EL2 and EL3), millimetres, document kind `ecad`. A 555-style LED blinker on one sheet: timer U1 (generic 8-pin timer symbol, footprint `SOIC-8`), power connector J1 (`HDR-1x02`) and output header J2 (`HDR-1x03`), resistors R1 to R3 (`CHIP-0603`), capacitors C1 and C2 (`CHIP-0805`, `CHIP-0603`), bulk capacitor C3 (`RADIAL-D5_P2.5`) and LED D1 (`CHIP-0805`). Ten components and seven nets (`+5V`, `GND`, `CTRL`, `DIS`, `LED_A`, `OUT`, `TIMING`), built through the engine (39 part, wire, label, junction and power operations) with ERC clean (0 errors, 0 warnings) and the same netlist after save and reopen.

## route/piping.fcad

RT2 fixture (Phase 39 exit, pipes and tubing), millimetres, an assembly with two components (`Chassis A` at the origin, `Chassis B` moved to x = 400; part file `chassis.fcad` beside it). Spec `S1` (12 x 1 tube, minimum radius factor 1.5, springback 1.5 degrees, all user-entered examples). Run `R1` is a bent tube from an anchor on Chassis A to an anchor on Chassis B through four interior points, centreline radius 24: developed length 568.045 mm, four bends, bender rows (length, rotation, angle) 66.0 / 0 / 90, 72.0 / 180 / 90, 72.0 / 90 / 90, 32.0 / 197.53 / 90 and a tail of 175.25 (with Chassis B at x = 300 the last rotation is 213.69; the table is recomputed from the anchors). Run `R2` is a fitted pipe run with a flange on end A, a tee on the first segment, an elbow and a reducer on the second. The bodies of both runs (straights, bends, fittings) are generated into the assembly; elbow volume matches the torus section formula and the flange and reducer match their closed forms.

## route/schematic.fcad

RT2 fixture (Phase 39 exit, electrical schematic), millimetres, a drawing with two sheets laid out side by side at a 500 mm pitch. Sheet 1 mirrors `harness.fcad`: connectors J1 (10), J2 (8), J3 (3) and splice SP1 as a junction, eleven wires named W1 to W9, CB1-1 and CB1-2 as in the harness; the comparison against the harness by wire name finds 11 matches and no differences. Sheet 2 is a small control circuit (supply, fuse, push button, normally closed contact, relay coil, hold contact, lamp, motor, earth) with ten wires. 14 electrical nodes get one number each by FormCAD's scheme (template `{prefix}{sheet}-{seq:02}`, for example `W1-07` for the splice node shared by W7, W8 and W9). The 2D entities (249: frames, symbols, orthogonal wires, number labels) are tagged by xdata and replaced when the schematic is drawn again.

## ecad/board.fcad

EL2 fixture (Phase 38, board side; EL3 adds outputs and the enclosure link), millimetres, document kind `ecad`. The `board-schematic.fcad` design laid out and routed: a 45 x 32 mm two-layer board with 2 mm corner radii and four 3.2 mm mounting holes, the ten parts synced from the netlist (27 pads, auto placed), a GND pour on the bottom layer with thermal reliefs, net classes giving `+5V` and `GND` 0.4 mm tracks, the rest at the profile width. The generic profile (0.16 mm clearance and width, 0.7 / 0.3 mm vias, 0.2 mm ring) is the rule set. Autorouted by the engine: 7 of 7 nets, 139 track segments, 9 vias, no rip-ups needed, about 5 s; DRC reports 0 errors and 0 warnings, the same after save and reopen, and the board also passes the JLCPCB, PCBWay and OSH Park profiles.

## ecad/board-linked.fcad and ecad/enclosure.fcad

EL3 fixtures (Phase 38 outputs and links), millimetres. `enclosure.fcad` is a part: a 45 by 32 mm block with 2 mm corner radius, 12 mm tall, with four 3.2 mm through holes at the board's mounting holes (sketches `Shell` and `Posts`, features `Shell block` and `Screw holes`). `board-linked.fcad` is a copy of `board.fcad` with the header value `ECAD_LINK` set to the relative path `enclosure.fcad` and synced once: the outline was pulled from the highest upward face (28 points at 0.02 mm tolerance), the four holes matched the board's own mounting holes, and DRC reports 0 errors and 0 warnings. Scaling the enclosure sketch marks the link stale; syncing again moves the outline (checked at 1.25 and 1.2 times, undo and redo exact). Exports from it: 9 Gerber layers (35 apertures, 114 flashes, 1191 draws, 2 regions), two Excellon files (16 plated hits in 3 tools, 4 unplated hits), an IDF board and library, and a board STEP of two bodies.

## mold/part.fcad

MD1 fixture (Phase 40 mold tools), millimetres. A 40 mm disc, 16 mm tall, drafted 1.5 degrees each way from the mid plane (two extrusions), with two through holes (8 and 6 mm at the parting plane, drafted 1.5 degrees). Settings: pull +Z, minimum draft 0.5 degrees, shrinkage 0.5 percent multiply. The stored split: parting height 0, 3 silhouette wires, 2 shut-off discs, bodies Mold core, Mold cavity, Parting surface, Shut-off surfaces, Part with shrinkage. Volume check (block 160740.835, core 70948.231, cavity 70948.231, scaled part 18844.373, residual 3e-11, overlap 0). Reopened, the record and bodies are present and a fresh split gives the same numbers.

## toolbox/assembly.fcad

TB1 fixture (Phase 41 toolbox), millimetres. Assembly of a fixed 80 by 40 by 10 base plate and a 6 mm cover plate (parts in `toolbox/parts/`, three mates), clamped by two toolbox sets inserted from entered sizes (`toolbox/toolbox/`): flat washer 6.4 x 12.8 x 0.96, socket head cap screw M6 x 25 and hex nut M6 each, every one concentric to its hole and seated by a coincident or distance mate. Eight components, 0 interferences over 28 pairs, six free fastener spins. Sizes are the user's entries, not a standard's table.

## weld/frame.fcad

WM1 fixture (Phase 40 weldments), millimetres. A 1000 by 600 by 800 table frame: four rails (a sketch tube profile) mitered at the top, four legs butted under the rails, two cross members butted to legs, one diagonal flat bar coped at one end and butted at the other, four foot plates and two gussets, plus a cut list table in the drawing. Cut list: 11 members in 6 rows, rails 1040 and 640 at 45 and 45, legs 780, cross members 760, brace 953.75 at 36.87 and 36.87.
