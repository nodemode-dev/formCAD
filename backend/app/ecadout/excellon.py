import datetime
import math

from app import __version__
from app.ecadout import gerber
from app.ecadout import view as V

EXTENSIONS = (".drl", ".xln")


def f3(v: float) -> str:
    return "%.3f" % v if abs(round(v, 3) - v) < 5e-5 else "%.4f" % v


def hits(view):
    rows = []
    layers = view["layers"]
    last = len(layers)
    for p in view["pads"]:
        d = p.get("drill")
        if not d:
            continue
        rows.append({"d": float(d), "x": float(p["x"]), "y": float(p["y"]), "plated": bool(p.get("plated", True)), "span": (1, last), "slot": float(p["slot"]) if p.get("slot") else 0.0, "rot": float(p.get("rot", 0.0))})
    for v in view["vias"]:
        a = layers.index(v.get("from", "F.Cu")) + 1
        b = layers.index(v.get("to", "B.Cu")) + 1
        rows.append({"d": float(v["drill"]), "x": float(v["x"]), "y": float(v["y"]), "plated": True, "span": (min(a, b), max(a, b)), "slot": 0.0, "rot": 0.0})
    for h in view["holes"]:
        rows.append({"d": float(h["d"]), "x": float(h["x"]), "y": float(h["y"]), "plated": bool(h.get("plated", False)), "span": (1, last), "slot": float(h["slot"]) if h.get("slot") else 0.0, "rot": float(h.get("rot", 0.0))})
    for r in rows:
        if r["d"] <= 0 or r["d"] > 20:
            raise V.OutputError("A drill diameter of %g mm is outside 0 to 20 mm." % r["d"])
    return rows


def groups(rows):
    out = {}
    for r in rows:
        out.setdefault((r["plated"], r["span"]), []).append(r)
    return out


def build(view: dict) -> list:
    ox, oy = view["origin"]
    files = []
    created = view["created"] or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    nlayers = len(view["layers"])
    for (plated, span), rows in sorted(groups(hits(view)).items(), key=lambda kv: (not kv[0][0], kv[0][1])):
        tools = sorted({round(r["d"], 4) for r in rows})
        number = {d: i + 1 for i, d in enumerate(tools)}
        if plated:
            func = "Plated,%d,%d,%s" % (span[0], span[1], "PTH" if span == (1, nlayers) else "Blind" if span[0] == 1 or span[1] == nlayers else "Buried")
            suffix = "PTH" if span == (1, nlayers) else "PTH-%d-%d" % span
        else:
            func = "NonPlated,%d,%d,NPTH" % span
            suffix = "NPTH"
        lines = ["M48", "; DRILL file written by FormCAD %s" % __version__, "; FORMAT={-:-/ absolute / metric / decimal}", "; #@! TF.GenerationSoftware,FormCAD,FormCAD,%s" % __version__, "; #@! TF.CreationDate,%s" % created, "; #@! TF.FileFunction,%s" % func, "; #@! TF.FilePolarity,Positive", "FMAT,2", "METRIC,TZ"]
        for d in tools:
            lines.append("T%dC%s" % (number[d], f3(d)))
        lines += ["%", "G90", "G05"]
        slots = 0
        for d in tools:
            lines.append("T%d" % number[d])
            for r in rows:
                if round(r["d"], 4) != d:
                    continue
                x, y = r["x"] - ox, r["y"] - oy
                if r["slot"] and r["slot"] > r["d"] + 1e-9:
                    half = (r["slot"] - r["d"]) / 2.0
                    ang = math.radians(r["rot"])
                    lines.append("X%sY%sG85X%sY%s" % (f3(x - half * math.cos(ang)), f3(y - half * math.sin(ang)), f3(x + half * math.cos(ang)), f3(y + half * math.sin(ang))))
                    slots += 1
                else:
                    lines.append("X%sY%s" % (f3(x), f3(y)))
        lines.append("M30")
        files.append({"suffix": suffix, "function": func, "text": "\n".join(lines) + "\n", "tools": len(tools), "hits": len(rows), "slots": slots})
    return files
