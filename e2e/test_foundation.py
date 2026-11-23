from conftest import dom_report, watch_dom


def test_the_app_reaches_its_start_screen_with_no_error_and_no_failed_request(page):
    assert page.locator(".cv-app").count() == 1
    assert page.get_by_text("Start a drawing or open a model").is_visible()
    assert not [w for w in page.warnings if w.startswith("error")]


def test_the_engine_behind_the_page_has_no_document_before_one_is_made(page, api):
    assert api.docs() == []


def test_the_shell_is_mounted_once_and_not_rebuilt_while_the_page_sits_idle(page):
    watch_dom(page)
    page.wait_for_timeout(1500)
    report = dom_report(page)
    assert report["sameRoot"] and not report["rootReplaced"]
