import io
import json

import numpy as np

from app.topo import surface
from app.topo.grid import Grid, TopoError


LEVEL_STEPS = 9
LEVEL_BAND = 0.01


def pack(grid: Grid, xphys, solid, vm, cls, history: list, meta: dict) -> bytes:
    shape = grid.shape()
    buf = io.BytesIO()
    hist = np.array([[h["iteration"], h["compliance"], h["volume"], h["change"], h["beta"]] for h in history], dtype=np.float64).reshape(-1, 5)
    full = dict(meta)
    full["grid"] = grid.dims()
    np.savez_compressed(buf, density=np.asarray(xphys, dtype=np.float32).reshape(shape), solid=np.asarray(solid, dtype=np.uint8).reshape(shape), vm=np.asarray(vm, dtype=np.float32).reshape(shape), cls=np.asarray(cls, dtype=np.uint8).reshape(shape), history=hist, meta=np.array(json.dumps(full, default=float)))
    return buf.getvalue()


def unpack(data: bytes):
    with np.load(io.BytesIO(data), allow_pickle=False) as z:
        arrays = {k: z[k] for k in z.files}
    meta = json.loads(str(arrays.pop("meta")))
    g = meta["grid"]
    grid = Grid(g["nx"], g["ny"], g["nz"], g["h"], g["origin"])
    return grid, arrays, meta


def field_for_surface(grid: Grid, arrays: dict, sigma: float) -> np.ndarray:
    solid = (arrays["solid"] > 0).astype(float)
    if sigma > 0:
        from scipy.ndimage import gaussian_filter

        padded = np.pad(solid, 3)
        return gaussian_filter(padded, sigma, mode="constant")[3:-3, 3:-3, 3:-3].ravel()
    return solid.ravel()


def extract(grid: Grid, arrays: dict, smooth: int = 8, sigma: float = 0.6):
    field = field_for_surface(grid, arrays, sigma)
    count = int((arrays["solid"] > 0).sum())
    target = count * grid.h ** 3
    lat = surface.lattice(grid, field)

    def build(level):
        v, t = surface.marching_tets(lat, level, grid.h, grid.origin)
        if not len(t):
            raise TopoError("The outcome has no surface: it holds no material.")
        v, t = surface.compact(v, t)
        if smooth > 0:
            v = surface.taubin(v, t, int(smooth), limit=0.4 * grid.h)
        return v, t, surface.volume(v, t)

    level = 0.5
    v, t, vol = build(level)
    if sigma > 0 and target > 0:
        lo, hi = 0.1, 0.9
        best = (abs(vol - target), level, v, t)
        for _ in range(LEVEL_STEPS):
            if abs(vol - target) <= LEVEL_BAND * target:
                break
            if vol < target:
                hi = level
            else:
                lo = level
            level = 0.5 * (lo + hi)
            v, t, vol = build(level)
            if abs(vol - target) < best[0]:
                best = (abs(vol - target), level, v, t)
        _gap, level, v, t = best
    return v, t, level


def decimate(v: np.ndarray, t: np.ndarray, count: int):
    if len(t) <= count:
        return v, t
    from app.meshes import reduce as reducer
    from app.meshes.core import Mesh

    out = reducer.simplify_to(Mesh(v, t), int(count), True)
    return out.v, out.t


def vertex_stress(grid: Grid, arrays: dict, v: np.ndarray) -> np.ndarray:
    from scipy.ndimage import maximum_filter

    vm = maximum_filter(arrays["vm"].astype(float), size=3)
    rel = np.floor((v - grid.origin) / grid.h).astype(int)
    rel[:, 0] = np.clip(rel[:, 0], 0, grid.nx - 1)
    rel[:, 1] = np.clip(rel[:, 1], 0, grid.ny - 1)
    rel[:, 2] = np.clip(rel[:, 2], 0, grid.nz - 1)
    return vm[rel[:, 2], rel[:, 1], rel[:, 0]]
