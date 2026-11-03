# Graph file format · schema 1.0.0

A graph is plain JSON data. It never carries code, and opening one never imports a module that is not already trusted. The same definition object is stored in the document table `graphs` (one record per graph) and written to standalone files with the extension `.graph`. A file adds the `format` field; the table record wraps the definition as `{name: "G1", id: "G1", n: 1, label, definition}`.

Files are UTF-8, two-space indent, keys sorted inside objects, array order kept, one trailing newline, so two saves of one graph diff cleanly.

## Top level

| Field | Meaning |
| --- | --- |
| `format` | always `"formcad.graph"` in a file |
| `version` | semantic version of the schema, `"1.0.0"` now |
| `min_reader` | lowest reader version that understands this file |
| `id`, `name` | graph id in the document (`G1`) and display name; the id is replaced on import |
| `created` | UTC time text |
| `app` | `{name}` of the writer |
| `meta` | `{name, description, author, license}` |
| `libraries` | `[{id, version}]` of the node libraries the graph uses, informational |
| `settings` | `{seed: 0, tolerance: 0.001, units: "mm", time_budget: 60.0, enabled: true}`; `enabled: false` stops solving (the global solutions switch), `time_budget` is seconds per node |
| `nodes` | node records, in creation order; the order is the tie-break of the solve order |
| `wires` | `[{id, from, to, order}]`, `from` an output port id, `to` an input port id, `order` ranks several wires into one input (0 first) |
| `groups` | `[{id, name, colour, members: [node id]}]`, colour a `#rrggbb` text |
| `notes` | `[{id, text, x, y}]` canvas notes |
| `view` | `{zoom, origin: [x, y]}` last canvas view |
| `extensions` | free object for tools; kept |

Any field not listed here is kept on a round trip, at the top level, in nodes, ports, wires and groups.

## Node record

```json
{"id": "n_7f3a", "type": "math.add", "guid": "7f0c...", "type_name": "Add", "library": "",
 "node_version": 1, "nickname": "", "enabled": true, "preview": true, "matching": "longest",
 "x": 120.0, "y": 80.0,
 "ports": {"in":  [{"id": "p_01", "name": "a", "access": "item",
                    "mods": {"flatten": true, "expression": "x*2"},
                    "persistent": {"type": "number", "tree": {"{0}": [1.5]}}}],
           "out": [{"id": "p_03", "name": "r", "access": "item", "mods": {}}]},
 "settings": {}}
```

- `id` is the instance id (unique in the graph, stable across saves). `type` is the type id (`namespace.name`, or `plugin-id/name` for a plugin node); `guid` is the permanent guid of the type, used to find a type whose id changed.
- `matching` is the data matching mode of the node: `longest`, `shortest` or `cross`.
- `enabled: false` makes the node skipped: it computes nothing and its outputs are empty. `preview` is a display flag only; a node with preview off still computes.
- Port ids are unique inside the graph. Ports are matched to the node type by `name`; a port the type no longer has is dropped on load with a note in `problems`, a port the type gained is added with a new id. `access` is `item`, `list` or `tree` and defaults to the type's.
- `mods` holds only the flags that are on: `reverse`, `flatten`, `graft`, `simplify`, `invert`, `principal` (booleans), `expression` (text, the calculator language with variable `x`), plus the P1 modifiers of the data module (`remove_null`, `remove_empty`, `sort`, `randomise`, `renumber`, `trim`, `null_to`). They apply to inputs before matching and to outputs before they are exposed.
- `persistent` (input ports only) is the value used when nothing is wired in: `{type, tree}` where `type` is a port kind and `tree` maps path text to an array of items, in the item encoding of the data module (numbers, text and booleans as JSON, geometry values as tagged objects).
- `settings` is the node's own configuration (a slider's range, a list's entries, a loop's maximum). Defaults from the type are filled in on load.

Nothing volatile is stored: no computed data, no node state, no messages.

## Compatibility rules

- A reader accepts a file whose `min_reader` is not above its own version and whose major version equals its own. It ignores and keeps unknown fields.
- A file with a newer major version, or a `min_reader` above the reader, is readable but locked: it can be solved, listed and exported byte for byte, and every edit is refused with the message that it was written by a newer version.
- Older majors are migrated by a chain of pure functions when one exists (none yet).
- A node whose type is not installed loads as a placeholder: it keeps its ports, persistent data, settings, unknown fields and wires, reports Error `MISSING_NODE`, outputs nothing, and is written back unchanged. Installing the library later replaces the placeholder with the real node on the next solve; ports are matched by name.
- A wire that would close a loop (or join a node to itself) is disabled on load with a note in `problems`, and the nodes it touches report Error `CYCLE`. The editor refuses such a wire with the names of the nodes in the loop.

## Table `graphs` and undo

Graph edits are document edits: each change commits one record in the `graphs` table, so undo, redo, autosave, save and reopen need nothing else. Header value `GRAPHS` holds `{schema: 1, next}` for the id counter. A run of live edits (a slider drag) merges into one undo step.
