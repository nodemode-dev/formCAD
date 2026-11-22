# DWG tools notices

The DWG tools are two programs of GNU LibreDWG, `dwg2dxf` (reads a DWG and writes a DXF) and `dxf2dwg` (reads a DXF and writes a DWG). They are shipped only from the `formai-binaries` releases, never inside the FormCAD app or its installers. FormCAD downloads them when the user asks, checks every file against the SHA-256 in `backend/app/data/dwg-licence.json`, and runs them as a separate process with an argument list and a timeout. Nothing from LibreDWG is linked into FormCAD or imported by it.

| Work | Version | Licence | Read from |
| --- | --- | --- | --- |
| GNU LibreDWG (`dwg2dxf`, `dxf2dwg`, linked statically with the LibreDWG library built from the same archive) | 0.14 | GPL-3.0-or-later | The GNU LibreDWG page, https://www.gnu.org/software/libredwg/ ("GNU General Public License, version 3 or (at your option) any later version"), and `COPYING` in the release archive |

Source. The archive is `libredwg-0.14.tar.xz` from https://ftp.gnu.org/gnu/libredwg/, SHA-256 `62ebb73b984f865960f20ed26619ea5f8789d5e3fd088fa40a2598384da81275`, signed by RSA key `38A4167B0DB69E49C5F7216CB8C28866AB27A7A2` (Reini Urban, in the GNU keyring). It is built unmodified by `setup/build_dwg`. Each release of the DWG tools carries `COPYING.txt` (the GPL text), `GPL-OFFER.txt` (the written offer) and this notice, and the same release page carries the source archive and its signature.

What the tools can do, as the GNU LibreDWG page states it: the reader reads DWG files, with some very advanced R2010+ and pre-R13 entities skipped; the writer "is good enough for R2000". FormCAD therefore saves DWG through these tools in the 2000 format only.

On Linux and macOS the programs use only the system C library. On Windows they are built with MinGW-w64 under MSYS2 and linked statically, so they need only Windows system libraries.
