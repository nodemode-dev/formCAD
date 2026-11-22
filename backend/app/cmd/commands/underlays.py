import math
import os

from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import geom
from app.doc import underlays as U
from app.doc.kinds.underlay import Underlay
from app.param.units import INSUNITS_MM

PX_DPI = 96.0


def unit_mm(d) -> float:
    return INSUNITS_MM.get(int(d.header.get("INSUNITS", 0) or 0)) or (1.0 if d.metric else 25.4)


def png_dpi(full: str) -> float:
    try:
        with open(full, "rb") as fh:
            head = fh.read(1 << 16)
    except OSError:
        return 0.0
    for kind, body in U.png_chunks(head):
        if kind == b"pHYs" and len(body) >= 9 and body[8] == 1:
            ppm = int.from_bytes(body[0:4], "big")
            return ppm * 0.0254 if ppm > 0 else 0.0
        if kind == b"IDAT":
            break
    return 0.0


def natural_size(d, full: str, info: dict) -> tuple:
    k = unit_mm(d)
    if info["kind"] == "pdf":
        return info["w"] / 72.0 * 25.4 / k, info["h"] / 72.0 * 25.4 / k
    dpi = (png_dpi(full) if info["kind"] == "png" else 0.0) or PX_DPI
    return info["w"] / dpi * 25.4 / k, info["h"] / dpi * 25.4 / k


def make(ctx, path: str, source: str, point, scale: float, rotation: float, page: int = 1, width=None) -> Underlay:
    folder = U.folder_of(ctx.doc)
    full = U.resolve(path, folder)
    try:
        info = U.probe(full, page)
    except U.UnderlayError as err:
        raise CommandError(str(err))
    if source == "pdf" and info["kind"] != "pdf":
        raise CommandError("The file is not a PDF; attach it with IMAGEATTACH.")
    if source == "image" and info["kind"] == "pdf":
        raise CommandError("The file is a PDF; attach it with PDFATTACH.")
    w, h = natural_size(ctx.d, full, info)
    if width is not None:
        k = float(width) / w if w > 0 else 0.0
    else:
        k = float(scale)
    if not (math.isfinite(k) and k > 0):
        raise CommandError("The scale must be a positive number.")
    w, h = w * k, h * k
    o = geom.as_pt(point)
    ca, sa = math.cos(rotation), math.sin(rotation)
    e = Underlay(source=source, path=U.stored(full, folder), name=os.path.splitext(os.path.basename(full))[0], page=int(page))
    e.pixels = [int(info["w"]) if source == "image" else float(info["w"]), int(info["h"]) if source == "image" else float(info["h"])]
    e.corners = [[o[0], o[1], 0.0], [o[0] + w * ca, o[1] + w * sa, 0.0], [o[0] - h * sa, o[1] + h * ca, 0.0]]
    ctx.stamp(e)
    if not e.valid():
        raise CommandError("The underlay could not be placed with those values.")
    return e


def attach_flow(ctx, source):
    word = "PDF" if source == "pdf" else "image"
    p = yield ctx.text("Enter path of the %s file to attach" % word)
    if p.kind != "text" or not p.value.strip():
        return
    path = p.value.strip().strip('"')
    page = 1
    if source == "pdf":
        n = yield ctx.number("Enter page number", default=1, integer=True, positive=True)
        if n.kind == "number":
            page = int(n.value)
        elif n.kind != "enter":
            return
    try:
        U.probe(U.resolve(path, U.folder_of(ctx.doc)), page)
    except U.UnderlayError as err:
        ctx.say(str(err))
        return
    pt = yield ctx.point("Specify insertion point", default=[0.0, 0.0, 0.0])
    if pt.kind not in ("point", "enter"):
        return
    point = pt.value if pt.kind == "point" else [0.0, 0.0, 0.0]
    s = yield ctx.number("Specify scale factor", default=1.0, positive=True)
    if s.kind not in ("number", "enter"):
        return
    scale = float(s.value) if s.kind == "number" else 1.0
    a = yield ctx.angle("Specify rotation angle", default=0.0)
    if a.kind not in ("number", "text", "enter"):
        return
    rot = float(a.value) if a.kind == "number" else 0.0
    try:
        e = make(ctx, path, source, point, scale, rot, page)
    except CommandError as err:
        ctx.say(str(err))
        return
    ctx.d.add_entity(e, ctx.doc.current_space)
    ctx.say("%s %s attached." % ("PDF" if source == "pdf" else "Image", e.name))


def attach_exec(ctx, args, source):
    path = str(args.get("path", "")).strip()
    if not path:
        raise CommandError("Give the path of the file to attach.")
    page = int(args.get("page", 1) or 1)
    e = make(ctx, path, source, args.get("point", [0.0, 0.0]), float(args.get("scale", 1.0)), math.radians(float(args.get("rotation", 0.0))), page, args.get("width"))
    h = ctx.d.add_entity(e, ctx.doc.current_space)
    return {"handle": h, "path": e.path, "corners": e.corners, "page": e.page}


@command("imageattach", group="block", label="Attach Image", description="Attach a PNG or JPEG image as an underlay.", menu="Insert > Raster Image Reference...")
def imageattach(ctx):
    yield from attach_flow(ctx, "image")


@executes("imageattach")
def imageattach_exec(ctx, args):
    return attach_exec(ctx, args, "image")


@command("pdfattach", group="block", label="Attach PDF", description="Attach a page of a PDF as an underlay.", menu="Insert > PDF Underlay...")
def pdfattach(ctx):
    yield from attach_flow(ctx, "pdf")


@executes("pdfattach")
def pdfattach_exec(ctx, args):
    return attach_exec(ctx, args, "pdf")


def pick_underlay(ctx, handle, source=None):
    e = ctx.d.get(int(handle)) if handle is not None else None
    if e is None or e.kind != "underlay" or (source and e.source != source):
        raise CommandError("The object is not an %s underlay." % ("image" if source == "image" else "PDF" if source == "pdf" else "image or PDF"))
    if ctx.locked(e):
        raise CommandError("The underlay is on a locked layer.")
    return e


def select_flow(ctx, source):
    s = yield ctx.select("Select %s to clip" % ("image" if source == "image" else "PDF underlay"), pick_one=True)
    if s.kind != "selection" or not s.value:
        return None
    for h in s.value:
        e = ctx.d.get(h)
        if e is not None and e.kind == "underlay" and e.source == source:
            return e
    ctx.say("The object is not an %s underlay." % ("image" if source == "image" else "PDF"))
    return None


def set_clip(ctx, e, ring_world) -> None:
    local = []
    for p in ring_world:
        q = e.to_local(p)
        if q is None:
            raise CommandError("The underlay has no area.")
        local.append([q[0], q[1]])
    if len(local) < 3:
        raise CommandError("A clipping boundary needs at least three points.")
    area = sum(local[i][0] * local[(i + 1) % len(local)][1] - local[(i + 1) % len(local)][0] * local[i][1] for i in range(len(local)))
    if abs(area) <= 1e-12:
        raise CommandError("The clipping boundary has no area.")
    m = ctx.d.modify(e.handle)
    m.clip = local
    m.clip_on = True


def clip_flow(ctx, source):
    e = yield from select_flow(ctx, source)
    if e is None:
        return
    k = yield ctx.keyword("Enter clipping option", ["ON", "OFF", "Delete", "New boundary"], "New boundary")
    if k.kind not in ("keyword", "enter", "text"):
        return
    opt = "New boundary" if k.kind == "enter" else str(k.value)
    low = opt.lower()
    if low == "on":
        if not e.clip:
            ctx.say("The underlay has no clipping boundary.")
            return
        ctx.d.modify(e.handle).clip_on = True
        return
    if low == "off":
        ctx.d.modify(e.handle).clip_on = False
        return
    if low.startswith("d"):
        ctx.d.modify(e.handle).clip = []
        return
    t = yield ctx.keyword("Enter clipping type", ["Polygonal", "Rectangular"], "Rectangular")
    if t.kind not in ("keyword", "enter", "text"):
        return
    poly = t.kind != "enter" and str(t.value).lower().startswith("p")
    if poly:
        pts = []
        while True:
            p = yield ctx.point("Specify %s point" % ("first" if not pts else "next"), base=pts[-1] if pts else None)
            if p.kind != "point":
                break
            pts.append(p.value)
        ring = pts
    else:
        a = yield ctx.point("Specify first corner point")
        if a.kind != "point":
            return
        b = yield ctx.point("Specify opposite corner point", base=a.value, rect=True)
        if b.kind != "point":
            return
        x0, y0 = min(a.value[0], b.value[0]), min(a.value[1], b.value[1])
        x1, y1 = max(a.value[0], b.value[0]), max(a.value[1], b.value[1])
        ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    try:
        set_clip(ctx, e, ring)
    except CommandError as err:
        ctx.say(str(err))


def clip_exec(ctx, args, source):
    e = pick_underlay(ctx, args.get("handle"), source)
    mode = str(args.get("mode", "new")).lower()
    if mode == "on":
        if not e.clip:
            raise CommandError("The underlay has no clipping boundary.")
        ctx.d.modify(e.handle).clip_on = True
    elif mode == "off":
        ctx.d.modify(e.handle).clip_on = False
    elif mode in ("delete", "remove"):
        ctx.d.modify(e.handle).clip = []
    else:
        if args.get("points"):
            ring = [geom.as_pt(p) for p in args["points"]]
        elif args.get("corners"):
            a, b = geom.as_pt(args["corners"][0]), geom.as_pt(args["corners"][1])
            ring = [[min(a[0], b[0]), min(a[1], b[1])], [max(a[0], b[0]), min(a[1], b[1])], [max(a[0], b[0]), max(a[1], b[1])], [min(a[0], b[0]), max(a[1], b[1])]]
        else:
            raise CommandError("Give points (a polygon) or corners (two opposite corners).")
        set_clip(ctx, e, ring)
    e = ctx.d.get(e.handle)
    return {"handle": e.handle, "clip": e.clip, "clip_on": e.clip_on}


@command("imageclip", group="modify", label="Clip Image", description="Clip an image underlay to a rectangle or polygon, or turn its clipping off.", menu="Modify > Clip > Image")
def imageclip(ctx):
    yield from clip_flow(ctx, "image")


@executes("imageclip")
def imageclip_exec(ctx, args):
    return clip_exec(ctx, args, "image")


@command("pdfclip", group="modify", label="Clip PDF Underlay", description="Clip a PDF underlay to a rectangle or polygon, or turn its clipping off.", menu="Modify > Clip > PDF Underlay")
def pdfclip(ctx):
    yield from clip_flow(ctx, "pdf")


@executes("pdfclip")
def pdfclip_exec(ctx, args):
    return clip_exec(ctx, args, "pdf")


def adjust_flow(ctx, source):
    s = yield ctx.select("Select %s" % ("image" if source == "image" else "PDF underlay"), pick_one=True)
    if s.kind != "selection" or not s.value:
        return
    e = next((ctx.d.get(h) for h in s.value if ctx.d.get(h) is not None and ctx.d.get(h).kind == "underlay" and ctx.d.get(h).source == source), None)
    if e is None:
        ctx.say("The object is not an %s underlay." % ("image" if source == "image" else "PDF"))
        return
    f = yield ctx.number("Enter fade value (0-100)", default=int(e.fade), integer=True, minimum=0, maximum=100)
    if f.kind != "number":
        return
    if ctx.locked(e):
        ctx.say("The underlay is on a locked layer.")
        return
    ctx.d.modify(e.handle).fade = int(f.value)


def adjust_exec(ctx, args, source):
    e = pick_underlay(ctx, args.get("handle"), source)
    m = ctx.d.modify(e.handle)
    if "fade" in args:
        v = int(args["fade"])
        if not 0 <= v <= 100:
            raise CommandError("Fade must be from 0 to 100.")
        m.fade = v
    if "show" in args:
        m.show = bool(args["show"])
    return {"handle": m.handle, "fade": m.fade, "show": m.show}


@command("imageadjust", group="modify", label="Adjust Image", description="Set the fade of an image underlay.", menu="Modify > Object > Image > Adjust...")
def imageadjust(ctx):
    yield from adjust_flow(ctx, "image")


@executes("imageadjust")
def imageadjust_exec(ctx, args):
    return adjust_exec(ctx, args, "image")


@command("pdfadjust", group="modify", label="Adjust PDF Underlay", description="Set the fade of a PDF underlay.", menu="Modify > Object > PDF Underlay > Adjust...")
def pdfadjust(ctx):
    yield from adjust_flow(ctx, "pdf")


@executes("pdfadjust")
def pdfadjust_exec(ctx, args):
    return adjust_exec(ctx, args, "pdf")
