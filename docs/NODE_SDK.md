# Node plugin SDK

A plugin adds node types to the graph editor and the headless runner. It uses the same plugin loader as command plugins, so the same trust rules apply: nothing is imported until the person enables the plugin, enabling records a hash of every file, and a changed file stops the plugin from loading until it is reviewed again. Plugin code runs inside the engine process as the person who enabled it, so enable only plugins you trust. A graph file never carries code; it only names node types.

## Two ways to ship a plugin

Plugin folder. Put a folder in `<data>/plugins/<plugin-id>/` with a `plugin.json` and the code files it lists. Seal it with `formcad-engine plugin seal <folder>` (this writes the sha256 of every `.py` file into `plugin.json`), then enable it in the plugin manager. `docs/examples/node_plugin/` is a working folder: copy it to `<data>/plugins/example-nodes/`.

Installed package. Declare an entry point in the group `formcad.nodes`; its value names a module or a function. The package is hashed as installed and enabled the same way.

```toml
[project.entry-points."formcad.nodes"]
acme = "acme_nodes:register"
```

Both ways call `register(api)` once when the plugin loads.

## Declaring a node

```python
def register(api):
    api.node(
        "repeat_text",
        guid="0b7f3e1a-4c52-4d8e-9f6a-2a1d5c7b9e30",
        name="Repeat Text", nick="Rep",
        category="Example", group="Text",
        description="Writes a piece of text several times in a row.",
        inputs=[api.port("text", "text", default="ab"), api.port("count", "integer", default=2, min=0, max=100)],
        outputs=[api.port("result", "text")],
        solve=lambda ctx, text, count: text * count,
    )
```

- The node type id is `<plugin-id>/<name>`, here `example-nodes/repeat_text`. The namespace comes from the plugin id and cannot be chosen.
- `guid` is a uuid that never changes. It lets a saved graph find the node after a rename.
- `api.port(name, kind, access="item", default=None, optional=False, min=None, max=None, choices=None, description="")`. Kinds are `any`, `number`, `integer`, `boolean`, `text`, `point`, `vector`, `plane`, `domain`, `colour`, `curve`, `surface`, `brep`, `mesh`, `geometry`, `transform` and `docref`. Access is `item`, `list` or `tree`.
- `solve(ctx, *inputs)` runs once for every matched set of inputs (item access gets one value, list access a list, tree access a whole tree). It returns one value per output, as a tuple when there are several. Pass `multi=True` when it returns a list that should become new branches.
- `run(ctx, trees)` replaces `solve` for nodes that need the whole input at once. It receives a dict of trees by port name and returns a dict of outputs.
- `ctx.warn(text, code, port)` and `ctx.remark(text)` add messages that keep the outputs. Raising `NodeWarning` (nulls the result of one call) or `NodeError` (fails the node) comes from `app.graph.sdk`.
- Other options: `version`, `settings` (defaults for node settings), `widget`, `icon`, `volatile` and `obsolete_by` (the id of the node that replaces this one).

## Rules

- Node ids, guids and port names are permanent. Add ports; do not remove or retype them.
- A node is a function of its inputs and `ctx.seed`. Take randomness from `random.Random(ctx.seed)`, never the clock.
- Use `ctx.kernel(method, params)` for solid geometry. Do not import the kernel libraries into the engine.
- Reading files or the network from a node is up to the plugin author and is the reason a plugin must be enabled by a person.

## Missing plugins

When a graph names a node type that is not installed, the graph still opens. The node becomes a placeholder: it keeps its ports, saved values and wires, reports the error `MISSING_NODE` with the plugin namespace, and is written back unchanged on save. Enabling the plugin and reopening the graph replaces the placeholder with the real node. The headless runner stops with exit code 3 and lists the missing types.

## Checking a plugin

```
formcad-engine plugin seal ./my-plugin
formcad-engine plugin list
formcad-engine graph io my.graph
formcad-engine graph run my.graph --in count=3
```

`graph run` loads the plugins that are enabled in the data folder (`--settings-dir DIR` picks another one).
