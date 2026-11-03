#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

SPEC = "1.6"
SPDX = {
    "Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Zlib", "MPL-2.0", "LGPL-2.1-only", "LGPL-2.1-or-later",
    "LGPL-3.0-only", "GPL-2.0-only", "GPL-3.0-only", "GPL-3.0-or-later", "0BSD", "BSL-1.0", "Unlicense", "CC0-1.0",
    "OFL-1.1", "PSF-2.0", "Python-2.0", "BlueOak-1.0.0", "CC-BY-4.0", "MIT-0", "Unicode-3.0", "Apache-2.0 WITH LLVM-exception",
}
CLASSIFIERS = {
    "MIT License": "MIT",
    "Apache Software License": "Apache-2.0",
    "BSD License": "BSD-3-Clause",
    "ISC License (ISCL)": "ISC",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "GNU Lesser General Public License v2 (LGPLv2)": "LGPL-2.1-only",
    "Python Software Foundation License": "PSF-2.0",
    "zlib/libpng License": "Zlib",
}
EXTRA = {
    "kernel": [
        {
            "name": "OpenCascade Technology",
            "version": "8.0.1",
            "licence": "LGPL-2.1-only WITH OCCT-exception-1.0",
            "purl": "pkg:github/Open-Cascade-SAS/OCCT@V8_0_1",
            "description": "geometry kernel, shipped as separate shared libraries inside the cadquery-ocp-novtk wheel",
        },
    ],
    "mesher": [
        {
            "name": "Netgen",
            "version": "6.2.2608",
            "licence": "LGPL-2.1-only",
            "purl": "pkg:github/NGSolve/netgen@v6.2.2608",
            "description": "tetrahedral mesher, shipped as separate shared libraries inside the netgen-mesher wheel",
        },
        {
            "name": "OpenCascade Technology",
            "version": "7.8.1",
            "licence": "LGPL-2.1-only WITH OCCT-exception-1.0",
            "purl": "pkg:github/Open-Cascade-SAS/OCCT@V7_8_1",
            "description": "geometry reader built into the netgen-occt wheel",
        },
    ],
}


def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def licence_entry(text):
    if not text:
        return None
    text = text.strip()
    if text in SPDX:
        return [{"license": {"id": text}}]
    if re.search(r"\b(AND|OR|WITH)\b", text) and len(text) < 200:
        return [{"expression": text}]
    return [{"license": {"name": text[:120]}}]


def read_requirements(path):
    out = []
    pending = None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip() if not raw.strip().startswith("--hash") else raw.strip()
        if not line:
            continue
        if line.startswith("--hash"):
            if pending is not None:
                pending["hashes"].append(line.split("sha256:", 1)[1].split()[0].rstrip("\\"))
            continue
        line = line.rstrip("\\").strip()
        match = re.match(r"^([A-Za-z0-9_.\-]+)(\[[^\]]*\])?==([^\s;]+)", line)
        if not match:
            continue
        pending = {"name": match.group(1), "version": match.group(3), "hashes": []}
        out.append(pending)
    return out


def installed(site):
    found = {}
    for meta in Path(site).glob("*.dist-info/METADATA"):
        name = version = lic = None
        classifier = None
        requires = []
        for line in meta.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line:
                break
            if line.startswith("Name: "):
                name = line[6:].strip()
            elif line.startswith("Version: "):
                version = line[9:].strip()
            elif line.startswith("License-Expression: "):
                lic = line[20:].strip()
            elif line.startswith("Classifier: License ::") and classifier is None:
                classifier = CLASSIFIERS.get(line.split("::")[-1].strip())
            elif line.startswith("License: ") and not lic and len(line) < 80 and "\n" not in line:
                short = line[9:].strip()
                if short and short.upper() != "UNKNOWN":
                    classifier = classifier or short
            elif line.startswith("Requires-Dist: ") and "extra ==" not in line:
                dep = re.match(r"Requires-Dist:\s*([A-Za-z0-9_.\-]+)", line)
                if dep:
                    requires.append(norm(dep.group(1)))
        if name:
            found[norm(name)] = {"name": name, "version": version, "licence": lic or classifier, "requires": requires}
    return found


def python_components(path, site, closure):
    pins = read_requirements(path)
    meta = installed(site) if site else {}
    items = {}
    for pin in pins:
        items[norm(pin["name"])] = {"name": pin["name"], "version": pin["version"], "hashes": pin["hashes"], "direct": True}
    if closure and meta:
        queue = list(items)
        while queue:
            key = queue.pop()
            for dep in meta.get(key, {}).get("requires", []):
                if dep in meta and dep not in items:
                    items[dep] = {"name": meta[dep]["name"], "version": meta[dep]["version"], "hashes": [], "direct": False}
                    queue.append(dep)
    out = []
    for key, item in sorted(items.items()):
        known = meta.get(key, {})
        out.append(
            {
                "name": item["name"],
                "version": item["version"],
                "purl": f"pkg:pypi/{key}@{item['version']}",
                "licence": known.get("licence"),
                "hashes": [("SHA-256", h) for h in item["hashes"]],
                "requires": [d for d in known.get("requires", []) if d in items],
                "key": key,
            }
        )
    return out


def npm_components(path, include_dev):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for key, pkg in sorted(data.get("packages", {}).items()):
        if not key or "node_modules/" not in key:
            continue
        if pkg.get("dev") and not include_dev:
            continue
        name = key.rsplit("node_modules/", 1)[1]
        hashes = []
        integrity = pkg.get("integrity", "")
        if integrity.startswith("sha512-"):
            hashes.append(("SHA-512", base64.b64decode(integrity[7:]).hex()))
        elif integrity.startswith("sha256-"):
            hashes.append(("SHA-256", base64.b64decode(integrity[7:]).hex()))
        purl_name = name.replace("@", "%40", 1) if name.startswith("@") else name
        lic = pkg.get("license")
        if isinstance(lic, dict):
            lic = lic.get("type")
        out.append(
            {
                "name": name,
                "version": pkg["version"],
                "purl": f"pkg:npm/{purl_name}@{pkg['version']}",
                "licence": lic if isinstance(lic, str) else None,
                "hashes": hashes,
                "requires": [],
                "key": key,
            }
        )
    return out


def cargo_components(path):
    out = []
    block = {}
    blocks = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("[[package]]"):
            block = {}
            blocks.append(block)
        else:
            match = re.match(r'^(\w+) = "(.*)"$', line)
            if match and blocks:
                block[match.group(1)] = match.group(2)
    for item in blocks:
        hashes = [("SHA-256", item["checksum"])] if item.get("checksum") else []
        out.append(
            {
                "name": item["name"],
                "version": item["version"],
                "purl": f"pkg:cargo/{item['name']}@{item['version']}",
                "licence": None,
                "hashes": hashes,
                "requires": [],
                "key": f"{item['name']}@{item['version']}",
            }
        )
    return sorted(out, key=lambda c: (c["name"], c["version"]))


def build(component, version, licence, comps, extra, source_name, source_files):
    digest = hashlib.sha256()
    for part in source_files:
        digest.update(Path(part).read_bytes())
    serial = uuid.uuid5(uuid.NAMESPACE_URL, f"formcad/{component}/{version}/{digest.hexdigest()}")
    stamp = os.environ.get("SOURCE_DATE_EPOCH")
    when = time.gmtime(int(stamp)) if stamp else time.gmtime()
    root_ref = f"formcad-{component}@{version}"
    components, refs = [], {}
    for comp in comps:
        ref = comp["purl"]
        refs[comp["key"]] = ref
        entry = {"type": "library", "bom-ref": ref, "name": comp["name"], "version": comp["version"], "purl": comp["purl"], "scope": "required"}
        lic = licence_entry(comp["licence"])
        if lic:
            entry["licenses"] = lic
        if comp["hashes"]:
            entry["hashes"] = [{"alg": a, "content": h} for a, h in comp["hashes"]]
        components.append(entry)
    for item in extra:
        entry = {
            "type": "library",
            "bom-ref": item["purl"],
            "name": item["name"],
            "version": item["version"],
            "purl": item["purl"],
            "scope": "required",
            "description": item["description"],
            "licenses": licence_entry(item["licence"]),
        }
        components.append(entry)
    seen = set()
    unique = []
    for entry in components:
        if entry["bom-ref"] in seen:
            continue
        seen.add(entry["bom-ref"])
        unique.append(entry)
    deps = [{"ref": root_ref, "dependsOn": [c["bom-ref"] for c in unique]}]
    for comp in comps:
        down = sorted({refs[d] for d in comp["requires"] if d in refs})
        if down:
            deps.append({"ref": comp["purl"], "dependsOn": down})
    return {
        "bomFormat": "CycloneDX",
        "specVersion": SPEC,
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", when),
            "tools": {"components": [{"type": "application", "name": "formcad-sbom", "version": "1.0.0"}]},
            "component": {
                "type": "application",
                "bom-ref": root_ref,
                "name": f"formCAD {component}",
                "version": version,
                "licenses": licence_entry(licence),
                "properties": [{"name": "formcad:source", "value": source_name}],
            },
        },
        "components": unique,
        "dependencies": deps,
    }


def check(bom):
    problems = []
    for key in ("bomFormat", "specVersion", "serialNumber", "version", "metadata", "components", "dependencies"):
        if key not in bom:
            problems.append(f"missing {key}")
    if bom.get("bomFormat") != "CycloneDX":
        problems.append("bomFormat is not CycloneDX")
    if not re.match(r"^urn:uuid:[0-9a-f-]{36}$", str(bom.get("serialNumber"))):
        problems.append("serialNumber is not a urn:uuid")
    refs = set()
    for comp in bom.get("components", []):
        for key in ("type", "bom-ref", "name", "version"):
            if not comp.get(key):
                problems.append(f"component without {key}: {comp.get('name')}")
        if comp.get("bom-ref") in refs:
            problems.append(f"duplicate bom-ref {comp.get('bom-ref')}")
        refs.add(comp.get("bom-ref"))
        for h in comp.get("hashes", []):
            want = {"SHA-256": 64, "SHA-512": 128}.get(h["alg"])
            if want and (len(h["content"]) != want or not re.fullmatch(r"[0-9a-f]+", h["content"])):
                problems.append(f"bad hash on {comp['name']}")
    root = bom.get("metadata", {}).get("component", {}).get("bom-ref")
    refs.add(root)
    for dep in bom.get("dependencies", []):
        if dep["ref"] not in refs:
            problems.append(f"dependency ref {dep['ref']} is not a component")
        for sub in dep.get("dependsOn", []):
            if sub not in refs:
                problems.append(f"dependsOn {sub} is not a component")
    return problems


def plan(repo):
    return {
        "engine": {"kind": "python", "files": ["backend/requirements.txt"], "site": "backend/venv", "licence": "Apache-2.0", "closure": True},
        "frontend": {"kind": "npm", "files": ["frontend/package-lock.json"], "licence": "Apache-2.0"},
        "shell": {"kind": "cargo", "files": ["src-tauri/Cargo.lock"], "licence": "Apache-2.0"},
        "kernel": {"kind": "python", "files": ["kernel/requirements_kernel.txt"], "site": "kernel/venv", "licence": "Apache-2.0", "closure": True, "lock": True},
        "mesher": {"kind": "python", "files": ["mesher/requirements_mesher.txt"], "site": "mesher/venv", "licence": "Apache-2.0", "closure": True},
    }


def site_packages(venv):
    for pattern in ("lib/python*/site-packages", "Lib/site-packages"):
        found = sorted(Path(venv).glob(pattern))
        if found:
            return found[0]
    return None


def main():
    ap = argparse.ArgumentParser(description="CycloneDX SBOM per FormCAD component, from lock and requirements files")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--out", required=True)
    ap.add_argument("--version")
    ap.add_argument("--component", action="append", choices=["engine", "frontend", "shell", "kernel", "mesher"])
    ap.add_argument("--no-metadata", action="store_true", help="do not read installed package metadata for licences and the dependency closure")
    ap.add_argument("--lock", help="use this requirements.lock instead of the requirements file (kernel and mesher)")
    ap.add_argument("--include-dev", action="store_true")
    args = ap.parse_args()
    repo = Path(args.repo)
    version = args.version or json.loads((repo / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))["version"]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    failed = False
    for name in args.component or list(plan(repo)):
        spec = plan(repo)[name]
        files = [repo / f for f in spec["files"]]
        if args.lock and spec.get("kind") == "python" and name == "kernel":
            files = [Path(args.lock)]
        site = None if args.no_metadata or not spec.get("site") else site_packages(repo / spec["site"])
        if spec["kind"] == "python":
            comps = python_components(files[0], site, spec.get("closure"))
        elif spec["kind"] == "npm":
            comps = npm_components(files[0], args.include_dev)
        else:
            comps = cargo_components(files[0])
        bom = build(name, version, spec["licence"], comps, EXTRA.get(name, []), str(files[0].relative_to(repo)) if files[0].is_relative_to(repo) else files[0].name, files)
        problems = check(bom)
        target = out / f"formCAD-v{version}-{name}.cdx.json"
        target.write_text(json.dumps(bom, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        unknown = sum(1 for c in bom["components"] if "licenses" not in c)
        print(f"{target.name}: {len(bom['components'])} components, {unknown} without a licence field, {'valid' if not problems else problems[:3]}")
        failed = failed or bool(problems)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
