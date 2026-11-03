import csv
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time

import numpy as np

from app.flow.limits import LIMITS, Cancelled, FlowError, cap

SETTINGS_FILE = "flow.json"
EXE_NAMES = ("SU2_CFD", "SU2_CFD.exe")
MPI_NAMES = ("mpirun", "mpiexec", "mpiexec.exe", "mpirun.exe")
MAX_TAIL = 64 * 1024
MAX_LOG = 256 * 1024 * 1024
MAX_RANKS = 16
ENV_KEEP = frozenset(("PATH", "HOME", "LANG", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"))
TUNABLE = frozenset(("CFL_NUMBER", "ITER", "CONV_NUM_METHOD_FLOW", "MUSCL_FLOW", "SLOPE_LIMITER_FLOW", "INC_NONDIM", "LINEAR_SOLVER_ITER", "JST_SENSOR_COEFF", "CONV_RESIDUAL_MINVAL", "NUM_METHOD_GRAD", "LINEAR_SOLVER_PREC"))
LABEL = "SU2 (LGPL-2.1), a separate program you install yourself, run as a separate process on straight-sided linear elements."


def settings_path():
    from app.core import config

    return config.data_dir() / SETTINGS_FILE


def load_settings() -> dict:
    try:
        raw = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    ranks = raw.get("su2Ranks", 1)
    ranks = ranks if isinstance(ranks, int) and 1 <= ranks <= MAX_RANKS else 1
    return {"su2Enabled": bool(raw.get("su2Enabled", False)), "su2Path": str(raw.get("su2Path", "") or ""), "mpiPath": str(raw.get("mpiPath", "") or ""), "su2Ranks": ranks}


def save_settings(enabled=None, path=None, mpi=None, ranks=None) -> dict:
    cur = load_settings()
    if path is not None:
        want = str(path).strip()
        if want and os.path.basename(want.replace("\\", "/")) not in EXE_NAMES:
            raise FlowError("The SU2 program must be named SU2_CFD.")
        if want and not (os.path.isabs(want) and os.path.isfile(want)):
            raise FlowError("The SU2 program must be given as a full path to an existing file.")
        cur["su2Path"] = want
    if mpi is not None:
        want = str(mpi).strip()
        if want and os.path.basename(want.replace("\\", "/")).lower() not in MPI_NAMES:
            raise FlowError("The MPI launcher must be mpirun or mpiexec.")
        if want and not (os.path.isabs(want) and os.path.isfile(want)):
            raise FlowError("The MPI launcher must be given as a full path to an existing file.")
        cur["mpiPath"] = want
    if ranks is not None:
        if not isinstance(ranks, int) or isinstance(ranks, bool) or not 1 <= ranks <= MAX_RANKS:
            raise FlowError("The process count must be a whole number from 1 to %d." % MAX_RANKS)
        cur["su2Ranks"] = ranks
    if enabled is not None:
        cur["su2Enabled"] = bool(enabled)
    from app.doc import container

    container.atomic_write(str(settings_path()), json.dumps(cur).encode("utf-8"), 0o600)
    return cur


def status() -> dict:
    s = load_settings()
    path = s["su2Path"]
    present = bool(path and os.path.isfile(path) and os.access(path, os.X_OK))
    usable = bool(s["su2Enabled"] and present)
    if usable:
        message = ""
    elif not s["su2Enabled"]:
        message = "The SU2 link is off. Install SU2 yourself, set its path in the flow settings and turn the link on."
    elif not path:
        message = "No SU2 path is set."
    else:
        message = "The SU2 program was not found at the configured path."
    return {"enabled": s["su2Enabled"], "path": path, "mpiPath": s["mpiPath"], "ranks": s["su2Ranks"], "present": present, "usable": usable, "message": message, "label": LABEL}


def need_program() -> tuple:
    s = load_settings()
    if not s["su2Enabled"]:
        raise FlowError("SU2 is off. Turn the SU2 link on in the flow settings after installing SU2 yourself.")
    path = s["su2Path"]
    if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
        raise FlowError("The SU2 program was not found at the configured path.")
    return path, s


def oriented(p: np.ndarray, t: np.ndarray) -> np.ndarray:
    a, b, c, d = (p[t[:, i]] for i in range(4))
    vol = np.einsum("ij,ij->i", np.cross(b - a, c - a), d - a)
    out = t.copy()
    flip = vol < 0
    out[flip, 2], out[flip, 3] = t[flip, 3], t[flip, 2]
    return out


def write_mesh(path: str, points: np.ndarray, tets: np.ndarray, markers: dict) -> None:
    t = oriented(points, tets)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("NDIME= 3\nNELEM= %d\n" % len(t))
        np.savetxt(fh, np.column_stack([np.full(len(t), 10), t, np.arange(len(t))]), fmt="%d")
        fh.write("NPOIN= %d\n" % len(points))
        np.savetxt(fh, np.column_stack([points, np.arange(len(points))]), fmt=["%.12e", "%.12e", "%.12e", "%d"])
        fh.write("NMARK= %d\n" % len(markers))
        for name, tris in markers.items():
            fh.write("MARKER_TAG= %s\nMARKER_ELEMS= %d\n" % (name, len(tris)))
            np.savetxt(fh, np.column_stack([np.full(len(tris), 5), tris]), fmt="%d")


def profile_text(name: str, points: np.ndarray, values: np.ndarray, direction: np.ndarray, temperature: float = 293.15) -> str:
    d = direction / np.linalg.norm(direction)
    rows = ["NMARK= 1", "MARKER_TAG= %s" % name, "NROW= %d" % len(points), "NCOL= 8"]
    for p, w in zip(points, values):
        rows.append("%.10e %.10e %.10e %.4f %.10e %.10e %.10e %.10e" % (p[0], p[1], p[2], temperature, w, d[0], d[1], d[2]))
    return "\n".join(rows) + "\n"


def config_text(mesh_file: str, density: float, viscosity: float, speed: float, direction: np.ndarray, inlet: str, outlet: str, walls: list, profile_file: str = "", iterations: int = 4000, residual: float = -12.0, outputs: str = "RESTART_ASCII", extra: dict | None = None) -> str:
    d = direction / np.linalg.norm(direction)
    lines = [
        "SOLVER= INC_NAVIER_STOKES",
        "KIND_TURB_MODEL= NONE",
        "INC_DENSITY_MODEL= CONSTANT",
        "INC_ENERGY_EQUATION= NO",
        "INC_DENSITY_INIT= %.10g" % density,
        "INC_VELOCITY_INIT= ( %.10g, %.10g, %.10g )" % tuple(speed * d),
        "INC_NONDIM= INITIAL_VALUES",
        "VISCOSITY_MODEL= CONSTANT_VISCOSITY",
        "MU_CONSTANT= %.10g" % viscosity,
        "INC_INLET_TYPE= VELOCITY_INLET",
        "MARKER_INLET= ( %s, 293.15, %.10g, %.10g, %.10g, %.10g )" % (inlet, speed, d[0], d[1], d[2]),
        "INC_OUTLET_TYPE= PRESSURE_OUTLET",
        "MARKER_OUTLET= ( %s, 0.0 )" % outlet,
        "MARKER_HEATFLUX= ( %s )" % ", ".join("%s, 0.0" % w for w in walls),
        "MARKER_ANALYZE= ( %s, %s )" % (inlet, outlet),
        "MARKER_PLOTTING= ( %s )" % ", ".join([inlet, outlet] + list(walls)),
        "NUM_METHOD_GRAD= WEIGHTED_LEAST_SQUARES",
        "CONV_NUM_METHOD_FLOW= FDS",
        "MUSCL_FLOW= YES",
        "SLOPE_LIMITER_FLOW= NONE",
        "TIME_DISCRE_FLOW= EULER_IMPLICIT",
        "CFL_NUMBER= 20",
        "LINEAR_SOLVER= FGMRES",
        "LINEAR_SOLVER_PREC= ILU",
        "LINEAR_SOLVER_ERROR= 1E-6",
        "LINEAR_SOLVER_ITER= 10",
        "ITER= %d" % iterations,
        "CONV_FIELD= RMS_PRESSURE",
        "CONV_RESIDUAL_MINVAL= %g" % residual,
        "CONV_STARTITER= 10",
        "MESH_FILENAME= %s" % mesh_file,
        "MESH_FORMAT= SU2",
        "OUTPUT_FILES= ( %s )" % outputs,
        "SCREEN_OUTPUT= ( INNER_ITER, RMS_PRESSURE, RMS_VELOCITY-X )",
        "HISTORY_OUTPUT= ( ITER, RMS_RES )",
        "OUTPUT_WRT_FREQ= 100000",
    ]
    if profile_file:
        lines += ["SPECIFIED_INLET_PROFILE= YES", "INLET_FILENAME= %s" % profile_file]
    if extra and not isinstance(extra, dict):
        raise FlowError("The SU2 settings are a list of names and values.")
    for key, value in (extra or {}).items():
        if key not in TUNABLE:
            raise FlowError("The SU2 setting %s cannot be changed here. Allowed: %s." % (key, ", ".join(sorted(TUNABLE))))
        text = str(value).strip()
        if not text or len(text) > 80 or any(c in text for c in "\n\r\x00%"):
            raise FlowError("The SU2 setting %s has an invalid value." % key)
        if key == "ITER" and not (text.isdigit() and 1 <= int(text) <= LIMITS["iterations"][0]):
            raise FlowError("The SU2 iteration count is a whole number from 1 to %d." % LIMITS["iterations"][0])
        lines = [ln for ln in lines if not ln.startswith(key + "=")] + ["%s= %s" % (key, text)]
    return "\n".join(lines) + "\n"


def run_program(args: list, cwd: str, timeout: float, check=None, log_name: str = "su2.log") -> str:
    check = check or (lambda: None)
    log_path = os.path.join(cwd, log_name)
    env = {k: v for k, v in os.environ.items() if k in ENV_KEEP or k.startswith(("OMPI_", "PMIX_", "LC_"))}
    with open(log_path, "wb") as log:
        try:
            proc = subprocess.Popen(args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, shell=False, env=env)
        except OSError as err:
            raise FlowError("SU2 could not be started: %s" % err)
        started = time.time()
        try:
            while True:
                try:
                    proc.wait(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    pass
                try:
                    check()
                except BaseException:
                    proc.kill()
                    proc.wait()
                    raise
                if time.time() - started > timeout:
                    proc.kill()
                    proc.wait()
                    raise FlowError("SU2 did not finish within %d seconds and was stopped." % int(timeout))
                if os.path.getsize(log_path) > MAX_LOG:
                    proc.kill()
                    proc.wait()
                    raise FlowError("SU2 wrote more than 256 MB of messages and was stopped.")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
    tail = tail_text(log_path)
    if proc.returncode != 0:
        lines = [ln for ln in tail.splitlines() if ln.strip() and "UCX" not in ln][-4:]
        raise FlowError("SU2 stopped with code %d. %s" % (proc.returncode, " ".join(lines)[-400:]))
    return tail


def tail_text(path: str) -> str:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - MAX_TAIL))
            return fh.read(MAX_TAIL).decode("utf-8", "replace")
    except OSError:
        return ""


def read_restart(path: str, count: int) -> dict:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        head = [h.strip().strip('"') for h in next(reader)]
        rows = []
        for i, row in enumerate(reader):
            if i >= count + 1:
                break
            rows.append([float(x) for x in row])
    arr = np.asarray(rows, dtype=float)
    if len(arr) != count:
        raise FlowError("The SU2 result has %d points but the mesh has %d." % (len(arr), count))
    return {h: arr[:, i] for i, h in enumerate(head)}


def history_residual(path: str) -> tuple:
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            head = [h.strip().strip('"') for h in next(reader)]
            last = None
            n = 0
            for row in reader:
                last = row
                n += 1
    except (OSError, StopIteration):
        return None, 0
    if last is None:
        return None, 0
    for key in ("rms[P]", "rms[Pressure]"):
        if key in head:
            try:
                return float(last[head.index(key)]), n
            except ValueError:
                return None, n
    return None, n


def solve(points, tets, markers: dict, inlet: str, outlet: str, walls: list, density: float, viscosity: float, speed: float, direction, profile=None, check=None, runner=None, keep: str = "", extra: dict | None = None) -> dict:
    exe, s = need_program()
    if len(tets) > cap("su2_cells", runner):
        raise FlowError("The mesh has %d cells, above the SU2 limit of %d." % (len(tets), cap("su2_cells", runner)))
    work = tempfile.mkdtemp(prefix="fcsu2_")
    try:
        write_mesh(os.path.join(work, "mesh.su2"), points, tets, markers)
        profile_file = ""
        if profile is not None:
            with open(os.path.join(work, "inlet.dat"), "w", encoding="utf-8") as fh:
                fh.write(profile_text(inlet, *profile))
            profile_file = "inlet.dat"
        cfg = config_text("mesh.su2", density, viscosity, speed, np.asarray(direction, dtype=float), inlet, outlet, walls, profile_file, extra=extra)
        with open(os.path.join(work, "run.cfg"), "w", encoding="utf-8") as fh:
            fh.write(cfg)
        ranks = s["su2Ranks"]
        mpi = s["mpiPath"]
        args = [exe, "run.cfg"]
        if ranks > 1:
            if not mpi or not os.path.isfile(mpi):
                raise FlowError("More than one SU2 process needs the MPI launcher path in the flow settings.")
            args = [mpi, "-n", str(ranks), exe, "run.cfg"]
        tail = run_program(args, work, float(cap("su2_seconds", runner)), check)
        restart = os.path.join(work, "restart.csv")
        if not os.path.isfile(restart):
            raise FlowError("SU2 finished but wrote no result file.")
        fields = read_restart(restart, len(points))
        got = np.stack([fields["x"], fields["y"], fields["z"]], axis=1)
        scale = max(float(np.ptp(points, axis=0).max()), 1e-12)
        if np.abs(got - points).max() > 1e-6 * scale:
            from scipy.spatial import cKDTree

            dist, order = cKDTree(got).query(points)
            if dist.max() > 1e-6 * scale or len(np.unique(order)) != len(points):
                raise FlowError("The SU2 result points do not match the mesh points.")
            fields = {k: v[order] for k, v in fields.items()}
        res, iters = history_residual(os.path.join(work, "history.csv"))
        out = {"fields": fields, "residual": res, "iterations": iters, "log_tail": tail[-2000:]}
        return out
    finally:
        if keep:
            shutil.copytree(work, keep, dirs_exist_ok=True)
        shutil.rmtree(work, ignore_errors=True)
