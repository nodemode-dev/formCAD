from app.graph import docvalues
from app.graph.geo import guid
from app.graph.nodes.docref import colour_of, drawing_of
from app.graph.sdk import NodeType, NodeWarning, Port, register
from app.graph.values import Colour

CAT = "Document"


def set_attributes(geometry, name, layer, colour):
    if geometry is None:
        raise NodeWarning("There is no geometry to describe.", "NO_GEOMETRY")
    base = geometry if isinstance(geometry, docvalues.Attributed) else docvalues.Attributed(geometry)
    return base.with_(
        name=str(name) if name not in (None, "") else base.name,
        layer=str(layer) if layer not in (None, "") else base.layer,
        colour=colour if isinstance(colour, Colour) else base.colour,
    )


register(NodeType(
    id="attr.set", guid=guid("attr.set"), name="Set Attributes", nick="Attr", category=CAT, group="Attributes",
    inputs=[
        Port("geometry", "geometry"),
        Port("name", "text", optional=True, description="Object name written at bake time"),
        Port("layer", "text", optional=True, description="Layer for the baked object; made when missing"),
        Port("colour", "colour", optional=True, description="Display colour of the baked object"),
    ],
    outputs=[Port("geometry", "geometry")],
    solve=lambda ctx, geometry, name, layer, colour: set_attributes(geometry, name, layer, colour),
    description="Pass geometry on with a name, layer and colour that the bake step applies. A value wired in replaces the one carried in.",
))


def set_property(geometry, key, value):
    if geometry is None:
        raise NodeWarning("There is no geometry to describe.", "NO_GEOMETRY")
    k = str(key or "").strip()
    if not k or "=" in k:
        raise NodeWarning("A property key is text without an equals sign.", "BAD_KEY")
    base = geometry if isinstance(geometry, docvalues.Attributed) else docvalues.Attributed(geometry)
    kept = tuple(p for p in base.props if p[0] != k)
    return base.with_(props=kept + ((k, str(value if value is not None else "")),))


register(NodeType(
    id="attr.user_property", guid=guid("attr.user_property"), name="Set User Property", nick="Prop", category=CAT, group="Attributes",
    inputs=[Port("geometry", "geometry"), Port("key", "text", default="source"), Port("value", "text", default="")],
    outputs=[Port("geometry", "geometry")],
    solve=lambda ctx, geometry, key, value: set_property(geometry, key, value),
    description="Attach a text property to geometry; the bake step stores it on the object.",
))


def read_attributes(ctx, handle):
    d = drawing_of(ctx)
    h = int(handle)
    docvalues.watch(ctx.graph, ctx.node.id, docvalues.Sub(d, [h]))
    ent = d.ents.get(h)
    if ent is None:
        raise NodeWarning("There is no object with handle %d in the document." % h, "NO_OBJECT")
    pairs = []
    for app, items in sorted((ent.xdata or {}).items()):
        if app == "FORMCAD_PROPS":
            for code, text in items:
                key, _eq, val = str(text).partition("=")
                pairs.append("%s=%s" % (key, val))
    return getattr(ent, "name", "") or "", ent.layer, colour_of(ent, d), ent.kind, "\n".join(pairs)


register(NodeType(
    id="attr.read", guid=guid("attr.read"), name="Read Attributes", nick="Read", category=CAT, group="Attributes",
    inputs=[Port("id", "integer", description="Handle of a document object")],
    outputs=[Port("name", "text"), Port("layer", "text"), Port("colour", "colour"), Port("kind", "text"), Port("properties", "text", description="key=value lines, one per user property")],
    solve=lambda ctx, handle: read_attributes(ctx, handle),
    volatile=True,
    description="Name, layer, colour and user properties of a document object. The node recomputes when the object changes.",
))
