---
name: agent-dock
description: Explains working from a tab of FormCAD's agent dock, where Claude Code, Codex, Cursor or Antigravity runs inside the window. Use when an agent was started from the dock, when edits should appear in the open window, or when a tab's calls are refused.
---

# The agent dock

The agent dock is a panel of the FormCAD window (Window, Agent Dock; Ctrl+J, Cmd+J on a Mac) with a terminal tab and one tab per agent program. A program started there is already connected to this window's engine: FormCAD gives the tab a server named `formcad_tab` over HTTP with a token made for that tab.

## What a tab is

- Live, not headless. Every tool call edits the documents open in the window, and the person sees each change as it lands. There is nothing to register and no `--connect` to pass.
- The same tools as any other client: the fixed `formcad_*` tools and the `cmd_*` tools. Start with `formcad_status`, then `formcad_list_documents` to learn which document is active.
- The same trust class as any outside agent: granted folders apply, barred commands stay barred, job caps are the agent's.
- The tab's token opens the MCP server and nothing else. Any other route of the engine answers 403 with a sentence that says so. Do not try other routes; report the refusal.
- The token ends when the tab closes. A restarted tab gets a new one.

## Working beside a person

1. Say what you are about to change before a destructive step; the person is watching the same drawing.
2. Leave the selection and the view as you found them unless the task is about them: `formcad_get_selection` first, `formcad_select` to put it back.
3. One command per step when the person is following along, so each undo step in their Edit menu is one of yours. `formcad_undo` takes back yours and theirs alike: undo only what you made.
4. If the person is in the middle of a command, `formcad_command_line` answers their prompt. Ask before you send `formcad_cancel`.

## When something is missing

- A program that is not installed shows its install line in the dock. FormCAD does not run it; the person does.
- `formcad_status` says the kernel or the mesher is not installed: the person uses Install kernel in the status bar or Install mesher in the Studies panel. Wait for them, then call `formcad_status` again.
