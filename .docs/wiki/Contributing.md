# Contributing

Read `CLAUDE.md` and `AGENTS.md` at the repository root first. The laws bind every change, whether a person or an agent makes it.

## The laws

1. **Surgical edits.** Single-region hand edits to existing files. No patches, diffs, codemods, sed or edit scripts on tracked files. New files are written whole.
2. **Zero DOM flash.** Render once, patch in place, reserve space before content arrives. Check UI changes under throttled CPU and network.
3. **Tokens only.** Colours, spacing and z-index come from the token files; icons are inline `currentColor` SVG from the app's own icon module. No icon libraries.
4. **No emoji, no long dash in markdown.** Use the interpunct. Near-zero comments in code; decisions go to the HASHOUT logs in the same change.
5. **Versions** are `v*.*.*` with dots, bumped together at every version site by hand.
6. **The engine owns geometry and commands.** The interface renders and dispatches. Features land as registered modules.
7. **Clean room.** Specs only. Never open, quote or name another CAD, CAM, CAE or EDA product.
8. **Licences.** Permissive anywhere; MPL unedited; LGPL only as separate, replaceable programs; GPL and AGPL never in a distributed build. A `NOTICE.md` row before any dependency.
9. **No code from the GPL sibling projects.**
10. **Tests** are not written until the owner asks; `TEST_PLAN.md` is written instead.
11. **Planning documents** live in the planning sidecar, not in this tree.

## Also

- Every new route requires the session token. Paths are validated and output extensions forced. Subprocesses take argument lists, a timeout and bounded output.
- Every command or route that touches files, processes or settings is classified for macros and agents.
- Every computing job has size caps checked before it starts.
- Data ships with a cited source per value, or not at all.

## Commits

Author and committer are `nodemode-ai <mackin@nodemode.ai>`. Style: `type(scope): lowercase sentence describing the effect (x.y.z)`. No co-author trailers and no generated-with lines. See `BRANCHING.md`.
