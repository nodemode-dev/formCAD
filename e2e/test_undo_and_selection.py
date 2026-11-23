import pytest

from helpers import bluest, focus_canvas, idle, inked, lines, new_drawing, open_menu, quiet_pointer, type_in, until, zoom_to

LINE = ((-100.0, -50.0), (100.0, 50.0))
ALONG = [(-75, -37.5), (-40, -20), (40, 20), (75, 37.5)]


def _one_line(page, api):
    new_drawing(page, api)
    type_in(page, "OSMODE", "0")
    view = zoom_to(page, api, 0, 0, 338)
    type_in(page, "LINE", "%g,%g" % LINE[0], "%g,%g" % LINE[1], "")
    idle(api)
    assert lines(api) == [LINE]
    return view


def _count(api) -> int:
    return len(api.entities())


def test_ctrl_z_removes_the_line_and_ctrl_y_restores_it_in_the_engine_and_on_the_canvas(page, api):
    view = _one_line(page, api)
    quiet_pointer(page)
    assert inked(page, view, ALONG) == [True] * 4
    focus_canvas(page, view)
    page.keyboard.press("Control+z")
    until(lambda: _count(api) == 0, 5, what="undo")
    quiet_pointer(page)
    assert inked(page, view, ALONG) == [False] * 4
    page.keyboard.press("Control+y")
    until(lambda: _count(api) == 1, 5, what="redo")
    assert lines(api) == [LINE]
    quiet_pointer(page)
    assert inked(page, view, ALONG) == [True] * 4


def test_undo_and_redo_from_the_edit_menu_remove_and_restore_the_line(page, api):
    focus_canvas(page, _one_line(page, api))
    open_menu(page, "Edit").get_by_role("menuitem", name="Undo").first.click()
    until(lambda: _count(api) == 0, 5, what="undo")
    open_menu(page, "Edit").get_by_role("menuitem", name="Redo").first.click()
    until(lambda: _count(api) == 1, 5, what="redo")
    assert lines(api) == [LINE]


def test_clicking_a_line_selects_it_in_the_engine_and_shows_grips_at_its_ends(page, api):
    view = _one_line(page, api)
    handle = api.entities("line")[0]["handle"]
    quiet_pointer(page)
    assert bluest(page, *view.screen(*LINE[1])) < 60
    page.mouse.click(*view.screen(50, 25))
    until(lambda: api.state()["selection"] == [handle], 5, what="selection")
    quiet_pointer(page)
    assert bluest(page, *view.screen(*LINE[0])) >= 120
    assert bluest(page, *view.screen(*LINE[1])) >= 120


def test_the_delete_key_erases_the_selected_line_and_undo_brings_it_back(page, api):
    view = _one_line(page, api)
    page.mouse.click(*view.screen(50, 25))
    until(lambda: api.state()["selection"], 5, what="selection")
    page.keyboard.press("Delete")
    until(lambda: _count(api) == 0, 5, what="erase")
    quiet_pointer(page)
    assert inked(page, view, ALONG) == [False] * 4
    page.keyboard.press("Control+z")
    until(lambda: _count(api) == 1, 5, what="undo")
    assert lines(api) == [LINE]


@pytest.mark.xfail(strict=True, reason="DEFECT: the dock's Properties panel body stays invisible (the part pane rule .pp in part.css sets visibility hidden on the shared .pp class), so a selected line's colour cannot be changed there; manual chapter 2 lists properties as the way to edit layers and properties.")
def test_choosing_red_in_the_properties_panel_makes_the_selected_line_red(page, api):
    view = _one_line(page, api)
    page.mouse.click(*view.screen(50, 25))
    until(lambda: api.state()["selection"], 5, what="selection")
    colour = page.locator("[data-panel=properties] button.cv-dd-btn[aria-label=Color]").filter(visible=True).first
    colour.click(timeout=3000)
    page.locator(".cv-dd-pop:not([hidden]) [role=option]", has_text="Red").first.click(timeout=3000)
    until(lambda: api.entities("line")[0]["color"] == 1, 5, what="red line")


def test_turning_a_layer_off_in_the_layers_panel_hides_its_line_and_on_shows_it_again(page, api):
    new_drawing(page, api)
    type_in(page, "OSMODE", "0")
    view = zoom_to(page, api, 0, 0, 338)
    type_in(page, "-LAYER", "M", "WALLS", "")
    type_in(page, "LINE", "%g,%g" % LINE[0], "%g,%g" % LINE[1], "")
    idle(api)
    assert api.entities("line")[0]["layer"] == "WALLS"

    def walls_on() -> bool:
        return next(l["on"] for l in api.snapshot()["tables"]["layers"] if l["name"] == "WALLS")

    page.locator("[data-panel=layers] .lp-disc").click()
    bulb = page.locator('[data-panel=layers] .lp-list .lp-row[data-key="WALLS"] [data-t="on"]')
    bulb.click()
    until(lambda: walls_on() is False, 5, what="layer off")
    quiet_pointer(page)
    assert inked(page, view, ALONG) == [False] * 4
    bulb.click()
    until(lambda: walls_on() is True, 5, what="layer on")
    quiet_pointer(page)
    assert inked(page, view, ALONG) == [True] * 4
