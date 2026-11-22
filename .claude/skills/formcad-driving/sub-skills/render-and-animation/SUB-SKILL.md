---
name: render-and-animation
description: Says what an agent can and cannot do with FormCAD's rendering, appearances, storyboards and exploded views. Use when asked for a picture, a rendered image, a turntable, a video or an exploded view of a model.
---

# Render and animation

Be exact about the boundary: the path-traced render mode, appearances, environments, the storyboard and video export run in the window's own graphics and have no MCP tools. An agent cannot start them, set them or collect their files. Say so plainly and hand that step to the person.

## What an agent can produce

| Wanted | Tool | Notes |
| --- | --- | --- |
| A picture of the drawing | `formcad_render` | A PNG of the 2D display list, optionally a model-space `window` [x1, y1, x2, y2] and a `size` in pixels. It is a drafting image, not a shaded or path-traced one. |
| The plot as an image | `cmd_preview` | The current layout as it would plot. |
| A PDF, PNG or SVG file | `formcad_export` | The path must lie in a granted folder; the extension picks the format. |
| An exploded view | `cmd_explodeview` | Named steps that move components along a direction by a distance; arguments `action`, `id`, `view`, `step`, `index`, `t`, `save_as`. Read the result's `state` after each call. |

## What to hand to the person

- A path-traced image: Render View turns the render mode on, and Render Image in the Render Panel writes the picture. Tell them the resolution and view you would use.
- A turntable: Render Turntable in the Render Panel.
- An appearance or an environment: the Render Panel. Three environments ship with the app; a larger copy of one is a download the person starts.
- A storyboard or a video of an assembly: the Storyboard panel (Window, Storyboard), with Play Storyboard to preview it.

## Preparing the model so their render is one click

1. Name the bodies and layers that should read as different materials; appearances are assigned by body.
2. Save named views with the view commands (find them with `formcad_list_commands` filter `view`), so the person renders from a view you chose.
3. For an assembly, build the exploded view with `cmd_explodeview` and tell them its id.
