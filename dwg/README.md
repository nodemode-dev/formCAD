# DWG tools

Two programs of GNU LibreDWG 0.14, `dwg2dxf` and `dxf2dwg`, built unmodified and shipped as their own archive from the `formai-binaries` releases. They are GPL-3.0-or-later, so FormCAD never links or imports them and never puts them in its app bundle or installers. The engine downloads them when the user asks (Preferences, DWG tools), checks every file against `backend/app/data/dwg-licence.json`, and runs them as separate processes through a temporary folder (`backend/app/interchange/dwg.py`).

What they give FormCAD: DWG files of every version open (some advanced R2010+ and pre-R13 objects are skipped by LibreDWG and listed in the import notes), and DWG saves in the 2000 format (R2000) only. A converter the user installed and turned on (the ODA File Converter) still takes precedence and writes any version.

## Archive

`dwg-gpl-<release>-<triple>.tar.gz`, one folder of the same name:

| File | What |
| --- | --- |
| `dwg2dxf`, `dxf2dwg` (`.exe` on Windows) | the two programs, linked statically with the LibreDWG library |
| `COPYING.txt` | the GNU GPL version 3 text from the source archive |
| `GPL-OFFER.txt` | the written source offer, filled in with the release and the source SHA-256 |
| `NOTICE.md` | `dwg/NOTICE.md` |

Triples: `aarch64-apple-darwin`, `x86_64-apple-darwin`, `x86_64-unknown-linux-gnu`, `x86_64-pc-windows-msvc` (the name the app uses for Windows; the build itself is MinGW-w64).

## Build

`setup/build_dwg` on the target system (on Windows, in an MSYS2 MINGW64 shell with `base-devel` and `mingw-w64-x86_64-toolchain`; on macOS with Xcode's command line tools; on Linux with gcc, make and xz). It downloads `libredwg-0.14.tar.xz` from ftp.gnu.org, checks the pinned SHA-256, checks the GNU signature when gpg is present, configures with shared libraries, bindings, Python and docs off, builds, collects the two programs, refuses a program that needs a library outside the system, converts `fixtures/sheetmetal/channel-cutting.dxf` to DWG and back as a smoke test, and writes to `dwg/dist`:

- `dwg-gpl-0.14-<triple>.tar.gz`, the archive;
- `dwg-gpl-0.14-<triple>.files.json`, the `files` rows for the record;
- `dwg-gpl-0.14-<triple>.SHA256SUMS`, the archive's and the source's SHA-256;
- `libredwg-0.14.tar.xz` and its `.sig`, the corresponding source.

## Publish

1. Run `setup/build_dwg` on each of the four systems.
2. Make one release `dwg-0.14` in `nodemode-dev/formai-binaries` with the four archives, the source archive and its signature.
3. Put the rows of the four `.files.json` files into `files` in `backend/app/data/dwg-licence.json`, in one commit of this repository.

Until step 3, the record has no files, the app shows no DWG tools row, and DWG keeps working through a converter the user installs (the earlier route), with no error. `FORMCAD_DWG_RECORD` points the engine at another record file, to try a release before the record is committed.
