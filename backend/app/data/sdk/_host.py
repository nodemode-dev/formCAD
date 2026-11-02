import hashlib
import json
import os
import sys
import sysconfig
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
LIMITS = json.loads(os.environ.get("FORMCAD_LIMITS") or "{}")
GRANTS = json.loads(os.environ.get("FORMCAD_GRANTS") or "{}")
ENGINE_PORT = int(os.environ.get("FORMCAD_PORT") or 0)
WORKDIR = os.path.realpath(os.getcwd())
LOCAL = {"127.0.0.1", "::1", "localhost"}
SPAWNS = {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork", "os.forkpty", "pty.spawn", "os.startfile"}
MUTATIONS = {"os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.truncate", "os.chmod", "os.chown", "os.symlink", "os.link", "shutil.rmtree", "shutil.copyfile", "shutil.move", "os.utime", "os.mkfifo", "os.mknod"}
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def _real(path):
    try:
        return os.path.realpath(os.fsdecode(path))
    except (TypeError, ValueError):
        return ""


def _roots(values):
    return [_real(v) for v in values if v]


def _inside(path, roots):
    for root in roots:
        if path == root or path.startswith(root.rstrip(os.sep) + os.sep):
            return True
    return False


def _read_roots():
    paths = set(sysconfig.get_paths().values())
    paths.update([sys.prefix, sys.base_prefix, sys.exec_prefix, HERE, WORKDIR, getattr(sys, "_MEIPASS", "")])
    paths.update(os.path.dirname(p) for p in sys.path if p)
    paths.update(p for p in sys.path if p)
    paths.update(["/dev", "/etc/localtime", "/usr/share/zoneinfo", "/usr/lib", "/lib", "/lib64", "/usr/local/lib", "/etc/ssl", "/etc/python3", os.environ.get("SystemRoot", "")])
    paths.update(GRANTS.get("files", []))
    return _roots(paths)


def _write_roots():
    paths = [WORKDIR, "/dev/null", "/dev/tty"] + list(GRANTS.get("files", []))
    return _roots(paths)


READ_ROOTS = []
WRITE_ROOTS = []


def _writes(mode, flags):
    if isinstance(flags, int) and flags & WRITE_FLAGS:
        return True
    return isinstance(mode, str) and any(c in mode for c in "wax+")


def _deny(what):
    raise PermissionError("FormCAD blocked this macro from %s. Grant it to the macro in FormCAD if it is intended." % what)


def _readable(path, what):
    if GRANTS.get("anyRead") or not isinstance(path, (str, bytes, os.PathLike)):
        return
    real = _real(path)
    if real and (real.startswith("/proc") or real.startswith("/sys") or not _inside(real, READ_ROOTS)):
        _deny("%s %s" % (what, real))


def _stat(path, *args, **kwargs):
    _readable(path, "inspecting")
    return _STAT(path, *args, **kwargs)


_STAT = os.stat


def _hook(event, args):
    if event in ("os.listdir", "os.scandir"):
        _readable(args[0] if args else None, "listing")
        return
    if event == "open":
        path = _real(args[0]) if args and isinstance(args[0], (str, bytes, os.PathLike)) else ""
        if not path:
            return
        if path.startswith("/proc") or path.startswith("/sys"):
            _deny("reading %s" % path)
        if _writes(args[1] if len(args) > 1 else None, args[2] if len(args) > 2 else None):
            if not _inside(path, WRITE_ROOTS):
                _deny("writing %s" % path)
        elif not GRANTS.get("anyRead") and not _inside(path, READ_ROOTS):
            _deny("reading %s" % path)
        return
    if event in MUTATIONS:
        for item in args[:2]:
            if isinstance(item, (str, bytes, os.PathLike)):
                path = _real(item)
                if path and not _inside(path, WRITE_ROOTS):
                    _deny("changing %s" % path)
        return
    if event in SPAWNS:
        if not GRANTS.get("subprocess"):
            _deny("starting another program")
        return
    if event == "import" and args and args[0] in ("ctypes", "_ctypes") and not GRANTS.get("native"):
        _deny("loading native code")
    if event in ("ctypes.dlopen", "ctypes.dlsym", "ctypes.call_function") and not GRANTS.get("native"):
        _deny("loading native code")
    if event in ("socket.connect", "socket.sendto", "socket.bind", "socket.getaddrinfo", "socket.gethostbyname"):
        if GRANTS.get("network"):
            return
        target = args[1] if len(args) > 1 else None
        if event in ("socket.gethostbyname", "socket.getaddrinfo"):
            host = target if isinstance(target, str) else (args[0] if args and isinstance(args[0], str) else "")
            if str(host).lower() in LOCAL:
                return
            _deny("looking up %s" % host)
        if isinstance(target, tuple) and target and str(target[0]) in LOCAL and (not ENGINE_PORT or event == "socket.bind" or target[1] == ENGINE_PORT):
            if event != "socket.bind":
                return
        _deny("using the network")


def _limits():
    if os.name != "posix":
        return
    try:
        import resource
    except ImportError:
        return

    def put(name, value):
        if value is None:
            return
        try:
            limit = getattr(resource, name)
            soft, hard = resource.getrlimit(limit)
            value = int(value)
            if hard != resource.RLIM_INFINITY:
                value = min(value, hard)
            resource.setrlimit(limit, (value, value if hard == resource.RLIM_INFINITY else hard))
        except (ValueError, OSError, AttributeError):
            pass

    put("RLIMIT_CPU", LIMITS.get("cpuSeconds"))
    put("RLIMIT_AS", LIMITS.get("memoryBytes"))
    put("RLIMIT_FSIZE", LIMITS.get("fileBytes"))
    put("RLIMIT_NOFILE", LIMITS.get("openFiles"))
    put("RLIMIT_CORE", 0)
    if not GRANTS.get("subprocess") and LIMITS.get("processes") is not None:
        put("RLIMIT_NPROC", LIMITS.get("processes"))


def main():
    if len(sys.argv) < 2:
        sys.stderr.write("usage: _host.py macro.py\n")
        return 2
    macro = os.path.realpath(sys.argv[1])
    name = os.environ.get("FORMCAD_MACRO_NAME") or macro
    want = os.environ.get("FORMCAD_MACRO_SHA256", "")
    with open(macro, "rb") as fh:
        data = fh.read()
    if not want or hashlib.sha256(data).hexdigest() != want:
        sys.stderr.write("The macro does not match the reviewed hash; it was not run.\n")
        return 3
    for key in ("FORMCAD_MACRO_NAME", "FORMCAD_MACRO_SHA256"):
        os.environ.pop(key, None)
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    READ_ROOTS.extend(_read_roots())
    WRITE_ROOTS.extend(_write_roots())
    _limits()
    os.stat = _stat
    sys.addaudithook(_hook)
    sys.argv = [name]
    try:
        code = compile(data, name, "exec")
        scope = {"__name__": "__main__", "__file__": name, "__builtins__": __builtins__}
        exec(code, scope)
    except SystemExit as err:
        code = err.code
        sys.stdout.flush()
        return code if isinstance(code, int) else (0 if code is None else 1)
    except BaseException:
        traceback.print_exc()
        return 1
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
