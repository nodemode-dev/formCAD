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
