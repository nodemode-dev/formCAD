#!/usr/bin/env python3
"""Write backend/app/data/hole-sizes.json and fastener-sizes.json from the cited readings below.

usage: python3 setup/hole_tables.py [--check]
Every number here was read from a published standard named in SOURCES. A value that two independent
sources give alike is marked two_sources; one source read twice alike, read_twice; one reading only,
read_once; a value that could not be read is left empty (illegible_in_source) and never filled in.
--check compares the files on disk with what this script would write and exits 1 when they differ.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOLES = ROOT / "backend" / "app" / "data" / "hole-sizes.json"
FASTENERS = ROOT / "backend" / "app" / "data" / "fastener-sizes.json"
RETRIEVED = "2026-11-22"
ACCESS_BIS = "Copy published by the Bureau of Indian Standards or by Public.Resource.Org; BIS reserves its copyright, so only the numbers are used, in FormCAD's own layout."

SOURCES = {
    "BIS-IS-4218-2-2001": {
        "title": "IS 4218 (Part 2): 2001, ISO general purpose metric screw threads, Part 2 General plan (second revision)",
        "publisher": "Bureau of Indian Standards",
        "identical_to": "ISO 261:1998",
        "url": "https://law.resource.org/pub/in/bis/S01/is.4218.2.2001.pdf",
        "retrieved": "2026-11-02",
        "access": ACCESS_BIS,
        "reading": "Text extraction of a scanned page, two separate reads. Rows read_twice agree in both reads; read_once appeared in one read only.",
    },
    "BIS-IS-1364-3-2025": {
        "title": "IS 1364 (Part 3): 2025, Hexagon head bolts, screws and nuts of product grades A and B, Part 3 Hexagon nuts, style 1 (sixth revision)",
        "publisher": "Bureau of Indian Standards",
        "identical_to": "ISO 4032:2023",
        "url": "https://www.services.bis.gov.in/tmp/PGD32022813_14072025_2.pdf",
        "retrieved": RETRIEVED,
        "access": ACCESS_BIS,
        "reading": "Text layer of a typeset PDF, two separate reads; every value marked read_twice agreed in both. Annex A (sizes below M5 and above M39) is informative and warns against these nuts for new or critical uses.",
    },
    "BIS-IS-10952-1984": {
        "title": "IS 10952: 1984, Recommendations for drills for use prior to tapping screw threads (reaffirmed 2005)",
        "publisher": "Bureau of Indian Standards",
        "identical_to": "ISO 2306-1972",
        "url": "https://law.resource.org/pub/in/bis/S01/is.10952.1984.pdf",
        "retrieved": RETRIEVED,
        "access": ACCESS_BIS,
        "reading": "Text extraction of a scanned page, one read of Table 1 (coarse pitch series). A drill that does not fall between the table's own minimum and maximum minor diameters of the nut thread is treated as damaged by the scan and left empty.",
    },
    "BIS-IS-2269-2006": {
        "title": "IS 2269: 2006, Hexagon socket head cap screws (fifth revision)",
        "publisher": "Bureau of Indian Standards",
        "identical_to": "ISO 4762:2004",
        "url": "https://law.resource.org/pub/in/bis/S01/is.2269.2006.pdf",
        "retrieved": RETRIEVED,
        "access": ACCESS_BIS,
        "reading": "Text extraction, one read of Table 1. Only the columns from M14 up are in the text layer; smaller sizes could not be read.",
    },
    "BIS-IS-1821-1987": {
        "title": "IS 1821: 1987, Dimensions for clearance holes for bolts and screws (third revision)",
        "publisher": "Bureau of Indian Standards",
        "identical_to": "ISO 273-1979",
        "url": "https://law.resource.org/pub/in/bis/S01/is.1821.1987.pdf",
        "retrieved": RETRIEVED,
        "access": ACCESS_BIS,
        "reading": "Text extraction of a badly scanned page, one read. Only rows whose three values could be tied to their thread size are kept; every other row is left out.",
    },
}

PITCH_4218 = {
    "M1": (0.25, "read_twice"), "M2": (None, "illegible_in_source"), "M2.5": (None, "illegible_in_source"), "M3": (None, "illegible_in_source"),
    "M4": (0.7, "read_twice"), "M5": (0.8, "read_twice"), "M6": (1.0, "read_twice"), "M8": (1.25, "read_twice"), "M10": (1.5, "read_twice"),
    "M12": (1.75, "read_twice"), "M14": (2.0, "read_once"), "M16": (2.0, "read_twice"), "M18": (2.5, "read_once"), "M20": (2.5, "read_twice"),
    "M22": (2.5, "read_once"), "M24": (3.0, "read_twice"), "M27": (3.0, "read_once"), "M30": (3.5, "read_twice"), "M33": (3.5, "read_once"),
    "M36": (4.0, "read_once"), "M39": (4.0, "read_once"), "M42": (4.5, "read_once"), "M45": (4.5, "read_once"), "M48": (5.0, "read_once"),
}

NUTS_4032 = [
    ("M1.6", 0.35, 3.2, 1.30, 1.05, "annex"), ("M2", 0.4, 4.0, 1.60, 1.35, "annex"), ("M2.5", 0.45, 5.0, 2.00, 1.75, "annex"),
    ("M3", 0.5, 5.5, 2.40, 2.15, "annex"), ("M3.5", 0.6, 6.0, 2.80, 2.55, "annex"), ("M4", 0.7, 7.0, 3.20, 2.90, "annex"),
    ("M5", 0.8, 8.0, 4.70, 4.40, ""), ("M6", 1.0, 10.0, 5.20, 4.90, ""), ("M7", 1.0, 11.0, 6.50, 6.14, ""), ("M8", 1.25, 13.0, 6.80, 6.44, ""),
    ("M10", 1.5, 16.0, 8.40, 8.04, ""), ("M12", 1.75, 18.0, 10.80, 10.37, ""), ("M14", 2.0, 21.0, 12.80, 12.10, ""), ("M16", 2.0, 24.0, 14.80, 14.10, ""),
    ("M18", 2.5, 27.0, 15.80, 15.10, ""), ("M20", 2.5, 30.0, 18.00, 16.90, ""), ("M22", 2.5, 34.0, 19.40, 18.10, ""), ("M24", 3.0, 36.0, 21.50, 20.20, ""),
    ("M27", 3.0, 41.0, 23.80, 22.50, ""), ("M30", 3.5, 46.0, 25.60, 24.30, ""), ("M33", 3.5, 50.0, 28.70, 27.40, ""), ("M36", 4.0, 55.0, 31.00, 29.40, ""),
    ("M39", 4.0, 60.0, 33.40, 31.80, ""), ("M42", 4.5, 65.0, 34.00, 32.40, "annex"), ("M45", 4.5, 70.0, 36.00, 34.40, "annex"), ("M48", 5.0, 75.0, 38.00, 36.40, "annex"),
    ("M52", 5.0, 80.0, 42.00, 40.40, "annex"), ("M56", 5.5, 85.0, 45.00, 43.40, "annex"), ("M60", 5.5, 90.0, 48.00, 46.40, "annex"), ("M64", 6.0, 95.0, 51.00, 49.10, "annex"),
]

TAP_10952 = [
    ("M3", 0.5, 2.459, 2.639, 2.50, ""), ("M3.5", 0.6, 2.850, 3.050, 2.90, ""), ("M4", 0.7, 3.242, 3.466, 3.30, ""), ("M4.5", 0.75, 3.668, 3.924, 3.70, ""),
    ("M5", 0.8, 4.134, 4.364, 4.20, ""), ("M6", 1.0, None, 5.217, 5.00, ""), ("M7", 1.0, 5.917, 6.217, 6.00, ""), ("M8", 1.25, None, 6.962, None, "The drill is printed without its decimal point in the scan."),
    ("M9", 1.25, 7.647, 7.982, 7.60, ""), ("M10", 1.5, 8.376, 8.751, 8.50, ""), ("M11", 1.5, 9.376, 9.751, 9.50, ""), ("M12", 1.75, 10.106, 10.531, 10.20, ""),
    ("M14", 2.0, 11.835, 12.310, 12.00, ""), ("M16", 2.0, None, 14.310, 14.00, ""), ("M18", 2.5, 15.294, 15.854, 15.50, "The row's size is damaged in the scan; it is the row between M16 and M20, with pitch 2.5 and the basic minor diameter of M18."),
    ("M20", 2.5, 17.294, None, 17.50, ""), ("M22", 2.5, 19.294, 19.854, 19.50, ""), ("M24", 3.0, 20.752, 21.382, 21.90, ""), ("M27", 3.0, 23.752, 24.382, 24.00, ""),
    ("M30", 3.5, 26.211, 26.921, 26.50, ""), ("M33", 3.5, 29.211, 29.921, 29.50, ""), ("M36", 4.0, 31.670, 32.420, 32.00, ""), ("M39", 4.0, 34.670, None, 35.00, ""),
    ("M42", 4.5, 37.129, 37.979, 37.50, ""), ("M45", 4.5, 40.129, 40.979, 40.50, ""), ("M48", 5.0, 42.587, 43.467, 43.00, ""), ("M52", 5.0, 46.567, 47.467, 47.00, ""),
    ("M56", 5.5, 50.046, 50.996, 50.50, ""),
]

SHCS_4762 = [
    ("M14", 2.0, 21.0, 14.0, 12.0), ("M16", 2.0, 24.0, 16.0, 14.0), ("M20", 2.5, 30.0, 20.0, 17.0), ("M24", 3.0, 36.0, 24.0, 19.0),
    ("M30", 3.5, 45.0, 30.0, 22.0), ("M36", 4.0, 54.0, 36.0, 27.0), ("M42", 4.5, 63.0, 42.0, 32.0), ("M48", 5.0, 72.0, 48.0, 36.0),
    ("M56", 5.5, 84.0, 56.0, 41.0), ("M64", 6.0, 96.0, 64.0, 46.0),
]

CLEAR_1821 = [
    ("M42", 43.0, 45.0, 48.0), ("M45", 46.0, 48.0, 52.0), ("M48", 50.0, 52.0, 56.0), ("M52", 54.0, 56.0, 62.0),
    ("M56", 58.0, 62.0, 66.0), ("M60", 62.0, 66.0, None), ("M64", 66.0, 70.0, 74.0),
]

NOTICE = ("Every number in this table names its source, a published standard identical to the ISO standard it cites, and says how well it could be read: "
          "two_sources (two independent standards agree), read_twice (one source, two readings agree), read_once (one reading only). A value that could not be read is left empty "
          "and must be typed. Coarse pitches and tap drills cover M1 to M64; clearance holes are given only from M42 to M64, because the only free copy of ISO 273 is too badly scanned below that; "
          "counterbore and countersink sizes do not ship, because no free published source for them was found. Check every value against your own copy of the standard. "
          "Add rows in your own copy of this file; a row in your copy replaces the shipped row with the same key.")


def size_key(sid: str) -> float:
    return float(sid[1:])


def pitch_rows() -> list:
    seen = {}
    for sid, (p, st) in PITCH_4218.items():
        seen.setdefault(sid, []).append(("BIS-IS-4218-2-2001", p, st))
    for sid, p, *_rest in NUTS_4032:
        seen.setdefault(sid, []).append(("BIS-IS-1364-3-2025", p, "read_twice"))
    for sid, p, *_rest in TAP_10952:
        seen.setdefault(sid, []).append(("BIS-IS-10952-1984", p, "read_once"))
    for sid, p, *_rest in SHCS_4762:
        seen.setdefault(sid, []).append(("BIS-IS-2269-2006", p, "read_once"))
    out = []
    for sid in sorted(seen, key=size_key):
        given = [(src, p, st) for src, p, st in seen[sid] if p is not None]
        values = {p for _src, p, _st in given}
        if len(values) > 1:
            raise SystemExit("%s: the sources disagree on the pitch: %s" % (sid, given))
        row = {"id": sid, "standard": "iso_metric_coarse", "nominal": size_key(sid)}
        if not given:
            row.update({"pitch": None, "source": seen[sid][0][0], "status": "illegible_in_source", "note": "Enter the coarse pitch from your standard."})
        else:
            srcs = sorted({src for src, _p, _st in given})
            status = "two_sources" if len(srcs) > 1 else given[0][2]
            row.update({"pitch": given[0][1], "source": srcs[0], "status": status})
            if len(srcs) > 1:
                row["sources"] = srcs
        out.append(row)
    return out


def tap_rows() -> list:
    out = []
    for sid, p, lo, hi, drill, note in TAP_10952:
        row = {"id": sid, "standard": "iso_metric_coarse", "pitch": p, "source": "BIS-IS-10952-1984"}
        ok = drill is not None and (lo is None or drill >= lo) and (hi is None or drill <= hi)
        if ok:
            row.update({"diameter": drill, "status": "read_once"})
        else:
            row.update({"diameter": None, "status": "illegible_in_source"})
            note = note or "The printed drill lies outside the table's own minor diameter range, so the scan is taken as damaged."
        if note:
            row["note"] = note
        out.append(row)
    return out


def clearance_rows() -> list:
    out = []
    for sid, fine, medium, coarse in CLEAR_1821:
        row = {"id": sid, "standard": "iso_metric_coarse", "fine": fine, "medium": medium, "coarse": coarse, "source": "BIS-IS-1821-1987", "status": "read_once"}
        if coarse is None:
            row["note"] = "The coarse series value is damaged in the scan."
        out.append(row)
    return out


def holes_doc() -> dict:
    keep = ("BIS-IS-4218-2-2001", "BIS-IS-1364-3-2025", "BIS-IS-10952-1984", "BIS-IS-2269-2006", "BIS-IS-1821-1987")
    return {
        "format": 1,
        "units": "mm",
        "generated_by": "setup/hole_tables.py",
        "notice": NOTICE,
        "user_file": "hole-sizes.json in the FormCAD data folder",
        "sources": {k: SOURCES[k] for k in keep},
        "thread_series": pitch_rows(),
        "clearance": clearance_rows(),
        "counterbore": [],
        "countersink": [],
        "tap_drill": tap_rows(),
    }


def fasteners_doc() -> dict:
    nuts = []
    for sid, p, s, mmax, mmin, where in NUTS_4032:
        row = {"id": sid, "nominal": size_key(sid), "pitch": p, "across_flats": s, "thickness": mmax, "thickness_min": mmin, "source": "BIS-IS-1364-3-2025", "status": "read_twice"}
        if where == "annex":
            row["status"] = "read_once"
            row["note"] = "Informative annex size: the standard advises against it for new or critical uses. Its thickness was read twice, its width across flats once."
        nuts.append(row)
    screws = [{"id": sid, "nominal": size_key(sid), "pitch": p, "head_d": dk, "head_h": k, "socket_s": s, "source": "BIS-IS-2269-2006", "status": "read_once"} for sid, p, dk, k, s in SHCS_4762]
    return {
        "format": 1,
        "units": "mm",
        "generated_by": "setup/hole_tables.py",
        "notice": "Hex nut sizes follow ISO 4032:2023 and socket head cap screw head sizes ISO 4762:2004 (M14 and up only), each read from the published standard named in its source. Thickness and head sizes are the standards' maximum values. Sizes not listed are entered by hand.",
        "sources": {k: SOURCES[k] for k in ("BIS-IS-1364-3-2025", "BIS-IS-2269-2006")},
        "hex_nut": nuts,
        "socket_screw": screws,
    }


def text(doc: dict) -> str:
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def main(argv) -> int:
    pairs = ((HOLES, text(holes_doc())), (FASTENERS, text(fasteners_doc())))
    if "--check" in argv:
        bad = [str(p.relative_to(ROOT)) for p, t in pairs if not p.is_file() or p.read_text(encoding="utf-8") != t]
        print("hole tables: %s" % ("differ: " + ", ".join(bad) if bad else "current"))
        return 1 if bad else 0
    for path, t in pairs:
        path.write_text(t, encoding="utf-8")
        print("wrote %s" % path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
