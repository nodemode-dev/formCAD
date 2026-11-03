# FormCAD assembly document schema

Schema version: **1** (header value `ASSEMBLY.schema`). This file is a contract: scripts, importers and other tools may rely on it. It changes only by the rules in "Versioning" below.

An assembly is an ordinary FormCAD project file (`.fcad`, a zip with `manifest.json` and `document.json`) whose manifest says `"kind": "assembly"`. Nothing about the container changes; the assembly lives in the same drawing tables the rest of the program uses, which is why undo, redo, autosave and save need no special case.

## 1. Where the data lives

| Place in `document.json` | Content |
| --- | --- |
| `header.ASSEMBLY` | one object, the assembly settings (section 2) |
| `tables.components` | one record per component (section 3) |
| `tables.patterns` | one record per component pattern (section 6) |
| `tables.asmconfigs` | one record per assembly configuration (section 7) |
| `spaces` / `entities` | for an embedded part, its solid bodies sit in a space named `part:C<n>`; solid bodies in the plain `model` space are loose bodies and are drawn in place |
| `header.DOCPROPS` | document properties of this file (section 9) |
| `cache/<blob>-d1.mesh` | copies of part meshes kept for components (section 5) |

Units: transforms and distances are in the document units of the assembly (`INSUNITS`). Part geometry is physical, so a part drawn in inches and placed in a millimetre assembly keeps its true size; only the placement numbers are in the assembly's units.

## 2. Header value `ASSEMBLY`

```json
{"schema": 1, "next": 4, "next_pattern": 2, "active_config": "Default",
 "search_folders": ["../library"], "search_order": ["relative", "absolute", "same_folder", "search_folders"],
 "embed_cache": true, "finds": {"pn:pl-100": 1}, "find_next": 2}
```

| Field | Meaning |
| --- | --- |
| `schema` | integer, 1 for this document |
| `next`, `next_pattern` | counters for component ids `C<n>` and pattern ids `P<n>`; ids are never reused |
| `active_config` | name of the active assembly configuration |
| `search_folders` | extra folders searched for a missing file; relative entries are relative to the assembly's folder |
| `search_order` | the order in which places are tried, steps from section 4 |
| `embed_cache` | keep a copy of each part's mesh in this file so a missing part can still be drawn (default true) |
| `finds`, `find_next` | find numbers assigned so far, keyed by item identity (section 8) |

## 3. Component record (table `components`)

The table key (`name`) is the component id and equals `id`.

```json
{"name": "C3", "id": "C3", "n": 3, "label": "Bracket", "type": "part",
 "ref": {"path": "parts/bracket.fcad", "abs": "/home/u/proj/parts/bracket.fcad"},
 "embedded": null,
 "transform": [1,0,0,10, 0,1,0,0, 0,0,1,0, 0,0,0,1],
 "visible": true, "suppressed": false, "fixed": false, "config": "",
 "props": {}, "sig": {"size": 5444, "mtime": 1793665599540771625, "sha256": "..."},
 "cache": {"bodies": [], "props": {}, "configs": [], "active_config": "", "mmu": 1.0, "taken": "2026-11-03T00:00:00+00:00"},
 "search": {"found_by": "relative", "resolved": "/home/u/proj/parts/bracket.fcad", "log": [], "order": [], "at": ""},
 "note": ""}
```

| Field | Meaning |
| --- | --- |
| `id`, `n` | `C<n>`; `n` is the number and the display order |
| `label` | the instance name, unique within the assembly (case-insensitive), up to 120 characters |
| `type` | `part` (a part file), `assembly` (another assembly file, a sub-assembly) or `embedded` (bodies stored in this file) |
| `ref.path` | the stored path of the file: relative to the folder of the assembly file with `/` separators when the file lies inside that folder, otherwise absolute |
| `ref.abs` | the last absolute path the file was found at; a hint only |
| `embedded.space` | for `embedded`, the space holding the bodies, `part:C<n>` |
| `transform` | 16 numbers, row major, see section 4.3 |
| `visible` | drawn or hidden (hidden components still count in the BOM) |
| `suppressed` | not loaded, not drawn, not counted, and its patterns and nested components are skipped |
| `fixed` | grounded; a fixed component is not moved by a solve or a drag. The first component inserted is fixed |
| `config` | for a part, one of its configurations; for a sub-assembly, one of its assembly configurations; empty means the file's own state |
| `props` | per-component overrides of the properties used by the BOM (section 9) |
| `sig` | signature of the file when it was last accepted into the assembly: `size`, `mtime` in nanoseconds, and `sha256` (empty for files over 64 MB) |
| `cache` | what is kept so the component can be drawn without the file; `bodies` lists `{handle, name, blob, rgb, offset, closed, material, has_mesh}` |
| `search` | the outcome of the last file search, with the order used and the places tried |
| `note` | free text, up to 2000 characters |

Readers must keep fields they do not know and write them back unchanged.

## 4. The reference model

### 4.1 Status

Status is computed whenever the assembly is read; it is not stored. Each component has:

| Field | Values |
| --- | --- |
| `status` | `loaded`, `missing`, `outofdate` |
| `reason` | `found`, `notfound`, `unreadable`, `cycle`, `toodeep`, `changed` |
| `stale` | true when what is drawn comes from the copy kept in the assembly, not from the file |
| `source` | `file`, `cache`, `embedded`, `none` |
| `found_by` | the search step that located the file |
| `nested` | for a sub-assembly, the problems found inside it (`key`, `status`, `message`) |

`loaded`: the file was found and matches `sig`. `outofdate`: the file was found but changed after the assembly last accepted it; the assembly keeps drawing its accepted copy (`stale: true`) until the component is reloaded. `missing`: the file could not be found, could not be read, or would contain the assembly that contains it (`cycle`); the kept copy is drawn and marked `stale`, or nothing is drawn when no copy exists.

### 4.2 Search order

When a file is needed, these steps are tried in the order of `search_order`; the default is the first four. Every place tried is recorded in `search.log` with whether it held the file.

| Step | Place |
| --- | --- |
| `relative` | `ref.path` joined to the folder of the assembly file |
| `absolute` | `ref.path` if it is absolute, then `ref.abs` |
| `same_folder` | the file name in the folder of the assembly file |
| `search_folders` | the file name in each of `search_folders`, then any folders given for this search |
| `deep` | the file name anywhere below the assembly's folder and the search folders (depth 5, at most 4000 folders); off unless named in `search_order` or asked for |

Paths that lead away from this computer (`://`, another machine's share, another operating system's absolute path) are never followed. Only `.fcad` files are opened.

### 4.3 Operations

Find File runs the search with extra folders and optionally relinks the stored path. Reload takes the current file (new `sig`, new copy, refreshed properties, refreshed feature-pattern sites). Replace points a component at another file of the same type, keeping its transform, name, state and, when it still exists, its configuration. Make Paths Relative rewrites stored paths relative to the assembly's folder. Nothing is ever deleted silently.

### 4.4 Cycles

An assembly cannot contain itself, directly or through sub-assemblies. Insert, Replace and Reload refuse a loop; a loop found in a file edited by hand is reported as `missing` with `reason: cycle` and not opened. Nesting is limited to 12 levels and 20000 instances.

## 5. Transforms

`transform` is a 4 by 4 matrix written as 16 numbers, row by row, using column vectors: `p_world = M p_local`. The last column holds the translation (elements 3, 7, 11), the last row is `0 0 0 1`. The upper 3 by 3 must be a proper rotation (orthonormal, determinant +1) to 1e-6; scaling, shearing and mirroring are refused. Part-local coordinates are the part's own model coordinates. The world transform of a nested component is the product of the transforms down the chain, `M_sub * M_inner`.

## 6. Patterns (table `patterns`)

```json
{"name": "P1", "id": "P1", "kind": "circular", "label": "Circular pattern 1", "seed": "C2",
 "params": {"axis_origin": [0,0,0], "axis_dir": [0,0,1], "count": 6, "angle": 360.0, "equal": true},
 "skip": [], "suppressed": false}
```

A pattern repeats the seed component; the seed is instance 0 and copies are numbered from 1 (key `C2#1`, `C2#2`). A copy's transform is `P_k * M_seed`, with `P_k` expressed in the frame of the assembly that holds the seed. Copies are derived, not stored: they have no records, count in the BOM, and cannot be moved by themselves. `skip` lists copy numbers to leave out; `suppressed` turns the whole pattern off.

| Kind | Parameters |
| --- | --- |
| `linear` | `dir1`, `spacing1`, `count1`, and optionally `dir2`, `spacing2`, `count2`; counts include the seed; direction 1 runs fastest |
| `circular` | `axis_origin`, `axis_dir`, `count` (including the seed), `angle` (360 spreads copies evenly; any other angle puts the last copy on that angle), `equal` |
| `feature` | `target` (a part component), `feature` (a feature id or name of that part), `ref_site`, `flip`, `sites` |

A feature pattern follows a feature of a part: the sites are the axes of the cylindrical faces whose radius and direction match the cylinder faces that the feature created (holes and round bosses, including copies made by a pattern feature), one site per axis, in part millimetres. The seed stays at the site `ref_site` (the one nearest to it when the pattern is made) and the copies take the other sites, so moving the target part moves the copies with it. `flip` turns the copies end for end.

## 7. Assembly configurations (table `asmconfigs`)

```json
{"name": "NoPin", "description": "", "default": false, "suppress": {"C2": true}, "visible": {}, "component_config": {}, "patterns": {}}
```

Each configuration stores, by component id (or pattern id), the suppression, the visibility, the part or sub-assembly configuration to use, and the suppression of patterns. The record `Default` holds the state the assembly had before the first configuration was made, filled in for every key any configuration uses, so activating Default restores the base. A key a configuration does not list inherits from Default. Activating a configuration writes those values into the component records. Changing suppression, visibility or the component configuration while a configuration is active updates that configuration. A sub-assembly's `config` selects one of that file's own assembly configurations without changing the file.

## 8. Bill of materials

The BOM is computed from the instances, never stored. A row is an item: components with the same part number are one item; without a part number, the same file and configuration are one item; an embedded part is its own item.

| Column | Source |
| --- | --- |
| Find | find number (below) |
| Part number | `props.part_number` of the component, else the file's `DOCPROPS.part_number`, else `idno` |
| Description | `description`, else `title` |
| Material | `material`, else the material of the part's first body |
| Qty | instances per one parent (indented) or total (flat and top) |
| Total qty | instances multiplied through every level above |
| Revision, File, Status, Name, Level, Type | as named |

Modes: `top` (the items of the top level only), `indented` (sub-assemblies followed by their items, quantity per level), `flat` (parts only, summed over all levels; an assembly with nothing inside, such as a missing one, stays as a line). Suppressed components are left out unless asked for.

Find numbers follow MIL-STD-100G practice: a find number is a reference number given to an item for cross-reference within a drawing and its lists, not an identifying number. They are assigned once per item in the order items first appear, stored in `ASSEMBLY.finds`, and stay with the item when the assembly changes. New items take the next unused number; Renumber starts again from 1.

CSV export goes through the program's checked output path (extension `.csv` forced, an existing file of another kind is never replaced). Cells that begin with `=`, `+`, `-`, `@`, tab or carriage return are written with a leading apostrophe.

## 9. Document properties

`header.DOCPROPS` is an object of text values on any FormCAD file: `part_number`, `description`, `material`, `revision`, `title`, `author`, `vendor`, `note`, and other names (lower case letters, digits, underscore; up to 100 properties, values up to 512 characters). The BOM and the title block read them. A sub-assembly file's properties are those of the assembly file.

## 10. Scene

The scene route of an assembly document (`GET /api/docs/{id}/scene`) uses the same binary layout as other documents. It does not tessellate anything that is already cached: each part's stored mesh is read, placed with the instance transform and written as one body record per instance body (positions and normals transformed, document units of the assembly). Hidden components are written with no mesh, suppressed ones are left out. The text block of the answer carries `instance`, `component`, `label`, `status`, `stale` and `source_of_mesh` for each record, plus any `issues`. The answer is always complete (never a delta).

## 11. Versioning

- `schema` is an integer. Adding an optional field, a new component type that older readers can skip, or a new pattern kind does not change it.
- Changing the meaning of an existing field, the transform convention, or the key rules for ids raises it, and the new reader must still read the older schema.
- A reader that meets a larger `schema` than it knows may show the assembly but refuses to change or save it, and says so.
- Readers keep unknown fields on records and in the header.
