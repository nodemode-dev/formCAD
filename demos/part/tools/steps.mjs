export default async ({ cdp, click, key, rects, idle, sleep, log }) => {
  const mouse = (type, x, y, button = 'none', buttons = 0) => cdp.send('Input.dispatchMouseEvent', { type, x: Math.round(x), y: Math.round(y), button, buttons, clickCount: 1 });
  const drag = async (ax, ay, bx, by, button = 'middle', n = 10) => {
    const mask = button === 'left' ? 1 : button === 'right' ? 2 : 4;
    await mouse('mouseMoved', ax, ay);
    await mouse('mousePressed', ax, ay, button, mask);
    for (let i = 1; i <= n; i++) { await mouse('mouseMoved', ax + ((bx - ax) * i) / n, ay + ((by - ay) * i) / n, button, mask); await sleep(16); }
    await mouse('mouseReleased', bx, by, button, 0);
  };

  const on3d = async () => {
    for (let i = 0; i < 60; i++) {
      if (await cdp.eval(`!!document.querySelector('.is-3d .v3-canvas, .cv-view3d .v3-canvas') && document.querySelector('.is-3d') !== null`)) return true;
      await sleep(250);
    }
    return false;
  };
  if (!(await on3d())) {
    const t = (await rects('[data-cmd="v3-toggle"]')) || [];
    if (t.length) { await click(t[0][0], t[0][1]); await idle('enter 3d'); }
  }
  log(`3d view: ${await on3d()}`);

  await cdp.eval(`localStorage.setItem('formCAD.workspace', 'part')`);
  await cdp.send('Page.reload', {});
  await sleep(500);
  for (let i = 0; i < 240 && !(await cdp.eval(`document.body.classList.contains('app-ready')`).catch(() => false)); i++) await sleep(250);
  await idle('part boot');
  log(`workspace: ${await cdp.eval(`document.querySelector('select.cv-tt-select')?.value`)}, 3d view: ${await on3d()}`);

  const head = await cdp.eval(`(() => { const s = document.querySelector('[data-panel="features"]'); if (!s) return null; const h = s.querySelector('.cv-group-head'); const r = h.getBoundingClientRect(); return { open: h.getAttribute('aria-expanded') === 'true', at: [r.x + r.width / 2, r.y + r.height / 2], seen: !!s.offsetParent }; })()`);
  log(`features panel: ${JSON.stringify(head)}`);
  if (head && head.seen && !head.open) { await click(head.at[0], head.at[1]); await idle('features open'); }

  const rows = (await rects('.pt-list [data-id]')) || [];
  for (const [x, y] of rows) {
    await mouse('mouseMoved', x, y);
    await sleep(120);
    await click(x, y);
    await idle('feature');
  }
  log(`features clicked: ${rows.length}`);

  const box = await cdp.eval(`(() => { const c = document.querySelector('.v3-canvas'); if (!c) return null; const r = c.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })()`);
  if (box) {
    const [x, y, w, h] = box;
    const cx = x + w / 2;
    const cy = y + h / 2;
    for (const [fx, fy] of [[0.5, 0.5], [0.45, 0.45], [0.55, 0.55], [0.4, 0.55], [0.6, 0.45]]) {
      await click(x + w * fx, y + h * fy);
      await idle('face pick');
    }
    await key('Escape', 'Escape', 27);
    await idle('pick clear');
    await drag(cx, cy, cx + 160, cy + 60, 'middle');
    await idle('orbit');
    await drag(cx, cy, cx + 80, cy - 40, 'middle');
    await idle('orbit 2');
    for (const dy of [-240, 240, 120]) {
      await cdp.send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: Math.round(cx), y: Math.round(cy), deltaX: 0, deltaY: dy });
      await sleep(80);
    }
    await idle('zoom');
    for (const [ox, oy] of [[70, 70], [70, 40], [40, 70], [100, 70]]) {
      await click(x + w - ox, y + oy);
      await idle('cube');
    }
  }

  await key('p', 'KeyP', 80, 2 | 8);
  await idle('palette');
  await key('Escape', 'Escape', 27);
  await idle('palette close');

  const gear = (await rects('.cv-tt-btn')) || [];
  if (gear.length) {
    await click(gear[0][0], gear[0][1]);
    await idle('preferences');
    const tabs = (await rects('.cv-prefs-nav [role="tab"], .cv-prefs-nav button')) || [];
    for (const [x, y] of tabs) { await click(x, y); await idle('preferences tab'); }
    log(`preferences tabs: ${tabs.length}`);
    await key('Escape', 'Escape', 27);
    await idle('preferences close');
  }

  const heads = (await rects('.cv-group-head')) || [];
  for (const [x, y] of heads) { await click(x, y); await idle('panel'); await click(x, y); await idle('panel back'); }
  log(`panels toggled: ${heads.length}`);

  if (box) {
    const [x, y, w, h] = box;
    await click(x + w * 0.5, y + h * 0.5);
    await idle('final pick');
    await key('Escape', 'Escape', 27);
    await idle('final clear');
  }
};
