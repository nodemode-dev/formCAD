# formcad-mesher

The tetrahedral mesher of FormCAD, a separate program like the kernel worker: the engine starts it as a child process and talks to it in JSON lines over stdin and stdout, one object per line (`{"id", "method", "params"}` in, `{"id", "result"}` or `{"id", "error": {"message"}}` out). It exists as its own program, with its own venv, because netgen-mesher pulls netgen-occt 7.8.1 and the kernel worker carries OCP with OpenCascade 8.0.1; two OpenCascade builds must not share a process. Netgen is LGPL-2.1-only, so it is never imported by the engine. Units are millimetres.

| Method | Params | Result |
| --- | --- | --- |
| `hello` | | versions of netgen-mesher, netgen-occt and numpy, `units`, `methods`, `protocol` |
| `faces` | `path` (a `.brep`, `.step` or `.stp` file) | `faces` (`index`, `center`, `bbox`, `area` in the order of the shape's faces), `volume`, `solids` |
| `mesh` | `path`, `out` (an `.npz` path), `maxh` (mm, default bounding-box diagonal over 20), `refine` (`[{select, maxh}]`), `groups` (`{name: select}`), `second_order` (default true), `max_elements` (capped at 400000), `grading`, `curvature` | counts, `curved`, `groups` (name to face indices), `volume`, `bbox`, `maxh`; the file holds `nodes` (N,3 corner nodes, mm), `tets` (M,4), `tet_domain`, `tris` (F,3), `tri_face` (F, face index), `edge_mid_pairs` and `edge_mid_xyz` (only when a face is curved, the true-surface midside nodes), `meta` (JSON) |

A face selector is `{"faces": [i]}`, `{"box": [[x0,y0,z0],[x1,y1,z1]], "tol"}` (faces whose bounding box lies inside), `{"plane": {"axis", "value", "tol"}}`, `{"point": [x,y,z]}` (nearest face centre) or `{"all": true}`. The element count is estimated from the volume and refused before meshing when it would exceed 1.5 times the cap, and checked again after.

`formcad_mesher.py --selfcheck` imports `netgen.meshing` and `netgen.occ` and prints the versions. Development: `./formCAD install-mesher`; frozen: `./formCAD freeze-mesher` into `mesher/dist` (shipped from formai-binaries, never inside the app). The engine finds it through `FORMCAD_MESHER`, then `<data>/mesher/<release>/formcad-mesher`, then `mesher/formcad_mesher.py` beside the repo with its venv.
