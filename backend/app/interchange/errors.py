class InterchangeError(Exception):
    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.message = message
        self.code = code


class Report:
    def __init__(self):
        self.notes: list = []
        self.counts: dict = {}
        self.dropped: dict = {}
        self.converted: dict = {}
        self.warnings: list = []

    def count(self, what: str, n: int = 1) -> None:
        self.counts[what] = self.counts.get(what, 0) + n

    def drop(self, what: str, n: int = 1) -> None:
        self.dropped[what] = self.dropped.get(what, 0) + n

    def convert(self, what: str, n: int = 1) -> None:
        self.converted[what] = self.converted.get(what, 0) + n

    def note(self, text: str) -> None:
        if text not in self.notes and len(self.notes) < 200:
            self.notes.append(text)

    def warn(self, text: str) -> None:
        if text not in self.warnings and len(self.warnings) < 200:
            self.warnings.append(text)

    def to_dict(self) -> dict:
        return {"notes": list(self.notes), "warnings": list(self.warnings), "counts": dict(self.counts), "dropped": dict(self.dropped), "converted": dict(self.converted)}

    def summary(self) -> str:
        parts = []
        if self.dropped:
            parts.append("not saved: " + ", ".join("%d %s" % (n, k) for k, n in sorted(self.dropped.items())))
        if self.converted:
            parts.append("converted: " + ", ".join("%d %s" % (n, k) for k, n in sorted(self.converted.items())))
        parts.extend(self.warnings[:5])
        return "; ".join(parts)
