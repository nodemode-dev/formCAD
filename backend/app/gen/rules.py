import numpy as np
from scipy.ndimage import binary_dilation, binary_opening, generate_binary_structure, label

from app.gen.filters import AXES, axis_of
from app.topo.grid import DESIGN, SOLID, VOID, Grid, TopoError

METHODS = ("additive", "milling3", "cutting", "casting", "free")
LABELS = {"additive": "Additive", "milling3": "3-axis milling", "cutting": "2-axis cutting", "casting": "Casting", "free": "Unconstrained"}
FLAT = np.ones((3, 3), dtype=bool)


def spec_filters(method: str, ms: dict) -> dict:
    if method == "additive":
        return {"filters": [{"name": "overhang", "last": True, "direction": ms.get("direction", "+z")}]}
    if method == "milling3":
        dirs = ms.get("directions") or [ms.get("direction", "+z")]
        return {"filters": [{"name": "access", "last": True, "directions": list(dirs)}]}
    if method == "casting":
        d = ms.get("direction", "+z")
        axis = str(d).lstrip("+-")
        return {"filters": [{"name": "access", "last": True, "directions": ["+" + axis, "-" + axis]}]}
    if method == "cutting":
        return {"extrusion": ms.get("axis", "z")}
    if method == "free":
        return {}
    raise TopoError("The method %s is not one of %s." % (method, ", ".join(METHODS)))


def cube(grid: Grid, flat: np.ndarray) -> np.ndarray:
    return flat.reshape(grid.shape())


def flat_of(grid: Grid, a: np.ndarray) -> np.ndarray:
    return a.reshape(-1)


def reach(solid3: np.ndarray, axis: int, sign: int) -> np.ndarray:
    a = np.moveaxis(solid3, axis, 0)
    if sign > 0:
        a = a[::-1]
    out = np.logical_or.accumulate(a, axis=0)
    if sign > 0:
        out = out[::-1]
    return np.moveaxis(out, 0, axis)


def repair(grid: Grid, cls: np.ndarray, solid: np.ndarray, method: str, ms: dict, xphys: np.ndarray = None, level: float = 0.5) -> np.ndarray:
    s3 = cube(grid, solid).copy()
    c3 = cube(grid, cls)
    free = c3 != VOID
    if method == "additive":
        axis, sign = axis_of(ms.get("direction", "+z"))
        a = np.moveaxis(s3, axis, 0)
        a = a[::-1] if sign < 0 else a
        keep = np.moveaxis(c3 == SOLID, axis, 0)
        keep = keep[::-1] if sign < 0 else keep
        a = a.copy()
        for l in range(1, len(a)):
            sup = binary_dilation(a[l - 1], structure=FLAT, border_value=0)
            a[l] &= sup | keep[l]
        a = a[::-1] if sign < 0 else a
        s3 = np.moveaxis(a, 0, axis)
    elif method in ("milling3", "casting"):
        if method == "casting":
            axis_name = str(ms.get("direction", "+z")).lstrip("+-")
            dirs = ["+" + axis_name, "-" + axis_name]
        else:
            dirs = ms.get("directions") or [ms.get("direction", "+z")]
        hull = None
        for d in dirs:
            ax, sg = axis_of(d)
            r = reach(s3, ax, sg)
            hull = r if hull is None else hull & r
        s3 = hull & free
    elif method == "cutting":
        ax, _sg = axis_of(ms.get("axis", "z"))
        src = cube(grid, xphys) if xphys is not None else s3.astype(float)
        live = free
        num = np.where(live, src, 0.0).sum(axis=ax, keepdims=True)
        den = np.maximum(1, live.sum(axis=ax, keepdims=True))
        line = (num / den) >= level
        s3 = np.broadcast_to(line, s3.shape) & live
    s3 = s3 | (c3 == SOLID)
    s3 &= free
    return flat_of(grid, s3)


def overhang_cells(grid: Grid, cls: np.ndarray, solid: np.ndarray, direction: str) -> int:
    axis, sign = axis_of(direction)
    a = np.moveaxis(cube(grid, solid), axis, 0)
    a = a[::-1] if sign < 0 else a
    keep = np.moveaxis(cube(grid, cls) == SOLID, axis, 0)
    keep = keep[::-1] if sign < 0 else keep
    bad = 0
    for l in range(1, len(a)):
        sup = binary_dilation(a[l - 1], structure=FLAT, border_value=0)
        bad += int((a[l] & ~sup & ~keep[l]).sum())
    return bad


def gap_cells(grid: Grid, solid: np.ndarray, dirs) -> int:
    s3 = cube(grid, solid)
    hull = None
    for d in dirs:
        ax, sg = axis_of(d)
        r = reach(s3, ax, sg)
        hull = r if hull is None else hull & r
    return int((hull & ~s3).sum())


def line_variation(grid: Grid, cls: np.ndarray, solid: np.ndarray, axis: str) -> int:
    ax, _sg = axis_of(axis)
    s3 = cube(grid, solid)
    c3 = cube(grid, cls)
    live = c3 == DESIGN
    anyin = np.where(live, s3, False).any(axis=ax, keepdims=True)
    allin = np.where(live, s3, True).all(axis=ax, keepdims=True)
    return int(((anyin & ~allin) & live).sum())


def thin_cells(grid: Grid, solid: np.ndarray, size_cells: float) -> int:
    n = int(np.floor(size_cells))
    if n < 2:
        return 0
    s3 = np.pad(cube(grid, solid), n)
    opened = binary_opening(s3, structure=np.ones((n, n, n), dtype=bool))
    return int((s3 & ~opened).sum())


def holes(grid: Grid, solid: np.ndarray) -> int:
    s3 = np.pad(cube(grid, solid), 1)
    _l, n_solid = label(s3, structure=generate_binary_structure(3, 1))
    _l2, n_void = label(~s3, structure=generate_binary_structure(3, 1))
    return int(n_void - 1)


def manufacturing_report(grid: Grid, cls: np.ndarray, solid: np.ndarray, method: str, ms: dict, member_cells: float) -> dict:
    n = max(1, int(solid.sum()))
    out = {"method": method, "violations": {}}
    if method == "additive":
        out["violations"]["unsupported_cells"] = overhang_cells(grid, cls, solid, ms.get("direction", "+z"))
    elif method == "milling3":
        dirs = ms.get("directions") or [ms.get("direction", "+z")]
        out["violations"]["unreachable_cells"] = gap_cells(grid, solid, dirs)
    elif method == "casting":
        axis_name = str(ms.get("direction", "+z")).lstrip("+-")
        out["violations"]["undercut_cells"] = gap_cells(grid, solid, ["+" + axis_name, "-" + axis_name])
    elif method == "cutting":
        out["violations"]["varying_line_cells"] = line_variation(grid, cls, solid, ms.get("axis", "z"))
    out["violations"]["thin_cells"] = thin_cells(grid, solid, member_cells)
    out["violation_share"] = sum(out["violations"].values()) / n
    out["thin_share"] = out["violations"]["thin_cells"] / n
    out["member_size_ok"] = out["thin_share"] <= 0.05
    out["manufacturable"] = all(v == 0 for k, v in out["violations"].items() if k != "thin_cells")
    out["holes"] = holes(grid, solid)
    return out
