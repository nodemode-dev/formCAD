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
