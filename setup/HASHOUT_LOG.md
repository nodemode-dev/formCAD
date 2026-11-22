# HASHOUT_LOG · scripts (setup/, the launchers and the check workflow)

Living record of decisions and removed context for the install, build and check scripts, newest first. Read before editing.

## ST2 v0.24.0 language table check (i18n.py)

`python3 setup/i18n.py check` reads `frontend/src/ui/i18n/keys.ts` and every table under `frontend/src/ui/i18n/tables/`, prints how many rows each language has, and lists problems: a part file missing, a line that is not a table row, a row outside its part or repeated, a full language missing rows, an empty row, placeholders such as `{n}` that differ from the English, an em dash. es-MX and fr-CA are override tables and may be short. It exits 1 on any problem. It changes no file and needs only the standard library. The part ranges (a 0 to 548, b 549 to 1060, c 1061 to 1572) live in `PARTS` and must match `LOADERS` in `frontend/src/ui/i18n.ts`.

## ST1 v0.20.1 pinned tools, a hashed engine lock, the Windows agents command and one Node minimum (lib.sh, install_backend, install_kernel, install_mesher, install_frontend, doctor, agents.bat, freeze_backend, their .bat twins, ../formCAD.bat, ../rust-toolchain.toml, ../.nvmrc, ../.github/workflows/ci.yml)

Engine lock. `backend/requirements.txt` pins the packages the engine names, not what they pull in, so the same commit could install different files on different days. `backend/requirements.lock` is made by `uv pip compile requirements.txt --universal --generate-hashes --python-version 3.12 -o requirements.lock` (uv 0.13.9), run in `backend/`; the command is the file's first lines. It is one file for every platform, with markers. `install_backend` and its twin install it with `--require-hashes`. To change a dependency: edit `requirements.txt`, run that command again, commit both. Read from PyPI for the 53 locked packages: every one that is not pure Python has a ready wheel for Python 3.12 on Intel Mac, Apple silicon and Windows, except glfw and mujoco on Intel Mac and uvloop on Windows, which their markers leave out there. formcompiler's Intel Mac build puts family-built wheels on `PIP_FIND_LINKS`; the only one that touched this engine was cryptography, which the lock installs on Linux alone, so the hash check does not meet a family-built wheel. Seen: the hash-checked install and `--selfcheck` on Linux. Not seen: macOS and Windows.

Removed: `backend/requirements_macos.txt`. No script read it and most of its lines had no version.

pip. `python -m pip install --upgrade pip` took whatever was newest. All six installers pin pip 26.3.

Rust. `rust-toolchain.toml` pins 1.97.0 with the two Apple targets, so a cross build on a Mac finds its standard library. `fc_rust_env` used to export `RUSTUP_TOOLCHAIN=stable`, and that variable wins over a toolchain file, so the pin would have been ignored by every build script. It now exports the variable only when `FORMCAD_RUST_TOOLCHAIN` is set, clears it when the toolchain file exists, and keeps the old stable default only for a checkout without the file. formcompiler installs stable before it calls `./formCAD desktop build`; with the file, rustup then fetches 1.97.0 on first use. That first formcompiler build after this change is the proof and has not happened yet. If it fails on the toolchain, setting `FORMCAD_RUST_TOOLCHAIN=stable` in the build restores the old behaviour without a code change.

Node. The README said 20.19 or 22.12, `package.json` said 20.19, the scripts said 22, and the pinned Vite needs 22.12 on the 22 line. Everything says 22.12 now. `fc_node_ok` compares major and minor; `install_frontend.bat` used to pass any Node on PATH and now runs the same comparison and prints the same sentence as the bash twin.

Windows agents command. `formCAD.bat agents ...` calls the new `setup\agents.bat`, which activates the engine venv and runs `setup\agents.py` with the arguments. `agents install` runs the real `claude mcp add`; never run it in an automated job without the stand-ins.

form-app.json. Both freeze scripts copy `apps/form-app.json` into `src-tauri/engine/` after the frozen folder, so it ships beside `formcad-engine` in the engine resource. On macOS the copy happens before the signing pass, which signs Mach-O files only.

Check workflow. New `shell` job: `cargo check --locked` in `src-tauri` on macos-latest and windows-latest, with stand-in `frontend/dist` and `src-tauri/engine` folders because Tauri's build script refuses to run without them. `engine-freeze` gained `macos-15-intel` and a `./formCAD agents check` step after the engine install. The handoff named `macos-13`; formcompiler's `scripts/plan.py` builds `macos-x64` on `macos-15-intel`, so the check uses the runner the release uses. pip-licenses is pinned to 5.5.5. None of the workflow changes has run: there is no pull request yet.
