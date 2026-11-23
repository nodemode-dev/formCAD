# HASHOUT_LOG · kernel worker (kernel/)

Living record of decisions and removed context for the `formcad-kernel` worker, newest first. Read before editing.

Entries older than v0.21.0 are in `backend/HASHOUT_LOG.md`, which logged the engine and the kernel together; look there for anything this file does not hold. From v0.21.0 a change to a file in `kernel/` is logged here.

## KW7 v0.29.0 match and extend on displayed surfaces (kernel_surf.py, kernel_match.py)

Once a surface has been meshed for the 3D view, `BRepBuilderAPI_NurbsConvert` on its face returns a face with a null surface, so `surf_match` failed with "The moving surface could not be converted to a B-spline surface" (and `surf_extend` and `to_bspline_surface` used the same pattern). In the window every surface is displayed, so match failed there every time; the walks passed because they ran without fetching the scene. `kernel_surf.nurbs_convert` converts a copy made without the mesh (`BRepBuilderAPI_Copy(shape, True, False)`), as `kernel_cv` and the 3DM writer already did, and the three call sites use it. Checked against the walk engine (2026-11-22): two lofts, the scene fetched, then match G2 in 0.1 s (achieved G2, gap 6.07e-14 mm) and extend by 10 mm; before the change every match after the scene failed. This reaches users with the next kernel bundle.

## KW6 v0.29.0 surface control points (kernel_cv.py, formcad_kernel.py)

Handoff 9.2. `surf_net` and `surf_set_poles`, loaded from their own module with a fallback message; they work on a body with exactly one face. The face is first copied without its mesh, because after a B-spline face has been meshed `BRepBuilderAPI_NurbsConvert` returns a face with a null surface (`to_bspline_surface` in `kernel_surf.py` and `match` in `kernel_match.py` use the same convert-then-check pattern and were not tested on a displayed surface). Non-B-spline faces are converted; periodic surfaces are made non-periodic so the pole indices are plain. `surf_net` returns poles, weights (empty when not rational), flat knot sequences and a preview grid: knot spans subdivided to about 64 nodes a direction, or 81 with an inside mask from the face classifier for a trimmed face (about 0.3 s). `surf_set_poles` takes absolute positions in mm; an untrimmed face is rebuilt with `MakeFace`, a trimmed one from its own parameter-space trim curves on the new surface, then fixed and checked, and an invalid result is refused. History maps face 0 to 0 and edges by the midpoints of their parameter-space curves.

## KW5 v0.29.0 untrim, shrink and G3 on seams (kernel_trim.py, kernel_match.py, formcad_kernel.py)

Handoff 9.4 and 9.5. `surf_untrim` gives a face back its whole underlying surface (mode all) or drops only its inner loops (mode holes), optionally returning the removed trim curves as B-spline records (degenerate edges and edges on the natural boundary skipped); a plane or extrusion has no natural boundary, so it untrims to the face's own extent. `surf_shrink` cuts the underlying surface to the trim's parameter box plus 1 percent of that box on each side, clamped to the old range: B-spline and Bezier surfaces are segmented, other types become a rectangular trimmed surface, the parameter-space trim curves move across unchanged, and an invalid result is refused. Loaded from their own module.

`seam_report` now measures G3: at each seam sample both surfaces give, from third derivatives, the rate of change across the seam of the three curvature components (across, twist, along); the figure is the largest difference in 1/mm2, the tolerance `max(curvature_relative * max(rate, kmax squared), angle / length squared)`, and G3 requires G2. The report gains `g3` (null when no sample could be evaluated), `max_curvature_rate_gap`, its place, the sample count, `tolerance.curvature_rate` and a rate per hair; `level` may be G3. Checked against a numeric derivative along the normal section (11.45522 against 11.45516) and a parabolic extrusion's closed form. Finding: the hermite G2 surface blend has a rate gap of 12 to 15 per mm2 at its seams, so it is G2 and far from G3; surface blend still offers 0 to 2 only. Curve blend does offer G3.

Proven against a worker engine (2026-11-22): a loft of 108.18750 mm2 split by a projected circle; untrimming the 95.49134 piece gave 108.18750 again with two trim curves kept; shrinking the 12.69613 disc took its parameters from 0..1 to about 0.296..0.704 with the area changed by 7e-15; a second shrink and an untrim of an untrimmed face were refused with their messages; undo restored the disc. Not tested on closed periodic surfaces with seam edges.

## KW4 v0.29.0 surface fillet, chamfer and variable fillet (kernel_surf.py, formcad_kernel.py)

Handoff 9.1. `surf_fillet` with kind fillet, chamfer or variable. Two faces of one body use their shared edge; two bodies are sewn first; two single surfaces that cross are cut along their intersection, keeping the largest piece of each or the piece nearest `keep_a` and `keep_b`. Built with BRepFilletAPI on the shell. The variable law is `[t, r]` pairs mapped by length over the whole spine (tangent chains included), per spine edge through `SetRadius(UandR, IC, IinC)`; `from` picks the end where t is 0; a closed spine needs equal end radii. Trim and join gives one shell, or a solid when no free edge remains, with face and edge history; trim alone gives three pieces; no trim gives the blend surface only. The report carries tol, angtol, the stored-tolerance audit, valid, free edges, closed solid, shells, the spine, radii measured at stations (by three-point circumradius, because GeomLProp curvature was wrong on rational fillet surfaces), radius range and the largest tangent angle. A result whose stored tolerance exceeds 5 percent of the smallest size is refused as too large, although OpenCascade calls it valid. `closed_solid` is shared with `join`.

## KW3 v0.28.0 modelled threads, thicken, delete face (kernel_features3.py, formcad_kernel.py)

Handoff 8.6. `feat_thread`, `feat_thicken` and `feat_delete_face`, registered from their own module with a fallback message when it cannot load. They reach users with the next kernel bundle; until then the engine says the installed kernel is older than the feature.

Threads: a sweep along one long helix edge gave volumes about 11 percent off, so the thread is built from ruled faces one turn at a time between four helical rails; the tool volume then matches the hand value (114.03 against 114.0 mm3). Basic ISO 60 degree profile, depth 5H/8, flats P/8 and P/4; a cut tool reaches 0.05 pitch beyond the face and an added thread starts half a profile in from the free end. Faces get roles `thread:root.k`, `thread:flank1.k`, `thread:flank2.k`, `thread:crest.k`, `thread:start` and `thread:end`, k the turn.

Thicken uses the kernel's offset with thickening; both sides offsets the sheet by minus half the thickness first. A slab that changes the volume by less than 1e-6 of its own volume is refused with a message. Roles `thicken:front`, `thicken:back`, `thicken:side`.

Delete and heal uses the kernel's defeaturing, which reports success even when it cannot heal and returns the shape unchanged, so a removed face still present in the result counts as a failure. Delete and patch fills each gap with a filling surface, tangent only on edges where the deleted face met its neighbour smoothly (within about 5 degrees; tangency everywhere put a patch 44.5 mm off), and fails when the patch misses the gap edges by more than 1 percent of the part size. Patch faces are matched to history by surface type, centroid and area or length, because sewing makes new faces; roles `patch.k`.

## KW2 v0.25.0 fillet check, two-rail sweep, identical bodies in STEP (kernel_features2.py, kernel_surf.py, kernel_xde.py)

These reach users only with a new kernel release in `formai-binaries`; the published 8.0.1 bundle carries the old code. The engine works with either: the only new answer field, `untranslated`, is optional.

Fillet. The result check said "The fillet removed no material" whenever the volume did not fall. A fillet on an inside corner (a boss on a plate) adds material, so every such fillet was refused. The check now refuses only when the volume did not change.

Two-rail sweep. It was `BRepOffsetAPI_MakePipeShell` with the second rail as an auxiliary spine and a scaling law. On rails that bow toward each other the result had an 86 mm surface error and about twice the true area, though the audit flagged it. It is now a loft (`BRepOffsetAPI_ThruSections`, not smoothed) through copies of the profile: at each of `sections` stations (default 24, 3 to 200) spaced by arc length on both rails, the profile is moved from its own frame to the frame of the two rail points (x from rail to rail, normal along the mean rail tangent) and scaled by the rail distance. The profile's ends are matched to the rails by distance, so it may be drawn either way round. On the walk's rails the surface lies within 0.00028 mm of both rails, area 10593.5 mm2, vertex tolerance 1e-7. The one-rail sweep is unchanged.

STEP and IGES write. Two bodies with the same shape (two identical sweeps) got one label from `AddShape`, and the file held one of them. A body whose shape already has a label is copied first, so each body is its own product. Nine bodies, two identical, now come back as nine from STEP and from IGES.

STEP read. The walker skipped a label whose shape was empty without a record. It collects them in `empty`, and `xde_read` returns the first 50 as `untranslated`.

## KW1 v0.21.0 this log exists

The kernel is a separate program: the engine never imports OCP or build123d, and talks to the worker in JSON lines on stdio. It is frozen on its own (`setup/freeze_kernel`), published in `nodemode-dev/formai-binaries` and checked file by file against `backend/app/data/kernel-licence.json` when the app installs it. `requirements_kernel.lock` pins it for every platform. Nothing in `kernel/` changed in v0.21.0.
