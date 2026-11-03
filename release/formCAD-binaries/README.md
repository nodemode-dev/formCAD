# formCAD-binaries

Binary releases of the two LGPL worker programs that FormCAD downloads on first use. Git holds text only; every binary lives on a GitHub Release. This folder is the layout of the `nodemode-dev/formCAD-binaries` repository, prepared inside the FormCAD repository and pushed by the owner.

| Program | Contains | Tag | Asset per platform |
| --- | --- | --- | --- |
| `formcad-kernel` | OpenCascade Technology 8.0.1 (LGPL-2.1 with the Open CASCADE exception), build123d, rhino3dm | `occt-<release>` | `occt-lgpl-<release>-<triple>.tar.gz` |
| `formcad-mesher` | Netgen 6.2.2608 and the OpenCascade build in netgen-occt (LGPL-2.1) | `mesher-<release>` | `mesher-lgpl-<release>-<triple>.tar.gz` |

Triples: `aarch64-apple-darwin`, `x86_64-apple-darwin`, `x86_64-unknown-linux-gnu`, `x86_64-pc-windows-msvc`. A published tag is never replaced; a rebuild gets a new number such as `8.0.1-2`.

## Layout

| Path | What it is |
| --- | --- |
| `records/` | `occt-licence.json`, `mesher-licence.json` (schema 2, empty until a release is recorded) and `SCHEMA.md` |
| `licences/` | `LGPL-2.1.txt`, `OCCT-EXCEPTION.txt`, `NETGEN-LICENSE.txt`, copied unedited from the upstream files |
| `templates/` | the per-archive `THIRD-PARTY-NOTICES` and `README` texts |
| `LGPL-OFFER.txt`, `SOURCES.md` | the written offer of source, and where each source lives |
| `tools/` | `stage_notices.py`, `update_record.py`, `pack_release.py`, `merge_records.py`, `preflight.py` (standard library only, Python 3.12) |
| `.github/workflows/preflight.yml` | record checks, including equality with the copies inside the app |

The build workflow lives in the FormCAD repository (`.github/workflows/binaries.yml`) because it freezes the programs from FormCAD's own source. It builds one archive per triple on native runners (ubuntu-22.04 for a glibc 2.35 floor), signs, records, merges the records, writes `SHA256SUMS`, the source asset and `RELEASE_NOTES.md`, and creates a draft release here.

## An archive

```
occt-lgpl-<release>-<triple>/
  formcad-kernel[.exe]      the program, first in the record
  _internal/                the frozen Python runtime and the shared libraries, replaceable
  LGPL-2.1.txt  OCCT-EXCEPTION.txt  THIRD-PARTY-NOTICES.txt  LGPL-OFFER.txt  README.md
```

The schema 2 record is published as a release asset beside the archives, not inside them, because the app refuses any file that is not in its shipped record and a file cannot hold its own hash. A release carries: the archives, `occt-licence.json`, `requirements.lock`, `occt-source-<release>.tar.gz`, `SHA256SUMS`, `RELEASE_NOTES.md`, and the CycloneDX file of the program.

## Local check

`release/dry_run` in the FormCAD repository builds the archive, the record and the checksums from `kernel/dist` without signing or fetching anything. See `docs/RELEASE.md` there.

## Licence

The files of this repository are Apache-2.0 (`LICENSE`). The programs in the releases carry their own licences, listed in `THIRD-PARTY-NOTICES.txt` inside each archive.
