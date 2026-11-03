import math

from app.cam.limits import CamError

RCTF_CAP = 3.0


def rpm_from_vc(vc: float, dcap: float) -> float:
    if dcap <= 0:
        raise CamError("Diameter must be positive.")
    return vc * 1000.0 / (math.pi * dcap)


def vc_from_rpm(rpm: float, dcap: float) -> float:
    return math.pi * dcap * rpm / 1000.0


def table_feed(fz: float, rpm: float, flutes: int) -> float:
    return fz * rpm * flutes


def feed_per_tooth(vf: float, rpm: float, flutes: int) -> float:
    if rpm <= 0 or flutes <= 0:
        raise CamError("Spindle speed and flute count must be positive.")
    return vf / (rpm * flutes)


def chip_thinning(ae: float, d: float) -> float:
    if d <= 0 or ae <= 0 or ae >= d / 2.0:
        return 1.0
    x = 1.0 - 2.0 * ae / d
    s = math.sqrt(max(1.0 - x * x, 1e-12))
    return min(1.0 / s, RCTF_CAP)


def engagement_angle(ae: float, d: float) -> float:
    return math.acos(max(-1.0, min(1.0, 1.0 - 2.0 * ae / d)))


def ae_from_engagement(phi: float, d: float) -> float:
    return d * (1.0 - math.cos(phi)) / 2.0


def scallop_from_stepover(r: float, p: float) -> float:
    if p >= 2.0 * r:
        return r
    return r - math.sqrt(r * r - p * p / 4.0)


def stepover_from_scallop(r: float, h: float) -> float:
    h = min(h, r)
    return 2.0 * math.sqrt(max(2.0 * h * r - h * h, 0.0))


def removal_rate(ap: float, ae: float, vf: float) -> float:
    return ap * ae * vf / 1000.0


def power(ae: float, ap: float, vf: float, kc: float) -> float:
    return ae * ap * vf * kc / (60.0 * 1e6)


def drill_feed(fn: float, rpm: float) -> float:
    return fn * rpm


def corner_feed(vf: float, path_radius: float, tool_radius: float) -> float:
    if path_radius <= tool_radius or path_radius <= 0:
        return vf
    return vf * (path_radius - tool_radius) / path_radius


def resolve(tool, feeds: dict, ae: float = 0.0, ap: float = 0.0) -> dict:
    feeds = feeds or {}
    material = str(feeds.get("material") or "")
    data = tool.cutting.get(material) if material else None
    vc = feeds.get("vc")
    fz = feeds.get("fz")
    notes = []
    if data:
        if vc is None and data.get("vc"):
            vc = data["vc"]
        if fz is None and data.get("fz"):
            fz = data["fz"]
    rpm = feeds.get("rpm")
    dcap = tool.effective_diameter(ap) if ap and tool.kind in ("ball", "bull") else tool.diameter
    if rpm is None and vc:
        rpm = rpm_from_vc(vc, dcap)
    if rpm is None:
        raise CamError("Give a spindle speed or a cutting speed (or add cutting data for the material to the tool).")
    rpm = float(rpm)
    if tool.rpm_max and rpm > tool.rpm_max:
        rpm = tool.rpm_max
        notes.append("Spindle speed limited to the tool maximum.")
    if rpm <= 0:
        raise CamError("Spindle speed must be positive.")
    vf = feeds.get("vf_cut")
    thin = 1.0
    if vf is None:
        if not fz:
            raise CamError("Give a cutting feed or a feed per tooth.")
        thin = chip_thinning(ae, tool.diameter) if ae > 0 else 1.0
        vf = table_feed(fz, rpm, tool.flutes) * thin
    vf = float(vf)
    plunge_f = data.get("plunge_factor", 0.5) if data else 0.5
    ramp_f = data.get("ramp_factor", 0.7) if data else 0.7
    vp = feeds.get("vf_plunge")
    vr = feeds.get("vf_ramp")
    return {"rpm": rpm, "vf_cut": vf, "vf_plunge": float(vp) if vp is not None else vf * plunge_f, "vf_ramp": float(vr) if vr is not None else vf * ramp_f, "vc": vc_from_rpm(rpm, dcap), "fz": fz if fz else feed_per_tooth(vf, rpm, tool.flutes), "chip_thinning": thin, "notes": notes, "material": material}


def calculate(body: dict) -> dict:
    d = float(body.get("diameter", 0))
    z = int(body.get("flutes", 1))
    out = {}
    vc = body.get("vc")
    rpm = body.get("rpm")
    fz = body.get("fz")
    ae = float(body.get("ae", 0) or 0)
    ap = float(body.get("ap", 0) or 0)
    if d <= 0:
        raise CamError("Give a positive diameter.")
    if rpm is None and vc is not None:
        rpm = rpm_from_vc(float(vc), d)
    if vc is None and rpm is not None:
        vc = vc_from_rpm(float(rpm), d)
    out["rpm"] = rpm
    out["vc"] = vc
    if rpm is not None and fz is not None:
        thin = chip_thinning(ae, d) if ae else 1.0
        out["chip_thinning"] = thin
        out["vf"] = table_feed(float(fz), float(rpm), z) * thin
        if ae and ap:
            out["removal_rate_cm3_min"] = removal_rate(ap, ae, out["vf"])
        if ae and ap and body.get("kc"):
            out["power_kw"] = power(ae, ap, out["vf"], float(body["kc"]))
    elif rpm is not None and body.get("vf") is not None:
        out["fz"] = feed_per_tooth(float(body["vf"]), float(rpm), z)
        out["vf"] = float(body["vf"])
    if body.get("scallop") is not None and body.get("ball_radius") is not None:
        out["stepover"] = stepover_from_scallop(float(body["ball_radius"]), float(body["scallop"]))
    if body.get("stepover") is not None and body.get("ball_radius") is not None:
        out["scallop"] = scallop_from_stepover(float(body["ball_radius"]), float(body["stepover"]))
    return out
