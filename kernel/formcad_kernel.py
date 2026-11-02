import json
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
        return versions()
    except Exception as err:
        raise RuntimeError(f"The OpenCascade bindings could not be loaded ({err}).") from err


METHODS = {"hello": hello}


def reply(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def serve() -> int:
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
