# formcad-kernel

The geometry worker of FormCAD. It is a separate program: the engine starts it as a child process and talks to it in JSON lines over stdin and stdout, one object per line. `{"id", "method", "params"}` goes in; `{"id", "result"}` or `{"id", "error": {"message"}}` comes back. It answers `hello` (versions, the method list, `units: "mm"`), `shutdown` and the modelling methods below. Kernel units are millimetres; the engine converts document units at its boundary. OpenCascade's console output is routed to stderr, so stdout carries only protocol lines. Shapes live in the worker under ids (`s1`, `s2`, ...); the engine keeps the BREP text in the `.fcad` container and reloads shapes after a worker restart.

| Method | Params | Result |
| --- | --- | --- |
| `primitive` | `kind` box, cylinder, sphere, cone, torus or extrude; `origin`, `axis`, `xdir`; sizes (`dx dy dz`, `radius`, `radius1 radius2`, `major minor`, `height`); extrude takes `loops` (`{"vertices": [[x, y, bulge]], "outer"}` or `{"circle": {"c", "r"}}`), `plane` and `height` or `vector` | `id`, `summary` |
| `boolean` | `op` fuse, cut or common; `base`; `tools`; `unify` | `id`, `summary`, `history` (per input face and edge: new indices, deleted) |
| `transform` | `matrix` (12 numbers) or `translate`, `rotate`, `scale` | `id`, `summary`, `history` |
| `open_step`, `open_iges` | `path` | `bodies` (id, name, rgb, summary) |
| `save_step` | `path`, `bodies` (id, name, rgb), `schema` ap203, ap214 or ap242 | path |
| `shape_save`, `shape_load` | `.brep` path | id, summary |
| `tessellate` | `id`, `linear`, `angular`, `path` (`.mesh`) | counts and the written file, laid out as in `handoff/G1.md` |
| `mass_properties` | `id`, `density` | volume (only for a closed valid solid), area, centroid, inertia |
| `bounds` | `id`, `mode` geometry or mesh | min, max |
| `check`, `shape_summary`, `shape_free`, `shape_list` | | |
| `combine` | `op` add, subtract or common; `bodies` (first is the base); `fuzzy` (mm), `analyze`, `force`, `retry`, `unify` | `id`, `summary`, `history`, `diagnostics` (argument analyzer findings, fuzzy used, whether the larger-fuzzy retry ran) |
| `split` | `body`; `planes` (`{origin, normal}`) and/or `tools` (shape ids of surfaces or solids); `fuzzy`, `analyze`, `force` | `pieces` (each `id`, `summary`, per-face and per-edge `history` against the body) |
| `geometry` | `id` and one of `face`, `edge`, `vertex` (0-based index) | surface or curve kind with origin and normal (plane), axis and radius (cylinder, cone), centre (sphere, torus, circle), end points, midpoint and centroid, in millimetres |
| `body_props` | `id`, `eps` (relative integration error, default 1e-9) | area always; volume, centroid, inertia about the centre of mass per unit density, principal moments and axes only for a closed valid solid |
| `feature_fillet` | `id`, `edges` (indices or `{edge, radius}`, `{edge, radius1, radius2}`, `{edge, points: [[position, radius]]}`), `faces`, `radius`, `profile` | `ok`, `id`, `summary`, `history`, `contours`, `blend_faces`, `warnings`, or `failed` edges with a reason |
| `feature_chamfer` | `id`, `edges`, `faces`, `distance`, `distance2` with `face`, or `angle` with `face` | as `feature_fillet` |
| `feature_shell` | `id`, `faces` to remove, `thickness`, `direction` inward or outward, `join` arc or intersection | as `feature_fillet` |
| `feature_draft` | `id`, `faces`, `angle`, `pull`, `neutral_plane`, `allow_partial` | as `feature_fillet`, plus `drafted_faces` |
| `feature_pattern` | `id`, `seed`, `op` fuse, cut or copies, `pattern` linear (`directions`) or circular (`axis`, `count`, `angle`), `skip`, `include_seed` | as `feature_fillet`, plus `instance_faces` |
| `feature_mirror` | `id`, `plane`, `mode` feature (`seed`, `op`) or body (`merge`) | as `feature_pattern` |
| `feature_precheck` | `kind`, then the parameters of that feature | `ok`, `errors`, `warnings` |
| `feat_extrude` | `id` (base body or none), `op` add or cut, `profile` (`frame`, `regions`, `open`), `end1`/`end2` with depths, `mid`, `flip`, `draft1`/`draft2`, `thin`, `target` face for up to face | `ok`, `id`, `summary`, `history`, `created` (face index to role), `adjacency`, `tool`, `warnings`, `errors` |
| `feat_revolve` | `id`, `op`, `profile`, `axis` (`origin`, `dir`), `angle1`, `angle2`, `mid`, `flip`, `thin` | as `feat_extrude` |
| `sweep`, `loft`, `boundary_solid`, `rib`, `hole`, `sweep_preview` | module `kernel_shapes.py`. `sweep`: `profile`, `path` (shape, segments, nurbs record, vertices or planar sketch), `mode` fixed, frenet, corrected_frenet or binormal, `twist`, `scale_end`, `transition`, `guide`, `guide_contact`. `loft`: `sections` (profiles or a point at either end), `ruled`, `smoothing`, `start`/`end` condition. `boundary_solid`: `surfaces` (curve groups), `cap_planar`, `tolerance`. `rib`: `id`, `profile` (open), `thickness`, `thickness_side`, `grow`, `flip`, `draft`. `hole`: `id`, `spec` (kind, diameter, depth or through, cbore, csk, tap_drill, thread), `positions`, `normal` | `id`, `summary`, `origins` (face index to role), `volume`, `warnings` |
| `feat_sweep`, `feat_loft`, `feat_boundary`, `feat_rib`, `feat_hole` | the same parameters plus `op` add, cut or new, with the base in `id` | as `feat_extrude`; `feat_hole` adds `cosmetic_threads` |
| `feat_signatures` | `id`, `faces`, `edges` | per index: `k` kind, `n`, `c`, `a`, `r`, `l` |
| `feat_topology` | `id` | `faces`, `edges`, `vertices` with adjacency |
| `feat_rays` | `id`, `rays` | hit faces for each ray |
| `curve_make` | `curve` (degree, poles, weights, knots, mults, periodic), `tol`, `angle_tol` | `curve`, `tolerances` (audit of vertex, edge and face tolerances) |
| `curve_interpolate` | `points`, `tangents`, `parametrization` chord, centripetal or uniform, `periodic` | `curve`, `deviation`, `tolerances` |
| `curve_approximate`, `curve_refit`, `curve_rebuild`, `curve_simplify` | `curve` or `points`, `degree`, `count`, `tol` | `curve`, `deviation`, `tol_used` |
| `curve_degree`, `curve_knot_insert`, `curve_knot_remove`, `curve_periodic`, `curve_trim`, `curve_reverse` | `curve` plus the knob of each | `curve`, `deviation` |
| `curve_offset`, `curve_extend` | `curve`, `distance` and `normal`, or `end`, `length`, `kind` line, arc or smooth | `curve`, `deviation` |
| `curve_continuity` | `a`, `b`, `end_a`, `end_b`, `tol`, `angle_tol`, `curvature_tol` | OCCT G0 to G2 flags and measured gaps |
| `curve_eval`, `curve_to_shape`, `curve_from_shape` | `curve` and `params`, or a shape id | points and derivatives, or a stored edge chain |
| `surf_loft`, `surf_sweep`, `surf_network`, `surf_patch`, `surf_extrude`, `surf_revolve`, `surf_planar`, `surf_edge` | module `kernel_surf.py`; every call carries `tol` (mm) and `angtol` (rad). Curves are specs: `line`, `circle`, `ellipse`, `bspline`, `path`, `shape`, `shape_edge`. Sweep takes `rail`, optional `rail2`, `profiles`, `frame`; network `u`, `v` | `id`, `summary`, `report` (method errors and a stored-tolerance audit) |
| `surf_extend`, `surf_match`, `surf_blend`, `surf_continuity`, `surf_edges` | module `kernel_match.py`; a side is `{face: {id, index}, edge: {id, index}}`. Blend: `continuity` 0 to 2, `influence`, `method` auto, filling or hermite. Match: `moving`, `target`, `continuity`. Extend: `face`, `edge`, `length` | `id`, `summary`, `report` with `level`, `max_gap`, `max_angle`, `max_curvature_gap`; G3 is not measured |
| `view_build` | module `kernel_views.py`; `items` (`id`, `matrix` 12 numbers, row major, mm), `normal` (toward the viewer), `up`, `origin`, `mode` (`exact` HLRBRep_Algo, `draft` HLRBRep_PolyAlgo, `auto` by `cutover` faces), optional `section` (`kind` full, half, offset, aligned; `points`, `pnormal`, `keep`), `clip` (`circle`, `polygon` or `rect` in view mm), `breaks` (`axis`, `lo`, `hi`, `gap`, `style`) | `classes` (eight edge classes of 2D curve records in view mm, each with `s` source and `p` 3D ends where known), `faces` (section loops), `extra` (break lines), `bounds`, `frame`, `stats` |
| `surf_offset`, `surf_split`, `surf_join`, `surf_naked` | module `kernel_surf.py` and `kernel_diag.py`; split takes `tool_curves` and `direction` or `tools`, with `remove_points` to trim; join takes `ids`, `solid` | `id` or `pieces`, `report`, `history`; join and naked add free-edge polylines |
| `asm_interference` | module `kernel_asm.py`; `items` (`id`, `shape`, `matrix` 12 numbers, row major, mm), `fuzzy` (mm), `min_volume`, `clearance` (mm, report gaps below it), `linear` (mesh deflection), optional `pairs` and `skip`. Bounding-box prefilter, `BRepExtrema_ShapeProximity` on meshes, `BRepAlgoAPI_Common` with the fuzzy value and `BRepGProp` volume, then `BRepExtrema_DistShapeShape` | `interferences` (pair, volume, centre), `clearances` (pair, distance, points), `errors`, `stats` (pairs and hits per stage), `linear`, `fuzzy`, `ms` |
| `asm_blocking` | module `kernel_asm.py`; `items` as above, `directions`, `distance`, `fuzzy`, `min_volume`; samples translations of each item against the rest | per item and direction, the blocking items; used only for the auto-explode suggestion |
| `bool_diag`, `fillet_edge`, `chamfer_edge` | module `kernel_diag.py`; boolean `op`, `base`, `tools`, `fuzzy`, `max_fuzzy`, `retry`, `check_only`; fillet `edges`, `radius`, `radius2`, `radii`, `continuity`; chamfer `distance`, `distance2`, `angle` | `id`, `summary`, `report` (argument analysis, retry ladder, fuzzy value used, result check), `history` |
| `an_shape_data`, `an_deviation`, `an_comb`, `an_affine`, `an_snap` | module `kernel_analysis.py`; shape data takes `id`, `linear`, `angular`, `curvature`, `path` and writes normals and K, H, k1, k2 per display vertex to a `.adat` file; deviation takes `points_path`, `target`, `faces`, `signed`, `path`; comb takes a curve spec and a sample count; affine takes `id` and a 12 number `matrix` (mm); snap takes `items`, `ray`, `aperture`, `modes`, `base`, `plane`, `limit` | `path` or `ok`, comb samples (points, normals, curvature), `summary` and `id`, or snap `candidates` |
| `threedm_info`, `threedm_read`, `threedm_write`, `threedm_compare`, `threedm_curve_compare`, `threedm_verify` | module `kernel_3dm.py`, needs rhino3dm 8.35.0 (the worker answers `threedm_unavailable` without it). Info takes `path`. Read takes `path` and `work_dir` and checks the archive version (2 and up). Write takes `path`, `version` (0 is the latest, else 2 to 80), `unit`, `abs_tol` (mm), `angle_tol`, `layers`, `items` (kinds `curve`, `spec`, `line`, `polyline`, `point`, `shape`, `mesh`, `points`). Compare takes two shape ids and optional `samples`; verify takes the written `path` and `expect` rows keyed by object | info: version, unit, tolerances, layers, object counts. Read: `items` (shape ids, curve records, `.fmesh` paths), `report`, `failed_faces`, `notes`. Write: `written`, `failed`, `lossy` (trimmed faces, unjoined faces, 32-bit mesh vertices), `skipped`, `version_written`. Compare: `max`, `rms`, `a_to_b`, `b_to_a`, `samples` in mm |

The third-party notices of the worker are in `NOTICE.md`.

## Why it is separate

The worker carries OpenCascade (OCCT), which is LGPL-2.1 with the OCCT exception. FormCAD itself stays permissively licensed, so the worker is never bundled in the app, the installers or the engine. It ships from the `formCAD-binaries` repository as release archives, one per platform, and the app downloads the one for its machine on first run, the way formcut fetches ffmpeg from `formcut-binaries`.

- Release tag: `occt-<release>`
- Archive: `occt-lgpl-<release>-<triple>.tar.gz`, holding one folder `occt-lgpl-<release>-<triple>/` with `formcad-kernel` (`formcad-kernel.exe` on Windows), the shared OpenCascade libraries beside it so they can be replaced, the LGPL text and the third-party notices
- Address: `https://github.com/nodemode-dev/formCAD-binaries/releases/download/occt-<release>/occt-lgpl-<release>-<triple>.tar.gz`
- The engine checks every file against the SHA-256 in `backend/app/data/kernel-licence.json` and installs to `<data>/kernel/<release>/` only if all of them match. No build is published yet, so the record holds `"release": null` and an empty file list.

## Dependencies

`requirements_kernel.txt` pins `cadquery-ocp-novtk` (Apache-2.0 wrapper around dynamically linked OCCT) and `build123d` (Apache-2.0), for Python 3.12.

## Running it from source

```
python3.12 -m venv kernel/venv
kernel/venv/bin/pip install -r kernel/requirements_kernel.txt
echo '{"id":1,"method":"hello"}' | kernel/venv/bin/python kernel/formcad_kernel.py
```

## How the engine finds it

In order: `FORMCAD_KERNEL` (a frozen `formcad-kernel` file, or `kernel/formcad_kernel.py`, which the engine runs with the `venv` python beside it); then `<data>/kernel/<release>/formcad-kernel` (`FORMCAD_KERNEL_RELEASE` picks the release, else the newest folder); then the repository's `kernel/venv` with `kernel/formcad_kernel.py`. With none of these the kernel is absent, which is a normal state: the app runs its 2D features.
