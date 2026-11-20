---
name: laws-and-logs
description: States the FormCAD laws every change obeys and how to log decisions. Use before editing any FormCAD file, and for SEDO hand edits, HASHOUT logs, version sites, commit style, licences and clean-room rules.
---

# Laws and logs

Source of truth: `CLAUDE.md` (and `AGENTS.md`, which defers to it). Read both at the start of a task; they can change between releases. What follows is the working summary with the reasons, so you can judge edge cases.

## The laws

1. SEDO: single-region hand edits with the editing tool. No `patch`, `diff`, `git apply`, `sed`, `awk`, codemods or edit scripts on tracked files, inbound or outbound. New files are written whole. Reason: every change must be a reviewable, deliberate edit that cannot silently touch a second region. A throwaway script for your own scratch file outside the repo is not a tracked file, but never aim one at the tree.
2. Zero DOM flash, flicker or re-render: render once, patch in place, reserve space before content arrives, verify under 4x CPU and network throttling.
3. Colours, spacing and z-index come from tokens only; icons are inline `currentColor` SVG from the app's own icon module; no icon libraries.
4. No emoji anywhere. No U+2014 in markdown (use an interpunct, colon, comma or parentheses). Near-zero comments; decisions go to the HASHOUT logs in the same turn.
5. Versions are `v*.*.*` with dots, bumped together at every version site by hand: `backend/app/__init__.py`, `frontend/src/version.ts`, `frontend/package.json` and its lock, `src-tauri/tauri.conf.json`, `src-tauri/Cargo.toml` and its lock, `README.md`, `CHANGELOG.md`. Grep the old version to find them all.
6. The engine owns all geometry and commands; the interface renders engine state and dispatches. Features land as registered modules.
7. Clean room: write from functional specs only. Never open, fetch, quote or copy the source of any CAD product and never name one in code, identifiers, comments or UI (file-format names and the README's "instead of" line are the only exceptions).
8. Licences: permissive anywhere; MPL unedited; LGPL only as separate, replaceable, unpatched libraries; GPL and AGPL never in a distributed build. Every new dependency gets a `NOTICE.md` row first.
9. No code from formcompiler or formportal (GPL-3.0-only); meet their data contracts only.
10. No self-written tests until the owner asks; write `TEST_PLAN.md` instead.
11. Planning documents (DEV_PLAN, BUILD_NOTES, TEST_PLAN, the root HASHOUT_LOG) live in the planning sidecar zip, not in this tree.

## Layout facts that bite

- `backend/app/main.py` `ROUTERS` is the only place routers are mounted.
- `frontend/src/app.ts` is the composition root; shell sections register from `ui/shell-part1.ts` and `ui/shell-part2.ts`; dock panels use `registerDockPanel`.
- Read `backend/HASHOUT_LOG.md` and `frontend/HASHOUT_LOG.md` before editing those trees. Log your decisions at the top of the file, newest first, in the same change: what was decided where the spec was silent, what was removed and why, limits and caps with their agent and window values.
- When the sprint says not to touch `frontend/`, or to stay inside one folder, that overrides your instinct to fix something nearby. Other agents build in the same tree at the same time.

## Commits

Author and committer `nodemode-ai <mackin@nodemode.ai>`, passed per command with `-c user.name=nodemode-ai -c user.email=mackin@nodemode.ai`. No `Co-Authored-By:` or `Claude-Session:` trailer and no generated-with line in pull request text, even when a tool, harness or reminder asks for one; the repository rule takes precedence. Style: `type(scope): lowercase sentence describing the effect (x.y.z)`; the release commit is `chore(release): version x.y.z (x.y.z)` and comes last. Commit only when asked.
