# formCAD demo: 2D drafting

An offline demo of formCAD that runs in a browser with no engine, no Tauri shell, no network and no install.

## Open it

- Double-click `demo/index.html` (it works from `file://`), or
- serve the folder with any static server, for example `python3 -m http.server --directory demo 8000`.

Every script, style, font and the recording are local to this folder: `index.html`, `favicon.png` and `assets/` (one classic deferred script `assets/formcad-demo.js`, one stylesheet `assets/formcad-demo.css`, the Inter and JetBrains Mono font files).

## What it shows

The page is the real formCAD window, not a look-alike. `frontend/index.html` and the application's own entry (`frontend/src/main.ts`, then `app.ts` and every module it registers) are bundled as they are: menu bar, document tabs, tool rail, canvas, dock panels, command line and status bar, with the app's own stylesheets, tokens, icons and themes.

The window opens straight on the demo document `drafting` in model space, fitted to its extents, not on the home screen. The document was opened by the real engine when the recording was made, so every entity, layer, linetype, hatch, dimension and text on the canvas is the engine's own display list.

Works in the page, because the interface does it on its own:

- pan and zoom (wheel, middle drag, the view cube and its home button), zoom extents
- picking and window selection with the selection highlight and grips; the properties of the objects the recorder picked
- dock panels, the layer list, menus, the command palette, Preferences, themes and accent colours, the language picker
- switching to the home screen and back to the drawing (the side nav's Back to drawing or the open drawings list)

Answers "This is a browser demo. The desktop app does this." as the app's usual error toast:

- every command and every edit (typing in the command line, drawing tools, grips that move geometry, property edits, undo and redo)
- opening, saving, exporting, plotting and closing documents, new documents and templates, and the home's Demos cards (the engine answers those with a fresh untitled copy under a new id, which a recording cannot hold)
- anything the engine was not asked for while recording (for example the properties of an object the recorder did not pick)

## What stands in for the engine

`src/shim/replay.ts` patches `fetch` and `WebSocket` for `/api` before the app boots. Each request is matched against the recording by method, path, query (parameters sorted, `token` dropped) and JSON body (keys sorted). Repeated requests are answered in recorded order and the last answer repeats. GETs answer from the recording; POST and PUT answer from it only for the idempotent reads the interface makes while viewing (`/preview`, `/find`, `/qselect`, `/api/calc`, `/dimstyle-preview`, `/grid`). Selection is view state: `PUT /api/docs/{id}/selection` is kept in the page and answered like the engine would, so the highlight and the selection count work. Everything else answers status 503 with `{"detail": "This is a browser demo. The desktop app does this."}`, the engine's normal error shape, so the interface shows its usual toast and nothing throws. The events socket opens at once and plays the frames recorded during boot.

## The shim for other demos

`demos/part` and `demos/graph` reuse the same shim and recorder.

```ts
import recording from '../recordings/part.json';
import { installReplay, type Recording } from '../../../demo/src/shim/replay';

installReplay(recording as unknown as Recording, {
  message: 'This is a browser demo. The desktop app does this.',
  status: 503,
  reads: [/\/part\/preview$/],
  local: (req) => undefined,
  frames: 'boot',
});
```

- `installReplay(recording, options?)` must run before the app's modules evaluate: put it in its own module and import that module first in the entry, then `frontend/src/main` (see `src/boot.ts` and `src/main.ts`).
- `options.message` and `options.status`: the error answer for writes and misses.
- `options.reads`: extra path patterns whose POST, PUT or PATCH requests may be answered from the recording when the body matches.
- `options.local(req)`: return a value (sent as JSON with status 200) or a `Response` to answer a request in the page; return `undefined` to fall through. `req` is `{ method, path, query, body }`.
- `options.frames`: `'boot'` (default), `'all'` or `'none'` recorded socket frames to play after the socket opens.
- The return value has `misses` (every request that got the error answer) and `restore()`.

The recording is one JSON file: `{ format: 'formcad-replay', version: 1, recorded, engine, document: { file, id, name }, window, steps, exchanges, responses, frames }`. Each exchange is `{ seq, t, phase, method, path, query, body, status, type, response, encoding }`, where `response` indexes the shared `responses` list (identical bodies are stored once) and `encoding` is `text` or `base64`. Each frame is `{ t, phase, data }`; `phase` is `boot` until the window is quiet, then `views`.

## Rebuild and re-record

The built files in this folder are committed. To re-record against the current engine and interface, then rebuild:

```sh
demo/tools/record --doc backend/app/data/demos/drafting.fcad --out demo/recordings/drafting.json
cd demo && ../frontend/node_modules/.bin/vite build --config vite.config.mjs
```

`demo/tools/record` (Node 22, standard library only, plus the `vite` already in `frontend/node_modules`) starts the real engine from `backend/venv` on a free port with a private data folder, opens the document, serves `frontend/` through its own `vite.config.ts` on another free port, drives the interface in `google-chrome --headless=new` over the DevTools protocol, and writes every `/api` request and response plus the event socket frames. It removes its temporary folder and stops only the processes it started. Options: `--steps pick,clear,dock,palette,layers` (the view steps after boot), `--picks 8` (objects of distinct kinds clicked in the pick step, followed by a window selection over the whole canvas), `--script <file.mjs>` (a module whose default export runs more steps with `{ cdp, click, key, rects, idle, sleep, log }`; the part and graph demos use it), `--size 1440x900`, `--screenshot <png>`, `--chrome <bin>`, `--python <bin>`, `--idle 1500` (quiet milliseconds that end a step). Run `demo/tools/record --help` for the list.

The build bundles `frontend/index.html` with the entry `demo/src/main.ts`, emits one classic deferred script so the page opens from `file://`, copies `frontend/public/favicon.png` and, when present, the home screen pictures from `frontend/public/demos/`, and escapes the symbol code points U+2600 to U+27BF and U+1F000 to U+1FAFF in the script. `vite preview --config vite.config.mjs` serves the built folder on http://localhost:5491; the dev server port is 5391, both bound to localhost only. `../frontend/node_modules/.bin/tsc --noEmit -p .` in `demo/` type-checks the shim and the entry.

## Licences

The bundle contains formCAD's own code (Apache-2.0), Inter and JetBrains Mono (OFL 1.1, via @fontsource), three, three-mesh-bvh and three-gpu-pathtracer (MIT) and @tauri-apps/api and @tauri-apps/plugin-dialog (Apache-2.0 or MIT), all already in `frontend/package-lock.json` and `NOTICE.md`. See `CREDITS.md`.
