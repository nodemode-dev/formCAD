# Building and releasing

## The dispatcher

`./formCAD` is a shell script that routes to the scripts in `setup/`: `boot`, `install`, `install-kernel`, `install-mesher`, `backend`, `frontend`, `build`, `serve`, `freeze`, `freeze-kernel`, `freeze-mesher`, `desktop dev|build`, `doctor`, `mcp`, `clean`, `version`. Windows has a `.bat` beside each script.

## The three freezes

| Freeze | Script | Output | Shipped how |
| --- | --- | --- | --- |
| Engine | `setup/freeze_backend` | `src-tauri/engine` (PyInstaller onedir) | inside the app bundle |
| Kernel | `setup/freeze_kernel` | `kernel/dist` | never inside the app; downloaded from the formai-binaries releases and verified against `backend/app/data/kernel-licence.json` |
| Mesher | `setup/freeze_mesher` | `mesher/dist` | the same pattern, verified against `mesher-licence.json` |

A new dependency that must be bundled is added to the requirements file and to the freeze script in the same change, with a row in `NOTICE.md` first.

## The release folder

`release/` holds what the owner needs to publish: `formCAD-binaries/` (a mirror of the `formcad/` folder of `nodemode-dev/formai-binaries`: notices, licences, source offer, records and tools), `dry_run`, `sbom/` (a CycloneDX generator) and `sign/` (signing scripts that read secrets from the environment only). `docs/RELEASE.md` is the step list.

## Releasing the app

1. Bump the version at every version site by hand, and `CHANGELOG.md`. They must agree.
2. Land it on main through a pull request, merged with a merge commit, with CI green.
3. The owner starts the release with `formai-build`, which creates the `compile_vX.Y.Z` branch at `main`; the family's compiler builds the draft release. Nobody pushes that branch by hand.
4. Attach the SBOM files. A person publishes.

## Releasing the kernel and mesher

Run `release/dry_run`, then the `binaries` workflow by hand with the release number. Copy the resulting record over the licence data file in FormCAD. Settle every entry in the record's `needs_review` list before publishing. Keep the source asset on the release for at least three years after the last distribution.

Nothing is pushed or published by the repository's files; the owner does that.
