import hashlib
import http.server
import io
import json
import subprocess
import tarfile
import threading

import numpy as np
import pytest

pytestmark = [pytest.mark.kernel, pytest.mark.mesher]

SIZE = (10.0, 20.0, 30.0)


@pytest.fixture()
def box_brep(kernel, tmp_path):
    made = kernel.call("primitive", {"kind": "box", "dx": SIZE[0], "dy": SIZE[1], "dz": SIZE[2]})
    path = tmp_path / "box.brep"
    kernel.call("shape_save", {"id": made["id"], "path": str(path)})
    yield str(path)
    kernel.call("shape_free", {"id": made["id"]})


def tet_volumes(npz):
    with np.load(npz) as z:
        p = z["nodes"][z["tets"]]
    return np.einsum("ij,ij->i", np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), p[:, 3] - p[:, 0]) / 6.0


def mesh(mesher, brep, tmp_path, maxh, name="m.npz", **extra):
    out = str(tmp_path / name)
    return mesher.call("mesh", {"path": brep, "out": out, "maxh": maxh, **extra}), out


def test_the_mesher_greets_with_protocol_one_in_millimetres_and_lists_its_methods(mesher):
    hello = mesher.call("hello")
    assert hello["protocol"] == 1 and hello["units"] == "mm"
    assert {"hello", "faces", "mesh"} <= set(hello["methods"])


def test_the_mesher_answers_a_bad_line_and_an_unknown_method_with_errors_and_keeps_serving(mesher):
    command = mesher.resolve()[0]
    lines = "this is not json\n" + json.dumps({"id": 7, "method": "no_such_method"}) + "\n" + json.dumps({"id": 8, "method": "hello"}) + "\n" + json.dumps({"id": 9, "method": "shutdown"}) + "\n"
    done = subprocess.run(command, input=lines, capture_output=True, text=True, timeout=120)
    replies = [json.loads(x) for x in done.stdout.splitlines() if x.strip()]
    assert [r.get("id") for r in replies] == [None, 7, 8, 9]
    assert "error" in replies[0] and "error" in replies[1]
    assert "no_such_method" in replies[1]["error"]["message"]
    assert replies[2]["result"]["protocol"] == 1
    assert replies[3]["result"] == {"ok": True}
    assert done.returncode == 0


@pytest.mark.parametrize("params, words", [
    ({"path": "/nonexistent/box.brep", "out": "/tmp/x.npz"}, "not found"),
    ({"path": "BREP", "out": "/tmp/x.txt"}, ".npz"),
    ({"path": "BREP", "out": "OUT", "maxh": -1.0}, "positive"),
])
def test_the_mesher_refuses_bad_input_with_a_reason(mesher, box_brep, tmp_path, params, words):
    params = {k: (box_brep if v == "BREP" else str(tmp_path / "m.npz") if v == "OUT" else v) for k, v in params.items()}
    with pytest.raises(mesher.MesherError) as err:
        mesher.call("mesh", params)
    assert words in str(err.value)


def test_the_mesher_reports_the_six_faces_area_and_volume_of_a_box(mesher, box_brep):
    a, b, c = SIZE
    got = mesher.call("faces", {"path": box_brep})
    assert got["solids"] == 1 and len(got["faces"]) == 6
    assert sorted(round(f["area"], 6) for f in got["faces"]) == sorted([a * b, a * b, b * c, b * c, a * c, a * c])
    assert got["volume"] == pytest.approx(a * b * c, rel=1e-9)


def test_a_box_meshes_to_tetrahedra_whose_volumes_sum_to_the_box(mesher, box_brep, tmp_path):
    info, out = mesh(mesher, box_brep, tmp_path, 5.0)
    vols = tet_volumes(out)
    assert len(vols) == info["tets"] > 0
    assert abs(vols.sum()) == pytest.approx(SIZE[0] * SIZE[1] * SIZE[2], rel=1e-9)


def test_every_tetrahedron_has_a_nonzero_volume_of_one_orientation(mesher, box_brep, tmp_path):
    _info, out = mesh(mesher, box_brep, tmp_path, 4.0)
    vols = tet_volumes(out)
    assert np.all(np.sign(vols) == np.sign(vols[0]))
    assert np.abs(vols).min() > 1e-6 * 4.0 ** 3


def test_a_finer_element_size_gives_more_elements(mesher, box_brep, tmp_path):
    counts = [mesh(mesher, box_brep, tmp_path, s, "m%g.npz" % s)[0]["tets"] for s in (10.0, 5.0, 2.5)]
    assert counts[0] < counts[1] < counts[2]
    assert counts[2] > 3 * counts[1]


def test_second_order_midside_nodes_on_a_cylinder_wall_lie_on_the_curved_surface(mesher, kernel, tmp_path):
    radius, height = 10.0, 20.0
    made = kernel.call("primitive", {"kind": "cylinder", "radius": radius, "height": height})
    brep = str(tmp_path / "cyl.brep")
    kernel.call("shape_save", {"id": made["id"], "path": brep})
    kernel.call("shape_free", {"id": made["id"]})
    info, out = mesh(mesher, brep, tmp_path, 5.0, second_order=True)
    assert info["curved"] is True
    with np.load(out) as z:
        nodes, pairs, mids = z["nodes"], z["edge_mid_pairs"], z["edge_mid_xyz"]
    r = np.hypot(nodes[:, 0], nodes[:, 1])
    on_wall = (np.abs(r[pairs[:, 0]] - radius) < 1e-6) & (np.abs(r[pairs[:, 1]] - radius) < 1e-6)
    around = np.abs(np.arctan2(nodes[pairs[:, 0], 1], nodes[pairs[:, 0], 0]) - np.arctan2(nodes[pairs[:, 1], 1], nodes[pairs[:, 1], 0])) > 1e-3
    chosen = on_wall & around
    assert chosen.sum() > 20
    straight = 0.5 * (nodes[pairs[chosen, 0]] + nodes[pairs[chosen, 1]])
    assert np.all(np.hypot(straight[:, 0], straight[:, 1]) < radius - 1e-4)
    assert np.allclose(np.hypot(mids[chosen, 0], mids[chosen, 1]), radius, atol=1e-6 * radius)


def test_a_plane_selector_names_the_one_face_on_that_plane(mesher, box_brep, tmp_path):
    info, _out = mesh(mesher, box_brep, tmp_path, 10.0, groups={"top": {"plane": {"axis": "z", "value": SIZE[2]}}, "side": {"plane": {"axis": "x", "value": 0.0}}})
    faces = mesher.call("faces", {"path": box_brep})["faces"]
    top = faces[info["groups"]["top"][0]]
    side = faces[info["groups"]["side"][0]]
    assert len(info["groups"]["top"]) == 1 and len(info["groups"]["side"]) == 1
    assert top["center"][2] == pytest.approx(SIZE[2]) and top["area"] == pytest.approx(SIZE[0] * SIZE[1])
    assert side["center"][0] == pytest.approx(0.0) and side["area"] == pytest.approx(SIZE[1] * SIZE[2])


def test_a_mesh_over_the_element_cap_is_refused_before_it_is_written(mesher, box_brep, tmp_path):
    with pytest.raises(mesher.MesherError) as err:
        mesh(mesher, box_brep, tmp_path, 0.5, max_elements=1000)
    assert "limit" in str(err.value)
    assert not (tmp_path / "m.npz").exists()


class Server:
    def __init__(self, payload: bytes):
        body = payload

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d/mesher.tar.gz" % self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def bundle(folder: str, files: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo("%s/%s" % (folder, name))
            info.size = len(data)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture()
def install_env(mesher, repo, monkeypatch):
    monkeypatch.setenv("FORMCAD_MESHER", str(repo / "mesher" / "formcad_mesher.py"))
    release = "0.0.1-lanetest"
    target = mesher.root() / release
    yield release, target
    import shutil

    shutil.rmtree(target, ignore_errors=True)
    mesher._set("", 0.0, False)
    monkeypatch.undo()
    mesher.refresh()


def install(mesher, release, files, recorded):
    triple = "x86_64-unknown-linux-gnu"
    folder = "mesher-test-%s" % release
    rec = {"folder": folder, "files": [{"triple": triple, "path": p, "sha256": hashlib.sha256(d).hexdigest()} for p, d in recorded.items()]}
    server = Server(bundle(folder, files))
    try:
        rec["url"] = server.url
        mesher.run_install(rec, release, triple)
    finally:
        server.close()
    return mesher.status()["message"]


def test_the_mesher_install_puts_files_in_place_only_when_every_file_matches_the_record(mesher, install_env):
    release, target = install_env
    files = {"formcad-mesher": b"#!/bin/sh\nexit 3\n", "README.md": b"mesher\n"}
    message = install(mesher, release, files, files)
    assert "installed" in message.lower()
    assert (target / "formcad-mesher").read_bytes() == files["formcad-mesher"]
    assert (target / "README.md").read_bytes() == files["README.md"]


@pytest.mark.parametrize("case", ["changed", "extra", "missing"])
def test_the_mesher_install_refuses_a_download_that_differs_from_the_record(mesher, install_env, case):
    release, target = install_env
    recorded = {"formcad-mesher": b"#!/bin/sh\nexit 3\n", "README.md": b"mesher\n"}
    sent = dict(recorded)
    if case == "changed":
        sent["formcad-mesher"] = b"#!/bin/sh\necho tampered\n"
    elif case == "extra":
        sent["extra.bin"] = b"\x00"
    else:
        del sent["README.md"]
    message = install(mesher, release, sent, recorded)
    assert "Nothing was installed" in message
    assert not target.exists()
