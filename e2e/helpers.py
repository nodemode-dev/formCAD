import io
import time

from PIL import Image

INK = 160
AWAY = (1300, 886)


def until(check, timeout: float = 10.0, step: float = 0.1, what: str = "condition"):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = check()
        if last:
            return last
        time.sleep(step)
    raise AssertionError("%s not met within %.1fs (last: %r)" % (what, timeout, last))


def new_drawing(page, api) -> str:
    before = {d["id"] for d in api.docs()}
    page.keyboard.press("Control+n")
    doc = until(lambda: next((d["id"] for d in api.docs() if d["id"] not in before), None), what="a new drawing")
    page.wait_for_function("() => { const i = document.querySelector('.cv-cmd-input'); return i && i.placeholder === 'Type a command'; }", timeout=15000)
    return doc


def type_in(page, *entries: str) -> None:
    box = page.locator(".cv-cmd-input")
    for text in entries:
        box.fill(text)
        box.press("Enter")
        page.wait_for_function("() => document.querySelector('.cv-cmd-input').value === ''", timeout=10000)
        page.wait_for_timeout(120)


def idle(api, timeout: float = 10.0) -> dict:
    return until(lambda: (lambda s: s if not s["active"] else None)(api.state()), timeout, what="engine idle")


def lines(api) -> list:
    return [(tuple(e["start"][:2]), tuple(e["end"][:2])) for e in api.entities("line")]


class View:
    def __init__(self, page, cx: float, cy: float, height: float):
        box = page.locator(".cv-canvas-scene").bounding_box()
        self.left, self.top, self.width, self.height = box["x"], box["y"], box["width"], box["height"]
        self.cx, self.cy = cx, cy
        self.scale = self.height / height

    def screen(self, x: float, y: float) -> tuple:
        return (self.left + self.width / 2 + (x - self.cx) * self.scale, self.top + self.height / 2 - (y - self.cy) * self.scale)

    def world(self, px: float, py: float) -> tuple:
        return (self.cx + (px - self.left - self.width / 2) / self.scale, self.cy - (py - self.top - self.height / 2) / self.scale)


def zoom_to(page, api, cx: float, cy: float, height: float) -> View:
    type_in(page, "ZOOM", "C", "%g,%g" % (cx, cy), "%g" % height)
    until(lambda: (lambda v: abs(v["height"] - height) < 1e-9 and abs(v["center"][0] - cx) < 1e-9 and abs(v["center"][1] - cy) < 1e-9)(api.snapshot()["view"]), what="engine view")
    page.wait_for_timeout(400)
    return View(page, cx, cy, height)


def focus_canvas(page, view: "View") -> None:
    page.mouse.click(view.left + 30, view.top + view.height - 140)
    page.wait_for_timeout(150)
    page.keyboard.press("Escape")
    page.wait_for_timeout(150)


def quiet_pointer(page) -> None:
    page.mouse.move(*AWAY)
    page.wait_for_timeout(250)


def patch(page, px: float, py: float, r: int = 3) -> Image.Image:
    clip = {"x": round(px) - r, "y": round(py) - r, "width": 2 * r + 1, "height": 2 * r + 1}
    return Image.open(io.BytesIO(page.screenshot(clip=clip))).convert("RGB")


def pixels(page, px: float, py: float, r: int = 3) -> list:
    raw = patch(page, px, py, r).tobytes()
    return [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]


def brightest(page, px: float, py: float, r: int = 3) -> float:
    return max(0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2] for p in pixels(page, px, py, r))


def bluest(page, px: float, py: float, r: int = 3) -> int:
    return max(p[2] - max(p[0], p[1]) for p in pixels(page, px, py, r))


def inked(page, view: View, points, r: int = 3) -> list:
    return [brightest(page, *view.screen(x, y), r) >= INK for x, y in points]


def luminance(css: str) -> float:
    nums = [float(v) for v in css[css.index("(") + 1:css.index(")")].split(",")[:3]]
    return (0.299 * nums[0] + 0.587 * nums[1] + 0.114 * nums[2]) / 255.0


def choose(page, button, option: str) -> None:
    button.click()
    page.locator(".cv-dd-pop:not([hidden]) [role=option]", has_text=option).first.click()


def pick_workspace(page, name: str) -> None:
    choose(page, page.get_by_role("button", name="Workspace", exact=True), name)
    page.wait_for_function("(n) => document.querySelector('.cv-dd-btn.cv-tt-select .cv-dd-label')?.textContent === n", arg=name, timeout=10000)


def open_menu(page, name: str):
    page.locator(".cv-menubar .cv-menu-btn", has_text=name).first.click()
    menu = page.locator(".cv-menu[role=menu]:not([hidden])").first
    menu.wait_for(state="visible", timeout=5000)
    return menu


def path_dialog(page):
    dialog = page.locator(".cv-scrim:not([hidden]) .cv-dialog")
    dialog.wait_for(state="visible", timeout=5000)
    return dialog


def in_view(page, panel: str) -> bool:
    return page.evaluate(
        "(id) => { const e = document.querySelector('[data-panel=\"' + id + '\"]'); if (!e) return false; const h = e.querySelector('.cv-group-head').getBoundingClientRect();"
        " const hit = document.elementFromPoint(h.x + h.width / 2, h.y + h.height / 2); return !!hit && e.contains(hit); }", panel)


def panel_label(page, panel: str) -> str:
    return page.locator('[data-panel="%s"] > .cv-group-head' % panel).inner_text().strip()


THEME_PROBE = """
(seed) => {
  if (seed && !sessionStorage.getItem('e2e-seeded')) {
    localStorage.setItem('nodemode_ui_settings', JSON.stringify(seed));
    sessionStorage.setItem('e2e-seeded', '1');
  }
  const frames = window.__e2eFrames = [];
  const tick = () => {
    const b = document.body;
    if (b) frames.push({ root: getComputedStyle(document.documentElement).backgroundColor, body: getComputedStyle(b).backgroundColor, light: b.classList.contains('theme-light') });
    if (frames.length < 600) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}
"""


def theme_probe(context, seed=None) -> None:
    import json
    context.add_init_script("(%s)(%s);" % (THEME_PROBE, json.dumps(seed)))


def frames(page) -> list:
    return page.evaluate("() => window.__e2eFrames")
