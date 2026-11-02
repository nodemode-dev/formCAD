import re

PERCENT = {"d": "°", "p": "±", "c": "⌀", "%": "%"}
_CODE = re.compile(r"%%([dDpPcC%uUoOkK]|\d{3})")


def decode(text):
    out = []
    ul = ol = sk = False
    pos = 0
    for m in _CODE.finditer(text):
        for ch in text[pos:m.start()]:
            out.append((ch, ul, ol, sk))
        code = m.group(1)
        low = code.lower()
        if low == "u":
            ul = not ul
        elif low == "o":
            ol = not ol
        elif low == "k":
            sk = not sk
        elif code.isdigit():
            n = int(code)
            if 0 < n < 0x110000:
                out.append((chr(n), ul, ol, sk))
        else:
            out.append((PERCENT[low], ul, ol, sk))
        pos = m.end()
    for ch in text[pos:]:
        out.append((ch, ul, ol, sk))
    return [c for c in out if c[0] not in ("\n", "\r")]
