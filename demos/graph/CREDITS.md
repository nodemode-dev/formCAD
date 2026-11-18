# Credits

## The document

`graph` is formCAD's own demo document, `backend/app/data/demos/graph.fcad` ("Plate with bolt holes"), made for formCAD by its authors with the engine's own graph nodes. It ships under the repository licence, Apache-2.0. The recording in `recordings/graph.json` is the engine's and the dev kernel's answers for that document, made with `demo/tools/record` and `tools/steps.mjs`, and is under the same licence.

## Fonts

| Font | Files | Licence | Source |
| --- | --- | --- | --- |
| Inter | `assets/inter-*-{400,500,600}-normal.woff2` and `.woff` | SIL Open Font License 1.1 | @fontsource/inter 5.3.0 |
| JetBrains Mono | `assets/jetbrains-mono-*-{400,700}-normal.woff2` and `.woff` | SIL Open Font License 1.1 | @fontsource/jetbrains-mono 5.3.0 |

## Code in the bundle

| Package | Licence |
| --- | --- |
| formCAD interface (`frontend/src`) and the replay shim (`demo/src/shim`) | Apache-2.0 |
| three, three-mesh-bvh, three-gpu-pathtracer | MIT |
| @tauri-apps/api, @tauri-apps/plugin-dialog | Apache-2.0 or MIT |

All of them are already listed in `NOTICE.md` and pinned in `frontend/package-lock.json`. The demo adds no dependency.

## Pictures

`favicon.png` is formCAD's own app icon, copied from `frontend/public/favicon.png`; `demos/*.webp` are the home screen's Demos card pictures, copied from `frontend/public/demos/` and captured from formCAD itself.
