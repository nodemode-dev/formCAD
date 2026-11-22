# HASHOUT_LOG · kernel worker (kernel/)

Living record of decisions and removed context for the `formcad-kernel` worker, newest first. Read before editing.

Entries older than v0.21.0 are in `backend/HASHOUT_LOG.md`, which logged the engine and the kernel together; look there for anything this file does not hold. From v0.21.0 a change to a file in `kernel/` is logged here.

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
