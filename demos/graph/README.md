# formCAD demo: node graph (Demo 3 of 3)

An offline demo of formCAD's node graph, the visual programming editor, running in a browser with no engine, no Tauri shell, no network and no install.

## Open it

- Double-click `demos/graph/index.html` (it works from `file://`), or
- serve the folder with any static server, for example `python3 -m http.server --directory demos/graph 8000`.

Every script, style, font and the recording are local to this folder: `index.html`, `favicon.png`, `demos/` (the home screen pictures) and `assets/` (one classic deferred script `assets/formcad-demo.js`, one stylesheet `assets/formcad-demo.css`, the Inter and JetBrains Mono font files).

## What it shows

The page is the real formCAD window, bundled by Vite from `frontend/` as it is, over a replay of a recording made against the real engine. It opens on the demo document `graph` with the graph editor open on graph G1, "Plate with bolt holes": a box plate and a cylinder hole, a polar ring of holes, a difference that cuts them, a tag, the mass properties and a mid section with its length. Every node shows its solved state from the recording, and the 3D preview layer carries the solved preview mesh.

## Things to try

- Pan the graph (drag empty space with the middle button, or hold Space and drag) and zoom with the wheel, the zoom buttons or `+` and `-`; Zoom to fit brings it all back.
- Click a node to select it, drag a box to select several, and drag nodes around: moving nodes is layout, kept in the page.
- Hover a port for its tooltip: the data it carries, from the recorded solve.
- Double-click empty space to open the node search and type, for example, `cyl` or `mass`.
- Turn snap to grid on and off.
- Switch themes from the menu bar, open the command palette with Ctrl+Shift+P, and leave and re-open the editor with the Drawing button and the Graph Editor command.

## What is not in the demo

The page cannot compute. Solving, recomputing, adding or removing nodes, changing wires, editing values, baking, running, optimising, importing and exporting go to the engine in the desktop app; here they answer with the notice "This is a browser demo. The desktop app does this." and the graph returns to its recorded state. The drawing behind the editor is a replay too, so its commands answer the same way.

## Re-record and rebuild

The built files in this folder are committed. From the repository root, with the engine's `backend/venv` and the dev kernel in `kernel/venv` installed:

```sh
demo/tools/record --doc backend/app/data/demos/graph.fcad --out demos/graph/recordings/graph.json --steps clear,dock,palette --script demos/graph/tools/steps.mjs --idle 800
cd demos/graph && ../../frontend/node_modules/.bin/vite build --config vite.config.mjs
```

`tools/steps.mjs` opens the graph editor through the command palette, waits for the solve, clicks every node, opens the node search, zooms and fits. Set `FORMCAD_GRAPH_SHOT=/some/file.png` to have it also save a screenshot with the editor open.

`../../frontend/node_modules/.bin/tsc --noEmit -p .` in `demos/graph/` type-checks the entry. `vite preview --config vite.config.mjs` serves the built folder on http://localhost:5493; the dev server port is 5393, both bound to localhost only.

The home screen picture `frontend/public/demos/graph.webp` is a 1440 by 900 capture of this demo in the dark theme with the editor zoomed out one step, cropped to x 136 to 1048 and y 163 to 733 and scaled to 640 by 400.

## Licences

The bundle contains formCAD's own code (Apache-2.0), Inter and JetBrains Mono (OFL 1.1, via @fontsource), three, three-mesh-bvh and three-gpu-pathtracer (MIT) and @tauri-apps/api and @tauri-apps/plugin-dialog (Apache-2.0 or MIT), all already in `frontend/package-lock.json` and `NOTICE.md`. See `CREDITS.md`.
