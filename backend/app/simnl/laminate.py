import math

import numpy as np

MAX_PLIES = 256


class LaminateError(ValueError):
    pass


PLY_KEYS = ("E1", "E2", "G12", "nu12")
STRENGTH_KEYS = ("Xt", "Xc", "Yt", "Yc", "S")


def ply_matrix(E1, E2, G12, nu12):
    nu21 = nu12 * E2 / E1
    d = 1.0 - nu12 * nu21
    if d <= 0.0:
        raise LaminateError("The ply constants are not physical: nu12 squared exceeds E1 over E2.")
    return np.array([[E1 / d, nu12 * E2 / d, 0.0], [nu12 * E2 / d, E2 / d, 0.0], [0.0, 0.0, G12]])


def rotate(Q, deg):
    th = math.radians(deg)
    c, s = math.cos(th), math.sin(th)
    T = np.array([[c * c, s * s, 2 * c * s], [s * s, c * c, -2 * c * s], [-c * s, c * s, c * c - s * s]])
    R = np.diag([1.0, 1.0, 2.0])
    Ti = np.linalg.inv(T)
    return Ti @ Q @ R @ T @ np.linalg.inv(R)


def stress_transform(deg):
    th = math.radians(deg)
    c, s = math.cos(th), math.sin(th)
    return np.array([[c * c, s * s, 2 * c * s], [s * s, c * c, -2 * c * s], [-c * s, c * s, c * c - s * s]])


def clean_ply(raw):
    out = {}
    for k in PLY_KEYS:
        try:
            out[k] = float(raw[k])
        except (KeyError, TypeError, ValueError):
            raise LaminateError("The ply material needs %s." % k)
        if not out[k] > 0.0:
            raise LaminateError("%s must be positive." % k)
    if not 0.0 < out["nu12"] < 1.0:
        raise LaminateError("nu12 must be between 0 and 1.")
    for k in STRENGTH_KEYS:
        if raw.get(k) not in (None, ""):
            v = float(raw[k])
            if not v > 0.0:
                raise LaminateError("Strengths are positive numbers (compression strengths too).")
            out[k] = v
    return out


def expand_layup(layup, default_thickness):
    plies = []
    for item in layup:
        if isinstance(item, (int, float)):
            plies.append((float(item), default_thickness))
        else:
            ang = float(item.get("angle", 0.0))
            th = float(item.get("thickness", default_thickness))
            plies.append((ang, th))
    return plies


def build(ply, layup, thickness=None, symmetric=False):
    mat = clean_ply(ply)
    plies = expand_layup(layup, thickness)
    if symmetric:
        plies = plies + plies[::-1]
    if not plies or len(plies) > MAX_PLIES:
        raise LaminateError("A laminate has 1 to %d plies." % MAX_PLIES)
    if any(t is None or not t > 0.0 for _, t in plies):
        raise LaminateError("Every ply needs a positive thickness.")
    h = sum(t for _, t in plies)
    z = -h / 2.0
    Q = ply_matrix(mat["E1"], mat["E2"], mat["G12"], mat["nu12"])
    A = np.zeros((3, 3))
    B = np.zeros((3, 3))
    D = np.zeros((3, 3))
    rows = []
    for ang, t in plies:
        z0, z1 = z, z + t
        Qb = rotate(Q, ang)
        A += Qb * (z1 - z0)
        B += 0.5 * Qb * (z1**2 - z0**2)
        D += (1.0 / 3.0) * Qb * (z1**3 - z0**3)
        rows.append({"angle": ang, "thickness": t, "z0": z0, "z1": z1, "Qbar": Qb})
        z = z1
    return {"mat": mat, "plies": rows, "A": A, "B": B, "D": D, "h": h, "Q": Q}


def engineering_constants(lam):
    A, h = lam["A"], lam["h"]
    a = np.linalg.inv(A)
    return {"Ex": float(1.0 / (h * a[0, 0])), "Ey": float(1.0 / (h * a[1, 1])), "Gxy": float(1.0 / (h * a[2, 2])), "nu_xy": float(-a[0, 1] / a[0, 0]), "nu_yx": float(-a[0, 1] / a[1, 1])}


def tsai_wu_coefficients(mat):
    for k in STRENGTH_KEYS:
        if k not in mat:
            raise LaminateError("The Tsai-Wu check needs the strength %s." % k)
    Xt, Xc, Yt, Yc, S = (mat[k] for k in STRENGTH_KEYS)
    F1 = 1.0 / Xt - 1.0 / Xc
    F2 = 1.0 / Yt - 1.0 / Yc
    F11 = 1.0 / (Xt * Xc)
    F22 = 1.0 / (Yt * Yc)
    F66 = 1.0 / S**2
    F12 = -0.5 * math.sqrt(F11 * F22)
    return F1, F2, F11, F22, F66, F12


def tsai_wu(mat, s):
    F1, F2, F11, F22, F66, F12 = tsai_wu_coefficients(mat)
    s1, s2, t12 = s
    lin = F1 * s1 + F2 * s2
    quad = F11 * s1 * s1 + F22 * s2 * s2 + F66 * t12 * t12 + 2.0 * F12 * s1 * s2
    index = lin + quad
    if quad <= 0.0:
        ratio = math.inf if lin <= 0.0 else 1.0 / lin
    else:
        ratio = (-lin + math.sqrt(lin * lin + 4.0 * quad)) / (2.0 * quad)
    return float(index), float(ratio)


def analyse(lam, N=(0.0, 0.0, 0.0), M=(0.0, 0.0, 0.0), dT=0.0):
    A, B, D = lam["A"], lam["B"], lam["D"]
    ABD = np.block([[A, B], [B, D]])
    rhs = np.array(list(N) + list(M), dtype=float)
    try:
        sol = np.linalg.solve(ABD, rhs)
    except np.linalg.LinAlgError:
        raise LaminateError("The laminate stiffness is singular.")
    eps0, kappa = sol[:3], sol[3:]
    out = []
    worst = None
    for i, p in enumerate(lam["plies"]):
        pts = []
        for tag, zz in (("bottom", p["z0"]), ("middle", 0.5 * (p["z0"] + p["z1"])), ("top", p["z1"])):
            eps = eps0 + zz * kappa
            sg = p["Qbar"] @ eps
            sm = stress_transform(p["angle"]) @ sg
            row = {"at": tag, "z": zz, "strain_xy": [float(x) for x in eps], "stress_xy": [float(x) for x in sg], "stress_material": [float(x) for x in sm]}
            if all(k in lam["mat"] for k in STRENGTH_KEYS):
                idx, ratio = tsai_wu(lam["mat"], sm)
                row["tsai_wu_index"] = idx
                row["strength_ratio"] = ratio
                if worst is None or ratio < worst["strength_ratio"]:
                    worst = {"ply": i, "at": tag, "strength_ratio": ratio, "tsai_wu_index": idx}
            pts.append(row)
        out.append({"ply": i, "angle": p["angle"], "points": pts})
    return {"mid_strain": [float(x) for x in eps0], "curvature": [float(x) for x in kappa], "plies": out, "first_ply_failure": worst}
