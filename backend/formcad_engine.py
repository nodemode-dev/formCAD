import json
import os
import sys

PORT_NAME = "engine.port"


def resource_dir() -> str:
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def selfcheck() -> int:
    info = {"python": sys.version.split()[0]}
    for name in ("fastapi", "uvicorn", "numpy", "ezdxf", "keyring", "httpx"):
        try:
            module = __import__(name)
            info[name] = getattr(module, "__version__", "ok")
        except Exception as exc:
            info[name] = f"missing: {exc}"
    from app import __version__

    info["formcad"] = __version__
    info["dist_bundled"] = os.path.isdir(os.path.join(resource_dir(), "frontend_dist"))
    try:
        import app.main  # noqa: F401
        from app.services import kernel

        record = kernel.record()
        info["app"] = "ok"
        info["kernel_record"] = "ok" if record.get("program") == "formcad-kernel" else "missing"
    except Exception as exc:
        info["app"] = f"failed: {exc!r}"
        print(json.dumps(info))
        return 1
    print(json.dumps(info))
    return 0 if info["kernel_record"] == "ok" else 1


def watch_parent() -> None:
    if os.name != "posix":
        return
    parent = os.getppid()
    if parent <= 1:
        return
    import shutil
    import threading
    import time

    def run() -> None:
        while os.getppid() == parent:
            time.sleep(2)
        unpacked = getattr(sys, "_MEIPASS", "")
        if os.path.basename(unpacked).startswith("_MEI"):
            shutil.rmtree(unpacked, ignore_errors=True)
        os._exit(0)

    threading.Thread(target=run, name="formcad-parent-watch", daemon=True).start()


def run_mcp(argv: list[str]) -> int:
    print("formcad-engine mcp: the MCP server is not part of this build yet.", file=sys.stderr)
    return 2


def announce_port(server, data) -> None:
    import threading
    import time

    def run() -> None:
        for _ in range(600):
            if server.started and server.servers:
                break
            time.sleep(0.1)
        else:
            return
        try:
            port = server.servers[0].sockets[0].getsockname()[1]
            (data / PORT_NAME).write_text(json.dumps({"pid": os.getpid(), "port": port}), encoding="utf-8")
        except (OSError, IndexError):
            return

    threading.Thread(target=run, name="formcad-port-file", daemon=True).start()


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "mcp":
        return run_mcp(sys.argv[2:])
    if "--selfcheck" in sys.argv:
        return selfcheck()
    from app.core import runtime

    runtime.apply_switches(sys.argv[1:])
    from app.core import config

    data = config.data_dir()
    try:
        runtime.claim(data)
    except runtime.AlreadyRunning as err:
        print(err, file=sys.stderr)
        return 2
    watch_parent()
    bundled = os.path.join(resource_dir(), "frontend_dist")
    if os.path.isdir(bundled):
        os.environ.setdefault("FORMCAD_DIST", bundled)
    os.environ.setdefault("FORMCAD_DESKTOP", "1")
    import uvicorn

    from app.main import app as fastapi_app

    port = int(os.environ.get("FORMCAD_PORT", "0") or 0)
    host = os.environ.get("FORMCAD_HOST", "127.0.0.1")
    server = uvicorn.Server(uvicorn.Config(fastapi_app, host=host, port=port, log_level="info"))
    announce_port(server, data)
    try:
        server.run()
    finally:
        try:
            if json.loads((data / PORT_NAME).read_text(encoding="utf-8")).get("pid") == os.getpid():
                (data / PORT_NAME).unlink()
        except (OSError, ValueError, AttributeError):
            pass
        runtime.release(data)
    return 0 if server.started else 3


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    sys.exit(main())
