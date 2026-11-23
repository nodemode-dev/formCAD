from conftest import dom_report, throttle, watch_dom
from helpers import idle, new_drawing, open_menu, type_in, until

KEPT = [".cv-canvas-scene", ".cv-cmd", ".cv-menubar", "[data-panel=layers] > .cv-group-body", "[data-panel=properties] > .cv-group-body"]


def _hold(page, selectors) -> list:
    return [(s, page.evaluate_handle("(s) => document.querySelector(s)", s)) for s in selectors]


def _still_same(page, held) -> list:
    return [s for s, h in held if not page.evaluate("([n, s]) => !!n && n.isConnected && n === document.querySelector(s)", [h, s])]


def _box(page) -> dict:
    return page.locator(".cv-canvas-scene").bounding_box()


def test_drawing_a_line_under_slow_cpu_keeps_the_shell_and_canvas_nodes_and_layout(page, api):
    new_drawing(page, api)
    throttle(page, 4)
    held = _hold(page, KEPT)
    box = _box(page)
    watch_dom(page)
    type_in(page, "LINE", "0,0", "100,50", "")
    idle(api)
    report = dom_report(page)
    assert report["sameRoot"] and not report["rootReplaced"], report
    assert _still_same(page, held) == []
    assert _box(page) == box
    assert len(api.entities("line")) == 1


def test_switching_to_a_layout_tab_and_back_under_slow_cpu_keeps_the_shell_mounted(page, api):
    new_drawing(page, api)
    throttle(page, 4)
    held = _hold(page, KEPT)
    watch_dom(page)
    page.locator(".cv-lt-strip .cv-lt-tab", has_text="Layout1").click()
    until(lambda: api.docs()[0]["tab"] == "layout:Layout1", 10, what="paper space")
    page.locator(".cv-lt-strip .cv-lt-tab", has_text="Model").click()
    until(lambda: api.docs()[0]["tab"] == "model", 10, what="model space")
    report = dom_report(page)
    assert report["sameRoot"] and not report["rootReplaced"], report
    assert _still_same(page, held) == []


def test_opening_and_closing_a_menu_under_slow_cpu_keeps_the_shell_mounted(page, api):
    new_drawing(page, api)
    throttle(page, 4)
    held = _hold(page, KEPT)
    box = _box(page)
    watch_dom(page)
    open_menu(page, "Draw")
    page.keyboard.press("Escape")
    page.locator(".cv-menu[role=menu]:not([hidden])").first.wait_for(state="hidden", timeout=5000)
    report = dom_report(page)
    assert report["sameRoot"] and not report["rootReplaced"], report
    assert _still_same(page, held) == []
    assert _box(page) == box


def test_drawing_ten_lines_does_not_rebuild_the_layers_or_properties_panel(page, api):
    new_drawing(page, api)
    for selector in ("[data-panel=layers] > .cv-group-body", "[data-panel=properties] > .cv-group-body"):
        page.evaluate("(s) => document.querySelector(s).setAttribute('data-e2e-mark', 'kept')", selector)
    held = _hold(page, KEPT)
    for i in range(10):
        type_in(page, "LINE", "0,%d" % (i * 10), "50,%d" % (i * 10), "")
    until(lambda: len(api.entities("line")) == 10, 15, what="ten lines")
    assert _still_same(page, held) == []
    assert page.locator("[data-e2e-mark=kept]").count() == 2
