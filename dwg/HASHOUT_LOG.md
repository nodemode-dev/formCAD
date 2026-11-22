# HASHOUT_LOG · DWG tools (dwg/, setup/build_dwg)

Living record of decisions and removed context for the DWG tools bundle, newest first. Read before editing.

## DW1 v0.26.0 the DWG tools exist

Why a bundle. The owner chose, for DWG, to keep the route through a converter the user installs (the ODA File Converter) and to add GNU LibreDWG as a separate program fetched from `formai-binaries`, like the kernel and the mesher: never linked, never in the app bundle, checked by SHA-256, run as its own process. A clean-room reader and writer is a later sprint (`DEV_PLAN.md`). LibreDWG's source is never opened here: the build only configures and compiles the release archive, and the DWG samples used for the corpus check were checked out alone (a sparse checkout of `test/test-data/*.dwg`).

Licence check, done before anything was added. LibreDWG is GPL-3.0-or-later (GNU LibreDWG page; `COPYING` in the archive). Shipping it as a separate program from its own release, with the GPL text, a written offer and the source archive on the same release page, meets GPL-3.0 section 6 for object code; FormCAD stays Apache-2.0 because it only runs the programs and exchanges files. AGPL nowhere: the build turns off bindings and Python, so the programs carry only LibreDWG itself and the system C library (the build refuses a program that needs anything else). On Windows MinGW-w64 links statically; its runtime libraries carry the GCC Runtime Library Exception.

Pin. `libredwg-0.14.tar.xz`, the newest release on ftp.gnu.org on 2026-11-22 (0.13.4 and 0.14 are both dated 2026-08-31), SHA-256 `62ebb73b984f865960f20ed26619ea5f8789d5e3fd088fa40a2598384da81275`, GNU signature by RSA key `38A4167B0DB69E49C5F7216CB8C28866AB27A7A2`, verified here with the GNU keyring. The 0.14.NNNN tags in the GitHub mirror are nightly builds and were not used.

Configure. `--disable-shared --enable-static` so each program is one file; `--disable-bindings --disable-python --disable-docs` to keep Perl, Python, SWIG and TeX out; `--disable-werror --disable-Werror --enable-release` so a newer compiler's warnings do not stop the build. Built on Linux x86_64 here with gcc in about 6 minutes on 2 cores: `dwg2dxf` 14.9 MB and `dxf2dwg` 11.2 MB after strip, needing only libc and libm.

Smoke test. The first choice, `fixtures/dxf/survival-r2000.dxf`, crashes `dxf2dwg` (it reports `Invalid DXF code 16 for DIMENSION_ANG3PT`, then a double free). Group 16 on a three-point angular dimension is in Autodesk's DXF reference, so the fault is LibreDWG's DXF reader. The test uses `fixtures/sheetmetal/channel-cutting.dxf`, which converts, and reads the DWG back.

What LibreDWG can and cannot do for FormCAD, measured on 52 DWG samples (`BUILD_NOTES.md`, milestone 7): every file opened; saving through `dxf2dwg` worked for the 44 small drawings and failed for the 8 full example drawings (`Invalid DXF code 50 for MTEXT`; with that worked around, errors on block attributes and a crash). `dxf2dwg` reads its own DXF output well and other programs' DXF poorly, so FormCAD's save through it is honest only as "the 2000 format, for drawings LibreDWG can convert". Do not pass `--as r2018` to `dwg2dxf`: on R13, R14 and R2000 files it writes a DXF with no entities.
