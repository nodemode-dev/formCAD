# HASHOUT_LOG · engine (backend/ and kernel/)

Living record of decisions and removed context for the engine, newest first. Read before editing.

## Clean-room renames · _v0.2.0 (app/doc/service.py, app/routers/docs.py, app/routers/sysvars.py, app/cmd/registry.py)

`DocError` became `DocumentFault` and `CommandSpec` became `CommandEntry` because both collided with type names in the reference. Behaviour, attributes (`message`, `status`) and HTTP mapping are unchanged; no other file used either name. The generic lowercase identifiers from the audit (`state_id`, `next_handle` and similar) were left as ordinary vocabulary.

## Templates, document kinds and the frozen engine · _v0.2.0 (app/doc/templates.py, app/doc/container.py, app/doc/service.py, app/doc/autosave.py, setup/freeze_backend)

`POST /api/docs` takes the Home template ids (`drawing-mm-a3`, `drawing-inch-ansi-b`, `part`, `assembly`, `drawing-sheet`, `surface`, `form`, `graph`) and the plain `metric`, `iso`, `imperial`, `inch`; each sets kind, units, limits and the layout sheet; an unknown id is a 400. The manifest records `kind`; open and recovery read it back and treat a missing or unknown kind as `drawing`. The 3D kinds open in the drafting view until their workspaces land. The freeze puts `app/data` at `app/data` (the kernel record lookup path) and names numpy and ezdxf as hidden imports because nothing imports them yet; without both the frozen selfcheck failed.

Verified: all eight ids answer 200 with their kind and units, `bogus` answers 400, a saved surface document reopens as surface; the frozen engine (135 MB, 215 files, no OCP, build123d or OCCT inside) passes selfcheck and the licence scan.

## Engine core, document core and kernel link · _v0.2.0 (app/main.py, app/core/, app/services/, app/routers/, app/doc/, app/cmd/, app/sysvars/, formcad_engine.py, kernel/)

Routers load from one list, `ROUTERS` in `app/main.py`, as `(module, prefix)` pairs through importlib, so a phase adds a router with one line; route paths inside a module are relative to its prefix. The guard (`core/guard.py`) checks a loopback Host, an Origin allow list and the `X-FormCAD-Token` header; the token is new per start, written to `<data>/session.token` with mode 0600, injected as a meta tag when the engine serves the built interface; `/api/health` is the only open route. The autosave folder is created 0700.

The OpenCascade kernel never loads in this process. `services/kernel.py` finds the worker through `FORMCAD_KERNEL` (a frozen program or a `.py` path), `<data>/kernel/<release>/formcad-kernel`, then the repo's `kernel/venv`; it speaks JSON lines on stdio (`hello`, `shutdown`). OCP exposes no OCCT version constant, so the worker reports the first three parts of the OCP version as the OCCT version and the full OCP version beside it. The install path extracts with the tar `data` filter, requires every file to match `app/data/kernel-licence.json`, refuses extra files and installs nothing on a mismatch; the record ships with `release: null` until formCAD-binaries publishes a build.

The document is a handle-keyed store (handles from 0x100) with an entity kind registry; unknown kinds round-trip untouched in the foreign-data slot. Undo is a change journal of before-images per transaction, not document copies; marks, BEgin/End groups and a 2000-step cap. New drawings without a template follow MEASUREINIT (imperial by default). Typed object snaps that need a picked point answer that a canvas pick is required until the drafting canvas lands; window and crossing selection use bounding boxes until exact hit tests exist. Linetypes whose dash values the spec did not give numerically use our own consistent values.

Verified: selfcheck exits 0; health open, capabilities 401 without the token, 403 for a foreign Origin or Host; websocket refused without a token; the dev worker reports OCCT 8.0.1, OCP 8.0.1.1, build123d 0.13.0; LINE with four inputs makes two lines, save and reopen keep two, U removes both, REDO restores them.
