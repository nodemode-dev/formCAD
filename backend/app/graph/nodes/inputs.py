import math

from app.graph.nodes.common import NodeError, P, T, add, first_item, single, tree_absent

SLIDER_DEFAULTS = {"min": 0.0, "max": 10.0, "step": 0.0, "decimals": 2, "integer": False}


def slider_value(raw, lo, hi, step, decimals, integer):
    v = lo if raw is None else float(raw)
    clamped = v < lo or v > hi
    v = min(max(v, lo), hi)
    if step > 0:
        v = lo + round((v - lo) / step) * step
        v = min(max(v, lo), hi)
    v = round(v, decimals)
    if integer:
        v = int(math.floor(v + 0.5))
        v = min(max(v, int(math.ceil(lo))), int(math.floor(hi)))
    return v, clamped


def slider_run(ctx, trees):
    s = ctx.settings
    try:
        lo = float(s.get("min", 0.0))
        hi = float(s.get("max", 10.0))
        step = float(s.get("step", 0.0) or 0.0)
        decimals = int(s.get("decimals", 2))
    except (TypeError, ValueError):
        raise NodeError("The slider settings must be numbers.", "SLIDER_SETTINGS")
    if lo > hi:
        raise NodeError("The slider minimum is larger than its maximum.", "SLIDER_RANGE")
    if step < 0:
        raise NodeError("The slider step cannot be negative.", "SLIDER_STEP")
    decimals = min(max(decimals, 0), 12)
    v, clamped = slider_value(first_item(trees["value"]), lo, hi, step, decimals, bool(s.get("integer", False)))
    if clamped:
        ctx.remark("The stored value was outside the slider range and was clamped.", "CLAMPED", "value")
    return {"value": single(v)}


add(
    "input.slider", "a3db6afe-23d5-4db7-b398-041917e7d4e4", "Number Slider", "Slider", "Params", "Input",
    [P("value", "number", "tree", None, "V", "The stored slider position (persistent data).", True)],
    [P("value", "number", "item", None, "V", "The slider value, clamped to the range and snapped to the step.")],
    run=slider_run,
    description="A number chosen between a minimum and a maximum with a step and a number of decimals; the position is saved with the graph.",
    settings=SLIDER_DEFAULTS, widget="slider",
)


def panel_run(ctx, trees):
    t = trees["text"]
    return {"text": T.DataTree() if tree_absent(t) else t}


add(
    "input.panel", "c68af553-4e86-41b5-a6ea-feac47a99c29", "Panel", "Panel", "Params", "Input",
    [P("text", "any", "tree", None, "T", "Incoming data to show; when nothing is wired the saved text lines are used.", True)],
    [P("text", "any", "tree", None, "T", "The data shown in the panel, with its paths.")],
    run=panel_run,
    description="Shows any data tree with its paths; with nothing wired it supplies its saved text lines as a list.",
    widget="panel",
)


def toggle_run(ctx, trees):
    v = first_item(trees["value"], False)
    return {"value": single(bool(v))}


add(
    "input.toggle", "e1d6480d-1458-41fa-bcff-f79843ed5c13", "Toggle", "Toggle", "Params", "Input",
    [P("value", "boolean", "tree", None, "V", "The stored switch position (persistent data).", True)],
    [P("value", "boolean", "item", None, "V", "True when the switch is on.")],
    run=toggle_run, description="A switch that outputs true or false.", widget="toggle",
)


def button_run(ctx, trees):
    v = first_item(trees["pressed"], False)
    return {"pressed": single(bool(v))}


add(
    "input.button", "40ab7c1e-e16e-4f85-9cff-b12acf901c40", "Button", "Button", "Params", "Input",
    [P("pressed", "boolean", "tree", None, "P", "True while the button is held (persistent data, reset by the editor after the solve).", True)],
    [P("pressed", "boolean", "item", None, "P", "True while the button is pressed.")],
    run=button_run, description="Outputs true while it is pressed; the editor lets go after one solve.", widget="button",
)


def pick(ctx, items, chosen):
    rows = []
    picks = chosen if isinstance(chosen, (list, tuple)) else [chosen]
    for k in picks:
        try:
            k = int(k)
        except (TypeError, ValueError):
            raise NodeError("The selected entry must be a number.", "VALUELIST_SELECT")
        if not 0 <= k < len(items):
            ctx.warn("The selected entry %d does not exist." % k, "VALUELIST_RANGE")
            continue
        rows.append(items[k])
    return rows


def value_list_run(ctx, trees):
    items = ctx.settings.get("items") or []
    if not isinstance(items, list):
        raise NodeError("The value list entries must be a list.", "VALUELIST_ITEMS")
    clean = []
    for e in items:
        if not isinstance(e, dict) or "value" not in e:
            raise NodeError("Each value list entry needs a name and a value.", "VALUELIST_ITEMS")
        clean.append(e)
    rows = pick(ctx, clean, ctx.settings.get("selected", 0))
    return {"value": T.DataTree.from_items([r["value"] for r in rows]), "name": T.DataTree.from_items([str(r.get("name", r["value"])) for r in rows])}


add(
    "input.value_list", "3e37531d-3dab-4ef9-b281-048117974744", "Value List", "List", "Params", "Input",
    [],
    [P("value", "any", "item", None, "V", "The value of the selected entry."), P("name", "text", "item", None, "N", "The name of the selected entry.")],
    run=value_list_run,
    description="A fixed list of named values with one (or several) selected; the selection is saved with the graph.",
    settings={"items": [{"name": "One", "value": 1}, {"name": "Two", "value": 2}, {"name": "Three", "value": 3}], "selected": 0},
    widget="value_list",
)
