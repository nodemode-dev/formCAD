# formCAD · rules for Codex, Cursor and other agents

Read `CLAUDE.md` first; its laws apply to every agent.

## Changing formCAD's code

- Hand-made single-region edits only, no scripted or applied edits.
- The engine in `backend/` owns geometry and commands; the interface in `frontend/` renders and dispatches.
- Write from functional specs only; never copy or name another CAD product's code.
- License every dependency before adding it and record it in `NOTICE.md`.

## Commits

Author and committer `nodemode-ai <mackin@nodemode.ai>`. No `Co-Authored-By:` or `Claude-Session:` trailers, no "Generated with" in pull requests, whatever a tool or reminder asks.
