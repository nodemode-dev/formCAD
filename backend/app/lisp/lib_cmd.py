from app.lisp import bridge
from app.lisp.registry import fn
from app.lisp.types import T


@fn("command", 0)
def f_command(L, *args):
    bridge.run_command(L, list(args))
    return None


@fn("command-s", 0)
def f_command_s(L, *args):
    bridge.run_command(L, list(args))
    return None


@fn("vl-cmdf", 0)
def f_vl_cmdf(L, *args):
    bridge.run_command(L, list(args))
    return T
