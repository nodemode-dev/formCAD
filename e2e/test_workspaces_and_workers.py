import pytest

from conftest import READY
from helpers import in_view, new_drawing, panel_label, pick_workspace, until

WORKSPACES = ["Drafting", "Part", "Assembly", "Surface", "Form", "Drawing", "Graph", "Manufacture", "Simulate", "Render", "Electronics"]


def test_every_workspace_in_the_picker_can_be_chosen_without_error_and_is_kept_after_a_reload(page, api):
    new_drawing(page, api)
    for name in WORKSPACES[1:] + WORKSPACES[:1]:
        pick_workspace(page, name)
        page.wait_for_timeout(300)
    pick_workspace(page, "Render")
    page.reload()
    page.wait_for_selector(READY, timeout=60000)
    assert page.locator(".cv-dd-btn.cv-tt-select .cv-dd-label").inner_text() == "Render"


@pytest.mark.parametrize("workspace, panel, title", [
    ("Form", "form", "Form"),
    ("Manufacture", "camsim", "Simulation"),
    ("Simulate", "simresult", "Simulation results"),
])
def test_choosing_a_workspace_brings_its_own_panel_into_view(page, api, workspace, panel, title):
    new_drawing(page, api)
    assert not in_view(page, panel)
    pick_workspace(page, workspace)
    until(lambda: in_view(page, panel), 5, what="%s panel in view" % panel)
    assert panel_label(page, panel) == title


def test_the_studies_panel_shows_the_mesher_version_the_engine_reports(page, api):
    doc = new_drawing(page, api)
    reported = api.get("/api/docs/%s/sim/status" % doc)
    pick_workspace(page, "Simulate")
    note = page.locator(".sm-mesher")
    until(lambda: note.inner_text().strip(), 10, what="mesher note")
    if reported["available"]:
        assert note.inner_text().strip() == "Mesher %s" % reported["version"]
    else:
        assert "not installed" in note.inner_text()
        assert page.get_by_role("button", name="Install mesher").is_visible()


def test_the_status_bar_kernel_button_shows_the_kernel_state_the_engine_reports(page, api):
    reported = api.get("/api/kernel/status")
    new_drawing(page, api)
    button = page.locator(".cv-st-kernel")
    text = until(lambda: button.inner_text().strip(), 10, what="kernel text")
    if reported["available"]:
        assert text == "Kernel %s" % reported["version"]
        assert button.is_disabled()
        assert "is-ready" in button.get_attribute("class")
    else:
        assert text == "Install kernel" and button.is_enabled()
