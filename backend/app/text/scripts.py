import unicodedata

ARABIC = ((0x0600, 0x06FF), (0x0750, 0x077F), (0x0870, 0x08FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF), (0x1EE00, 0x1EEFF))
HEBREW = ((0x0590, 0x05FF), (0xFB1D, 0xFB4F))
THAI = ((0x0E00, 0x0E7F),)
LEADING_VOWELS = frozenset(range(0x0E40, 0x0E45))
FOLLOWING = frozenset((0x0E30, 0x0E32, 0x0E33, 0x0E45, 0x0E2F, 0x0E46, 0x0E5A, 0x0E5B))
FORMAT_CHARS = frozenset("​‌‍‎‏‪‫‬‭‮⁦⁧⁨⁩﻿")


def _in(cp, table):
    for a, b in table:
        if a <= cp <= b:
            return True
    return False


def script_of(ch):
    cp = ord(ch)
    if cp < 0x0590:
        return "other"
    if _in(cp, HEBREW):
        return "hebrew"
    if _in(cp, ARABIC):
        return "arabic"
    if _in(cp, THAI):
        return "thai"
    return "other"


def is_thai(ch):
    return 0x0E00 <= ord(ch) <= 0x0E7F


def needs_shaping(text):
    for ch in text:
        if ord(ch) >= 0x0590 and script_of(ch) != "other":
            return True
        if ch in FORMAT_CHARS:
            return True
    return False


def thai_break_before(prev, ch):
    if not (is_thai(prev) and is_thai(ch)):
        return False
    cp = ord(ch)
    if unicodedata.category(ch) in ("Mn", "Mc", "Me") or cp in FOLLOWING:
        return False
    if ord(prev) in LEADING_VOWELS:
        return False
    return True


def thai_pieces(text):
    out = []
    start = 0
    for i in range(1, len(text)):
        if thai_break_before(text[i - 1], text[i]):
            out.append((start, i))
            start = i
    if text:
        out.append((start, len(text)))
    return out
