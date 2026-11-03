import math

from app.graph import docvalues, model, shapes
from app.graph.values import Arc3, Circle3, Colour, Line3, Point3, Polyline3, Shape
from app.services import kernel

PROVENANCE = "FORMCAD_GRAPH"
PROPS = "FORMCAD_PROPS"
FLAT = 1e-9
MAX_BAKE = 20000


class BakeError(model.GraphError):
    pass


def flat_xy(points, tol: float = 1e-7) -> bool:
    return all(abs(p.z) <= tol for p in points)


def plane_is_xy(plane, tol: float = 1e-9) -> bool:
    return abs(abs(plane.z.z) - 1.0) <= tol and abs(plane.origin.z) <= 1e-7


def hex_of(colour) -> str:
    return colour.hex()[:7]


def rgb_floats(colour) -> list:
    return [colour.r / 255.0, colour.g / 255.0, colour.b / 255.0]


class Job:
    __slots__ = ("node", "port", "path", "index", "value", "name", "layer", "colour", "props", "drafting")

    def __init__(self, node, port, path, index, value, drafting):
        att = docvalues.attributes_of(value)
        self.node, self.port, self.path, self.index = node, port, str(path), index
        self.value = docvalues.unwrap(value)
        self.name, self.layer, self.colour, self.props = att["name"], att["layer"], att["colour"], att["props"]
        self.drafting = drafting

    def tag(self, gid: str) -> str:
        return "%s/%s/%s/%s/%d" % (gid, self.node, self.port, self.path, self.index)


BAKEABLE = (Point3, Line3, Polyline3, Circle3, Arc3, Shape)


def collect(graph, nodes, options: dict) -> tuple:
    only = set(str(n) for n in nodes) if nodes else None
    ports = set(str(p) for p in options.get("ports") or [])
    selected_only = bool(options.get("selected"))
    chosen = None
    if selected_only:
        from app.graph import preview

        chosen = preview.selected_of(graph)
    jobs, skipped = [], []
    with graph.lock:
        for nid, node in graph.nodes.items():
            if only is not None and nid not in only:
                continue
            if only is None and (not node.preview or not node.enabled):
                continue
            if chosen is not None and nid not in chosen:
                continue
            if node.state != "computed":
                if only is not None:
                    skipped.append("Node %s has no computed data." % (node.nickname or node.type_name or nid))
                continue
            drafting = bool(node.settings.get("bake_drafting", options.get("drafting", False)))
            for port, tree in (node.outputs or {}).items():
                if ports and port not in ports and "%s.%s" % (nid, port) not in ports:
                    continue
                for path, row in tree.items():
                    for i, v in enumerate(row):
                        geo = docvalues.unwrap(v)
                        if isinstance(geo, Shape) and geo.kind == "docref":
                            continue
                        if isinstance(geo, BAKEABLE):
                            jobs.append(Job(nid, port, path, i, v, drafting))
    if len(jobs) > MAX_BAKE:
        raise BakeError("The graph would bake %d objects; the limit is %d." % (len(jobs), MAX_BAKE))
    return jobs, skipped


def kernel_batch(ops: list) -> list:
    if not ops:
        return []
    try:
        res = kernel.call("graph_batch", {"ops": ops}, 60.0 + 0.1 * len(ops))
    except Exception as err:
        raise BakeError(str(err) or "The kernel did not answer.")
    return res.get("results") or []


def stamp(ent, job: Job, gid: str, defaults: dict, label: str, count: int) -> None:
    ent.layer = job.layer or defaults.get("layer") or ent.layer
    colour = job.colour or defaults.get("colour")
    if colour is not None and ent.kind != "solidbody":
        ent.color = hex_of(colour)
    name = job.name or (("%s %d" % (defaults["name"], count)) if defaults.get("name") else "")
    if hasattr(ent, "name") and name:
        ent.name = name
    xd = dict(ent.xdata or {})
    xd[PROVENANCE] = [[1000, job.tag(gid)]]
    lines = [[1000, "%s=%s" % (k, v)] for k, v in job.props]
    if name and not hasattr(ent, "name"):
        lines.append([1000, "name=%s" % name])
    if lines:
        xd[PROPS] = lines
    ent.xdata = xd


def light_entities(job: Job, s: float) -> list:
    from app.doc.entities import Arc, Circle, Line, LwPolyline, Point, Polyline3d

    v = job.value

    def sc(p):
        return [p.x / s, p.y / s, p.z / s]

    if isinstance(v, Point3):
        return [Point(position=sc(v))]
    if isinstance(v, Line3):
        return [Line(start=sc(v.a), end=sc(v.b))]
    if isinstance(v, Polyline3):
        if job.drafting and flat_xy(v.points):
            z = v.points[0].z / s
            return [LwPolyline(vertices=[{"p": [p.x / s, p.y / s], "bulge": 0.0} for p in v.points], closed=bool(v.closed), elevation=z)]
        return [Polyline3d(points=[sc(p) for p in v.points], closed=bool(v.closed))]
    if isinstance(v, Circle3) and plane_is_xy(v.plane) and job.drafting:
        n = [0.0, 0.0, 1.0 if v.plane.z.z > 0 else -1.0]
        return [Circle(center=sc(v.plane.origin), radius=v.radius / s, normal=n)]
    if isinstance(v, Arc3) and plane_is_xy(v.plane) and v.plane.z.z > 0 and job.drafting:
        a0 = math.atan2(v.plane.x.y, v.plane.x.x) + v.start
        a1 = a0 + v.sweep
        if v.sweep < 0:
            a0, a1 = a1, a0
        return [Arc(center=sc(v.plane.origin), radius=v.radius / s, start_angle=a0, end_angle=a1)]
    return []


def curve_spec_of(v):
    from app.graph.geo import curve_spec

    return curve_spec(v)


def nurbs_entity(rec: dict, s: float):
    from app.doc.kinds.nurbscurve import NurbsCurve

    ent = NurbsCurve(source={"op": "graph"})
    rec = dict(rec)
    rec["poles"] = [[c / s for c in q] for q in rec["poles"]]
    ent.set_record(rec)
    return ent


def bake(doc, graph, request: dict) -> dict:
    from app.solid import work

    request = request or {}
    options = dict(request.get("options") or {})
    d = doc.drawing
    if shapes.stale_nodes(graph):
        from app.graph import solver

        shapes.refresh(graph)
        solver.solve(graph, d)
    s = work.mm(d)
    gid = graph.id
    jobs, skipped = collect(graph, request.get("nodes"), options)
    defaults = {"layer": str(options.get("layer") or d.current_layer()), "name": str(options.get("name") or ""), "colour": Colour.from_hex(options["colour"]) if options.get("colour") else None}
    replaced = 0
    node_ids = {j.node for j in jobs}
    if options.get("replace", True):
        prefixes = tuple("%s/%s/" % (gid, n) for n in node_ids)
        for h in [h for h, e in list(d.ents.items()) if any(str(item[1]).startswith(prefixes) for item in (e.xdata or {}).get(PROVENANCE, []))] if prefixes else []:
            d.erase_entity(h)
            replaced += 1
    brep_jobs = [j for j in jobs if isinstance(j.value, Shape) and j.value.kind in ("brep", "surface")]
    curve_jobs = [j for j in jobs if (isinstance(j.value, Shape) and j.value.kind == "curve") or (isinstance(j.value, (Circle3, Arc3, Polyline3, Line3)) and not light_entities(j, s))]
    stale = [j for j in brep_jobs + curve_jobs if isinstance(j.value, Shape) and shapes.serial_of(j.value.sid) != shapes.current_serial()]
    if stale:
        raise BakeError("Some kernel shapes are from before the kernel restarted; solve the graph again, then bake.")
    copies = kernel_batch([{"op": "copy", "shape": {"sid": shapes.unwrap(j.value.sid)}, "summary": True} for j in brep_jobs])
    try:
        records = kernel_batch([{"op": "record", "curve": ({"sid": shapes.unwrap(j.value.sid)} if isinstance(j.value, Shape) else curve_spec_of(j.value))} for j in curve_jobs])
    except BakeError:
        if any(isinstance(j.value, Shape) for j in curve_jobs):
            raise
        for j in curve_jobs:
            j.drafting = True
        curve_jobs, records = [], []
    made, kinds, handles = 0, {}, []
    counter = 0
    label = lambda j: j.node

    def add(ent, job):
        nonlocal made, counter
        counter += 1
        stamp(ent, job, gid, defaults, label(job), counter)
        h = d.add_entity(ent, doc.current_space)
        handles.append(h)
        kinds[ent.kind] = kinds.get(ent.kind, 0) + 1
        made += 1

    for job, res in zip(brep_jobs, copies):
        if "error" in res:
            skipped.append("%s: %s" % (job.node, res["error"]))
            continue
        name = job.name or ("%s %d" % (defaults["name"], counter + 1) if defaults["name"] else ("Solid" if job.value.kind == "brep" else "Surface"))
        src = {"op": "graph", "graph": gid, "node": job.node, "surface": job.value.kind == "surface"}
        body = work.new_body(d, res["sid"], res["summary"], name, src, rgb_floats(job.colour or defaults["colour"]) if (job.colour or defaults["colour"]) else None)
        add(body, job)
    for job, res in zip(curve_jobs, records):
        if "error" in res:
            skipped.append("%s: %s" % (job.node, res["error"]))
            continue
        add(nurbs_entity(res["curve"], s), job)
    for job in jobs:
        if isinstance(job.value, Shape):
            continue
        for ent in light_entities(job, s):
            add(ent, job)
    return {"baked": made, "replaced": replaced, "entities": handles, "kinds": kinds, "skipped": skipped, "message": "Baked %d object(s) from graph %s." % (made, graph.name or gid)}
