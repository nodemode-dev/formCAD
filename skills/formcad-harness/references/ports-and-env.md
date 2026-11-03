# Ports, environment and data folder

## Contents

- Ports
- Environment variables
- Files the engine writes into its data folder
- Guarded routes

## Ports

| Service | Address | Notes |
| --- | --- | --- |
| Frontend | http://127.0.0.1:5290 | Vite dev server, `server.host` false, strict port. |
| Preview | http://127.0.0.1:5291 | `vite preview` of the built interface. |
| Engine | http://127.0.0.1:8290 | FastAPI, loopback only. The desktop app picks a free port (`FORMCAD_PORT` 0). |

When the sprint gives an agent its own ports (for example 84xx for the engine and 54xx for the frontend), pass them as `FORMCAD_PORT` for the engine and `FORMCAD_BACKEND_PORT` for the Vite proxy. Never kill a process you did not start; other agents boot from the same tree.

## Environment variables

| Variable | Read by | Meaning |
| --- | --- | --- |
| `FORMCAD_DATA_DIR` | engine config | Settings, sessions, autosaves, kernel and mesher downloads. Default: the platform app data folder. |
| `FORMCAD_PORTABLE` | engine config | `1` keeps all data beside the app. |
| `FORMCAD_LIBRARY_DIR` | engine config | A different folder for the drawing library (default: Projects inside the data folder). |
| `FORMCAD_PORT`, `FORMCAD_HOST` | boot scripts, engine | Engine port and bind address. Anything but loopback is unsupported. |
| `FORMCAD_BACKEND_PORT` | Vite config | Development only: the engine port Vite proxies to (default 8290). |
| `FORMCAD_DIST` | `setup/serve` | A built interface folder for the engine to serve instead of `frontend/dist`. |
| `FORMCAD_CONTROL_PORT` | engine runtime | Turns on the local control protocol on this loopback port. |
| `FORMCAD_CORS_ORIGINS` | engine guard | Extra interface origins accepted (development only). |
| `FORMCAD_KERNEL`, `FORMCAD_KERNEL_RELEASE` | kernel service | A worker path to use instead of the downloaded one; the formCAD-binaries release to download and verify. |
| `FORMCAD_MESHER`, `FORMCAD_MESHER_RELEASE` | mesher service | The same pair for the mesher. |
| `FORMCAD_FONTS` | text engine | Extra font folders. |
| `FORMCAD_LOG_LEVEL`, `FORMCAD_LOG_BYTES` | engine | Log level and log file size cap. |
| `FORMCAD_API_DOCS` | engine | `1` turns on the generated API pages. |
| `FORMCAD_HEADLESS` | CLI | Set by the CLI for every subcommand except `mcp`. |
| `FORMCAD_DESKTOP` | engine config | `1` when the Tauri shell started the engine. |
| `FORMCAD_URL`, `FORMCAD_TOKEN` | MCP bridge, macro SDK | Engine address and session token for a client that cannot read the data folder. |
| `FORMCAD_CHROMIUM` | render jobs | A Chromium-based browser for headless final frames. |
| `FORMCAD_TARGET`, `FORMCAD_RUST_TOOLCHAIN`, `FORMCAD_BUNDLES`, `FORMCAD_CARGO_TARGET`, `FORMCAD_PYI_ARCH` | `build_app`, freeze scripts | Build only: target triple, toolchain, bundle kinds, cargo target folder, PyInstaller architecture. |

Set them in the shell. A `backend/.env` file is read by `app/core/config.py` with `setdefault`, so a real environment variable wins; do not commit one.

## Files the engine writes into its data folder

| File | Purpose |
| --- | --- |
| `engine.port` | JSON with the engine pid and port; removed on a clean exit. The MCP bridge (`--connect auto`) reads it. |
| `session.token` | The per-start token, mode 0600. Sent as the header `x-formcad-token`. |
| `automation.json` | Automation settings, including the `agentFolders` list of folders an outside agent may read and write. |
| `kernel/` and `mesher/` | Downloaded worker releases, one folder per release. |
| `macros/`, `plugins/` | Python macros and sealed plugin folders. |

## Guarded routes

`GET /api/health` is the only open route. Every other `/api/` route and `/mcp` needs the token header and a loopback Host and Origin (`backend/app/core/guard.py`). A probe that gets 401 or 403 on another route is healthy and just lacks the token; read `session.token` from the data folder.
