import math

import numpy as np

from app.subd.cage import Cage, check_caps
from app.subd.cc import SubdError

MAX_SEGMENTS = 256


def count(value, lo, hi, what):
    n = int(value)
    if n < lo or n > hi:
        raise SubdError("%s must be %d to %d." % (what, lo, hi))
    return n


def box(origin, size, segs):
    nx, ny, nz = (count(s, 1, 64, "Segments") for s in segs)
    check_caps(0, 2 * (nx * ny + ny * nz + nx * nz))
    ox, oy, oz = origin
    dx, dy, dz = size
    n = (nx, ny, nz)
    ids = {}
    pts = []
    for k in range(nz + 1):
        for j in range(ny + 1):
            for i in range(nx + 1):
                if i in (0, nx) or j in (0, ny) or k in (0, nz):
                    ids[(i, j, k)] = len(pts)
                    pts.append([ox + dx * i / nx, oy + dy * j / ny, oz + dz * k / nz])
    faces = []
    for axis in range(3):
        u_ax, v_ax = (axis + 1) % 3, (axis + 2) % 3
        for sign in (1, 0):
            at = n[axis] if sign else 0
            for a in range(n[u_ax]):
                for b in range(n[v_ax]):
                    corners = []
                    for da, db in ((0, 0), (1, 0), (1, 1), (0, 1)):
                        idx = [0, 0, 0]
                        idx[axis], idx[u_ax], idx[v_ax] = at, a + da, b + db
                        corners.append(ids[tuple(idx)])
                    faces.append(corners if sign else corners[::-1])
    return Cage(pts, faces)


def plane(origin, size, segs):
    nx, ny = (count(s, 1, 128, "Segments") for s in segs)
    check_caps(0, nx * ny)
    pts = [[origin[0] + size[0] * i / nx, origin[1] + size[1] * j / ny, origin[2]] for j in range(ny + 1) for i in range(nx + 1)]
    faces = []
    for j in range(ny):
        for i in range(nx):
            a = j * (nx + 1) + i
            faces.append([a, a + 1, a + nx + 2, a + nx + 1])
    return Cage(pts, faces)


def cylinder(origin, radius, height, segments, height_segments):
    n = count(segments, 3, MAX_SEGMENTS, "Segments")
    hs = count(height_segments, 1, 128, "Height segments")
    check_caps(0, n * hs + 2)
    ox, oy, oz = origin
    pts = []
    for k in range(hs + 1):
        for i in range(n):
            t = 2 * math.pi * i / n
            pts.append([ox + radius * math.cos(t), oy + radius * math.sin(t), oz + height * k / hs])
    faces = []
    for k in range(hs):
        for i in range(n):
            a = k * n + i
            b = k * n + (i + 1) % n
            faces.append([a, b, b + n, a + n])
    faces.append([hs * n + i for i in range(n)])
    faces.append([i for i in reversed(range(n))])
    return Cage(pts, faces)


def sphere(origin, radius, segments, rings):
    n = count(segments, 3, MAX_SEGMENTS, "Segments")
    m = count(rings, 2, 128, "Rings")
    check_caps(0, n * m)
    ox, oy, oz = origin
    pts = [[ox, oy, oz - radius]]
    for k in range(1, m):
        phi = -math.pi / 2 + math.pi * k / m
        for i in range(n):
            t = 2 * math.pi * i / n
            pts.append([ox + radius * math.cos(phi) * math.cos(t), oy + radius * math.cos(phi) * math.sin(t), oz + radius * math.sin(phi)])
    pts.append([ox, oy, oz + radius])
    south, north = 0, len(pts) - 1
    faces = []
    for i in range(n):
        faces.append([south, 1 + (i + 1) % n, 1 + i])
    for k in range(m - 2):
        for i in range(n):
            a = 1 + k * n + i
            b = 1 + k * n + (i + 1) % n
            faces.append([a, b, b + n, a + n])
    base = 1 + (m - 2) * n
    for i in range(n):
        faces.append([north, base + i, base + (i + 1) % n])
    return Cage(pts, faces)


def quadball(origin, radius, spans):
    s = count(spans, 1, 32, "Spans")
    c = box([-1.0, -1.0, -1.0], [2.0, 2.0, 2.0], [s, s, s])
    v = c.v.copy()
    unit = v / np.linalg.norm(v, axis=1)[:, None]
    c.v = np.asarray(origin, dtype=np.float64) + unit * radius * fit_scale(c, unit)
    return c


def fit_scale(c, unit):
    from app.subd.cc import refine

    ch = refine(unit, c.f, {}, 3)
    r = np.linalg.norm(ch[-1].v, axis=1)
    return 1.0 / float(r.mean())


def torus(origin, major, minor, nm, nn):
    a = count(nm, 3, MAX_SEGMENTS, "Major segments")
    b = count(nn, 3, MAX_SEGMENTS, "Minor segments")
    check_caps(0, a * b)
    ox, oy, oz = origin
    pts = []
    for i in range(a):
        th = 2 * math.pi * i / a
        for j in range(b):
            ph = 2 * math.pi * j / b
            rr = major + minor * math.cos(ph)
            pts.append([ox + rr * math.cos(th), oy + rr * math.sin(th), oz + minor * math.sin(ph)])
    faces = []
    for i in range(a):
        for j in range(b):
            p00 = i * b + j
            p10 = ((i + 1) % a) * b + j
            p11 = ((i + 1) % a) * b + (j + 1) % b
            p01 = i * b + (j + 1) % b
            faces.append([p00, p10, p11, p01])
    return Cage(pts, faces)


def prism(loop, z0, height, spans):
    n = len(loop)
    if n < 3:
        raise SubdError("The profile needs at least 3 points.")
    spans = count(spans, 1, 128, "Spans")
    check_caps(0, n * spans + 2)
    area = 0.0
    for i in range(n):
        x0, y0 = loop[i]
        x1, y1 = loop[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    pts_loop = list(loop) if area >= 0 else list(reversed(loop))
    pts = []
    for k in range(spans + 1):
        for x, y in pts_loop:
            pts.append([x, y, z0 + height * k / spans])
    faces = []
    for k in range(spans):
        for i in range(n):
            a = k * n + i
            b = k * n + (i + 1) % n
            faces.append([a, b, b + n, a + n])
    faces.append([spans * n + i for i in range(n)])
    faces.append([i for i in reversed(range(n))])
    c = Cage(pts, faces)
    if height < 0:
        c.f = [list(reversed(f)) for f in c.f]
    return c


def revolve(points, origin, axis, angle_deg, segments):
    axis = np.asarray(axis, dtype=np.float64)
    ln = np.linalg.norm(axis)
    if ln < 1e-12:
        raise SubdError("The revolve axis has zero length.")
    k = axis / ln
    origin = np.asarray(origin, dtype=np.float64)
    m = len(points)
    if m < 2:
        raise SubdError("The profile needs at least 2 points.")
    full = abs(abs(angle_deg) - 360.0) < 1e-9
    nseg = count(segments, 3 if full else 1, MAX_SEGMENTS, "Segments")
    check_caps(0, nseg * (m - 1))
    P = np.asarray(points, dtype=np.float64) - origin
    along = P @ k
    radial = P - np.outer(along, k)
    rnorm = np.linalg.norm(radial, axis=1)
    scale = max(1.0, float(np.abs(P).max()))
    on_axis = rnorm < 1e-9 * scale
    if on_axis.sum() > 2 or (m > 2 and on_axis[1:-1].any()):
        raise SubdError("Only the first and last profile points may lie on the axis.")
    if rnorm[~on_axis].size == 0:
        raise SubdError("The profile lies on the axis.")
    ring = nseg if full else nseg + 1
    verts = []
    index = {}
    for j in range(m):
        if on_axis[j]:
            index[(j, 0)] = len(verts)
            verts.append((origin + k * along[j]).tolist())
            continue
        for i in range(ring):
            t = math.radians(angle_deg) * i / nseg
            rot = radial[j] * math.cos(t) + np.cross(k, radial[j]) * math.sin(t)
            index[(j, i)] = len(verts)
            verts.append((origin + k * along[j] + rot).tolist())

    def vid(j, i):
        return index[(j, 0)] if on_axis[j] else index[(j, i % ring)]

    faces = []
    for j in range(m - 1):
        for i in range(nseg):
            a, b = vid(j, i), vid(j, i + 1)
            c, d = vid(j + 1, i + 1), vid(j + 1, i)
            if on_axis[j] and on_axis[j + 1]:
                continue
            if on_axis[j]:
                faces.append([a, c, d])
            elif on_axis[j + 1]:
                faces.append([a, b, c])
            else:
                faces.append([a, b, c, d])
    cage = Cage(verts, faces)
    an = cage.analysis()
    if an["manifold"] and an["closed"] and an["volume_estimate"] is not None and an["volume_estimate"] < 0:
        cage.f = [list(reversed(f)) for f in cage.f]
    elif not an["closed"]:
        da = float(np.sum(np.diff(along)))
        if da < 0 or (abs(da) < 1e-12 * scale and angle_deg < 0):
            cage.f = [list(reversed(f)) for f in cage.f]
    return cage


def sym_mirror(symmetry, origin):
    out = []
    for ax in str(symmetry or "none").lower():
        if ax in "xyz":
            out.append({"axis": ax, "at": float(origin["xyz".index(ax)])})
    return out
