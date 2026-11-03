SEVERITIES = ("error", "warning", "info")


def make(rule: str, severity: str, message: str, ref=None, measured=None, limit=None, source: str = "", category: str = "dfm", single_source: bool = False, part: str = "") -> dict:
    return {
        "rule": rule,
        "severity": severity if severity in SEVERITIES else "warning",
        "category": category,
        "part": part,
        "ref": ref,
        "measured": measured,
        "limit": limit,
        "message": message,
        "source": source,
        "single_source": bool(single_source),
    }


def counts(findings: list) -> dict:
    out = {"errors": 0, "warnings": 0, "info": 0}
    for f in findings:
        out[{"error": "errors", "warning": "warnings", "info": "info"}[f["severity"]]] += 1
    return out
