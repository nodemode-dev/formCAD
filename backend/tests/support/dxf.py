from pathlib import Path


def pairs(text: str) -> list:
    rows = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out = []
    for i in range(0, len(rows) - 1, 2):
        code = rows[i].strip()
        if not code.lstrip("-").isdigit():
            raise ValueError("line %d is not a group code: %r" % (i + 1, rows[i]))
        out.append((int(code), rows[i + 1].strip()))
    return out


class Record:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.codes: list = []
        self.children: list = []

    def all(self, code: int) -> list:
        return [v for c, v in self.codes if c == code]

    def text(self, code: int, default: str = "") -> str:
        found = self.all(code)
        return found[0] if found else default

    def number(self, code: int, default: float = 0.0) -> float:
        found = self.all(code)
        return float(found[0]) if found else default

    def point(self, base: int = 10) -> tuple:
        return self.number(base), self.number(base + 10), self.number(base + 20)

    def points(self, base: int = 10) -> list:
        xs = [float(v) for v in self.all(base)]
        ys = [float(v) for v in self.all(base + 10)]
        return list(zip(xs, ys))

    @property
    def layer(self) -> str:
        return self.text(8, "0")


class Dxf:
    def __init__(self, text: str) -> None:
        self.sections: dict = {}
        self.header: dict = {}
        name = None
        current = None
        waiting = False
        variable = None
        for code, value in pairs(text):
            if code == 0 and value == "SECTION":
                waiting = True
                continue
            if waiting and code == 2:
                name = value
                self.sections[name] = []
                waiting = False
                current = None
                continue
            if code == 0 and value == "ENDSEC":
                name = None
                current = None
                continue
            if code == 0 and value == "EOF":
                break
            if name is None:
                continue
            if name == "HEADER":
                if code == 9:
                    variable = value
                    self.header[variable] = []
                elif variable is not None:
                    self.header[variable].append((code, value))
                continue
            if code == 0:
                current = Record(value)
                self.sections[name].append(current)
            elif current is not None:
                current.codes.append((code, value))

    @classmethod
    def read(cls, path) -> "Dxf":
        raw = Path(path).read_bytes()
        try:
            return cls(raw.decode("utf-8"))
        except UnicodeDecodeError:
            return cls(raw.decode("cp1252"))

    def entities(self, kind: str | None = None) -> list:
        found = self.sections.get("ENTITIES", [])
        return [r for r in found if kind is None or r.kind == kind.upper()]

    def kinds(self) -> dict:
        out: dict = {}
        for r in self.entities():
            out[r.kind] = out.get(r.kind, 0) + 1
        return out

    def table(self, name: str) -> list:
        out = []
        inside = False
        for r in self.sections.get("TABLES", []):
            if r.kind == "TABLE":
                inside = r.text(2).upper() == name.upper()
            elif r.kind == "ENDTAB":
                inside = False
            elif inside and r.kind == name.upper():
                out.append(r)
        return out

    def layers(self) -> list:
        return [r.text(2) for r in self.table("LAYER")]

    def blocks(self) -> list:
        return [r.text(2) for r in self.sections.get("BLOCKS", []) if r.kind == "BLOCK"]

    def variable(self, name: str, default=None):
        found = self.header.get(name if name.startswith("$") else "$" + name)
        if not found:
            return default
        return found[0][1] if len(found) == 1 else [v for _, v in found]
