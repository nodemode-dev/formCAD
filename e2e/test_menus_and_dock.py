import re

from helpers import new_drawing, open_menu, until

MENUS = ["File", "Edit", "View", "Insert", "Format", "Draw", "Modify", "Annotate", "Model", "Engineer", "Tools", "Window", "Help"]
OPEN_MENU = ".cv-menu[role=menu]:not([hidden])"


def test_each_top_menu_opens_with_its_items_and_escape_closes_it(page, api):
    new_drawing(page, api)
    for name in MENUS:
        menu = open_menu(page, name)
        button = page.locator(".cv-menubar .cv-menu-btn", has_text=name).first.bounding_box()
        box = menu.bounding_box()
        assert menu.get_by_role("menuitem").count() >= 2, name
        assert abs(box["x"] - button["x"]) <= 40 and box["y"] >= button["y"] + button["height"] - 2, name
        page.keyboard.press("Escape")
        page.locator(OPEN_MENU).first.wait_for(state="hidden", timeout=3000)


def test_the_file_menu_greys_out_save_and_close_on_the_start_screen_and_enables_them_with_a_drawing(page, api):
    menu = open_menu(page, "File")
    assert menu.get_by_role("menuitem", name="Save", exact=False).first.is_disabled()
    assert menu.get_by_role("menuitem", name="Close", exact=False).first.is_disabled()
    page.keyboard.press("Escape")
    new_drawing(page, api)
    menu = open_menu(page, "File")
    assert menu.get_by_role("menuitem", name="Save", exact=False).first.is_enabled()
    assert menu.get_by_role("menuitem", name="Close", exact=False).first.is_enabled()


def test_command_search_finds_line_and_running_it_starts_the_line_command(page, api):
    new_drawing(page, api)
    page.get_by_role("button", name="Search commands").click()
    page.locator(".cv-search-input").press_sequentially("line", delay=20)
    item = page.locator(".cv-search-item:not([hidden])").filter(has=page.locator(".cv-search-label", has_text=re.compile(r"^Line$"))).first
    item.click()
    state = until(lambda: (lambda s: s if s["active"] else None)(api.state()), 5, what="command running")
    assert state["command"] == "LINE"
    assert page.locator(".cv-search-pop").is_hidden()


def _dismiss_guide(page) -> None:
    guide = page.get_by_role("button", name="Close the guide")
    try:
        guide.click(timeout=2000)
    except Exception:
        return


def test_the_agent_dock_opens_from_the_window_menu_runs_echo_in_its_terminal_and_hides(page, api):
    new_drawing(page, api)
    open_menu(page, "Window").get_by_role("menuitem", name="Agent Dock").click()
    dock = page.locator(".ft-dock")
    dock.wait_for(state="visible", timeout=10000)
    tab = page.locator(".ft-dock-tab[data-dock-part='tab.shell']")
    until(lambda: tab.count() == 1, 10, what="terminal tab")
    assert tab.first.inner_text().strip().startswith("Terminal")
    until(lambda: api.get("/api/terminal")["terminals"], 10, what="engine terminal")
    _dismiss_guide(page)
    page.locator(".ft-dock .xterm").first.click()
    page.keyboard.type("echo lane13_$((6*7))_done\n")
    rows = page.locator(".ft-dock .xterm-rows")
    until(lambda: "lane13_42_done" in rows.inner_text(), 10, what="echo output")
    page.locator(".ft-dock-hide").click()
    dock.wait_for(state="hidden", timeout=5000)


def test_the_agent_dock_offers_each_agent_program_as_the_engine_finds_it_installed(page, api):
    new_drawing(page, api)
    found = api.get("/api/agents/status")
    page.keyboard.press("Control+j")
    page.locator(".ft-dock").wait_for(state="visible", timeout=10000)
    _dismiss_guide(page)
    page.locator(".ft-dock-more").click()
    assert page.locator(".ft-dock-claude").is_visible()
    for kind in ("codex", "cursor", "antigravity"):
        row = page.locator(".ft-dock-menu-row[data-kind='%s']" % kind)
        until(lambda: row.is_visible(), 5, what="%s row" % kind)
        go = row.locator(".ft-dock-menu-go")
        assert go.is_visible() == bool(found[kind]["installed"]), kind
        if not found[kind]["installed"] and found[kind].get("install"):
            assert row.locator(".ft-dock-menu-cmd").inner_text().strip() == found[kind]["install"]
