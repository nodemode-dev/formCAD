import math
import random

from app.calc import engine as cal
from app.graph.nodes.common import NodeError, NodeWarning, P, T, add
from app.graph.values import Domain, Point3

CAT = "Maths"
NUM = "number"


def op2(type_id, guid, name, nick, fn, text, da=0.0, db=0.0, group="Operators", kind=NUM, out=NUM, ka=None, kb=None):
    def solve(ctx, a, b):
        return fn(a, b)

    add(type_id, guid, name, nick, CAT, group, [P("a", ka or kind, "item", da, "A", "First value."), P("b", kb or kind, "item", db, "B", "Second value.")], [P("result", out, "item", None, "R", "The result.")], solve=solve, description=text)


def op1(type_id, guid, name, nick, fn, text, group="Operators", kind=NUM, out=NUM, default=0.0):
    def solve(ctx, a):
        return fn(a)

    add(type_id, guid, name, nick, CAT, group, [P("value", kind, "item", default, "X", "The value.")], [P("result", out, "item", None, "R", "The result.")], solve=solve, description=text)


def divide(a, b):
    if b == 0:
        raise NodeWarning("Division by zero.", "DIV_ZERO", "b")
    return a / b


def modulo(a, b):
    if b == 0:
        raise NodeWarning("Modulo by zero.", "DIV_ZERO", "b")
    return a - b * math.floor(a / b)


def power(a, b):
    try:
        r = a ** b
    except ZeroDivisionError:
        raise NodeWarning("Zero cannot be raised to a negative power.", "POWER", "a")
    except OverflowError:
        raise NodeWarning("The result is too large.", "OVERFLOW", "a")
    if isinstance(r, complex):
        raise NodeWarning("A negative number has no real fractional power.", "POWER", "a")
    return r


def need(ok, text, code="DOMAIN"):
    if not ok:
        raise NodeWarning(text, code, "value")


def f_sqrt(a):
    need(a >= 0, "The square root of a negative number is not real.")
    return math.sqrt(a)


def f_ln(a):
    need(a > 0, "The logarithm needs a positive number.")
    return math.log(a)


def f_log(a):
    need(a > 0, "The logarithm needs a positive number.")
    return math.log10(a)


def f_exp(a):
    try:
        return math.exp(a)
    except OverflowError:
        raise NodeWarning("The result is too large.", "OVERFLOW", "value")


def f_asin(a):
    need(-1.0 <= a <= 1.0, "The arc sine needs a value from -1 to 1.")
    return math.asin(a)


def f_acos(a):
    need(-1.0 <= a <= 1.0, "The arc cosine needs a value from -1 to 1.")
    return math.acos(a)


op2("math.add", "2fca7fa8-5910-4fa9-b13a-deda5db8a3b0", "Add", "A+B", lambda a, b: a + b, "Sum of two numbers.")
op2("math.subtract", "cedbbba7-9e7d-4daa-9330-1ef947fbe127", "Subtract", "A-B", lambda a, b: a - b, "Difference of two numbers.")
op2("math.multiply", "974dae3f-33a8-4cf3-af96-649ed578443d", "Multiply", "A*B", lambda a, b: a * b, "Product of two numbers.", 1.0, 1.0)
op2("math.divide", "b72f912c-a78f-4d30-9a1c-80649283f1ab", "Divide", "A/B", divide, "Quotient of two numbers; dividing by zero gives a warning and a null.", 1.0, 1.0)
op2("math.modulo", "9243fd4a-d8fc-4c3f-9dc6-4dbabbe3309a", "Modulo", "A%B", modulo, "Remainder of a division, with the sign of the divisor.", 0.0, 1.0)
op2("math.power", "ec2d01b3-9859-472f-bc5d-a8cc006aebd3", "Power", "A^B", power, "A raised to the power B.", 0.0, 1.0)
op1("math.negate", "f92f23c6-1fd1-400c-9105-1d099a255cce", "Negate", "Neg", lambda a: -a, "Changes the sign of a number.")
op1("math.abs", "66208532-d785-4d70-8b36-40cffe498fa6", "Absolute", "Abs", abs, "The size of a number without its sign.")
op2("math.min", "1d22cd6d-1594-4e0a-9154-6b3f3356a3c5", "Minimum", "Min", min, "The smaller of two numbers.")
op2("math.max", "e750dd3b-b9a2-421b-b5fb-96d339c59ef5", "Maximum", "Max", max, "The larger of two numbers.")
op1("math.sqrt", "7e0c7eda-0d67-4d88-b1c6-7fcc3eee2d16", "Square Root", "Sqrt", f_sqrt, "The non-negative square root.")
op1("math.square", "28b5c673-f966-4c86-bb93-f75c02462f2c", "Square", "Sqr", lambda a: a * a, "A number times itself.")
op1("math.exp", "ae72debb-0a5f-4bf1-be38-d01d128b5cf9", "Exponential", "Exp", f_exp, "e raised to a number.")
op1("math.ln", "ae966492-8a80-412f-840d-478cfd51e208", "Natural Log", "Ln", f_ln, "The natural logarithm.", default=1.0)
op1("math.log", "eaee11ed-0aa5-4fc9-9dbd-9fa3245d1e11", "Log Base 10", "Log", f_log, "The base 10 logarithm.", default=1.0)


def rounded(a, d):
    f = 10.0 ** int(d)
    return math.copysign(math.floor(abs(a) * f + 0.5), a) / f


add("math.round", "857b3642-f101-4bfd-9476-e7c7a4eb5fb1", "Round", "Round", CAT, "Rounding", [P("value", NUM, "item", 0.0, "X", "The number."), P("decimals", "integer", "item", 0, "D", "Decimal places to keep.")], [P("result", NUM, "item", None, "R", "The rounded number.")], solve=lambda ctx, a, d: rounded(a, d), description="Rounds to the nearest value, halves away from zero.")
op1("math.floor", "14dc5f0d-75b7-402f-99ee-6b42dd272278", "Floor", "Floor", lambda a: float(math.floor(a)), "The largest whole number not above the value.", group="Rounding")
op1("math.ceiling", "6f41d907-07a5-4de3-99b8-599f158b6b58", "Ceiling", "Ceil", lambda a: float(math.ceil(a)), "The smallest whole number not below the value.", group="Rounding")
op1("math.truncate", "9f8743ac-4781-4367-9809-61ceefa8382e", "Truncate", "Trunc", lambda a: float(math.trunc(a)), "The value with its fraction cut off.", group="Rounding")


def clamp(ctx, v, lo, hi):
    if lo > hi:
        raise NodeWarning("The minimum is larger than the maximum.", "CLAMP_RANGE", "min")
    return min(max(v, lo), hi)


add("math.clamp", "7dc4f933-7e39-4b23-84db-05fbbd572fa3", "Clamp", "Clamp", CAT, "Operators", [P("value", NUM, "item", 0.0, "X", "The number."), P("min", NUM, "item", 0.0, "Lo", "Lower limit."), P("max", NUM, "item", 1.0, "Hi", "Upper limit.")], [P("result", NUM, "item", None, "R", "The limited number.")], solve=clamp, description="Limits a number to a range.")
add("math.interpolate", "ae4b7f2d-a64e-439f-99f2-4d79771c4cec", "Interpolate", "Lerp", CAT, "Operators", [P("a", NUM, "item", 0.0, "A", "Value at t = 0."), P("b", NUM, "item", 1.0, "B", "Value at t = 1."), P("t", NUM, "item", 0.5, "T", "Blend factor.")], [P("result", NUM, "item", None, "R", "The blended value.")], solve=lambda ctx, a, b, t: a + (b - a) * t, description="Linear blend between two numbers.")


def equals(ctx, a, b, tol):
    return abs(a - b) <= abs(tol)


add("math.equals", "6a013f0a-5dc8-458a-bb7a-a22f3d16dc9a", "Equals", "Eq", CAT, "Compare", [P("a", NUM, "item", 0.0, "A", "First number."), P("b", NUM, "item", 0.0, "B", "Second number."), P("tolerance", NUM, "item", 1e-9, "T", "Largest difference still counted as equal.")], [P("result", "boolean", "item", None, "R", "True when equal within the tolerance.")], solve=equals, description="Tests two numbers for equality within a tolerance.")
op2("math.larger", "93bc98e2-8b03-40f5-b8fb-7ce4c401d597", "Larger Than", "A>B", lambda a, b: a > b, "True when A is larger than B.", group="Compare", out="boolean")
op2("math.smaller", "06994d91-797f-4d8a-a59e-6fdd94d9eeb2", "Smaller Than", "A<B", lambda a, b: a < b, "True when A is smaller than B.", group="Compare", out="boolean")
op2("math.larger_equal", "74256f95-74c7-407b-96b0-b1d1a504c762", "Larger Or Equal", "A>=B", lambda a, b: a >= b, "True when A is not smaller than B.", group="Compare", out="boolean")
op2("math.smaller_equal", "b386aff3-f548-4780-878e-051f98e447b6", "Smaller Or Equal", "A<=B", lambda a, b: a <= b, "True when A is not larger than B.", group="Compare", out="boolean")
op2("math.and", "4898965e-5d09-4241-9c17-f71a401e1bb7", "And", "And", lambda a, b: bool(a) and bool(b), "True when both are true.", False, False, "Logic", "boolean", "boolean")
op2("math.or", "1447c9c5-0ea7-4796-9af8-9da47b98807b", "Or", "Or", lambda a, b: bool(a) or bool(b), "True when either is true.", False, False, "Logic", "boolean", "boolean")
op2("math.xor", "92c72fe6-3507-42b4-9930-e2b35762e256", "Exclusive Or", "Xor", lambda a, b: bool(a) != bool(b), "True when exactly one is true.", False, False, "Logic", "boolean", "boolean")
op1("math.not", "681f8045-6432-4439-b6b7-0f439ba985dd", "Not", "Not", lambda a: not a, "Flips true and false.", group="Logic", kind="boolean", out="boolean", default=False)

op1("math.sin", "7a7b019f-8996-491b-a3ef-4e0b2caffd54", "Sine", "Sin", math.sin, "Sine of an angle in radians.", group="Trig")
op1("math.cos", "9aded9d5-d209-42e3-a960-391e256428e1", "Cosine", "Cos", math.cos, "Cosine of an angle in radians.", group="Trig")
op1("math.tan", "5de01eab-6341-42ba-9ba8-35d760a41924", "Tangent", "Tan", math.tan, "Tangent of an angle in radians.", group="Trig")
op1("math.asin", "3c3a4528-14fc-4180-8829-6cbbba6bdc75", "Arc Sine", "Asin", f_asin, "Angle in radians whose sine is the value.", group="Trig")
op1("math.acos", "8067dcbf-9290-4bb3-8e46-6737c4dc461c", "Arc Cosine", "Acos", f_acos, "Angle in radians whose cosine is the value.", group="Trig")
op1("math.atan", "33dbf0af-fdda-41cc-b57b-344d5d8714a7", "Arc Tangent", "Atan", math.atan, "Angle in radians whose tangent is the value.", group="Trig")
op2("math.atan2", "3bb728b2-a58c-4d82-9aa2-0fbee126bb7e", "Arc Tangent 2", "Atan2", lambda y, x: math.atan2(y, x), "Angle in radians of the direction (x, y), from -pi to pi.", group="Trig")
op1("math.radians", "6e0d6bdc-d121-4e8b-8a26-175c87476d87", "To Radians", "Rad", math.radians, "Converts degrees to radians.", group="Trig")
op1("math.degrees", "8bb71292-1ffd-4546-86d2-886ef5ef2910", "To Degrees", "Deg", math.degrees, "Converts radians to degrees.", group="Trig")


def expression(ctx, x, y, z, w, text):
    names = {k: v for k, v in (("x", x), ("y", y), ("z", z), ("w", w)) if v is not None}
    try:
        r = cal.evaluate(text if text else "x", names)
    except cal.CalcError as err:
        raise NodeError(str(err), "EXPRESSION", "expression")
    if cal.is_vec(r):
        return Point3(r[0], r[1], 0.0)
    return r


add("math.expression", "6e44f486-c9f4-4a80-bdaf-cc8f41698c47", "Expression", "Expr", CAT, "Script", [P("x", NUM, "item", None, "x", "Variable x.", True), P("y", NUM, "item", None, "y", "Variable y.", True), P("z", NUM, "item", None, "z", "Variable z.", True), P("w", NUM, "item", None, "w", "Variable w.", True), P("expression", "text", "item", "x", "F", "The formula; angles in sin, cos and tan are in degrees.")], [P("result", "any", "item", None, "R", "The value of the formula.")], solve=expression, description="Evaluates one formula over the variables x, y, z and w with the built in calculator; no code runs.")


add("math.domain", "b356a22a-a953-4be3-83ca-340e07aff865", "Construct Domain", "Dom", CAT, "Domain", [P("start", NUM, "item", 0.0, "S", "Start of the interval."), P("end", NUM, "item", 1.0, "E", "End of the interval.")], [P("domain", "domain", "item", None, "D", "The interval.")], solve=lambda ctx, s, e: Domain(s, e), description="Builds an interval from two numbers.")
add("math.domain_parts", "53c5749c-a508-4037-8b66-a33582208a11", "Deconstruct Domain", "DDom", CAT, "Domain", [P("domain", "domain", "item", None, "D", "The interval.")], [P("start", NUM, "item", None, "S", "Start."), P("end", NUM, "item", None, "E", "End."), P("length", NUM, "item", None, "L", "End minus start."), P("mid", NUM, "item", None, "M", "Midpoint.")], solve=lambda ctx, d: (d.t0, d.t1, d.length, d.mid), description="Splits an interval into its start, end, length and midpoint.")


def in_domain(ctx, v, d):
    d = d or Domain(0.0, 1.0)
    return d.contains(v)


add("math.in_domain", "94bd1bfb-7031-4615-b97f-16d4a4ded3f7", "Includes", "In", CAT, "Domain", [P("value", NUM, "item", 0.0, "X", "The number to test."), P("domain", "domain", "item", None, "D", "The interval (0 to 1 when empty).", True)], [P("result", "boolean", "item", None, "R", "True when the number lies in the interval, ends included.")], solve=in_domain, description="Tests whether a number lies inside an interval.")


def remap(ctx, v, src, dst):
    src = src or Domain(0.0, 1.0)
    dst = dst or Domain(0.0, 1.0)
    if abs(src.length) < 1e-300:
        raise NodeWarning("The source interval has zero length.", "DOMAIN_ZERO", "source")
    return dst.at((v - src.t0) / src.length)


add("math.remap", "501c5b4b-272c-4cb5-8465-5a72276b2acd", "Remap", "Remap", CAT, "Domain", [P("value", NUM, "item", 0.0, "X", "The number."), P("source", "domain", "item", None, "S", "Interval the number is measured in (0 to 1 when empty).", True), P("target", "domain", "item", None, "T", "Interval to map into (0 to 1 when empty).", True)], [P("result", NUM, "item", None, "R", "The mapped number.")], solve=remap, description="Maps a number from one interval to another, without clamping.")


def make_range(ctx, d, steps):
    d = d or Domain(0.0, 1.0)
    if steps < 1:
        raise NodeWarning("The range needs at least one step.", "RANGE_STEPS", "steps")
    if steps > 1000000:
        raise NodeWarning("The range is limited to one million steps.", "RANGE_STEPS", "steps")
    return [d.t0 + (d.t1 - d.t0) * i / steps for i in range(steps + 1)]


add("math.range", "3f798d02-fd79-4182-be3d-924354c13cc4", "Range", "Range", CAT, "Sequence", [P("domain", "domain", "item", None, "D", "The interval (0 to 1 when empty).", True), P("steps", "integer", "item", 10, "N", "Number of equal steps.")], [P("range", NUM, "item", None, "R", "Steps plus one numbers, both ends included.")], solve=make_range, multi=True, description="Splits an interval into equal steps.")


def series(ctx, start, step, count):
    if count < 0:
        raise NodeWarning("The count cannot be negative.", "SERIES_COUNT", "count")
    if count > 1000000:
        raise NodeWarning("The series is limited to one million numbers.", "SERIES_COUNT", "count")
    return [start + step * i for i in range(count)]


add("math.series", "f2f32425-2b3f-4338-b0cc-dd8cc5b94a40", "Series", "Series", CAT, "Sequence", [P("start", NUM, "item", 0.0, "S", "First number."), P("step", NUM, "item", 1.0, "N", "Step between numbers."), P("count", "integer", "item", 10, "C", "How many numbers.")], [P("series", NUM, "item", None, "S", "The arithmetic series.")], solve=series, multi=True, description="An arithmetic series from a start, a step and a count.")


def make_random(ctx, count, d, seed, whole):
    if count < 0 or count > 1000000:
        raise NodeWarning("The count must be from 0 to one million.", "RANDOM_COUNT", "count")
    d = d or Domain(0.0, 1.0)
    rng = random.Random(int(seed))
    out = []
    for _ in range(count):
        r = rng.random()
        if whole:
            lo, hi = math.ceil(d.lo), math.floor(d.hi)
            out.append(int(min(hi, lo + math.floor(r * (hi - lo + 1)))) if hi >= lo else int(lo))
        else:
            out.append(d.t0 + r * (d.t1 - d.t0))
    return out


add("math.random", "3ff1b38b-2053-456c-b586-755c6c13b0e4", "Random", "Rnd", CAT, "Sequence", [P("count", "integer", "item", 10, "N", "How many numbers."), P("domain", "domain", "item", None, "D", "Interval of the numbers (0 to 1 when empty).", True), P("seed", "integer", "item", 1, "S", "Seed; the same seed gives the same numbers."), P("whole", "boolean", "item", False, "I", "Produce whole numbers.")], [P("numbers", NUM, "item", None, "R", "The random numbers.")], solve=make_random, multi=True, description="Seeded random numbers inside an interval.")


def mass(fn, start):
    def run(ctx, trees):
        t = trees["values"]
        total = T.DataTree()
        partial = T.DataTree()
        for path, items in t.items():
            acc = start
            parts = []
            for v in items:
                if v is not None:
                    acc = fn(acc, v)
                parts.append(acc)
            total.set_branch(path, [acc])
            partial.set_branch(path, parts)
        return {"result": total, "partial": partial}

    return run


add("math.mass_addition", "dfa64fc0-5eea-4bdd-8ecd-b63b7efdaaa4", "Mass Addition", "Sum", CAT, "Operators", [P("values", NUM, "tree", None, "V", "The numbers; each branch is added on its own.")], [P("result", NUM, "tree", None, "R", "The total of each branch."), P("partial", NUM, "tree", None, "P", "The running totals of each branch.")], run=mass(lambda a, b: a + b, 0.0), description="Adds all numbers of a branch.")
add("math.mass_multiplication", "4cf3dace-da84-46bc-a25a-a93f02d21d6e", "Mass Multiplication", "Prod", CAT, "Operators", [P("values", NUM, "tree", None, "V", "The numbers; each branch is multiplied on its own.")], [P("result", NUM, "tree", None, "R", "The product of each branch."), P("partial", NUM, "tree", None, "P", "The running products of each branch.")], run=mass(lambda a, b: a * b, 1.0), description="Multiplies all numbers of a branch.")
