import fs from 'node:fs';
import path from 'node:path';

const until = async (cdp, sleep, js, timeout = 30000) => {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await cdp.eval(js)) return true;
    await sleep(200);
  }
  return false;
};

const typeText = async (cdp, text) => cdp.send('Input.insertText', { text });

const wheel = async (cdp, x, y, deltaY) => cdp.send('Input.dispatchMouseEvent', { type: 'mouseWheel', x, y, deltaX: 0, deltaY });

const hover = async (cdp, x, y) => cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, button: 'none' });

export default async ({ cdp, click, key, rects, idle, sleep, log }) => {
  const open = `!!document.querySelector('.is-graph .gx-node')`;
  if (!(await cdp.eval(open))) {
    await key('p', 'KeyP', 80, 2 | 8);
    await sleep(400);
    await typeText(cdp, 'Graph Editor');
    await sleep(400);
    await key('Enter', 'Enter', 13);
    await idle('graph open');
  }
  if (!(await until(cdp, sleep, open))) { log('the graph editor did not open'); return; }
  await idle('graph ready');
  await sleep(1500);
  await idle('graph solved');

  const heads = (await rects('.gx-node .gx-nt')) || [];
  log(`graph: ${heads.length} nodes`);
  for (const [x, y] of heads) {
    await click(Math.round(x), Math.round(y));
    await idle('node select');
    await hover(cdp, Math.round(x), Math.round(y) + 30);
    await sleep(900);
    await idle('node tip');
  }
  await key('Escape', 'Escape', 27);
  const pins = (await rects('.gx-node .gx-dot')) || [];
  for (const [x, y] of pins) {
    await hover(cdp, Math.round(x), Math.round(y));
    await sleep(500);
    await idle('port tip');
  }
  log(`graph: ${pins.length} ports hovered`);
  const trees = await cdp.eval(`(async () => {
    const tok = document.querySelector('meta[name="formcad-token"]')?.content ?? '';
    const get = (u) => fetch(u, { headers: { 'X-FormCAD-Token': tok } }).then((r) => r.json());
    const docs = await get('/api/docs');
    const list = Array.isArray(docs) ? docs : docs.docs ?? [];
    let n = 0;
    for (const d of list) {
      const base = '/api/docs/' + encodeURIComponent(d.id) + '/graphs';
      const gs = await get(base);
      for (const g of gs.graphs ?? []) {
        const one = await get(base + '/' + encodeURIComponent(g.id));
        for (const node of one.definition?.nodes ?? []) for (const p of node.ports?.out ?? []) {
          await get(base + '/' + encodeURIComponent(g.id) + '/tree/' + encodeURIComponent(node.id) + '/' + encodeURIComponent(p.name) + '?offset=0&limit=24');
          n++;
        }
      }
    }
    return n;
  })()`);
  await idle('trees');
  log(`graph: ${trees} output trees read`);
  await hover(cdp, 5, 5);

  const area = await cdp.eval(`(() => { const r = document.querySelector('.gx-root').getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })()`);
  if (area) {
    const [x, y, w, h] = area;
    const cx = Math.round(x + w * 0.5);
    const cy = Math.round(y + h * 0.9);
    const seq = [['mouseMoved', 0], ['mousePressed', 1], ['mouseReleased', 1], ['mousePressed', 2], ['mouseReleased', 2]];
    for (const [type, clickCount] of seq) {
      await cdp.send('Input.dispatchMouseEvent', { type, x: cx, y: cy, button: type === 'mouseMoved' ? 'none' : 'left', clickCount });
      await sleep(30);
    }
    await sleep(400);
    await typeText(cdp, 'cyl');
    await sleep(600);
    await idle('search');
    await key('Escape', 'Escape', 27);
    await wheel(cdp, Math.round(x + w / 2), Math.round(y + h / 2), -240);
    await sleep(300);
    await wheel(cdp, Math.round(x + w / 2), Math.round(y + h / 2), 240);
    await idle('zoom');
  }
  const fit = (await rects('.gx-head [data-a="fit"]')) || [];
  if (fit.length) { await click(Math.round(fit[0][0]), Math.round(fit[0][1])); await idle('fit'); }
  await hover(cdp, 5, 5);
  await sleep(600);

  const shot = process.env.FORMCAD_GRAPH_SHOT;
  if (shot) {
    const img = await cdp.send('Page.captureScreenshot', { format: 'png' });
    fs.mkdirSync(path.dirname(path.resolve(shot)), { recursive: true });
    fs.writeFileSync(path.resolve(shot), Buffer.from(img.data, 'base64'));
    log(`graph screenshot ${shot}`);
  }
};
