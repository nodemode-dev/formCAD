# HASHOUT_LOG · kernel worker (kernel/)

Living record of decisions and removed context for the `formcad-kernel` worker, newest first. Read before editing.

Entries older than v0.21.0 are in `backend/HASHOUT_LOG.md`, which logged the engine and the kernel together; look there for anything this file does not hold. From v0.21.0 a change to a file in `kernel/` is logged here.

## KW2 v0.25.0 fillet check, two-rail sweep, identical bodies in STEP (kernel_features2.py, kernel_surf.py, kernel_xde.py)

These reach users only with a new kernel release in `formai-binaries`; the published 8.0.1 bundle carries the old code. The engine works with either: the only new answer field, `untranslated`, is optional.

Fillet. The result check said "The fillet removed no material" whenever the volume did not fall. A fillet on an inside corner (a boss on a plate) adds material, so every such fillet was refused. The check now refuses only when the volume did not change.

Two-rail sweep. It was `BRepOffsetAPI_MakePipeShell` with the second rail as an auxiliary spine and a scaling law. On rails that bow toward each other the result had an 86 mm surface error and about twice the true area, though the audit flagged it. It is now a loft (`BRepOffsetAPI_ThruSections`, not smoothed) through copies of the profile: at each of `sections` stations (default 24, 3 to 200) spaced by arc length on both rails, the profile is moved from its own frame to the frame of the two rail points (x from rail to rail, normal along the mean rail tangent) and scaled by the rail distance. The profile's ends are matched to the rails by distance, so it may be drawn either way round. On the walk's rails the surface lies within 0.00028 mm of both rails, area 10593.5 mm2, vertex tolerance 1e-7. The one-rail sweep is unchanged.

STEP and IGES write. Two bodies with the same shape (two identical sweeps) got one label from `AddShape`, and the file held one of them. A body whose shape already has a label is copied first, so each body is its own product. Nine bodies, two identical, now come back as nine from STEP and from IGES.

STEP read. The walker skipped a label whose shape was empty without a record. It collects them in `empty`, and `xde_read` returns the first 50 as `untranslated`.

## KW1 v0.21.0 this log exists

The kernel is a separate program: the engine never imports OCP or build123d, and talks to the worker in JSON lines on stdio. It is frozen on its own (`setup/freeze_kernel`), published in `nodemode-dev/formai-binaries` and checked file by file against `backend/app/data/kernel-licence.json` when the app installs it. `requirements_kernel.lock` pins it for every platform. Nothing in `kernel/` changed in v0.21.0.
