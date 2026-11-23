import copy


class Builder:
    def __init__(self, name: str = "test"):
        self.name = name
        self.nodes: list = []
        self.wires: list = []

    def node(self, nid: str, kind: str, ins: dict | None = None, outs=(), nickname: str = "", settings: dict | None = None) -> str:
        ports_in = []
        for pname, value in (ins or {}).items():
            port = {"id": "%s_i_%s" % (nid, pname), "name": pname}
            if value is not None:
                items = value if isinstance(value, list) else [value]
                port["persistent"] = {"type": "any", "tree": {"{0}": items}}
            ports_in.append(port)
        ports_out = [{"id": "%s_o_%s" % (nid, p), "name": p} for p in outs]
        rec = {"id": nid, "type": kind, "nickname": nickname, "x": 0.0, "y": 0.0, "ports": {"in": ports_in, "out": ports_out}}
        if settings is not None:
            rec["settings"] = settings
        self.nodes.append(rec)
        return nid

    def wire(self, src: str, out: str, dst: str, inp: str) -> None:
        self.wires.append({"id": "w%d" % (len(self.wires) + 1), "from": "%s_o_%s" % (src, out), "to": "%s_i_%s" % (dst, inp), "order": 0})

    def slider(self, nid: str, name: str, value, lo=-1000, hi=1000, integer=False) -> str:
        return self.node(nid, "input.slider", {"value": value}, ["value"], nickname=name, settings={"min": lo, "max": hi, "step": 0, "integer": integer, "decimals": 3})

    def output(self, nid: str, name: str, src: str, port: str) -> str:
        self.node(nid, "io.output", {"value": None}, ["value"], settings={"name": name})
        self.wire(src, port, nid, "value")
        return nid

    def definition(self) -> dict:
        return {
            "format": "formcad.graph",
            "version": "1.0.0",
            "min_reader": "1.0.0",
            "name": self.name,
            "settings": {"seed": 0, "tolerance": 0.001, "units": "mm", "time_budget": 60.0, "enabled": True},
            "nodes": copy.deepcopy(self.nodes),
            "wires": copy.deepcopy(self.wires),
        }


def values(result: dict, name: str) -> list:
    tree = result["outputs"][name]["tree"]
    out = []
    for path in tree:
        out.extend(tree[path])
    return out
