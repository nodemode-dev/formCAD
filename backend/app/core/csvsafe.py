import re

NUMBER = re.compile(r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$")
LEAD = ("=", "+", "-", "@", "\t", "\r")


def cell(v) -> str:
    s = "" if v is None else (("%.6g" % v) if isinstance(v, float) else str(v))
    return ("'" + s) if s[:1] in LEAD and not NUMBER.match(s) else s
