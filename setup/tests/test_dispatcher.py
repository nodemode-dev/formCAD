import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(sys.platform.startswith("win"), reason="the bash dispatcher serves macOS and Linux; Windows uses formCAD.bat")


def dispatcher(*args, timeout: int = 180):
    return subprocess.run([str(REPO / "formCAD"), *args], cwd=REPO, capture_output=True, text=True, timeout=timeout)


def engine_version() -> str:
    out = subprocess.run([sys.executable, "-c", "import app; print(app.__version__)"], cwd=REPO / "backend", capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_version_prints_the_version_the_engine_reports():
    out = dispatcher("version")
    assert out.returncode == 0
    found = re.match(r"FormCAD (\d+\.\d+\.\d+)", out.stdout)
    assert found, out.stdout
    assert found.group(1) == engine_version()


def test_every_place_a_build_reads_the_version_agrees():
    want = engine_version()
    package = json.loads((REPO / "frontend" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((REPO / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    tauri = json.loads((REPO / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    cargo = tomllib.loads((REPO / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8"))
    cargo_lock = tomllib.loads((REPO / "src-tauri" / "Cargo.lock").read_text(encoding="utf-8"))
    form_app = json.loads((REPO / "apps" / "form-app.json").read_text(encoding="utf-8"))
    locked = [p["version"] for p in cargo_lock["package"] if p["name"] == cargo["package"]["name"]]
    seen = {
        "frontend/package.json": package["version"],
        "frontend/package-lock.json": lock["version"],
        "frontend/package-lock.json root package": lock["packages"][""]["version"],
        "src-tauri/tauri.conf.json": tauri["version"],
        "src-tauri/Cargo.toml": cargo["package"]["version"],
        "src-tauri/Cargo.lock": locked[0] if locked else None,
        "apps/form-app.json": form_app["version"],
    }
    assert {place: v for place, v in seen.items() if v != want} == {}


def test_an_unknown_command_exits_2_and_prints_the_usage():
    out = dispatcher("no-such-command")
    assert out.returncode == 2
    assert "unknown command: no-such-command" in out.stdout
    assert "usage: ./formCAD" in out.stdout


def test_an_unknown_test_layer_exits_2_and_names_the_layers():
    out = dispatcher("test", "no-such-layer")
    assert out.returncode == 2
    for layer in ("unit", "engine", "workers", "browser", "scripts"):
        assert layer in out.stdout


def test_doctor_passes_on_an_installed_tree_and_names_what_it_checked():
    out = dispatcher("doctor")
    assert out.returncode == 0, out.stdout
    assert "FAIL" not in out.stdout
    for item in ("node", "python", "engine venv", "frontend node_modules"):
        assert re.search(r"ok\s+%s" % re.escape(item), out.stdout), out.stdout


def copy_of_the_tree(tmp_path: Path) -> Path:
    target = tmp_path / "tree"
    target.mkdir()
    made = subprocess.run(["git", "checkout-index", "-a", "--prefix=%s/" % target], cwd=REPO, capture_output=True, text=True, timeout=120)
    if made.returncode != 0:
        pytest.skip("this checkout has no git index to copy from: %s" % made.stderr.strip()[:200])
    return target


def agents_check(tree: Path):
    return subprocess.run([sys.executable, "setup/agents.py", "check"], cwd=tree, capture_output=True, text=True, timeout=180, env={**os.environ, "FORMCAD_ROOT": str(tree)})


def test_the_agent_kit_check_passes_on_a_clean_tree_and_fails_when_a_mirrored_skill_drifts(tmp_path):
    tree = copy_of_the_tree(tmp_path)
    clean = agents_check(tree)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    mirrored = sorted((tree / ".claude" / "skills").rglob("SKILL.md"))
    assert mirrored
    mirrored[0].write_text(mirrored[0].read_text(encoding="utf-8") + "\nA line the source skill does not have.\n", encoding="utf-8")
    drifted = agents_check(tree)
    assert drifted.returncode != 0
    assert "skills" in (drifted.stdout + drifted.stderr)


def test_the_hole_and_fastener_tables_match_their_generator_and_a_changed_table_is_caught(tmp_path):
    tree = copy_of_the_tree(tmp_path)
    clean = subprocess.run([sys.executable, "setup/hole_tables.py", "--check"], cwd=tree, capture_output=True, text=True, timeout=180)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    for name in ("hole-sizes.json", "fastener-sizes.json"):
        table = tree / "backend" / "app" / "data" / name
        kept = table.read_text(encoding="utf-8")
        table.write_text(kept.rstrip() + " ", encoding="utf-8")
        changed = subprocess.run([sys.executable, "setup/hole_tables.py", "--check"], cwd=tree, capture_output=True, text=True, timeout=180)
        assert changed.returncode != 0, name
        table.write_text(kept, encoding="utf-8")
