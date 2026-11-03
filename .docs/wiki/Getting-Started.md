# Getting started

## Requirements

Node 20.19 or newer (or 22.12), Python 3.12 or newer. Desktop builds also need Rust. `./formCAD doctor` checks them and the ports.

## Install and boot (macOS and Linux)

```shell
chmod +x formCAD_oc_install formCAD build_app
./formCAD_oc_install
./formCAD install-kernel
./formCAD install-mesher
./formCAD
```

- `install-kernel` is optional and gives you 3D solids, STEP, IGES and 3DM.
- `install-mesher` is optional and gives you simulation meshing.
- `./formCAD` boots the engine (127.0.0.1:8290) and the interface (127.0.0.1:5290) together.
- `./formCAD desktop dev` runs the desktop shell.

On Windows use `formCAD_oc_install.bat` and `formCAD.bat`.

## Your first drawing

1. Start a new drawing (`new`).
2. Type `line`, click two points, press Enter.
3. Type `circle`, then `dimdiameter` to dimension it.
4. `save` writes a `.fcad` file.

## Your first part

1. `partworkspace`, then `partsketch` on a plane.
2. Draw a rectangle, `partsketchdone`.
3. `featextrude`. The feature tree shows it; `featrollback` walks back through history.

## Where your data lives

The engine keeps settings, sessions, autosaves and the downloaded kernel under the platform's app data folder, or the folder named by `FORMCAD_DATA_DIR`. `FORMCAD_PORTABLE=1` keeps everything beside the app. The full variable list is in the README.

## Next

Read [[Workspaces]] for what is available, and `docs/MANUAL.md` for commands and limits.
