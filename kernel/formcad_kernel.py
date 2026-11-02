import json
import os
import sys
from importlib import metadata


def versions() -> dict:
    import OCP

    ocp = str(getattr(OCP, "__version__", "unknown"))
    parts = ocp.split(".")
    occt = ".".join(parts[:3]) if len(parts) >= 3 else ocp
    try:
        builder = metadata.version("build123d")
    except metadata.PackageNotFoundError:
        builder = "unknown"
    return {"occt": occt, "ocp": ocp, "build123d": builder, "python": sys.version.split()[0]}


def hello(_params: dict) -> dict:
    try:
        out = versions()
    except Exception as err:
        raise RuntimeError(f"The OpenCascade bindings could not be loaded ({err}).") from err
    out["units"] = "mm"
    out["methods"] = sorted(METHODS)
    out["protocol"] = 2
    return out


METHODS = {"hello": hello}

OUT = sys.stdout


def isolate_stdout() -> None:
    global OUT
    try:
        saved = os.dup(1)
        OUT = os.fdopen(saved, "w", encoding="utf-8", buffering=1)
        os.dup2(2, 1)
    except OSError:
        OUT = sys.stdout


def load_operations() -> None:
    try:
        from OCP.Message import Message

        printers = Message.DefaultMessenger_s().Printers()
        for printer in list(printers):
            Message.DefaultMessenger_s().RemovePrinter(printer)
    except Exception:
        pass
    try:
        import kernel_io
        import kernel_ops
        import kernel_props
    except Exception as err:
        failure = str(err)

        def unavailable(_params):
            raise RuntimeError("The modelling operations could not be loaded (%s)." % failure)

        METHODS["primitive"] = unavailable
        return
    for module in (kernel_ops, kernel_io, kernel_props):
        METHODS.update(module.METHODS)


def reply(payload: dict) -> None:
    OUT.write(json.dumps(payload) + "\n")
    OUT.flush()


def serve() -> int:
    isolate_stdout()
    load_operations()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            ident = request.get("id")
            method = request.get("method")
        except (ValueError, AttributeError):
            reply({"id": None, "error": {"message": "The request is not a JSON object."}})
            continue
        if method == "shutdown":
            reply({"id": ident, "result": {"ok": True}})
            return 0
        handler = METHODS.get(method)
        if handler is None:
            reply({"id": ident, "error": {"message": f"Unknown method {method}."}})
            continue
        try:
            reply({"id": ident, "result": handler(request.get("params") or {})})
        except Exception as err:
            reply({"id": ident, "error": {"message": str(err)}})
    return 0


if __name__ == "__main__":
    sys.exit(serve())
