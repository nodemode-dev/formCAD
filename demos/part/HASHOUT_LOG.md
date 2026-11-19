# HASHOUT_LOG · parametric part demo (demos/part/)

Living record of decisions for the parametric part demo, newest first. Read before editing. The shim and the recorder belong to `demo/`; their decisions are in `demo/HASHOUT_LOG.md`.

## P1, demo 2 of 3: the Part workspace over a recorded engine (demos/part/ new)

What it is. The same construction as `demo/`: the real window bundled from `frontend/` with `frontend/src/main` as the app entry, behind the shared replay shim, built to one classic deferred script so it opens from `file://`. `vite.config.mjs` is `demo/vite.config.mjs` one folder deeper, with the title "FormCAD demo: parametric part" and ports 5392 and 5492; the symbol escaping plugin is kept. Nothing in `demo/`, `frontend/` or `backend/` was edited.

Opening in 3D. No code is needed for it: `part/register.ts` enters the 3D view on its own when the active document's tree has features, and the Features panel registers with order -1, so it is first in the dock. The document carries its solid and a cached display mesh, so `GET /scene` answers with the shaded part whether the kernel worker ran or not.

The Part workspace. A fresh browser profile opens in the Drafting workspace. `boot.ts` sets `formCAD.workspace` to `part` in local storage before the app evaluates, only when nothing is saved, so the first visit opens on the Part panels and a visitor's own later choice is kept. The recorder script does the same and reloads before its steps, so the recorded boot is the Part workspace's own boot: the first recording, made in Drafting and switched afterwards, missed `GET /pmi/display` at boot. After the reload the boot has no miss.

Selection. The 3D view sends `PUT /selection` with `faces`, `edges` and `owners` beside `handles`, and the engine echoes all four. The shim's built-in selection keeper answers only `handles`, so `boot.ts` keeps the whole selection in the page through the `local` hook, which runs before the built-in keeper. Revision stays 0, as recorded.

Extra reads. `/snap3d` (hover snap, POST) and `/scene-at` (the scene at a rolled-back feature) are reads, added through `reads`. Snap answers only for cursor positions the recorder visited; elsewhere the request misses quietly, because the snap layer swallows errors. `POST /grid` asks for grid lines around the current view, so after an orbit the body never matches; it is left as a quiet miss and the 3D view's own grid stays. Answering it with the nearest recorded body was rejected: a grid drawn for another view is wrong rather than missing.

Recorder script. `tools/steps.mjs` runs after the built-in `dock,palette,layers` steps (the built-in `pick` step reads the 2D display store, which is empty in the 3D view, so it is skipped). It clicks every feature row, picks five points on the part, pans, zooms, clicks the view cube, opens the palette and folds every dock panel open and shut. The recorder resolves `--script` against the folder it was started in (`demo/HASHOUT_LOG.md`, D2), so the README's command uses paths from the repository root.

Not done. Feature editing, rebuilds, rollback previews driven by the rollback bar and the part dialogs (materials, mass properties, design table) answer the demo message. No loading veil, as in `demo/`. Preferences, the vault and the automation panels show the recorder's temporary data folder and the repository path the engine reported; scrubbing them belongs in the recorder, so the recording is kept as the engine answered.

Preferences. The script opens Preferences and clicks each of its sections, so `GET /automation/*`, `/interchange/dwg` and `/kernel/status` are in the recording; before that they missed with a toast when a visitor opened the dialog.
