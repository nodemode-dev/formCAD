import math

import numpy as np

LAYER_CHANGE_S = 0.15


def path_length(pts) -> float:
    if len(pts) < 2:
        return 0.0
    d = np.diff(pts, axis=0)
    return float(np.hypot(d[:, 0], d[:, 1]).sum())


def extrude_time(pts, v: float, accel: float) -> float:
    if len(pts) < 2:
        return 0.0
    d = np.diff(pts, axis=0)
    seg = np.hypot(d[:, 0], d[:, 1])
    total = float(seg.sum())
    if total <= 0.0:
        return 0.0
    t = total / v + v / accel
    if len(d) > 1:
        a, b = d[:-1], d[1:]
        la, lb = seg[:-1], seg[1:]
        ok = (la > 1e-9) & (lb > 1e-9)
        cosv = np.where(ok, (a[:, 0] * b[:, 0] + a[:, 1] * b[:, 1]) / np.where(ok, la * lb, 1.0), 1.0)
        theta = np.arccos(np.clip(cosv, -1.0, 1.0))
        vj = v * np.maximum(0.0, 1.0 - theta / (math.pi / 2.0))
        t += float(((v - vj) ** 2 / (accel * v)).sum())
    return t


def travel_time(dist: float, v: float, accel: float) -> float:
    if dist <= 0:
        return 0.0
    if dist >= v * v / accel:
        return dist / v + v / accel
    return 2.0 * math.sqrt(dist / accel)


def layer_time(ops, s: dict, start, scale: float = 1.0, min_speed: float = 0.0):
    accel = s["acceleration"]
    pos = start
    t_ext = t_trv = 0.0
    fil = 0.0
    for op in ops:
        if op[0] == "T":
            if pos is not None:
                t_trv += travel_time(math.hypot(op[1] - pos[0], op[2] - pos[1]), s["speed_travel"], accel)
            if op[3]:
                t_trv += 2.0 * s["retract_length"] / s["retract_speed"]
            pos = (op[1], op[2])
        else:
            pts = op[2]
            v = op[4]
            if scale != 1.0:
                v = max(min(v, min_speed), v * scale)
            t_ext += extrude_time(pts, v, accel)
            fil += op[5] * path_length(pts)
            pos = (float(pts[-1][0]), float(pts[-1][1]))
    return t_ext, t_trv + LAYER_CHANGE_S, fil, pos


def finish(layers: list, s: dict) -> None:
    pos = None
    for L in layers:
        t_ext, t_trv, fil, end = layer_time(L.ops, s, pos)
        total = t_ext + t_trv
        if s["min_layer_time"] > 0 and total < s["min_layer_time"] and t_ext > 0:
            f = max(0.05, t_ext / max(s["min_layer_time"] - t_trv, 1e-6))
            if f < 1.0:
                L.ops = [op if op[0] == "T" else (op[0], op[1], op[2], op[3], max(min(op[4], s["min_speed"]), op[4] * f), op[5]) for op in L.ops]
                t_ext, t_trv, fil, end = layer_time(L.ops, s, pos)
        L.time_s = t_ext + t_trv
        L.fil_mm = fil
        L.fan = 0.0 if L.index < s["fan_start_layer"] else s["fan"]
        pos = end
