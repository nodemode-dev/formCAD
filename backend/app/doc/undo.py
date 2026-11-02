MAX_STEPS = 2000
MAX_MARKS = 1000


class Tx:
    def __init__(self, label: str):
        self.label = label
        self.before: dict = {}
        self.live = False

    def note(self, key, reader) -> None:
        if key not in self.before:
            self.before[key] = reader()


class Step:
    def __init__(self, label: str, before: dict, state_before: int, state_after: int):
        self.label = label
        self.before = before
        self.state_before = state_before
        self.state_after = state_after


class UndoManager:
    def __init__(self):
        self.steps: list = []
        self.redo_stack: list = []
        self.marks: list = []
        self.control = "all"
        self.group = None
        self.auto = True
        self.combine_view = True
        self.combine_layer = True

    def bits(self) -> int:
        b = 0
        if self.control != "none":
            b |= 1
        if self.control == "one":
            b |= 2
        if self.auto:
            b |= 4
        if self.group is not None:
            b |= 8
        if self.combine_view:
            b |= 16
        if self.combine_layer:
            b |= 32
        return b

    def reachable_marks(self) -> int:
        return len([m for m in self.marks if m <= len(self.steps)])

    def record(self, step: Step) -> None:
        if self.control == "none":
            return
        if self.group is not None:
            for k, v in step.before.items():
                self.group.before.setdefault(k, v)
            if self.group.state_before is None:
                self.group.state_before = step.state_before
            self.group.state_after = step.state_after
            self.redo_stack.clear()
            return
        self.redo_stack.clear()
        self.marks = [m for m in self.marks if m <= len(self.steps)]
        self.steps.append(step)
        if self.control == "one":
            self.steps = [step]
            self.marks = []
        drop = len(self.steps) - MAX_STEPS
        if drop > 0:
            del self.steps[:drop]
            self.marks = [m - drop for m in self.marks if m - drop >= 0]

    def begin_group(self) -> None:
        if self.group is not None:
            self.end_group()
        self.group = Step("Group", {}, None, None)

    def end_group(self) -> bool:
        g = self.group
        if g is None:
            return False
        self.group = None
        if g.before:
            self.marks = [m for m in self.marks if m <= len(self.steps)]
            self.steps.append(g)
            drop = len(self.steps) - MAX_STEPS
            if drop > 0:
                del self.steps[:drop]
                self.marks = [m - drop for m in self.marks if m - drop >= 0]
        return True

    def add_mark(self) -> bool:
        if len(self.marks) >= MAX_MARKS:
            return False
        self.marks.append(len(self.steps))
        return True

    def set_control(self, mode: str) -> None:
        if mode != "all":
            self.group = None
            self.marks = []
            self.redo_stack.clear()
        self.control = mode
        if mode == "none":
            self.steps.clear()
        elif mode == "one" and len(self.steps) > 1:
            self.steps = self.steps[-1:]

    def pop_undo(self, n: int) -> list:
        self.end_group()
        out = []
        for _ in range(max(n, 0)):
            if not self.steps:
                break
            s = self.steps.pop()
            self.redo_stack.append(s)
            out.append(s)
        return out

    def pop_redo(self, n: int) -> list:
        out = []
        for _ in range(max(n, 0)):
            if not self.redo_stack:
                break
            s = self.redo_stack.pop()
            self.steps.append(s)
            out.append(s)
        return out

    def undo_to_mark(self):
        valid = [m for m in self.marks if m <= len(self.steps)]
        if not valid:
            return None
        target = valid[-1]
        self.marks = [m for m in self.marks if m < target]
        return len(self.steps) - target
