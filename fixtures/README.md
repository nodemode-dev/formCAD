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
