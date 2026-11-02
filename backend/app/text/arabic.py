import unicodedata

JOIN_CAUSING = frozenset((0x0640, 0x200D))
ALEFS = frozenset((0x0622, 0x0623, 0x0625, 0x0627))
LAM = 0x0644

FORMS = {}
LIGATURES = {}


def _index():
    for cp in list(range(0xFB50, 0xFE00)) + list(range(0xFE70, 0xFF00)):
        dec = unicodedata.decomposition(chr(cp))
        if not dec.startswith("<"):
            continue
        tag, _, rest = dec.partition(" ")
        form = tag.strip("<>")
        if form not in ("isolated", "initial", "medial", "final"):
            continue
        parts = tuple(int(x, 16) for x in rest.split())
        if len(parts) == 1:
            FORMS.setdefault(parts[0], {}).setdefault(form, cp)
        elif len(parts) == 2 and parts[0] == LAM and parts[1] in ALEFS:
            LIGATURES.setdefault(parts, {}).setdefault(form, cp)


_index()


def join_type(ch):
    cp = ord(ch)
    if cp in JOIN_CAUSING:
        return "C"
    if cp == 0x200C:
        return "U"
    cat = unicodedata.category(ch)
    if cat in ("Mn", "Me") or (cat == "Cf" and cp not in (0x200C,)):
        return "T"
    forms = FORMS.get(cp)
    if not forms:
        return "U"
    if "initial" in forms or "medial" in forms:
        return "D"
    if "final" in forms:
        return "R"
    return "U"


def _neighbour(types, i, step):
    j = i + step
    while 0 <= j < len(types):
        if types[j] != "T":
            return types[j], j
        j += step
    return "U", -1


def presentation(text):
    types = [join_type(c) for c in text]
    out = [c for c in text]
    skip = set()
    for i, ch in enumerate(text):
        if i in skip or types[i] not in ("D", "R"):
            continue
        before, _ = _neighbour(types, i, -1)
        after, j = _neighbour(types, i, 1)
        joined_prev = before in ("D", "C")
        if ord(ch) == LAM and j >= 0 and ord(text[j]) in ALEFS:
            lig = LIGATURES.get((LAM, ord(text[j])))
            if lig:
                form = "final" if joined_prev and "final" in lig else "isolated"
                if form in lig:
                    out[i] = chr(lig[form])
                    out[j] = ""
                    skip.add(j)
                    continue
        joined_next = types[i] == "D" and after in ("D", "R", "C")
        if joined_prev and joined_next:
            form = "medial"
        elif joined_prev:
            form = "final"
        elif joined_next:
            form = "initial"
        else:
            form = "isolated"
        forms = FORMS.get(ord(ch), {})
        if form in forms:
            out[i] = chr(forms[form])
        elif form == "medial" and "final" in forms:
            out[i] = chr(forms["final"])
        elif form == "initial" and "isolated" in forms:
            out[i] = chr(forms["isolated"])
    return out
