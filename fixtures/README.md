# Fixtures

Sample data for manual checks and demos. These are data files, not tests.

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
