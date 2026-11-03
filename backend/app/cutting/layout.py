import math

from app.cutting import nest as N
from app.cutting import plan as P
from app.cutting import shapes as S


def place_loops(part, tr):
    out = []
    for lp in part["loops"]:
        pts = S.transform(lp["pts"], tr["rot"], tr["dx"], tr["dy"])
        circ = None
        if lp.get("circle"):
            c = S.transform([tuple(lp["circle"]["c"])], tr["rot"], tr["dx"], tr["dy"])[0]
            circ = {"c": [c[0], c[1]], "r": lp["circle"]["r"]}
        out.append({"pts": pts, "circle": circ, "outer": lp["outer"]})
    return out


def world_parts(parts, sheet):
    out = []
    for pl in sheet["placements"]:
        p = parts[pl["index"]]
        out.append({"name": "%s #%d" % (p["name"], pl["instance"] + 1), "loops": place_loops(p, pl["transform"])})
    return out


def part_list(specs):
    return [S.normalize_part(s, i) if "gross" not in s else s for i, s in enumerate(specs)]


def plan_all(parts, nested, process, order="part", home=(0.0, 0.0)):
    sheets = []
    for sh in nested["sheets"]:
        wp = world_parts(parts, sh)
        res = P.plan_sheet(wp, process, order, (0.0, 0.0, sh["width"], sh["height"]), home)
        res["sheet"] = sh["index"]
        res["parts"] = len(wp)
        sheets.append(res)
    return sheets
