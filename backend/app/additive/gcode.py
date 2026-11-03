import re

import numpy as np

from app.additive.toolpath import BRIDGE, GCODE_TYPE

PLACE = re.compile(r"\{([a-z_0-9]+)\}")


def fill_template(text: str, values: dict) -> list:
    def sub(m):
        key = m.group(1)
        return str(values[key]) if key in values else m.group(0)

    return [PLACE.sub(sub, line).rstrip() for line in str(text).splitlines() if line.strip()]


def fmt(v: float) -> str:
    return ("%.3f" % v).rstrip("0").rstrip(".") or "0"


def write_gcode(layers: list, s: dict, header: dict) -> tuple:
    out = ["; FormCAD slicer for Marlin-style firmware"]
    for key, value in header.items():
        out.append("; %s = %s" % (key, value))
    bx, by = s["bed"]
    travel = int(round(s["speed_travel"] * 60))
    vals = {"bed_temp": int(round(s["bed_temp"])), "nozzle_temp": int(round(s["nozzle_temp"])), "first_nozzle_temp": int(round(s["first_nozzle_temp"])), "travel_mm_min": travel, "first_layer_height": fmt(s["first_layer_height"]), "layer_height": fmt(s["layer_height"]), "bed_x": fmt(bx), "bed_y": fmt(by), "prime_x": 10, "prime_x2": 70, "prime_y": 3}
    out.extend(fill_template(s["start_gcode"], vals))
    layer_lines = []
    ret_len = s["retract_length"]
    ret_f = int(round(s["retract_speed"] * 60))
    lift = s["retract_lift"]
    fw = s["firmware_retraction"]
    cur_f = None
    fan_now = None
    last_type = None
    for L in layers:
        layer_lines.append(len(out))
        out.append(";LAYER:%d" % L.index)
        out.append(";Z:%s" % fmt(L.z))
        out.append(";HEIGHT:%s" % fmt(L.h))
        out.append("G1 Z%s F600" % fmt(L.z))
        cur_f = None
        if L.index == 1 and abs(s["nozzle_temp"] - s["first_nozzle_temp"]) > 1e-9:
            out.append("M104 S%d" % int(round(s["nozzle_temp"])))
        want_fan = L.fan
        if fan_now != want_fan:
            out.append("M106 S%d" % int(round(255.0 * want_fan / 100.0)) if want_fan > 0 else "M107")
            fan_now = want_fan
        for op in L.ops:
            if op[0] == "T":
                x, y, retract = op[1], op[2], op[3]
                if retract and ret_len > 0:
                    out.append("G10" if fw else "G1 E%s F%d" % (fmt(-ret_len), ret_f))
                    if lift > 0:
                        out.append("G1 Z%s F%d" % (fmt(L.z + lift), 600))
                out.append("G0 X%s Y%s F%d" % (fmt(x), fmt(y), travel))
                cur_f = travel
                if retract and ret_len > 0:
                    if lift > 0:
                        out.append("G1 Z%s F%d" % (fmt(L.z), 600))
                    out.append("G11" if fw else "G1 E%s F%d" % (fmt(ret_len), ret_f))
                    cur_f = ret_f
                continue
            feat, pts, width, speed, e = op[1], op[2], op[3], op[4], op[5]
            if last_type != feat:
                out.append(";TYPE:%s" % GCODE_TYPE.get(feat, "FILL"))
                last_type = feat
            want = s["bridge_fan"] if feat == BRIDGE else L.fan
            if fan_now != want:
                out.append("M106 S%d" % int(round(255.0 * want / 100.0)) if want > 0 else "M107")
                fan_now = want
            f = int(round(speed * 60))
            prev = pts[0]
            for q in pts[1:]:
                d = float(np.hypot(q[0] - prev[0], q[1] - prev[1]))
                if d < 1e-4:
                    continue
                if cur_f != f:
                    out.append("G1 X%s Y%s E%.5f F%d" % (fmt(q[0]), fmt(q[1]), d * e, f))
                    cur_f = f
                else:
                    out.append("G1 X%s Y%s E%.5f" % (fmt(q[0]), fmt(q[1]), d * e))
                prev = q
    out.extend(fill_template(s["end_gcode"], vals))
    return out, layer_lines
