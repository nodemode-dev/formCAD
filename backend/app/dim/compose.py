from app.dim import numfmt

DIAMETER = "⌀"
LINEAR_KINDS = ("linear", "aligned", "radius", "diameter", "jogged", "arc", "ordinate")


def linear_pieces(value: float, V, prefix: str = ""):
    val = numfmt.round_to(value, float(V.get("DIMRND", 0.0) or 0.0))
    pieces = numfmt.linear(val, int(V["DIMLUNIT"]), int(V["DIMDEC"]), int(V["DIMZIN"]), V["DIMDSEP"], int(V["DIMFRAC"]))
    if prefix:
        pieces = numfmt.prefix_pieces(pieces, prefix)
    return pieces


def tol_pieces(value: float, V):
    return numfmt.linear(abs(value), int(V["DIMLUNIT"]), int(V["DIMTDEC"]), int(V["DIMTZIN"]), V["DIMDSEP"], int(V["DIMFRAC"]))


def tolerance(value: float, V, prefix: str):
    tp = float(V.get("DIMTP", 0.0))
    tm = float(V.get("DIMTM", 0.0))
    if int(V.get("DIMLIM", 0)):
        hi = value + tp
        lo = value - tm
        up = numfmt.affix(numfmt.prefix_pieces(tol_pieces(hi, V), prefix) if prefix else tol_pieces(hi, V), V["DIMPOST"])
        dn = numfmt.affix(numfmt.prefix_pieces(tol_pieces(lo, V), prefix) if prefix else tol_pieces(lo, V), V["DIMPOST"])
        return ("lim", _signed(up, hi), _signed(dn, lo))
    if not int(V.get("DIMTOL", 0)):
        return None
    if abs(tp - tm) < 1e-12 and tp != 0:
        return ("sym", "±" + numfmt.plain(tol_pieces(tp, V)))
    plus = _sign(tp, True) + numfmt.plain(tol_pieces(tp, V))
    minus = _sign(-tm, False) + numfmt.plain(tol_pieces(tm, V))
    return ("dev", plus, minus)


def _signed(pieces, value):
    if value < 0 and pieces and pieces[0][0] == "t" and not pieces[0][1].startswith("-"):
        return [("t", "-" + pieces[0][1])] + list(pieces[1:])
    return pieces


def _sign(value: float, plus: bool) -> str:
    if value == 0:
        return ""
    return "+" if value > 0 else "-"


def alternate(value: float, V):
    if not int(V.get("DIMALT", 0)):
        return None
    val = numfmt.round_to(value * float(V.get("DIMALTF", 1.0)), float(V.get("DIMALTRND", 0.0) or 0.0))
    pieces = numfmt.linear(val, int(V["DIMALTU"]), int(V["DIMALTD"]), int(V["DIMALTZ"]), V["DIMDSEP"], int(V["DIMFRAC"]))
    pieces = numfmt.affix(pieces, V.get("DIMAPOST", ""))
    return [("t", "[")] + pieces + [("t", "]")]


def measured(dim, V):
    t = dim.dim_type
    m = float(dim.measurement)
    if t in ("angular", "angular3"):
        txt = numfmt.angular(m, int(V["DIMAUNIT"]), int(V["DIMADEC"]), int(V["DIMAZIN"]))
        return numfmt.affix([("t", txt)], V["DIMPOST"]), None, None, m
    value = m * float(V.get("DIMLFAC", 1.0) if V.get("DIMLFAC", 1.0) else 1.0)
    prefix = ""
    if t in ("radius", "jogged"):
        prefix = "R"
    elif t == "diameter":
        prefix = DIAMETER
    pieces = numfmt.affix(linear_pieces(value, V, prefix), V["DIMPOST"])
    return pieces, tolerance(value, V, prefix), alternate(value, V), value


def content(dim, V):
    ov = dim.text_override or ""
    if ov == " ":
        return None
    pieces, tol, alt, _value = measured(dim, V)
    out = {"main": pieces, "tol": tol, "alt": alt}
    if dim.dim_type == "arc":
        sym = int(V.get("DIMARCSYM", 0))
        out["arcsym"] = "before" if sym == 0 else "above" if sym == 1 else None
    if ov:
        if "<>" in ov:
            pre, _, post = ov.partition("<>")
            out["main"] = ([("t", pre)] if pre else []) + list(pieces) + ([("t", post)] if post else [])
        else:
            out = {"main": [("t", ov)], "tol": None, "alt": None}
    if out.get("tol") and out["tol"][0] == "lim" and not (ov and "<>" not in ov):
        out["main"] = []
    return out


def measurement_text(dim, V) -> str:
    pieces, tol, alt, _value = measured(dim, V)
    return numfmt.plain(pieces)
