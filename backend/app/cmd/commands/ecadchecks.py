from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.ecad import erc, store as estore
from app.ecad.store import EcadError
from app.pcb import drc, jobs, store as pstore
from app.pcb.jobs import PcbError

GROUP = "solids"


def schematic_check(ctx):
    try:
        res = erc.run(estore.header(ctx.d))
    except EcadError as err:
        raise CommandError(str(err))
    return res


def board_check(ctx):
    try:
        with jobs.activity(ctx.doc.id, "drc") as act:
            return drc.run(pstore.header(ctx.d), act)
    except PcbError as err:
        raise CommandError(str(err))


def erc_line(res):
    s = res["summary"]
    return "Schematic check: %d errors, %d warnings." % (s["error"], s["warning"])


def drc_line(res):
    return "Board check %s: %d errors, %d warnings (%s rules)." % ("passed" if res["passed"] else "failed", res["errors"], res["warnings"], res["profile"])


@command("ecaderc", group=GROUP, label="Check Schematic", description="Run the electrical rule check on the schematic and report the findings.", menu="Electronics > Check Schematic", undoable=False)
def ecaderc(ctx):
    ctx.say(erc_line(schematic_check(ctx)))


@executes("ecaderc")
def ecaderc_exec(ctx, args):
    return schematic_check(ctx)


@command("pcbdrc", group=GROUP, label="Check Board", description="Run the design rule check on the board and report the errors and warnings.", menu="Electronics > Check Board", undoable=False)
def pcbdrc(ctx):
    ctx.say(drc_line(board_check(ctx)))


@executes("pcbdrc")
def pcbdrc_exec(ctx, args):
    return board_check(ctx)
