import json
import re
import threading
import time

import pytest

BOX = {"kind": "box", "dx": 10.0, "dy": 20.0, "dz": 30.0}
RING = {"kind": "torus", "major": 10.0, "minor": 3.0}


def pid(kernel):
    return kernel._worker.process.pid


def endless_mesh(path):
    return {"linear": 0.0005, "angular": 0.05, "path": str(path)}


@pytest.mark.kernel
def test_hello_reports_the_kernel_version_protocol_units_and_its_methods(kernel, engine):
    info = kernel.call("hello")
    assert re.fullmatch(r"\d+\.\d+\.\d+", info["occt"])
    assert info["protocol"] == 2 and info["units"] == "mm"
    assert {"primitive", "boolean", "transform", "mass_properties", "shape_free", "feat_extrude", "feature_fillet", "sm_base_flange", "unfold_solid"} <= set(info["methods"])
    status = engine.get("/api/kernel/status")
    assert status["available"] is True and status["version"] == info["occt"]


@pytest.mark.kernel
def test_every_method_hello_lists_answers_an_empty_request_without_killing_the_worker(kernel):
    before = pid(kernel)
    for method in kernel.call("hello")["methods"]:
        try:
            kernel.call(method, {}, timeout=20.0)
        except kernel.KernelError as err:
            text = str(err)
            assert "Unknown method" not in text and "could not be loaded" not in text and "in time" not in text, (method, text)
        assert pid(kernel) == before, method


@pytest.mark.kernel
def test_an_unknown_method_is_refused_by_name_and_the_same_worker_answers_next(kernel):
    before = pid(kernel)
    with pytest.raises(kernel.KernelError, match="Unknown method no_such_method"):
        kernel.call("no_such_method", {})
    made = kernel.call("primitive", BOX)
    kernel.call("shape_free", {"ids": [made["id"]]})
    assert pid(kernel) == before and made["summary"]["solids"] == 1


@pytest.mark.kernel
@pytest.mark.parametrize("params, said", [
    ({"kind": "box", "dx": -1.0, "dy": 1.0, "dz": 1.0}, "dx must be positive"),
    ({"kind": "box", "dx": "wide", "dy": 1.0, "dz": 1.0}, "wide"),
    ({"kind": "pyramid"}, "Unknown primitive pyramid"),
])
def test_bad_parameters_come_back_as_an_error_and_the_worker_lives_on(kernel, params, said):
    before = pid(kernel)
    with pytest.raises(kernel.KernelError, match=said):
        kernel.call("primitive", params)
    assert kernel.call("hello")["protocol"] == 2
    assert pid(kernel) == before


@pytest.mark.kernel
def test_a_line_that_is_not_json_gets_an_error_reply_and_the_worker_keeps_serving(kernel):
    worker = kernel.Worker(kernel.resolve()[0])
    try:
        assert worker.call("hello", timeout=60.0)["protocol"] == 2
        worker.process.stdin.write("this is not json\n")
        worker.process.stdin.flush()
        reply = json.loads(worker.lines.get(timeout=10.0))
        assert reply["id"] is None and "not a JSON object" in reply["error"]["message"]
        made = worker.call("primitive", BOX)
        assert made["summary"]["faces"] == 6 and worker.alive()
    finally:
        worker.stop()
    assert not worker.alive()


@pytest.mark.kernel
def test_a_call_that_runs_past_its_time_limit_is_reported_and_a_fresh_worker_takes_the_next_call(kernel, tmp_path):
    ring = kernel.call("primitive", RING)
    before = pid(kernel)
    started = time.monotonic()
    with pytest.raises(kernel.KernelError, match="did not answer tessellate in time"):
        kernel.call("tessellate", {"id": ring["id"], **endless_mesh(tmp_path / "ring.mesh")}, timeout=1.0)
    assert time.monotonic() - started < 10.0
    made = kernel.call("primitive", BOX)
    assert pid(kernel) != before and made["summary"]["bbox"] == [0.0, 0.0, 0.0, 10.0, 20.0, 30.0]


@pytest.mark.kernel
def test_a_worker_killed_in_the_middle_of_a_call_is_reported_and_a_fresh_worker_comes_up(kernel, tmp_path):
    ring = kernel.call("primitive", RING)
    victim = kernel._worker.process
    outcome = {}

    def long_call():
        try:
            outcome["result"] = kernel.call("tessellate", {"id": ring["id"], **endless_mesh(tmp_path / "ring.mesh")}, timeout=60.0)
        except kernel.KernelError as err:
            outcome["error"] = str(err)

    runner = threading.Thread(target=long_call)
    runner.start()
    time.sleep(1.0)
    victim.kill()
    runner.join(30.0)
    victim.wait(10)
    assert not runner.is_alive()
    assert "result" not in outcome and "exited" in outcome["error"]
    with pytest.raises(kernel.KernelError, match="No shape"):
        kernel.call("shape_summary", {"id": ring["id"]})
    assert pid(kernel) != victim.pid
    made = kernel.call("primitive", BOX)
    props = kernel.call("mass_properties", {"id": made["id"]})
    assert props["volume"] == pytest.approx(6000.0, rel=1e-9)


@pytest.mark.kernel
def test_solid_bodies_in_an_open_document_survive_a_kernel_restart(kernel, doc):
    doc.set_var("INSUNITS", 4)
    doc.command("box", corner=[0, 0, 0], size=[10, 20, 30])
    doc.command("cylinder", center=[50, 0, 0], radius=5, height=10)
    expected = 6000.0 + 3.141592653589793 * 25.0 * 10.0
    assert doc.post("/bodies/massprops", {})["volume"] == pytest.approx(expected, rel=1e-9)
    kernel._worker.process.kill()
    kernel._worker.process.wait(10)
    assert doc.post("/bodies/massprops", {})["volume"] == pytest.approx(expected, rel=1e-9)
