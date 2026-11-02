# Survival table · save then reopen, checked entity by entity

Source drawing: 1730 objects. Values: objects of the kind / objects that differ after reopen. Differences listed are the first found.

| kind | R12 | R2000 | R2004 | R2007 | R2010 | R2013 | R2018 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| arc | 78/0 | 78/0 | 78/0 | 78/0 | 78/0 | 78/0 | 78/0 |
| assoc_array | 19/19 | 19/0 | 19/0 | 19/0 | 19/0 | 19/0 | 19/0 |
| attdef | 19/17 | 19/17 | 19/17 | 19/16 | 19/16 | 19/16 | 19/16 |
| circle | 166/0 | 166/0 | 166/0 | 166/0 | 166/0 | 166/0 | 166/0 |
| dimension | 207/0 | 207/0 | 207/0 | 207/0 | 207/0 | 207/0 | 207/0 |
| ellipse | 19/19 | 19/0 | 19/0 | 19/0 | 19/0 | 19/0 | 19/0 |
| hatch | 67/67 | 67/3 | 67/0 | 67/0 | 67/0 | 67/0 | 67/0 |
| helix | 4/4 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 |
| insert | 33/5 | 33/5 | 33/5 | 33/4 | 33/4 | 33/4 | 33/4 |
| leader | 9/9 | 9/0 | 9/0 | 9/0 | 9/0 | 9/0 | 9/0 |
| line | 390/7 | 390/2 | 390/0 | 390/0 | 390/0 | 390/0 | 390/0 |
| lwpolyline | 209/209 | 209/3 | 209/3 | 209/3 | 209/3 | 209/3 | 209/3 |
| mleader | 30/30 | 30/1 | 30/1 | 30/0 | 30/0 | 30/0 | 30/0 |
| mline | 25/25 | 25/0 | 25/0 | 25/0 | 25/0 | 25/0 | 25/0 |
| mtext | 33/33 | 33/0 | 33/0 | 33/0 | 33/0 | 33/0 | 33/0 |
| point | 77/0 | 77/0 | 77/0 | 77/0 | 77/0 | 77/0 | 77/0 |
| polyline3d | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 |
| ray | 3/3 | 3/0 | 3/0 | 3/0 | 3/0 | 3/0 | 3/0 |
| region | 16/16 | 16/0 | 16/0 | 16/0 | 16/0 | 16/0 | 16/0 |
| solid | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 |
| spline | 42/42 | 42/0 | 42/0 | 42/0 | 42/0 | 42/0 | 42/0 |
| table | 10/10 | 10/0 | 10/0 | 10/0 | 10/0 | 10/0 | 10/0 |
| text | 249/0 | 249/0 | 249/0 | 249/0 | 249/0 | 249/0 | 249/0 |
| viewport | 2/2 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 |
| wipeout | 3/3 | 3/0 | 3/0 | 3/0 | 3/0 | 3/0 | 3/0 |
| xline | 14/14 | 14/0 | 14/0 | 14/0 | 14/0 | 14/0 | 14/0 |

Objects read back: R12 1566, R2000 1730, R2004 1730, R2007 1730, R2010 1730, R2013 1730, R2018 1730

Known differences at R2018 (all benign): attribute definition mode keys `annotative` and `multiline` default in on reopen; a cached attribute anchor `at` is rebuilt by the block cache; a polyline vertex that lacked `sw` and `ew` gains zeros.
R2000 and R2004: true colour becomes the nearest index, transparency and layer transparency are dropped, attribute position lock is dropped (DXF before R2007 cannot hold them).
R12: polylines become 3D polylines, ellipses and splines become flattened polylines, text blocks become text lines, hatch, leader, multileader, multiline, wipeout, table, array, region, ray and construction line are dropped and counted, only the first layout stays.
