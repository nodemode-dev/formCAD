import json
import math

import pytest

from tests.automation.graphs import Builder, values


def chain() -> Builder:
    b = Builder("chain")
    b.output("o_sum", "doubled", "m", "result")
    b.node("m", "math.multiply", {"a": None, "b": 2}, ["result"])
    b.node("a", "math.add", {"a": None, "b": None}, ["result"])
    b.node("s", "math.series", {"start": 0, "step": 1, "count": 5}, ["series"])
    b.slider("k", "k", 10)
    b.node("lone", "math.sqrt", {"value": 16}, ["result"])
    b.output("o_root", "root", "lone", "result")
    b.wire("s", "series", "a", "a")
    b.wire("k", "value", "a", "b")
    b.wire("a", "result", "m", "a")
    return b


def run(engine, defn: dict, **body) -> dict:
    return engine.post("/api/graph/run", dict(body, graph=defn))


def solve(doc, gid: str) -> dict:
    return doc.post("/graphs/%s/solve" % gid, {})


def test_a_graph_evaluates_its_nodes_in_dependency_order_whatever_order_they_were_created_in(engine):
    out = run(engine, chain().definition())
    assert out["ok"] is True
    assert values(out, "doubled") == pytest.approx([(i + 10) * 2 for i in range(5)], abs=1e-12)
    assert values(out, "root") == pytest.approx([4.0], abs=1e-12)


def test_a_named_input_given_to_a_run_replaces_the_slider_value(engine):
    out = run(engine, chain().definition(), inputs={"k": 100})
    assert values(out, "doubled") == pytest.approx([(i + 100) * 2 for i in range(5)], abs=1e-12)


def test_the_graph_io_route_lists_the_named_inputs_and_outputs(engine):
    io = engine.post("/api/graph/io", {"graph": chain().definition()})
    assert [(i["name"], i["default"]) for i in io["inputs"]] == [("k", 10)]
    assert sorted(o["name"] for o in io["outputs"]) == ["doubled", "root"]


def test_a_wire_that_closes_a_loop_is_disabled_on_load_and_its_nodes_report_cycle(engine):
    b = chain()
    b.wire("m", "result", "s", "start")
    out = run(engine, b.definition())
    assert out["ok"] is False
    assert {m["node"] for m in out["messages"] if m["code"] == "CYCLE"} == {"s", "m"}
    assert values(out, "doubled") == pytest.approx([(i + 10) * 2 for i in range(5)], abs=1e-12)


def test_the_editor_refuses_a_wire_that_would_make_a_loop_and_names_the_nodes_in_it(engine, doc):
    gid = doc.post("/graphs", {"name": "loop", "definition": chain().definition()})["id"]
    r = engine.raw("PATCH", doc.url("/graphs/%s" % gid), json={"ops": [{"op": "connect", "from": "m:result", "to": "s:start"}]})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "cycle" and set(detail["path"]) == {"s", "a", "m"}
    for name in ("Series", "Add", "Multiply"):
        assert name in detail["message"]
    r = engine.raw("PATCH", doc.url("/graphs/%s" % gid), json={"ops": [{"op": "connect", "from": "a:result", "to": "a:b"}]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "selfloop"


def test_changing_one_input_recomputes_only_the_nodes_that_depend_on_it(engine, doc):
    gid = doc.post("/graphs", {"name": "inc", "definition": chain().definition()})["id"]
    first = solve(doc, gid)
    assert set(first["report"]["ran"]) == set(first["nodes"])
    engine.call("PATCH", doc.url("/graphs/%s" % gid), json={"ops": [{"op": "set", "id": "s", "persistent": {"port": "count", "value": 3}}], "solve": False})
    second = solve(doc, gid)
    assert set(second["report"]["ran"]) == {"s", "a", "m", "o_sum"}
    assert second["nodes"]["o_sum"]["outputs"]["value"]["first"] == ["20.0", "22.0", "24.0"]
    assert second["nodes"]["o_root"]["outputs"]["value"]["first"] == ["4.0"]


def test_the_solve_order_puts_every_node_after_the_nodes_wired_into_it(doc):
    b = chain()
    gid = doc.post("/graphs", {"name": "order", "definition": b.definition()})["id"]
    order = solve(doc, gid)["report"]["order"]
    assert sorted(order) == sorted(n["id"] for n in b.nodes)
    for w in b.wires:
        src, dst = w["from"].split("_o_")[0], w["to"].split("_i_")[0]
        assert order.index(src) < order.index(dst), w


def test_a_disabled_node_computes_nothing_and_its_outputs_are_empty(doc):
    b = chain()
    b.nodes[1]["enabled"] = False
    gid = doc.post("/graphs", {"name": "off", "definition": b.definition()})["id"]
    report = solve(doc, gid)["report"]
    assert "m" not in report["ran"]
    tree = doc.get("/graphs/%s/tree/m/result" % gid)
    assert tree["items"] == 0 and tree["page"] == []
    assert doc.get("/graphs/%s/tree/lone/result" % gid)["page"][0]["items"] == ["4.0"]


def test_graph_edits_are_document_edits_that_undo_and_redo(engine, doc):
    gid = doc.post("/graphs", {"name": "undo", "definition": chain().definition()})["id"]
    engine.call("PATCH", doc.url("/graphs/%s" % gid), json={"ops": [{"op": "remove_node", "id": "lone"}]})
    assert "lone" not in [n["id"] for n in doc.get("/graphs/%s" % gid)["definition"]["nodes"]]
    doc.undo()
    assert "lone" in [n["id"] for n in doc.get("/graphs/%s" % gid)["definition"]["nodes"]]
    doc.redo()
    assert "lone" not in [n["id"] for n in doc.get("/graphs/%s" % gid)["definition"]["nodes"]]


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(format="something.else"),
        lambda d: d.update(nodes={"a": 1}),
        lambda d: d.update(wires="w1"),
    ],
    ids=["wrong format", "nodes not a list", "wires not a list"],
)
def test_a_malformed_graph_is_refused_as_a_whole(engine, change):
    defn = chain().definition()
    change(defn)
    r = engine.raw("POST", "/api/graph/run", json={"graph": defn})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "schema"


def test_a_graph_over_the_node_limit_is_refused_with_the_count_and_the_limit(engine):
    defn = chain().definition()
    defn["nodes"] = [{"id": "n%d" % i, "type": "math.add"} for i in range(5001)]
    message = engine.raw("POST", "/api/graph/run", json={"graph": defn}).json()["detail"]["message"]
    assert "5001" in message and "5000" in message


def test_a_graph_from_a_newer_major_version_solves_but_refuses_every_edit(engine, doc):
    defn = chain().definition()
    defn["version"] = "2.0.0"
    gid = doc.post("/graphs", {"name": "newer", "definition": defn})["id"]
    state = solve(doc, gid)
    assert state["readonly"] is True
    assert state["nodes"]["o_sum"]["outputs"]["value"]["first"] == ["20.0", "22.0", "24.0", "26.0", "28.0"]
    r = engine.raw("PATCH", doc.url("/graphs/%s" % gid), json={"ops": [{"op": "remove_node", "id": "lone"}]})
    assert r.status_code >= 400 and "newer version" in r.text


def test_unknown_fields_survive_a_save_and_the_file_is_sorted_two_space_json_with_one_trailing_newline(engine, doc, tmp_path):
    defn = chain().definition()
    defn["lane11_top"] = {"kept": [1, 2]}
    defn["nodes"][2]["lane11_node"] = "kept"
    defn["wires"][0]["lane11_wire"] = 7
    gid = doc.post("/graphs", {"name": "keep", "definition": defn})["id"]
    target = tmp_path / "keep.graph"
    doc.post("/graphs/%s/export" % gid, {"path": str(target)})
    text = target.read_text(encoding="utf-8")
    data = json.loads(text)
    assert text == json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert data["format"] == "formcad.graph"
    assert data["lane11_top"] == {"kept": [1, 2]}
    assert next(n for n in data["nodes"] if n["id"] == "a")["lane11_node"] == "kept"
    assert any(w.get("lane11_wire") == 7 for w in data["wires"])


def missing_graph() -> dict:
    b = chain()
    b.node("ghost", "no-such-library/ghost", {"value": 3}, ["out"], settings={"mine": 1})
    b.wire("ghost", "out", "lone", "value")
    return b.definition()


def test_a_headless_run_that_needs_a_missing_node_type_stops_and_names_it(engine):
    r = engine.raw("POST", "/api/graph/run", json={"graph": missing_graph()})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "missing" and [m["type"] for m in detail["missing"]] == ["no-such-library/ghost"]


def test_a_missing_node_type_opens_as_a_placeholder_and_is_written_back_unchanged(engine, doc, tmp_path):
    defn = missing_graph()
    gid = doc.post("/graphs", {"name": "ghost", "definition": defn})["id"]
    state = solve(doc, gid)
    ghost = state["nodes"]["ghost"]
    assert ghost["missing"] is True and any(m["code"] == "MISSING_NODE" for m in ghost["messages"])
    target = tmp_path / "ghost.graph"
    doc.post("/graphs/%s/export" % gid, {"path": str(target)})
    saved = json.loads(target.read_text(encoding="utf-8"))
    node = next(n for n in saved["nodes"] if n["id"] == "ghost")
    assert node["type"] == "no-such-library/ghost" and node["settings"] == {"mine": 1}
    assert node["ports"]["in"][0]["persistent"]["tree"] == {"{0}": [3]}
    assert any(w["from"] == "ghost_o_out" and w["to"] == "lone_i_value" for w in saved["wires"])


PLUGIN = '''
def register(api):
    api.node(
        "hypot",
        guid="6a1f2b3c-4d5e-4f60-8a71-92b3c4d5e6f7",
        name="Hypotenuse", nick="Hyp",
        category="Lane", group="Numbers",
        description="The long side of a right triangle.",
        inputs=[api.port("a", "number", default=3.0), api.port("b", "number", default=4.0)],
        outputs=[api.port("c", "number")],
        solve=lambda ctx, a, b: (a * a + b * b) ** 0.5,
    )
'''


def write_plugin(data_dir, pid: str):
    folder = data_dir / "plugins" / pid
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plugin.py").write_text(PLUGIN, encoding="utf-8")
    (folder / "plugin.json").write_text(json.dumps({"api": 1, "id": pid, "name": pid, "version": "1.0.0", "entry": "plugin.py", "files": {}}), encoding="utf-8")
    return folder


def seal(repo, folder):
    import subprocess
    import sys

    done = subprocess.run([sys.executable, str(repo / "backend/formcad_engine.py"), "plugin", "seal", str(folder)], capture_output=True, text=True, timeout=60, cwd=str(repo / "backend"))
    assert done.returncode == 0, done.stderr


def listed(engine, pid: str) -> dict:
    return next(p for p in engine.get("/api/automation/plugins")["plugins"] if p["id"] == pid)


def hypot_graph(pid: str) -> dict:
    b = Builder("plugin")
    b.node("h", "%s/hypot" % pid, {"a": [3, 5, 8], "b": [4, 12, 15]}, ["c"])
    b.output("o", "c", "h", "c")
    return b.definition()


def test_a_node_written_to_the_sdk_loads_after_it_is_sealed_and_enabled_and_then_runs(engine, data_dir, repo):
    pid = "lane11-hypot"
    folder = write_plugin(data_dir, pid)
    seal(repo, folder)
    assert engine.raw("POST", "/api/graph/run", json={"graph": hypot_graph(pid)}).status_code == 422
    item = listed(engine, pid)
    engine.post("/api/automation/plugins/%s/enable" % pid, {"enabled": True, "manifestSha256": item["manifestSha256"]})
    out = run(engine, hypot_graph(pid))
    assert out["ok"] is True
    assert values(out, "c") == pytest.approx([5.0, 13.0, 17.0], abs=1e-12)


def test_a_plugin_file_changed_after_sealing_cannot_be_enabled(engine, data_dir, repo):
    pid = "lane11-tampered"
    folder = write_plugin(data_dir, pid)
    seal(repo, folder)
    (folder / "plugin.py").write_text(PLUGIN + "\nTAMPERED = True\n", encoding="utf-8")
    item = listed(engine, pid)
    r = engine.raw("POST", "/api/automation/plugins/%s/enable" % pid, json={"enabled": True, "manifestSha256": item.get("manifestSha256") or ""})
    assert r.status_code >= 400
    assert engine.raw("POST", "/api/graph/run", json={"graph": hypot_graph(pid)}).status_code == 422


@pytest.mark.kernel
def test_the_plate_holes_graph_gives_the_box_minus_four_holes_and_the_section_of_its_outlines(doc, fixtures):
    gid = doc.post("/graphs/import", {"path": str(fixtures / "graph/plate-holes.graph")})["id"]
    solve(doc, gid)
    volume = float(doc.get("/graphs/%s/tree/mass/volume" % gid)["page"][0]["items"][0])
    assert volume == pytest.approx(100 * 60 * 20 - 4 * math.pi * 4 ** 2 * 20, rel=1e-9)
    lengths = sorted(float(v) for v in doc.get("/graphs/%s/tree/secl/length" % gid)["page"][0]["items"])
    assert lengths == pytest.approx(sorted([2 * math.pi * 4] * 4 + [2 * (100 + 60)]), rel=1e-9)


@pytest.mark.kernel
def test_the_facade_graph_makes_one_panel_per_grid_cell_and_bakes_the_stated_volume(engine, docs, fixtures, tmp_path):
    baked = tmp_path / "facade.fcad"
    out = engine.post("/api/graph/run", {"graph_path": str(fixtures / "graph/facade.graph"), "doc_path": str(fixtures / "graph/facade-base.fcad"), "bake_path": str(baked)})
    assert out["ok"] is True
    assert values(out, "panel_count") == [8 * 5]
    assert values(out, "fitness") == pytest.approx(values(out, "open_area"), rel=1e-12)
    d = docs.open(baked)
    panels = [e["handle"] for e in d.entities("solidbody") if e["layer"] == "FACADE"]
    assert len(panels) == 40
    mass = d.command("bodymass", handles=panels)["result"]
    assert mass["volume"] == pytest.approx(1230780242.474323, rel=1e-9)


@pytest.mark.kernel
def test_the_facade_graph_follows_its_sliders_and_penalises_panels_above_the_limit(engine, fixtures):
    out = engine.post("/api/graph/run", {"graph_path": str(fixtures / "graph/facade.graph"), "doc_path": str(fixtures / "graph/facade-base.fcad"), "inputs": {"columns": 4, "rows": 2, "panel_limit": 4}})
    assert values(out, "panel_count") == [8]
    assert values(out, "fitness")[0] < values(out, "open_area")[0]
