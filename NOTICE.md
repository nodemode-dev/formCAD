# Notices

formCAD
Copyright 2026 NodeAgentc, Inc.
https://github.com/nodemode-dev/formCAD

This product is licensed under the Apache License 2.0 (see `LICENSE`).

## Third-party works

Every dependency, binary, font or asset gets a row here before it lands, with its license and where it lives.

### Adapted from formvis (NodeMode form family)

| Work | License | Where |
| --- | --- | --- |
| NodeMode stylized design system: tokens, theme profiles, theme boot, dom-stable helpers, shell icon subset | MIT | `frontend/src/styles/tokens.css`, `frontend/src/ui/themes.ts`, `frontend/index.html`, `frontend/src/ui/dom.ts`, `frontend/src/ui/icons.ts` |
| formvis shell modules: i18n machinery, command registry, toast, dropdown, number fields, row builders, dialog shell, preferences store, tool registry, shell and dialog styles, splash and reveal, title bar placement, text editing bridge, window state, script suite, engine core layout | Apache-2.0 | `frontend/src/ui/`, `frontend/src/extensions/registry.ts`, `frontend/src/styles/`, `src-tauri/src/`, `setup/`, `backend/app/core/`, `backend/app/services/secrets.py`, `backend/formcad_engine.py` |

### Interface (frontend)

| Work | License | Where |
| --- | --- | --- |
| @fontsource/inter 5.3.0, @fontsource/jetbrains-mono 5.3.0 | OFL-1.1 (fonts), MIT (package) | `frontend/package.json`, `frontend/src/styles/fonts.css` |
| @tauri-apps/api 2.11.1, @tauri-apps/cli 2.11.4 | Apache-2.0 OR MIT | `frontend/package.json` |
| three 0.186.1 | MIT | `frontend/package.json` |
| typescript 7.0.2, vite 8.3.5, @types/three 0.186.0 | Apache-2.0, MIT, MIT | build tools, not shipped |

### Engine (backend)

| Work | License | Where |
| --- | --- | --- |
| fastapi 0.141.1, keyring 25.7.0, ezdxf 1.4.5 | MIT | `backend/requirements.txt` |
| uvicorn 0.53.0, httpx 0.28.1, numpy 2.5.4 | BSD-3-Clause | `backend/requirements.txt` |
| fonttools 4.68.0 | MIT | `backend/requirements.txt`, `backend/requirements_macos.txt` |
| uharfbuzz 0.57.0 (HarfBuzz 15.0.0 inside) | Apache-2.0 (uharfbuzz), MIT (HarfBuzz) | `backend/requirements.txt`, `backend/requirements_macos.txt`, used by `backend/app/text/shaping.py` |
| formcad-stroke single-stroke drafting font, drawn for FormCAD | Apache-2.0 (original work, no third-party glyph data) | `backend/app/data/fonts/formcad-stroke.json` |
| PyInstaller 6.22.3 | GPL-2.0-or-later with bootloader exception | build tool only; the bootloader exception covers the frozen engine |

### Desktop shell

| Work | License | Where |
| --- | --- | --- |
| tauri 2, tauri-plugin-shell, tauri-plugin-dialog, tauri-plugin-single-instance, regex, serde, serde_json | MIT OR Apache-2.0 | `src-tauri/Cargo.toml`, exact versions in `src-tauri/Cargo.lock` |
| objc2, objc2-app-kit, objc2-foundation (macOS) | MIT OR Apache-2.0 OR Zlib | `src-tauri/Cargo.toml` |

### DWG converters (optional, installed by the user, never shipped)

FormCAD bundles no DWG library or converter. DWG open and save are off until the user points FormCAD at a converter program they installed themselves (for example the ODA File Converter, under ODA's own terms, or LibreDWG's `dwg2dxf` and `dxf2dwg`, GPL-3.0-or-later). The engine runs that program as a separate process with an argument list and a timeout, and exchanges files through a temporary folder; nothing from either program is linked, imported or distributed. Code: `backend/app/interchange/dwg.py`.

### Kernel worker (separate program, never bundled in the app)

The `formcad-kernel` worker in `kernel/` is distributed only from the `formCAD-binaries` releases, with its own notices and sources. It carries OpenCascade Technology 8.0.1 (LGPL-2.1 with the Open CASCADE exception 1.0) through cadquery-ocp-novtk 8.0.1.1.0 (Apache-2.0), and build123d 0.13.0 (Apache-2.0) with cadquery-ocp-proxy (Apache-2.0), ocp_gordon (Apache-2.0) and ocpsvg 0.7.x (Apache-2.0). FormCAD runs it as a separate program and does not link to it.

| Work | License | Where |
| --- | --- | --- |
| Kernel worker third-party notices (OpenCascade 8.0.1, cadquery-ocp-novtk, build123d, ocpsvg, bd_materials, anytree, threejs-materials with a texture-licence flag) | LGPL-2.1 with the OCCT exception, Apache-2.0, MIT, BSD | `kernel/NOTICE.md` |

## Independent implementation

formCAD is an independent implementation. Where it offers behaviour comparable to other CAD software, that behaviour was written from functional descriptions only; no source code, text or artwork from those products is included. Product names are trademarks of their owners and are used only to describe compatibility.
