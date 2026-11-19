# HASHOUT_LOG · browser demo 3 (demos/graph/)

Living record of decisions for the node graph demo, newest first. Read before editing. The shim and the recorder are `demo/`'s; see `demo/HASHOUT_LOG.md`.

## G6, one reveal after the editor has painted

Under 4x CPU the page showed a layout shift of 0.00386 (`div.gx-grid`) on both load and reload. The app revealed `#app` at `body.app-ready`, and `gr-open` then opened the editor about 100 ms later. The demo page's head rule is now `body.app-ready.demo-ready #app { visibility: visible; }`, rewritten in `vite.config.mjs`. `src/main.ts` runs `gr-open` once the app is ready and adds `demo-ready` two animation frames after the editor has a graph record and a `.gx-node` in the layout. If the editor has not painted 4 s after app-ready, the class is added anyway, and a 30 s timer adds it in any case, so the page never stays blank. Measured with the throttle check (`--cpu 4 --reload`): 0 on load and on reload, no console errors.

## G5, the layout now lives in the document

The engine baked the G2 layout into `backend/app/data/demos/graph.fcad`. The engine opened the file, a `PUT /api/docs/{id}/graphs/G1` with `solve: false` set node x and y (columns by wire depth, 300 apart, stacked by estimated height and centred), and `POST /api/docs/{id}/save` wrote the file back to the same path. Positions: box 0,100; hole 0,348; ring 300,200; cut 600,236; tag 900,0; mass 900,224; sec 900,472; secl 1200,248. The part brep and the cached display mesh are byte for byte the same, `/scene` answers 200 from a fresh engine, and the file is 0644. Through the engine's save, the manifest `title` becomes the file stem `graph` (it was "Plate with bolt holes") and `app.version` becomes 0.17.0. The origin-layout step is gone from `src/boot.ts`, the recording was redone, and the fitted graph has the same bounds, so `graph.webp` was not captured again.

## G4, the home screen picture

`frontend/public/demos/graph.webp` was four circles because the old capture had the editor closed. It is now a 1440 by 900 capture of this demo in the dark theme with the editor fitted and zoomed out one step (the fitted graph is about 1000 px wide, wider than a 16:10 crop that stays inside the stage), cropped to x 136 to 1048 and y 163 to 733 and scaled to 640 by 400 WebP (quality 90) with the system Pillow. It is taken from the demo rather than from the recorder's window because the recorded document has no node layout (G2).

## G3, what is answered in the page

Through `installReplay`'s `local` hook in `src/boot.ts`, never by editing the shim:

- `GET .../graphs/{gid}`: the recorded answer, or the definition last accepted by a layout-only `PUT`.
- `PUT .../graphs/{gid}`: accepted with `{expired: [], busy: false}` only when the definition differs from the held one in node `x`, `y` and the `view` alone, compared after a `decodeGraph` and `encodeGraph` round trip so both sides have the same shape. The accepted definition becomes the held one, so a later reload keeps the moves. Any other change (wires, values, nodes, names) falls through to the 503 notice, and the store then reloads the held definition, which is the honest result: nothing changed.
- `GET .../state`: always the last recorded state, the solved one. The first recorded state is all blank (the document opens unsolved), and the store solves on open when every node is blank; replaying that order would toast the notice on open. Solve and Recompute still answer with the notice.
- `GET .../preview`: always the last recorded preview, the one after the solve.

Tooltips read `GET .../tree/{node}/{port}`; the recorder script reads every output port's first page through the page's own fetch, because hovering in the recorded window reaches only the top node (G2). The recorded requests with no answer are `POST /grid` (the canvas asks with a body that differs from the recorded one) and `GET /pmi/display`; neither shows a notice.

## G2, the document has no node layout

Superseded by G5. Every node of G1 in `graph.fcad` was at x 0, y 0, so the real window stacked all eight nodes on top of each other. At first the demo could not edit `backend/`, so `src/boot.ts` laid the graph out when every node is at the origin: columns by wire depth (300 units apart), nodes in a column stacked by an estimate of their height and centred on the tallest column. A real layout belongs in the document; once `graph.fcad` carries one, the layout step does nothing and a re-record picks it up.

## G1, opening on the graph editor (demos/graph/ new)

The app opens a graph document on the drawing; the editor opens only through the `gr-open` command. `src/main.ts` imports `boot.ts` (the shim), then `frontend/src/main`, then polls every 100 ms for up to 30 s until `body.app-ready` is set and the document store has an active document, and runs `commands.run('gr-open')` once. It uses the app's own `commands`, `docStore` and `graphEditor` modules, which the bundle shares with the app, so no frontend edit is needed.

`vite.config.mjs` is `demo/vite.config.mjs` with every path one level deeper, the title "FormCAD demo: node graph" and ports 5393 (dev) and 5493 (preview), both `host: false`; the symbol escape plugin is kept. The recorder is run with `--steps clear,dock,palette` (the pick step is for 2D drawings) and `--script tools/steps.mjs`, which opens the editor through the command palette, waits for the solve, clicks every node head, hovers every port, reads every output tree, opens the node search with a double click and types `cyl`, zooms and fits. The recorder resolves `--out` and `--script` against the folder it was started in (`demo/HASHOUT_LOG.md`, D2), so the README's command uses paths from the repository root.
