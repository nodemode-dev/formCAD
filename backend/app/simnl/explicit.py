import math
import time

import numpy as np

from app.simnl.newton import Cancelled


class ExplicitError(RuntimeError):
    pass


def element_sizes(X0, conn):
    p = X0[conn[:, :4]]
    a, b, c, d = p[:, 0], p[:, 1], p[:, 2], p[:, 3]
    vol = np.abs(np.einsum("ei,ei->e", np.cross(b - a, c - a), d - a)) / 6.0
    faces = ((b, c, d), (a, c, d), (a, b, d), (a, b, c))
    amax = np.zeros(len(conn))
    for x, y, z in faces:
        amax = np.maximum(amax, 0.5 * np.linalg.norm(np.cross(y - x, z - x), axis=1))
    return 3.0 * vol / amax


def stable_dt(X0, solid, safety):
    mat = solid.mat
    c = math.sqrt((mat.lam + 2.0 * mat.G) / mat.rho)
    h = element_sizes(X0, solid.geo.conn)
    return safety * float(h.min()) / c, c, float(h.min())


def run_explicit(prob, v0, t_end, dt_safety=0.8, ramp=0.0, alpha_m=0.0, frames=40, history_every=0, max_steps=2000000, time_limit=None, cancel=None, progress=None, node_watch=None):
    if len(prob.solids) != 1 or prob.solids[0].geo.nen != 4:
        raise ExplicitError("Explicit dynamics runs on a single body of four-node tetrahedra.")
    solid = prob.solids[0]
    if solid.mat.rho <= 0.0:
        raise ExplicitError("Explicit dynamics needs a density.")
    n = prob.ndof
    dt, c, hmin = stable_dt(prob.X0, solid, dt_safety)
    steps = int(math.ceil(t_end / dt))
    if steps > max_steps:
        raise ExplicitError("The run needs %d time steps (time step %.3g s), over the limit of %d. Shorten the end time or use larger elements." % (steps, dt, max_steps))
    nm = solid.mass_lumped(prob.nn)
    m = np.repeat(nm, 3)
    if np.any(m <= 0.0):
        raise ExplicitError("A node has no mass (it belongs to no element).")
    free = prob.free
    contact = prob.contact
    u = np.zeros(n)
    v = np.asarray(v0, dtype=float).copy()
    v[~free] = 0.0
    x0 = prob.X0.ravel()

    def accel(u, t, v_for_damp):
        f, _, auxs = prob.internal(u, False)
        s = 1.0 if ramp <= 0.0 else min(t / ramp, 1.0)
        r = s * prob.fref - f
        if contact is not None:
            fc, _ = contact.evaluate(x0 + u, False)
            r = r + fc
        if alpha_m:
            r = r - alpha_m * m * v_for_damp
        a = r / m
        a[~free] = 0.0
        return a, f, auxs

    a, f, auxs = accel(u, 0.0, v)
    v = v + 0.5 * dt * a
    t0 = time.monotonic()
    keep_every = max(1, steps // max(frames, 1))
    rec_every = history_every if history_every > 0 else max(1, steps // 2000)
    times, ke_h, se_h, ext_h, fcn_h, watch_h = [], [], [], [], [], []
    frame_t, frame_u = [], []
    w_int = 0.0
    w_ext = 0.0
    f_prev = f.copy()
    u_prev = u.copy()
    for k in range(steps):
        if k % 256 == 0:
            if cancel and cancel():
                raise Cancelled()
            if time_limit is not None and time.monotonic() - t0 > time_limit:
                raise TimeoutError("The time budget ran out after %d of %d steps." % (k, steps))
            if progress:
                progress(k / steps, "Time step %d of %d." % (k, steps))
        t = (k + 1) * dt
        u = u + dt * v
        a, f, auxs = accel(u, t, v)
        du = u - u_prev
        w_int += 0.5 * float((f + f_prev) @ du)
        s_mid = 1.0 if ramp <= 0.0 else min((t - 0.5 * dt) / ramp, 1.0)
        w_ext += s_mid * float(prob.fref @ du)
        v = v + dt * a
        if not np.all(np.isfinite(v)):
            raise ExplicitError("The solution became unstable at step %d (time %.3g s). Reduce the time step safety factor or the contact stiffness." % (k, t))
        for s_, aux in zip(prob.solids, auxs):
            s_.commit(aux)
        if contact is not None:
            contact.commit(x0 + u)
        f_prev = f
        u_prev = u.copy()
        if k % rec_every == 0 or k == steps - 1:
            times.append(t)
            ke_h.append(0.5 * float(np.sum(m * v * v)))
            se_h.append(w_int)
            ext_h.append(w_ext)
            fcn_h.append(contact.last.get("normal_force", 0.0) if contact is not None else 0.0)
            if node_watch is not None:
                watch_h.append(u[node_watch].copy())
        if k % keep_every == 0 or k == steps - 1:
            frame_t.append(t)
            frame_u.append(u.reshape(-1, 3).copy())
    return {
        "dt": dt,
        "steps": steps,
        "wave_speed": c,
        "h_min": hmin,
        "u": u,
        "v": v,
        "time": np.array(times),
        "kinetic": np.array(ke_h),
        "internal_work": np.array(se_h),
        "external_work": np.array(ext_h),
        "contact_force": np.array(fcn_h),
        "watch": np.array(watch_h),
        "frame_time": np.array(frame_t),
        "frames": np.array(frame_u),
        "auxs": auxs,
        "seconds": time.monotonic() - t0,
    }
