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

## graph/geometry-nodes.fcad

GR2 fixture (Phase 24, geometry nodes and bake), millimetres, with the same graph as `geometry-nodes.graph`. Graph `Plate with bolt holes`: a 100 by 60 by 20 box, one cylinder of radius 4 turned into a ring of four by the polar array, the difference of the two (volume 115978.7614 mm3, the box minus four holes), a tagged copy (`attr.set`: name `Plate`, layer `Plates`, colour #3a7bd5), the mass node and the mid height section (five curves of total length 420.5310 mm). Baked from the nodes `tag` and `sec`: one solid body named `Plate` on layer `Plates` and five NURBS curves, all carrying the provenance `G1/<node>/<port>/<path>/<index>` in `FORMCAD_GRAPH` extended data. Reopened, the graph solves to the same volume and the baked objects keep name, layer and colour.

## sheetmetal/bracket.fcad

SM1 fixture (Phase 22, sheet metal features), millimetres. Part with seven features: sketch `Profile` (an L, 40 up and 60 along), `Base Flange` (open profile, thickness 2, inside radius 3, K 0.44, width 50, one bend of 90 degrees), sketch `JogLine` on the flat top face, `Jog` (offset 12, two bends, the far side moves up), `Far Flange` (edge flange 20 long on the far end, 30 wide centred, material inside, rect relief at both sides), `Leg Flange` (edge flange 15 long on the free end of the standing leg, 40 wide centred, with relief) and `Hem` (closed, 8 long, on the side edge of the first flat). Six recorded bends (`F2.1`, `F4.1`, `F4.2`, `F5.1`, `F6.1`, `F7.1`); rule on `Base Flange`. Reopened with a cold cache all features rebuild; `GET /sheetmetal/verify` measures thickness at sampled points of every skin face (deviation below 1e-9 mm) and every bend face is a cylinder of radius 3 or 5 (0.1 or 2.1 for the hem); editing the base flange thickness to 3 and to 1.5 rebuilds all seven features with the same result.

## graph/facade-base.fcad and graph/facade.graph

GR3 fixtures (Phase 24 exit), millimetres. The document holds one box body 9000 by 300 by 4500 on layer `WALL` and an empty layer `FACADE`. The graph reads the wall with a document object node, takes its extents from the vertices, lays out a grid of panels (sliders `columns` 8 and `rows` 5), cuts a square opening in each panel whose side falls off with the distance to an attractor point (`attr_x`, `attr_z`, `reach`, `max_open`, `gap`), and tags the cut panels as `Panel` on layer `FACADE` in colour #2f6fed. Named outputs `open_area`, `panel_count` and `fitness` (open area with a penalty above `panel_limit` panels). Imported and baked in the engine (`GRAPHBAKE`) and run with `formcad-engine graph run fixtures/graph/facade.graph --doc fixtures/graph/facade-base.fcad --bake OUT.fcad`, both give 40 solid bodies with the same total volume (1230780242.474323 mm3), bounding box, per-body properties and shape hash. Optimizer: maximising `fitness` over all seven sliders (population 40, 40 generations, seed 7) finds 29895122.67 mm2 of open area with 4 columns and 2 rows.
