import ast
import math
import re

NAME = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
PARAM = re.compile(r"^p[0-9]{1,5}$")
FUNCS = {"atan2": 2, "sqrt": 1, "abs": 1, "sin": 1, "cos": 1, "tan": 1}
MAX_LEN = 400


class ExprError(ValueError):
    pass


def _parse(text):
    if not isinstance(text, str) or not text.strip():
        raise ExprError("An expression is a non-empty text.")
    if len(text) > MAX_LEN:
        raise ExprError("An expression is at most %d characters." % MAX_LEN)
    try:
        return ast.parse(text.strip(), mode="eval").body
    except SyntaxError:
        raise ExprError("The expression %r is not valid." % text[:60])


def _ngc(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return repr(float(node.value)) if isinstance(node.value, float) else str(node.value)
    if isinstance(node, ast.Name):
        if PARAM.match(node.id):
            return "#" + node.id[1:]
        if not NAME.match(node.id):
            raise ExprError("The name %s is not allowed." % node.id)
        return "#<_%s>" % node.id
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return ("-" if isinstance(node.op, ast.USub) else "") + _ngc(node.operand)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        op = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}[type(node.op)]
        return "[%s %s %s]" % (_ngc(node.left), op, _ngc(node.right))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCS and not node.keywords:
        if len(node.args) != FUNCS[node.func.id]:
            raise ExprError("%s takes %d arguments." % (node.func.id, FUNCS[node.func.id]))
        a = [_ngc(x) for x in node.args]
        if node.func.id == "atan2":
            return "ATAN[%s]/[%s]" % (a[0], a[1])
        return "%s[%s]" % (node.func.id.upper(), a[0])
    raise ExprError("Only numbers, names, + - * /, atan2, sqrt, abs, sin, cos and tan are allowed.")


def to_ngc(text) -> str:
    return _ngc(_parse(text))


def _eval(node, env):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise ExprError("The name %s has no value yet." % node.id)
        return float(env[node.id])
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, env)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        a, b = _eval(node.left, env), _eval(node.right, env)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if b == 0:
            raise ExprError("Division by zero.")
        return a / b
    if isinstance(node, ast.Call):
        args = [_eval(x, env) for x in node.args]
        n = node.func.id
        if n == "atan2":
            return math.degrees(math.atan2(args[0], args[1]))
        if n == "sqrt":
            if args[0] < 0:
                raise ExprError("Square root of a negative number.")
            return math.sqrt(args[0])
        if n == "abs":
            return abs(args[0])
        f = {"sin": math.sin, "cos": math.cos, "tan": math.tan}[n]
        return f(math.radians(args[0]))
    raise ExprError("Unsupported expression.")


def evaluate(text, env) -> float:
    _ngc(_parse(text))
    return _eval(_parse(text), env)
