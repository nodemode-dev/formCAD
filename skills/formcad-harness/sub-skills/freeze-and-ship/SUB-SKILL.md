---
name: freeze-and-ship
description: Freezes the FormCAD engine, kernel and mesher, builds the desktop app, and handles the release folder. Use for PyInstaller freezes, ./build_app, desktop builds, SBOM or signing scripts, and anything that touches release artifacts.
---

# Freeze and ship

## Commands

| Command | Output | Note |
| --- | --- | --- |
| `./formCAD build` | `frontend/dist` | Runs `tsc --noEmit` then `vite build`. |
| `./formCAD freeze` | `src-tauri/engine` (PyInstaller onedir `formcad-engine`) | Needs `./formCAD install-desktop` first. Bundles `backend/app/data` and `frontend/dist`; hidden imports are listed in `setup/freeze_backend`. |
| `./formCAD freeze-kernel` | `kernel/dist/formcad-kernel` | Answers a `hello` check itself. Never bundled into the app. |
| `./formCAD freeze-mesher` | `mesher/dist` | Same rule as the kernel. |
| `./formCAD desktop dev` and `./formCAD desktop build` | the Tauri shell | `./build_app` runs the whole desktop build, logging to `build_app.log`; flags `--no-install`, `--install`, `--open`, `--clean`, `--config FILE`. |
| `./formCAD clean` and `./formCAD clean --all` | removes build output; `--all` also venvs and `node_modules` | Ask before `--all`. |

Windows twins exist for every script as `.bat` files. Environment for builds (`FORMCAD_TARGET`, `FORMCAD_BUNDLES`, and the others) is listed in `references/ports-and-env.md`.

## After a freeze

Run the frozen engine's selfcheck: `src-tauri/engine/formcad-engine --selfcheck`. A library reading `missing:` means a hidden import or `--collect-all` entry is absent from the freeze script. When you add an engine dependency, the same change needs its `NOTICE.md` row, its `backend/requirements*.txt` line and its freeze entry. CI repeats the freeze on three operating systems and scans licences; Linux is tested here, macOS and Windows are configured but unproven, and any claim about them is reported as untested.

## The release folder

The family release is prepared in the tree and never published from it: `release/formCAD-binaries/` (the binaries repository layout: records, templates, tools, the LGPL offer, `SOURCES.md`), `release/sbom/`, `release/sign/` (signing scripts that read secrets from the environment only), `release/dry_run`, `apps/formCAD.json` for formcompiler, `apps/products-row.json` and `apps/form-app.json` for formportal. Rules:

- No remote is set. Do not add one and do not push. The owner pushes.
- Secrets come from the environment; never write one into a file or a log.
- Kernel and mesher archives are built from the records and tools in `release/formCAD-binaries/tools`; edit records through those tools, not by hand.
- Preflight before any release claim: diff the licence records, check SHA256SUMS and the SBOMs.

Read `docs/RELEASE.md` before changing these files; the field-by-field family contracts live outside the tree.
