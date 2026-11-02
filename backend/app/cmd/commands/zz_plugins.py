from app.automation import plugins
from app.cmd.context import CommandError
from app.cmd.registry import command, executes


@command("plugins", aliases=("pluginlist",), group="automation", label="Plugins", description="List the installed plugins and whether each is enabled.", menu="Tools > Plugins", undoable=False, repeatable=False)
def plugins_cmd(ctx):
    for item in plugins.discover():
        ctx.say("%s %s: %s" % (item["id"], item["version"], item["state"]))


@executes("plugins")
def plugins_exec(ctx, args):
    items = plugins.discover()
    for item in items:
        ctx.say("%s %s: %s" % (item["id"], item["version"], item["state"]))
    return {"plugins": [{"id": i["id"], "name": i["name"], "version": i["version"], "state": i["state"], "tier": i["tier"], "commands": i["commands"]} for i in items]}


@command("pluginenable", group="automation", label="Enable Plugin", description="Turn a plugin on after checking its file hashes, then load it.", menu="Tools > Plugins > Enable", undoable=False, repeatable=False)
def enable_cmd(ctx):
    r = yield ctx.word("Plugin id")
    if r.kind == "text":
        _enable(ctx, str(r.value), True)


@executes("pluginenable")
def enable_exec(ctx, args):
    return _enable(ctx, str(args.get("id", "")), bool(args.get("enabled", True)), str(args.get("manifestSha256", "")))


def _enable(ctx, plugin_id, enabled, digest=""):
    try:
        item = plugins.set_enabled(plugin_id, enabled, digest)
    except plugins.PluginError as err:
        raise CommandError(str(err))
    ctx.say("Plugin %s is %s." % (plugin_id, item["state"]))
    return {"id": plugin_id, "state": item["state"], "commands": item["commands"]}


def _startup():
    try:
        plugins.load_enabled()
    except Exception:
        pass


_startup()
