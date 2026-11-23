import math

from helpers import idle, inked, lines, new_drawing, quiet_pointer, type_in, until, zoom_to

ON_LINE = [(10, 0), (35, 0), (65, 0), (90, 0)]
OFF_LINE = [(-60, 0), (-30, 0), (130, 0), (160, 0)]


def _drafting(page, api, height: float = 338):
    new_drawing(page, api)
    type_in(page, "OSMODE", "0")
    type_in(page, "SNAPMODE", "0")
    return zoom_to(page, api, 0, 0, height)


def test_a_line_typed_on_the_command_line_is_held_by_the_engine_and_drawn_on_the_canvas(page, api):
    view = _drafting(page, api)
    type_in(page, "LINE", "0,0", "100,0", "")
    idle(api)
    assert lines(api) == [((0.0, 0.0), (100.0, 0.0))]
    quiet_pointer(page)
    assert inked(page, view, ON_LINE) == [True] * 4
    assert inked(page, view, OFF_LINE) == [False] * 4


def test_a_line_drawn_by_two_clicks_ends_where_the_clicks_map_in_drawing_units(page, api):
    view = _drafting(page, api)
    first, second = (-40.0, -15.0), (30.0, 45.0)
    type_in(page, "LINE")
    page.mouse.click(*view.screen(*first))
    page.wait_for_timeout(300)
    page.mouse.click(*view.screen(*second))
    page.wait_for_timeout(300)
    page.locator(".cv-cmd-input").press("Enter")
    idle(api)
    [(start, end)] = lines(api)
    tol = 0.5 / view.scale
    assert math.dist(start, first) <= tol and math.dist(end, second) <= tol, (start, end)


def test_a_typed_circle_has_its_centre_and_radius_and_is_drawn_through_its_rim(page, api):
    view = _drafting(page, api)
    type_in(page, "CIRCLE", "0,0", "60")
    idle(api)
    [circle] = api.entities("circle")
    assert circle["center"][:2] == [0.0, 0.0] and abs(circle["radius"] - 60.0) < 1e-9
    quiet_pointer(page)
    rim = [(60 * math.cos(math.radians(a)), 60 * math.sin(math.radians(a))) for a in (30, 135, 210, 320)]
    inside = [(25 * math.cos(math.radians(a)), 25 * math.sin(math.radians(a))) for a in (30, 135, 210, 320)]
    assert inked(page, view, rim) == [True] * 4
    assert inked(page, view, inside) == [False] * 4


def test_escape_cancels_a_command_halfway_and_leaves_no_entity(page, api):
    _drafting(page, api)
    type_in(page, "CIRCLE", "10,10")
    state = api.state()
    assert state["active"] and state["command"] == "CIRCLE"
    page.locator(".cv-cmd-input").press("Escape")
    state = idle(api)
    assert state["history"][-1] == "*Cancel*"
    assert api.entities() == []
    assert not state["dirty"]


def test_an_unknown_command_is_named_as_unknown_in_the_history_and_changes_nothing(page, api):
    _drafting(page, api)
    rev = api.state()["rev"]
    type_in(page, "NOSUCHCOMMAND")
    until(lambda: "NOSUCHCOMMAND" in page.locator(".cv-cmd-history").inner_text(), 5, what="history line")
    shown = page.locator(".cv-cmd-history .cv-cmd-line").last.inner_text()
    assert "unknown command" in shown.lower() and "NOSUCHCOMMAND" in shown
    state = idle(api)
    assert api.entities() == [] and state["rev"] == rev


def test_the_status_bar_shows_the_drawing_coordinates_under_the_pointer(page, api):
    view = _drafting(page, api)
    page.mouse.move(*view.screen(50, 25))
    page.wait_for_timeout(300)
    page.mouse.move(*view.screen(-70, 40))
    text = until(lambda: (lambda t: t if "-70.0000" in t else None)(page.locator(".cv-status").inner_text()), 5, what="coordinates")
    assert "X -70.0000" in text.replace("\n", " ") and "Y 40.0000" in text.replace("\n", " ")
