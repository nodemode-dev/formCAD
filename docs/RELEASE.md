# Releasing FormCAD

Everything here is prepared in the repository. Nothing is pushed or published by these files; the owner pushes, and a person publishes each draft release.

## The pieces

| Piece | Where | Who runs it |
| --- | --- | --- |
| Application release (dmg, app tar, msi, setup exe, AppImage, deb, rpm, `SHA256SUMS.txt`) | formcompiler, from `apps/formCAD.json` | formcompiler, after `ci.yml` is green on a `compile_vX.Y.Z` branch |
| Kernel and mesher archives | `.github/workflows/binaries.yml`, published to `nodemode-dev/formai-binaries` | a maintainer, by hand (`workflow_dispatch`) |
| SBOMs | `.github/workflows/sbom.yml` or `release/sbom/formcad_sbom.py` | a maintainer, attached to the application release |
| Registry entries | `apps/formCAD.json` (formcompiler), `apps/products-row.json` and `apps/form-app.json` (formportal) | copied by hand into those repositories |
| Signing scripts | `release/sign/` | the workflows, with secrets from the environment only |

## Application release

1. Bump `version` in `src-tauri/tauri.conf.json`, `apps/form-app.json` (`version`) and `CHANGELOG.md`. The three must agree.
2. Land it on main; `ci.yml` must pass.
3. Push `compile_vX.Y.Z`. formcompiler gates it and runs the contract on each runner: `./formCAD install --lite`, `./formCAD install-desktop`, `./formCAD desktop build --config <file>` (`formCAD.bat` under cmd on Windows). It then leaves a draft release tagged `vX.Y.Z` on this repository. formCAD never holds a signing secret for the application; formcompiler does.
4. While the repository is private, keep the release a draft and use a plain version. A `-beta.N` version is always published, and a published release is copied to the public download store. A private tester gets the installer file from the draft.
5. Attach the SBOM files and `docs/DATA_PROVENANCE.md` to the release. Publish when the repository is public.

## Kernel and mesher

1. Run `release/dry_run` first (below).
2. Run the `binaries` workflow with the kind and release number (`8.0.1`, `8.0.1-2`, `6.2.2608`). Four native runners build and sign, the assemble job merges the records, pins the upstream sources, writes `SHA256SUMS`, `RELEASE_NOTES.md` and the source asset, and with `publish` checked creates a draft release `occt-<release>` or `mesher-<release>`. An existing tag stops the run; a published tag is never replaced.
3. Copy `dist/app-<record>.json` over `backend/app/data/kernel-licence.json` (or `mesher-licence.json`) in FormCAD, and the merged record over `release/formCAD-binaries/records/` (and over `formcad/records/` in formai-binaries). `tools/preflight.py --app-data backend/app/data --published` must pass in both repositories.
4. Read the `needs_review` list in the record's `licence_gates` and settle every entry before publishing (see Open decisions).
5. Keep the source asset on the release for at least three years after the last distribution.

### Secrets (names only, read from the environment)

| Platform | Variables |
| --- | --- |
| macOS | `APPLE_SIGNING_IDENTITY`, `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_API_KEY`, `APPLE_API_ISSUER`, `APPLE_API_KEY_B64` (the .p8, written to `APPLE_API_KEY_PATH` by the workflow), or `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID` |
| Windows | Azure Artifact Signing: `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `ARTIFACT_SIGNING_ENDPOINT`, `ARTIFACT_SIGNING_ACCOUNT`, `ARTIFACT_SIGNING_PROFILE`; or `WINDOWS_CERTIFICATE`, `WINDOWS_CERTIFICATE_PASSWORD` |
| Linux AppImage | `APPIMAGE_GPG_PRIVATE_KEY`, `APPIMAGE_GPG_KEY_ID`, `APPIMAGETOOL_SIGN_PASSPHRASE` |
| Publishing | `BINARIES_REPO_TOKEN` (create releases in formai-binaries) |

Without the Apple identity the macOS files are signed ad hoc. Signing happens before hashing, so the recorded hashes are of the signed bytes.

### Scripts

- `release/sign/macos_sign.sh sign DIR` signs every Mach-O innermost first with the hardened runtime and a timestamp, then verifies each. `notarize-folder DIR` zips with `ditto` and submits; `notarize FILE` and `staple FILE` handle a dmg.
- `release/sign/windows_sign.ps1 -Path DIR` signs `.exe .dll .pyd .msi .sys` with Azure Artifact Signing or a pfx, and stops when no credentials are present.
- `release/sign/linux_appimage_sign.sh sign FILE` writes a detached `.asc` and, when `appimagetool` exists, an embedded signature. Publish the key id and fingerprint in the release notes; `SHA256SUMS` stays the primary check.

## Dry run

```
release/dry_run [--kind kernel|mesher] [--out DIR] [--release R] [--repro] [--freeze]
```

It copies the existing `kernel/dist/formcad-kernel` (or `mesher/dist`), writes the notices, takes a lock from the program's venv, records every file, packs a reproducible archive, re-extracts it and checks every file against the record, writes `SHA256SUMS`, the app-shaped record and the SBOM. It writes outside the repository, signs nothing and fetches nothing. `--freeze` runs the freeze script when the frozen folder is missing.

## SBOMs

`release/sbom/formcad_sbom.py --out DIR` writes one CycloneDX 1.6 file per component (engine, frontend, shell, kernel, mesher) from `backend/requirements.txt`, `frontend/package-lock.json`, `src-tauri/Cargo.lock`, the kernel lock and `mesher/requirements_mesher.txt`. OpenCascade and Netgen are added as named components. Licences come from the installed package metadata when the venvs exist; Cargo.lock carries none, so shell components have no licence field until `cargo metadata` data is merged in. `sbom.yml` validates each file against the official CycloneDX 1.6 JSON schema.

## Registry files

- `apps/formCAD.json`: the formcompiler file, kept byte for byte equal to formcompiler's `apps/formCAD.json`. After a change, copy it there and run `python3 scripts/registry.py check` in formcompiler.
- `apps/products-row.json`: the row for formai_dev `catalog/products.json`, then formportal's copy (`FAM3` item 1).
- `apps/form-app.json`: format_version 2 manifest. It must sit at the root of the application bundle; the build copies it in when the bundle step is extended.

## Open decisions

- Whether the libraries flagged in `licence_gates.needs_review` (libfreeimage, libraw, libjasper in the OpenCascade wheel; libquadmath and GCC runtime pieces; Netgen's GUI and MPI libraries) stay in the archives. FreeImage is offered under GPL or its own licence; settle it before publishing.
- Counsel review of the written offer and of relinking for a frozen onedir (FAM4).
- Whether the wheel's OpenCascade is unmodified upstream 8.0.1 (the source URL pins tag `V8_0_1`; the tag name and the pins are unchecked until the first fetch).
- Signing custody for formai-binaries (its own secrets, or a reusable workflow in formcompiler).
- Windows and macOS archives have not been built on those systems; only the Linux archive was built and verified.
