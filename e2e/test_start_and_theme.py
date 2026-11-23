from conftest import READY, open_app
from helpers import frames, luminance, theme_probe, until


def _errors(page) -> list:
    return [w for w in page.warnings if w.startswith("error")]


def test_the_start_screen_opens_a_blank_drawing_with_no_console_error_and_no_failed_request(page, api):
    bad: list = []
    page.on("response", lambda r: bad.append("%d %s" % (r.status, r.url)) if r.status >= 400 else None)
    page.on("requestfailed", lambda r: bad.append("failed %s" % r.url))
    page.reload()
    page.wait_for_selector(READY, timeout=60000)
    assert page.get_by_text("Start a drawing or open a model").is_visible()
    page.get_by_role("button", name="Blank drawing").first.click()
    docs = until(lambda: api.docs(), what="a document")
    assert [(d["kind"], d["entities"], d["dirty"]) for d in docs] == [("drawing", 0, False)]
    assert page.locator(".cv-tab.is-active .cv-tab-name").inner_text() == docs[0]["name"]
    page.wait_for_function("() => document.querySelector('.cv-cmd-input').placeholder === 'Type a command'", timeout=15000)
    page.wait_for_timeout(1000)
    assert not bad, bad
    assert not _errors(page), _errors(page)


def test_a_stored_light_theme_is_light_from_the_first_frame_with_no_dark_flash(context, api):
    api.close_all()
    theme_probe(context, {"theme": "light", "accentColor": "#9a7bd8", "appearance": 4})
    page = context.new_page()
    page.errors = open_app(page)
    page.wait_for_timeout(1000)
    seen = frames(page)
    assert len(seen) > 5
    assert all(f["light"] for f in seen), seen[:3]
    assert min(luminance(f["body"]) for f in seen) > 0.6
    assert min(luminance(f["root"]) for f in seen) > 0.6
    assert not page.errors and not page.failed and not _errors(page)


def test_a_theme_picked_in_preferences_applies_at_once_and_is_the_first_frame_after_reload(context, api):
    api.close_all()
    theme_probe(context, {"theme": "light", "accentColor": "#9a7bd8", "appearance": 4})
    page = context.new_page()
    page.errors = open_app(page)
    before = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    assert luminance(before) > 0.6
    page.get_by_role("button", name="Preferences").first.click()
    page.locator('[data-theme-id="forest"]').first.click()
    applied = until(lambda: (lambda c: c if luminance(c) < 0.2 else None)(page.evaluate("() => getComputedStyle(document.body).backgroundColor")), 5, what="dark theme applied")
    assert not page.evaluate("() => document.body.classList.contains('theme-light')")
    page.keyboard.press("Escape")
    page.reload()
    page.wait_for_selector(READY, timeout=60000)
    page.wait_for_timeout(1000)
    seen = frames(page)
    assert len(seen) > 5
    assert {f["body"] for f in seen} == {applied}
    assert not any(f["light"] for f in seen)
    assert not page.errors and not page.failed and not _errors(page)


def test_the_light_or_dark_button_switches_the_whole_window_between_light_and_dark(page):
    def body_luminance() -> float:
        return luminance(page.evaluate("() => getComputedStyle(document.body).backgroundColor"))
    assert body_luminance() < 0.2
    toggle = page.get_by_role("button", name="Light or dark")
    toggle.click()
    until(lambda: body_luminance() > 0.6, 5, what="light window")
    assert toggle.get_attribute("aria-pressed") == "true"
    toggle.click()
    until(lambda: body_luminance() < 0.2, 5, what="dark window")
    assert toggle.get_attribute("aria-pressed") == "false"
