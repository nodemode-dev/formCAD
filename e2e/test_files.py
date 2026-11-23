import uuid

import pytest

from conftest import READY
from helpers import idle, new_drawing, open_menu, path_dialog, type_in, until


def _geometry(api) -> list:
    keep = ("kind", "layer", "start", "end", "center", "radius")
    return sorted((tuple((k, repr(e.get(k))) for k in keep)) for e in api.entities())


def _draw_two(page, api) -> list:
    new_drawing(page, api)
    type_in(page, "LINE", "-100,-50", "100,50", "")
    type_in(page, "CIRCLE", "10,20", "30")
    idle(api)
    return _geometry(api)


def _save_as(page, path) -> None:
    page.keyboard.press("Control+Shift+s")
    dialog = path_dialog(page)
    assert dialog.locator(".cv-dialog-title").inner_text() == "Save As"
    dialog.get_by_label("File path").fill(str(path))
    dialog.get_by_role("button", name="Save").click()


@pytest.fixture()
def target(data_dir):
    made = []

    def make(folder=None):
        p = (folder or data_dir) / ("lane13_%s.fcad" % uuid.uuid4().hex[:8])
        made.append(p)
        return p
    yield make
    for p in made:
        p.unlink(missing_ok=True)


def test_save_as_writes_a_file_that_opens_after_a_reload_with_the_same_entities(page, api, target):
    path = target()
    drawn = _draw_two(page, api)
    _save_as(page, path)
    until(lambda: path.is_file() and not api.docs()[0]["dirty"], 10, what="saved file")
    assert api.docs()[0]["path"] == str(path)
    page.locator(".cv-tab.is-dirty").wait_for(state="detached", timeout=5000)
    page.locator(".cv-tab .cv-tab-close").first.click()
    until(lambda: api.docs() == [], 5, what="closed without a prompt")
    page.reload()
    page.wait_for_selector(READY, timeout=60000)
    page.keyboard.press("Control+o")
    dialog = path_dialog(page)
    dialog.get_by_label("File path").fill(str(path))
    dialog.get_by_role("button", name="Open").click()
    until(lambda: api.docs(), 10, what="reopened drawing")
    assert _geometry(api) == drawn
    assert page.locator(".cv-tab.is-active .cv-tab-name").inner_text() == path.stem


def test_closing_a_changed_drawing_asks_to_save_and_cancel_keeps_it_while_dont_save_drops_it(page, api, data_dir):
    new_drawing(page, api)
    type_in(page, "LINE", "0,0", "10,10", "")
    idle(api)
    name = api.docs()[0]["name"]
    page.locator(".cv-tab.is-dirty").wait_for(timeout=5000)
    close = page.locator(".cv-tab .cv-tab-close").first
    close.click()
    dialog = path_dialog(page)
    assert dialog.locator(".cv-dialog-title").inner_text() == "Unsaved Changes"
    assert dialog.locator(".cv-save-q strong").inner_text() == name
    dialog.get_by_role("button", name="Cancel").click()
    dialog.wait_for(state="hidden")
    assert [d["name"] for d in api.docs()] == [name] and len(api.entities("line")) == 1
    close.click()
    path_dialog(page).get_by_role("button", name="Don’t Save").click()
    until(lambda: api.docs() == [], 5, what="drawing closed")
    assert not list(data_dir.glob("%s.fcad" % name))


def test_a_drawing_saved_in_the_projects_folder_is_listed_in_recent_and_opens_from_there(page, api, data_dir, target):
    path = target(data_dir / "Projects")
    _draw_two(page, api)
    _save_as(page, path)
    until(lambda: path.is_file(), 10, what="saved file")
    menu = open_menu(page, "File")
    menu.get_by_role("menuitem", name="Open Recent").hover()
    until(lambda: page.locator(".cv-menu[role=menu]:not([hidden])", has_text=path.name).count() > 0, 5, what="recent entry in the File menu")
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")
    page.locator(".cv-menu[role=menu]:not([hidden])").first.wait_for(state="hidden", timeout=5000)
    page.locator(".cv-tab.is-dirty").wait_for(state="detached", timeout=5000)
    page.locator(".cv-tab .cv-tab-close").first.click()
    until(lambda: api.docs() == [], 5, what="closed")
    item = page.locator(".cv-hf-item", has_text=path.name).filter(visible=True).first
    item.wait_for(state="visible", timeout=10000)
    item.click()
    until(lambda: api.docs() and api.docs()[0]["path"] == str(path), 10, what="opened from recent")
