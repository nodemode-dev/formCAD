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
| @tauri-apps/api 2.12.4, @tauri-apps/plugin-dialog 2.8.4, @tauri-apps/cli 2.11.4 | Apache-2.0 OR MIT | `frontend/package.json` |
| three 0.186.1 | MIT | `frontend/package.json` |
| three-gpu-pathtracer 0.0.27 | MIT (package `LICENSE`, Copyright 2021 Garrett Johnson; npm metadata agrees); the deprecated WebGL 2 class `WebGLPathTracer` is used, peer range three >= 0.185; progressive and tiled path tracing in the render mode, `frontend/src/render/`. It bundles a spatial denoise filter (`DenoiseMaterial`) adapted from glslSmartDeNoise by Michele Morrone, BSD-2-Clause: Copyright (c) 2018-2019 Michele Morrone, all rights reserved, redistribution and use in source and binary forms with or without modification permitted provided the copyright notice, the conditions and the disclaimer are kept | `frontend/package.json` |
| three-mesh-bvh 0.9.18 | MIT (package `LICENSE`, Copyright 2018 Garrett Johnson); peer of the path tracer, builds the bounding volume hierarchy | `frontend/package.json` |
| xatlas-web 0.1.0 | MIT (package `LICENSE`, Copyright 2018-2020 Jonathan Young); peer of the path tracer, a WebAssembly build of xatlas for UV unwrapping that FormCAD does not call | `frontend/package.json` |
| mediabunny 1.65.0 | MPL-2.0 (package `LICENSE` file, "Mozilla Public License Version 2.0"; file-level copyleft, its files are used unedited from `node_modules` and bundled by Vite, any change to a Mediabunny file would have to be published under MPL-2.0); WebM or MP4 muxing for storyboard video, `frontend/src/an1/video.ts` | `frontend/package.json` |
| @xterm/xterm 6.0.0, @xterm/addon-fit 0.11.0 | MIT (package `LICENSE`, Copyright (c) 2017-2019 The xterm.js authors and others); the terminal emulator of the agent dock, loaded only when a tab opens | `frontend/package.json`, used by `frontend/src/dock/terminal.ts` |
| typescript 7.0.2, vite 8.3.5, @types/three 0.186.0 | Apache-2.0, MIT, MIT | build tools, not shipped |

### Engine (backend)

| Work | License | Where |
| --- | --- | --- |
| fastapi 0.141.1, keyring 25.7.0, ezdxf 1.4.5 | MIT | `backend/requirements.txt` |
| uvicorn 0.53.0, httpx 0.28.1, numpy 2.5.4 | BSD-3-Clause; numpy's Linux wheel carries OpenBLAS (BSD-3-Clause), libgfortran (GPL-3.0 with the GCC Runtime Library Exception) and libquadmath (LGPL-2.1) as separate, unmodified shared libraries in `numpy.libs`, replaceable by the user | `backend/requirements.txt` |
| scipy 1.18.1 | BSD-3-Clause; its Linux wheel also carries OpenBLAS (BSD-3-Clause), libgfortran (GPL-3.0 with the GCC Runtime Library Exception) and libquadmath (LGPL-2.1) as separate, unmodified shared libraries in `scipy.libs`, the same three numpy carries | `backend/requirements.txt`, used by `backend/app/graph/optimize.py` |
| fonttools 4.68.0 | MIT | `backend/requirements.txt` |
| ptyprocess 0.7.0 | ISC (package `LICENSE`); pure Python, the pseudo-terminals behind the agent dock's tabs on macOS and Linux; freeze flag `--hidden-import ptyprocess` | `backend/requirements.txt` (macOS and Linux only), used by `backend/app/services/terminal.py` |
| pywinpty 3.0.5 | MIT (package `LICENSE`); the same on Windows through ConPTY, its wheel carries the winpty-rs binding compiled in; freeze flag `--hidden-import winpty --collect-binaries winpty` | `backend/requirements.txt` (Windows only), used by `backend/app/services/terminal.py` |
| agent finder `agent_lookup.py` 1.0.1 (NodeMode form family, shared unchanged between engines) | Apache-2.0 | `backend/app/services/agent_lookup.py` |
| uharfbuzz 0.57.0 (HarfBuzz 15.0.0 inside) | Apache-2.0 (uharfbuzz), MIT (HarfBuzz) | `backend/requirements.txt`, used by `backend/app/text/shaping.py` |
| manifold3d 3.5.4 | Apache-2.0 (wheel metadata and bundled `licenses/LICENSE`); the compiled module statically contains oneTBB (Apache-2.0), Clipper2 (Boost-1.0), quickhull and nanobind (BSD-3-Clause), none shipped as a separate library, the wheel has no `*.libs` folder | `backend/requirements.txt`, used by `backend/app/meshes/solidops.py` |
| fast-simplification 0.2.0 | MIT (wheel `License-Expression` and bundled `licenses/LICENSE`); its Linux wheel carries libgomp (GPL-3.0 with the GCC Runtime Library Exception) as a separate, unmodified shared library in `fast_simplification.libs`, replaceable by the user | `backend/requirements.txt`, used by `backend/app/meshes/reduce.py` |
| pyclipper 1.4.0 | MIT for the wrapper (wheel `License` metadata and bundled `licenses/LICENSE`, copyright Gregor Ratajc, Lukas Treyer, Maxime Chalton); the compiled module statically contains Clipper 6.4.2 by Angus Johnson, which the wheel's own description states is under the Boost Software License 1.0 (the wheel ships no separate copy of that text; Boost-1.0 asks for the notice only with source, and this row is the notice for binary use). Checked on the installed Linux wheel: no `*.libs` folder and no data files, the extension links only the system C and C++ runtime libraries (libstdc++, libm, libgcc_s, libpthread, libc), `import pyclipper` needs no other package; wheels exist for Linux, macOS and Windows, cp310 to cp314 | `backend/requirements.txt`, freeze flag `--hidden-import pyclipper`, used by `backend/app/cam/geom.py` |
| blake3 1.0.11 | CC0-1.0 OR Apache-2.0 (wheel `License` metadata and bundled `LICENSE`; used here under Apache-2.0 terms or CC0 at the user's choice); a PyO3 binding of the official Rust implementation, the Linux wheel has no `*.libs` folder, needs Python 3.11 or newer; the SQLite module of the standard library is public domain and is not a dependency | `backend/requirements.txt`, used by `backend/app/vault/base.py` and `backend/app/vault/cdc.py` |
| mujoco 3.17.0 | Apache-2.0 (wheel `License-Expression` and bundled `licenses/LICENSE`, repository `LICENSE` is the same text); `licenses/LICENSES_THIRD_PARTY.md` in the wheel lists what the compiled `libmujoco` statically contains: Abseil, cereal, Eigen (MPL-2.0, used unmodified inside the library), fmt, libccd, Qhull, TinyXML2, tinyobjloader, miniz, lodepng, GLAD, GLFW, Dear ImGui, Filament, SDL2 and others under permissive licences; the same file also lists Glslang's bison-generated parser (GPL 3 with the special bison exception, which permits its use in the compiled library) and the Open Sans and Font Awesome fonts used by the viewer, which FormCAD never runs; Eigen's LGPL-licensed files are excluded from the build (`EIGEN_MPL2_ONLY`, stated in that file). None ships as a separate library. Checked on the installed Linux wheel: no `*.libs` folder, `libmujoco.so` and the native modules link only the C library, the math library, pthread, dl and rt (`ldd`), and `import mujoco` runs headless with only numpy and typing_extensions (no glfw, pyopengl, absl-py, etils or websockets are imported). pip also installs those declared dependencies; the engine does not use them and the freeze scripts do not bundle them. Wheels: Linux x86_64 and aarch64, Windows amd64, macOS arm64 only; **there is no macOS Intel wheel**, so dynamics runs are unavailable on an Intel Mac (everything else works, the dynamics command says so) | `backend/requirements.txt` (not on an Intel Mac), freeze flags `--hidden-import mujoco --collect-binaries mujoco`, used by `backend/app/joints/dyn.py` |
| scikit-fem 12.0.2 | BSD-3-Clause (wheel classifier and bundled `licenses/LICENSE`, "Copyright 2018-26 scikit-fem developers"); a single pure-Python wheel, no compiled code and no `*.libs` folder, requires only numpy and scipy; freeze flag `--collect-all skfem` | `backend/requirements.txt`, used by `backend/app/sim/` |
| Simulation material values (aluminium 6061-T6 and 7075-T6, Ti-6Al-4V, 304 stainless, OFHC copper) | Numeric property values read from NASA Materials Data Handbooks (NTRS 19720022808, 19720022809, 19720022814; NASA content is generally not subject to copyright in the United States) and from NIST cryogenic fits evaluated at 293 K and NBS IR 80-1627; each value keeps its source in the file; the reuse terms of the NIST and NTRS pages were not verified and a legal review is advised before wider redistribution | `backend/app/data/sim-materials.json` |
| scipy.spatial in the kernel worker (BSD-3-Clause) | already present as a dependency of build123d; `kernel/kernel_proxy.py` takes convex hulls with it, so the kernel freeze scripts name `--hidden-import scipy.spatial` | `setup/freeze_kernel`, `setup/freeze_kernel.bat` |
| formcad-stroke single-stroke drafting font, drawn for FormCAD | Apache-2.0 (original work, no third-party glyph data) | `backend/app/data/fonts/formcad-stroke.json` |
| PyInstaller 6.22.3 | GPL-2.0-or-later with bootloader exception | build tool only; the bootloader exception covers the frozen engine |

### Desktop shell

| Work | License | Where |
| --- | --- | --- |
| tauri 2, tauri-plugin-shell, tauri-plugin-dialog, tauri-plugin-single-instance, regex, serde, serde_json | MIT OR Apache-2.0 | `src-tauri/Cargo.toml`, exact versions in `src-tauri/Cargo.lock` |
| objc2, objc2-app-kit, objc2-foundation (macOS) | MIT OR Apache-2.0 OR Zlib | `src-tauri/Cargo.toml` |
| FormCAD app icon (gear over its outline), supplied by the owner | Copyright 2026 NodeAgentc, Inc., part of this product | `assets/formcad_icon.png` (1024 px source), `src-tauri/icons/`, `frontend/public/favicon.png`, embedded in `frontend/public/splash.html` |

### Seed data

| Work | License | Where |
| --- | --- | --- |
| Material properties for 304 stainless steel and 6061 aluminium (NIST and NBS publications) and Ti-6Al-4V (a 1972 NASA handbook) | numerical facts from US government publications, cited per row | `backend/app/data/materials.json` (each row carries its source) |
| Metric coarse thread pitches from a public copy of IS 4218 Part 2 | numerical facts, cited per row with a status | `backend/app/data/hole-sizes.json` |
| Render environments: three Poly Haven HDRIs at 1k (studio_small_08 by Sergej Majboroda, kloofendal_48d_partly_cloudy and kloofendal_overcast by Greg Zaal), larger sizes downloaded on request from dl.polyhaven.org with the catalogue size and SHA-256 checked | CC0-1.0 (Poly Haven licence page, https://polyhaven.com/license: all HDRIs are CC0, no attribution required, redistribution allowed); the three shipped files match the SHA-256 and size in `environments.json` | `backend/app/data/render/env/`, catalogue and per-file provenance in `backend/app/data/render/environments.json` |
| Render appearances: metal base colours and dielectric IOR values (silver, aluminium, titanium, iron, platinum, gold, brass, copper; water 1.33, plastics and glass 1.5) read from the reflectance tables of Google Filament's PBR document, Apache-2.0, https://raw.githubusercontent.com/google/filament/main/docs/Filament.md.html, the tables there credit Real-Time Rendering 4th edition and measured data; roughness, plastic and paint colours and transmission values are tagged `authored` (hand set, no source claimed) | numerical facts with a source per field; Apache-2.0 for the document the values are read from | `backend/app/data/render/appearances.json` (each row carries `sources` and `provenance`) |

### DWG converters (optional, never in the app bundle)

FormCAD bundles no DWG library or converter. DWG open and save work through one of two separate programs, run as a separate process with an argument list and a timeout, exchanging files through a temporary folder; nothing from either is linked into FormCAD or imported by it. Code: `backend/app/interchange/dwg.py`.

- A converter the user installed and turned on (for example the ODA File Converter, under ODA's own terms, or LibreDWG's tools from another source).
- The DWG tools: GNU LibreDWG 0.14 (`dwg2dxf`, `dxf2dwg`), GPL-3.0-or-later, built unmodified by `setup/build_dwg` from `libredwg-0.14.tar.xz` (ftp.gnu.org, SHA-256 `62ebb73b984f865960f20ed26619ea5f8789d5e3fd088fa40a2598384da81275`, signed by RSA key `38A4167B0DB69E49C5F7216CB8C28866AB27A7A2`), published as their own archive in the `formai-binaries` releases together with the GPL text, a written source offer and the source archive, and downloaded only when the user asks. FormCAD checks every file of the archive against `backend/app/data/dwg-licence.json` before it installs it. Notices: `dwg/NOTICE.md`; written offer: `dwg/GPL-OFFER.txt`.

### SU2 flow solver (optional, installed by the user, never shipped)

FormCAD bundles no CFD program. The SU2 link is off until the user points FormCAD at an `SU2_CFD` executable they installed themselves (SU2 8.5.0 prints the GNU Lesser General Public License v2.1 header; the conda-forge package metadata says GPL-2.0-or-later, which conflicts, and does not matter here because SU2 is only run as a separate process; the licence of the installed copy is the one that copy carries, and the user who installs it accepts it, not FormCAD). The engine writes a mesh and a configuration file to a temporary folder, runs the program with an argument list, a timeout and bounded output, and reads its restart file; nothing is linked, imported or distributed. Code: `backend/app/flow/su2.py`. FormCAD's own Stokes solver uses scikit-fem (row above).

### Kernel worker (separate program, never bundled in the app)

The `formcad-kernel` worker in `kernel/` is distributed only from the `formai-binaries` releases, with its own notices and sources. It carries OpenCascade Technology 8.0.1 (LGPL-2.1 with the Open CASCADE exception 1.0) through cadquery-ocp-novtk 8.0.1.1.0 (Apache-2.0), and build123d 0.13.0 (Apache-2.0) with cadquery-ocp-proxy (Apache-2.0), ocp_gordon (Apache-2.0) and ocpsvg 0.7.x (Apache-2.0). FormCAD runs it as a separate program and does not link to it.

| Work | License | Where |
| --- | --- | --- |
| Kernel worker third-party notices (OpenCascade 8.0.1, cadquery-ocp-novtk, build123d, ocpsvg, bd_materials, anytree, threejs-materials with a texture-licence flag) | LGPL-2.1 with the OCCT exception, Apache-2.0, MIT, BSD | `kernel/NOTICE.md` |
| Mesher worker `formcad-mesher` in `mesher/`, a separate program distributed only from the `formai-binaries` releases and never in the kernel worker's process: netgen-mesher 6.2.2608 (LGPL-2.1-only, wheel `License-Expression` and `licenses/LICENSE`) and netgen-occt 7.8.1 (OpenCascade 7.8.1 libraries, LGPL-2.1, wheel ships `LICENSE_LGPL_21.txt`), numpy 2.5.4. The netgen wheel also bundles libGLU, libXmu, libXt, a GUI library and MPI wrappers whose licences the wheel does not state (flagged in `mesher/NOTICE.md`); none loads when a shape is meshed. No wheel exists for Linux ARM or Windows ARM | LGPL-2.1-only, LGPL-2.1, BSD-3-Clause | `mesher/NOTICE.md`, `mesher/requirements_mesher.txt`, `setup/freeze_mesher`, `setup/freeze_mesher.bat` |
| rhino3dm 8.35.0, used only inside the kernel worker to read and write 3DM files; it carries openNURBS, zlib, pybind11, nanobind and draco. The openNURBS licence text has no SPDX name, so written confirmation from its owner is still recommended before the first kernel release | MIT for rhino3dm; openNURBS under its own permissive text; zlib; BSD-3-Clause; Apache-2.0 | `kernel/NOTICE.md`, `kernel/kernel_3dm.py` |

## File formats written from published specifications

The electronics outputs implement four file formats from their publicly published specifications, without copying specification text or any code: the Gerber layer format, the Excellon drill format, the IDF 3.0 board exchange format and the `.kicad_pcb` board file format. The formats are named only as formats. Whether the owner of the Gerber format requires written permission for a conforming exporter is an owner item and is not settled (research file R26 records it); the terms are not restated here.

## Independent implementation

formCAD is an independent implementation. Where it offers behaviour comparable to other CAD software, that behaviour was written from functional descriptions only; no source code, text or artwork from those products is included. Product names are trademarks of their owners and are used only to describe compatibility.
