# formCAD demo: parametric part

Demo 2 of 3. An offline demo of formCAD's Part workspace that runs in a browser with no engine, no 3D kernel, no Tauri shell, no network and no install. Demo 1 (2D drafting) is in `demo/`.

## Open it

- Double-click `demos/part/index.html` (it works from `file://`), or
- serve the folder with any static server, for example `python3 -m http.server --directory demos/part 8000`.

Every script, style, font and the recording are local to this folder: `index.html`, `favicon.png` and `assets/` (one classic deferred script `assets/formcad-demo.js` with the recording inside it, one stylesheet `assets/formcad-demo.css`, the Inter and JetBrains Mono font files).

## What it shows

The page is the real formCAD window, bundled by Vite from `frontend/` as it is. It opens in the Part workspace on the demo document `part`, a plate with a boss, a draft, a shell, a pocket, a hole pattern, fillets and a chamfer: 13 features. The part is shown shaded with edges in the 3D view, and the Features panel lists the history with each feature's build state. The shaded mesh and the tree are the engine's own answers for that document, recorded when the real engine had it open.

## Things to try

- Orbit by dragging with the left button, pan with the middle or right button, zoom with the wheel; a middle double-click zooms to the whole part.
- Click the view cube's faces, edges and corners for the standard views; its home button returns to the start view.
- Hover and click faces and edges of the part; the pick filter (Any, Body, Face, Edge) at the top left narrows what a click takes.
- Click features in the Features panel to select them; hover a row to see the features it depends on and the ones that depend on it.
- Switch the display mode in the status bar (shaded, shaded with edges, wireframe and the others), perspective or parallel projection, the grid.
- Fold and unfold the dock panels (Features, Configurations, Reference Geometry, Layers and the rest), open the command palette with Ctrl+Shift+P, change the theme with the sun and moon button, or pick another accent in Preferences.
- Switch workspaces in the title bar; the window rearranges its panels as the desktop app does.

## What is not in the demo

Every edit answers "This is a browser demo. The desktop app does this." as the app's usual error toast:

- rebuild, force rebuild, roll back and roll forward, suppress, reorder, rename and delete features
- new sketches and features, editing a feature's parameters, configurations, the design table, materials and mass properties
- opening, saving, exporting and closing documents, new documents, and the home screen's Demos cards
- anything the engine was not asked for while recording

Hover snapping on faces asks the engine for the nearest snap point at each cursor position; positions the recorder did not visit get no snap marker, quietly. The construction grid asks the engine for its lines whenever the view changes; views the recorder did not visit keep the grid the 3D view draws on its own.

## What stands in for the engine

`src/boot.ts` installs the shared replay shim from `demo/src/shim/replay.ts` (see `demo/README.md` for how it matches requests) with two extra read paths, `/snap3d` and `/scene-at`, which are POST or GET reads the 3D view makes while viewing. Selection in the 3D view carries faces, edges and owners as well as handles, so `boot.ts` keeps it in the page with a `local` handler that answers `GET` and `PUT /api/docs/{id}/selection` the way the engine does. It also sets the saved workspace to Part when none is saved, so the first visit opens on the Part panels.

## Rebuild and re-record

The built files in this folder are committed. To re-record against the current engine and interface, then rebuild, from the repository root:

```sh
demo/tools/record --doc backend/app/data/demos/part.fcad --out demos/part/recordings/part.json --steps dock,palette,layers --script demos/part/tools/steps.mjs
cd demos/part && ../../frontend/node_modules/.bin/vite build --config vite.config.mjs
```

`tools/steps.mjs` waits for the 3D view, sets the saved workspace to Part and reloads so the boot is the Part workspace's own, clicks every feature in the tree, picks faces in the 3D view, pans, zooms, clicks the view cube, opens the command palette and folds every dock panel open and shut. The engine starts the dev kernel from `kernel/venv` when it needs one; the document carries its solid and a cached display mesh, so the recording is the same without it.

`../../frontend/node_modules/.bin/tsc --noEmit -p .` in `demos/part/` type-checks the entry. `vite preview --config vite.config.mjs` serves the built folder on http://localhost:5492; the dev server port is 5392, both bound to localhost only.

## Licences

The bundle contains formCAD's own code (Apache-2.0), Inter and JetBrains Mono (OFL 1.1, via @fontsource), three, three-mesh-bvh and three-gpu-pathtracer (MIT) and @tauri-apps/api and @tauri-apps/plugin-dialog (Apache-2.0 or MIT), all already in `frontend/package-lock.json` and `NOTICE.md`. See `CREDITS.md`.
