import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS_FILE = os.path.join(ROOT, "frontend", "src", "ui", "i18n", "keys.ts")
TABLES = os.path.join(ROOT, "frontend", "src", "ui", "i18n", "tables")
PARTS = {"a": (0, 548), "b": (549, 1060), "c": (1061, 1572), "d": (1573, 2299)}
VARIANTS = {"es-MX": "es", "fr-CA": "fr"}
PLACEHOLDER = re.compile(r"\{[a-z0-9]+\}")
ROW = re.compile(r'^\s*(\d+):\s*("(?:[^"\\]|\\.)*"),\s*$')
HEAD = "const T: Record<number, string> = {"


def read_keys():
    text = open(KEYS_FILE, encoding="utf-8").read()
    return [json.loads(m.group(1)) for m in re.finditer(r'^  ("(?:[^"\\]|\\.)*"),$', text, re.M)]


def table_rows(path, code, part, problems):
    lines = open(path, encoding="utf-8").read().rstrip("\n").split("\n")
    if lines == [HEAD + "};", "export default T;"]:
        return []
    if lines[0] != HEAD or lines[-2:] != ["};", "export default T;"]:
        problems.append("%s.%s: not in the table format" % (code, part))
        return []
    out = []
    for n, line in enumerate(lines[1:-2], 2):
        m = ROW.match(line)
        if m:
            out.append((int(m.group(1)), json.loads(m.group(2))))
        else:
            problems.append("%s.%s line %d: not a table row" % (code, part, n))
    return out


def check():
    keys = read_keys()
    last = max(hi for _, hi in PARTS.values())
    problems = []
    if len(keys) - 1 > last:
        problems.append("%d strings sit past row %d; add a part here and in frontend/src/ui/i18n.ts" % (len(keys) - 1 - last, last))
    codes = sorted({os.path.basename(p).rsplit(".", 2)[0] for p in glob.glob(os.path.join(TABLES, "*.ts"))})
    for code in codes:
        have = 0
        for part, (lo, hi) in PARTS.items():
            path = os.path.join(TABLES, "%s.%s.ts" % (code, part))
            if not os.path.exists(path):
                problems.append("%s.%s: file missing" % (code, part))
                continue
            seen = set()
            for i, text in table_rows(path, code, part, problems):
                where = "%s.%s row %d" % (code, part, i)
                if i in seen or not lo <= i <= hi or i >= len(keys):
                    problems.append(where + ": repeated or outside this part")
                    continue
                seen.add(i)
                if not text.strip():
                    problems.append(where + ": empty")
                if sorted(PLACEHOLDER.findall(text)) != sorted(PLACEHOLDER.findall(keys[i])):
                    problems.append(where + ": placeholders differ from the English")
                if "—" in text:
                    problems.append(where + ": em dash")
            if code not in VARIANTS:
                missing = [i for i in range(lo, min(hi, len(keys) - 1) + 1) if i not in seen]
                if missing:
                    problems.append("%s.%s: %d rows missing, first %d" % (code, part, len(missing), missing[0]))
            have += len(seen)
        note = "overrides of %s" % VARIANTS[code] if code in VARIANTS else "of %d" % len(keys)
        print("%-8s %5d %s" % (code, have, note))
    for p in problems[:80]:
        print("  " + p)
    print("%d languages, %d problems." % (len(codes), len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    if sys.argv[1:] != ["check"]:
        print("Usage: python3 setup/i18n.py check")
        sys.exit(2)
    sys.exit(check())
