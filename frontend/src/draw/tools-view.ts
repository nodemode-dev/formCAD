import type { Pt } from '../canvas/types';
import { selection } from '../ui/panels/selection-bus';
import { toast } from '../ui/toast';
import { t } from '../ui/i18n';
import { dv, type BreakSpec, type ViewInfo } from './api';
import { palette, STANDARD_VIEWS } from './state';
import { drawStore } from './store';
import { lengthOf, toLocal, toPaper, type Tool, type ToolHost } from './tool-host';
import { checkCtl, ratio, selectCtl, textCtl, numberCtl } from './ui';
import { el } from '../ui/dom';
import type { Side } from './overlay';

export const sideToRel = (angle: 'first' | 'third', side: Side): Side => {
  if (angle === 'third') return side;
  return ({ top: 'bottom', bottom: 'top', left: 'right', right: 'left' } as const)[side];
};

const ortho = (from: Pt, p: Pt, on: boolean): Pt => (!on ? p : Math.abs(p[0] - from[0]) >= Math.abs(p[1] - from[1]) ? [p[0], from[1]] : [from[0], p[1]]);

export async function pickResult(info: ViewInfo | null): Promise<void> {
  if (info) selection.select([info.handle]);
}

export function createdView(body: Record<string, unknown>): Promise<ViewInfo | null> {
  return drawStore.run((id) => dv.create(id, body)).then(async (info) => { await pickResult(info); return info; });
}

export function baseSource(): Record<string, unknown> {
  const s: Record<string, string> = {};
  if (palette.sourceDoc) s.doc = palette.sourceDoc;
  if (palette.component) s.component = palette.component;
  return Object.keys(s).length ? { source: s } : {};
}

export function baseTool(h: ToolHost, dirId: string): Tool {
  const std = STANDARD_VIEWS.find((v) => v.id === dirId) ?? STANDARD_VIEWS[0];
  const direction = std.vnormal ? { vnormal: std.vnormal, vup: std.vup } : { direction: std.id };
  return {
    id: `base:${std.id}`,
    title: `Base view, ${std.label.toLowerCase()}`,
    hint: () => `Click the sheet where the view goes. Scale ${palette.scale}. Hold Shift to place more.`,
    move: (p) => h.env.overlay.setGhost({ cross: p }),
    click: async (p, e) => {
      const info = await createdView({ type: 'base', layout: drawStore.layout, scale: palette.scale, mode: palette.mode, position: p, ...direction, ...baseSource() });
      if (info && !e.shiftKey) h.disarm();
    },
  };
}

function viewAt(p: Pt): ViewInfo | null {
  return drawStore.at(p[0], p[1]);
}

export function sectionTool(h: ToolHost): Tool {
  const kind = selectCtl('Kind', [['full', 'Full'], ['half', 'Half'], ['offset', 'Offset'], ['aligned', 'Aligned']]);
  const flip = checkCtl('Flip');
  const opts = el('<span class="dw-inline"></span>');
  opts.append(kind.el, flip.el);
  let parent: ViewInfo | null = null;
  let pts: Pt[] = [];
  const need = (): number => ({ full: 2, half: 2, offset: 3, aligned: 3 } as Record<string, number>)[kind.get()] ?? 2;
  const arrows = (line: Pt[]): Array<[Pt, Pt]> => {
    if (line.length < 2 || !parent) return [];
    const a = line[0];
    const b = line[line.length - 1];
    const d: Pt = [b[0] - a[0], b[1] - a[1]];
    const n = Math.hypot(d[0], d[1]) || 1;
    const s = flip.get() ? -1 : 1;
    const v: Pt = [(-d[1] / n) * 12 * s, (d[0] / n) * 12 * s];
    return [[a, [a[0] + v[0], a[1] + v[1]]], [b, [b[0] + v[0], b[1] + v[1]]]];
  };
  const paint = (cur?: Pt): void => {
    const line = cur ? [...pts, cur] : pts;
    h.env.overlay.setGhost({ line, arrows: arrows(line) });
  };
  kind.input.addEventListener('change', () => { h.paintHint(); paint(); });
  flip.input.addEventListener('change', () => { paint(); });
  const create = async (): Promise<void> => {
    if (!parent || pts.length < (kind.get() === 'offset' ? 3 : need())) { toast(t('Add more points to the section line.')); return; }
    const p = parent;
    const line = pts.map((q) => toLocal(p, q));
    const info = await createdView({ type: 'section', parent: p.name, kind: kind.get(), line, flip: flip.get() });
    if (info) h.disarm();
  };
  return {
    id: 'section',
    title: 'Section view',
    opts,
    finishLabel: 'Create',
    hint: () => (!parent ? 'Click inside the view to cut, then click the points of the section line.' : `Click the next point of the section line (${pts.length} of ${need()}${kind.get() === 'offset' ? ' or more' : ''}). Shift keeps it straight.`),
    enter: () => { parent = null; pts = []; },
    leave: () => { parent = null; pts = []; },
    move: (p, e) => { if (pts.length) paint(ortho(pts[pts.length - 1], p, e.shiftKey)); },
    click: async (p, e) => {
      if (!parent) {
        parent = viewAt(p);
        if (!parent) { toast(t('Click inside a view first.')); return; }
      }
      const q = pts.length ? ortho(pts[pts.length - 1], p, e.shiftKey) : p;
      if (pts.length && lengthOf(pts[pts.length - 1], q) < 0.01) return;
      pts.push(q);
      paint();
      h.paintHint();
      if (kind.get() !== 'offset' && pts.length >= need()) await create();
    },
    dblclick: () => { if (kind.get() === 'offset') void create(); },
    finish: create,
    back: () => { pts.pop(); if (!pts.length) parent = null; paint(); h.paintHint(); },
  };
}

export function detailTool(h: ToolHost): Tool {
  const scale = textCtl('Scale');
  const opts = el('<span class="dw-inline"></span>');
  opts.append(scale.el);
  let parent: ViewInfo | null = null;
  let centre: Pt | null = null;
  const make = async (to: Pt): Promise<void> => {
    if (!parent || !centre) return;
    const p = parent;
    const rPaper = lengthOf(centre, to);
    const k = p.scale / (p.unitMm || 1);
    if (rPaper < 0.5) { toast(t('Make the circle larger.')); return; }
    const body: Record<string, unknown> = { type: 'detail', parent: p.name, center: toLocal(p, centre), radius: rPaper / k };
    if (scale.get().trim()) body.scale = scale.get().trim();
    const info = await createdView(body);
    if (info) h.disarm();
  };
  return {
    id: 'detail',
    title: 'Detail view',
    opts,
    hint: () => (!centre ? 'Click the centre of the area to enlarge.' : 'Click to set the radius of the circle.'),
    enter: () => { parent = null; centre = null; scale.set(ratio(Math.max(0.01, (drawStore.selected?.scale ?? 1) * 2))); },
    leave: () => { parent = null; centre = null; },
    move: (p) => { if (centre) h.env.overlay.setGhost({ circle: [centre, lengthOf(centre, p)] }); },
    click: async (p) => {
      if (!centre) {
        const v = viewAt(p);
        if (!v) { toast(t('Click inside a view first.')); return; }
        parent = v;
        centre = p;
        scale.set(ratio(v.scale * 2));
        h.paintHint();
        return;
      }
      await make(p);
    },
    drag: (from, to, end) => {
      if (!centre) {
        const v = viewAt(from);
        if (!v) return;
        parent = v;
        centre = from;
        scale.set(ratio(v.scale * 2));
      }
      if (!end) { h.env.overlay.setGhost({ circle: [centre, lengthOf(centre, to)] }); return; }
      return make(to);
    },
  };
}

interface EdgeLine { a: Pt; b: Pt }
const lineCache = new Map<number, { sig: string; lines: EdgeLine[] }>();

async function linesOf(v: ViewInfo): Promise<EdgeLine[]> {
  const hit = lineCache.get(v.handle);
  if (hit && hit.sig === v.state.sig) return hit.lines;
  const { call } = await import('../io/api');
  const { docStore } = await import('../ui/doc-store');
  const id = docStore.activeId;
  if (!id) return [];
  const r = await call<{ cache?: { classes?: Record<string, Array<{ t: string; a?: Pt; b?: Pt }>> } }>('GET', `/api/docs/${encodeURIComponent(id)}/drawviews/${v.handle}?cache=true`);
  const lines: EdgeLine[] = [];
  const classes = r.cache?.classes ?? {};
  for (const cls of ['sharp_v', 'outline_v', 'smooth_v']) {
    for (const rec of classes[cls] ?? []) if (rec.t === 'line' && rec.a && rec.b) lines.push({ a: rec.a, b: rec.b });
  }
  lineCache.set(v.handle, { sig: v.state.sig, lines });
  return lines;
}

const nearestSegment = (p: Pt, v: ViewInfo, lines: EdgeLine[], tol: number): EdgeLine | null => {
  let best: EdgeLine | null = null;
  let dist = tol;
  for (const l of lines) {
    const a = toPaper(v, l.a);
    const b = toPaper(v, l.b);
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const len2 = dx * dx + dy * dy || 1e-9;
    const u = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2));
    const d = Math.hypot(p[0] - (a[0] + u * dx), p[1] - (a[1] + u * dy));
    if (d < dist) { dist = d; best = l; }
  }
  return best;
};

export function auxTool(h: ToolHost): Tool {
  let busy = false;
  const near = async (p: Pt): Promise<{ v: ViewInfo; l: EdgeLine } | null> => {
    const v = viewAt(p);
    if (!v) return null;
    const lines = await linesOf(v);
    const px = h.env.canvas.worldFromScreen(6, 0)[0] - h.env.canvas.worldFromScreen(0, 0)[0];
    const l = nearestSegment(p, v, lines, Math.abs(px));
    return l ? { v, l } : null;
  };
  return {
    id: 'aux',
    title: 'Auxiliary view',
    hint: () => 'Click a straight edge of a view; the new view looks square onto it.',
    move: async (p) => {
      if (busy) return;
      busy = true;
      const hit = await near(p);
      busy = false;
      h.env.overlay.setGhost(hit ? { hot: [toPaper(hit.v, hit.l.a), toPaper(hit.v, hit.l.b)] } : {});
    },
    click: async (p) => {
      const hit = await near(p);
      if (!hit) { toast(t('Click on a straight edge of a view.')); return; }
      const info = await createdView({ type: 'auxiliary', parent: hit.v.name, edge: { line: [hit.l.a, hit.l.b] } });
      if (info) h.disarm();
    },
  };
}

export function breakTool(h: ToolHost): Tool {
  const style = selectCtl('Line', [['zigzag', 'Zigzag'], ['straight', 'Straight']]);
  const gap = numberCtl('Gap (mm)');
  gap.set(2);
  const opts = el('<span class="dw-inline"></span>');
  opts.append(style.el, gap.el);
  let view: ViewInfo | null = null;
  let first: Pt | null = null;
  const band = (a: Pt, b: Pt): { axis: 'x' | 'y'; lo: number; hi: number } => {
    const la = toLocal(view as ViewInfo, a);
    const lb = toLocal(view as ViewInfo, b);
    const axis = Math.abs(lb[0] - la[0]) >= Math.abs(lb[1] - la[1]) ? 'x' : 'y';
    const i = axis === 'x' ? 0 : 1;
    return { axis, lo: Math.min(la[i], lb[i]), hi: Math.max(la[i], lb[i]) };
  };
  const ghost = (b: Pt): void => {
    if (!view || !first) return;
    const r = band(first, b);
    const [x0, y0, x1, y1] = view.bounds;
    const k = view.scale / (view.unitMm || 1);
    const o = r.axis === 'x' ? view.position[0] : view.position[1];
    const lo = o + r.lo * k;
    const hi = o + r.hi * k;
    h.env.overlay.setGhost({ rect: r.axis === 'x' ? [[lo, y0], [hi, y1]] : [[x0, lo], [x1, hi]] });
  };
  const make = async (b: Pt): Promise<void> => {
    if (!view || !first) return;
    const v = view;
    const r = band(first, b);
    const g = Math.max(0, gap.get() ?? 0) / (v.scale / (v.unitMm || 1));
    if (r.hi - r.lo < 0.5) { toast(t('Make the removed band wider.')); return; }
    const spec: BreakSpec = { axis: r.axis, lo: r.lo, hi: r.hi, gap: Math.min(g, (r.hi - r.lo) * 0.9), style: style.get() as BreakSpec['style'] };
    const existing = v.broken.breaks ?? [];
    const res = await drawStore.run((id) => dv.patch(id, v.handle, { breaks: [...existing, spec] }));
    if (res) { await pickResult(res); h.disarm(); }
  };
  return {
    id: 'break',
    title: 'Break view',
    opts,
    hint: () => (!first ? 'Click one side of the part to remove.' : 'Click the other side of the part to remove.'),
    enter: () => { view = null; first = null; },
    leave: () => { view = null; first = null; },
    move: (p) => ghost(p),
    click: async (p) => {
      if (!first) {
        const v = viewAt(p);
        if (!v) { toast(t('Click inside a view first.')); return; }
        view = v;
        first = p;
        h.paintHint();
        return;
      }
      await make(p);
    },
    drag: (from, to, end) => {
      if (!first) {
        const v = viewAt(from);
        if (!v) return;
        view = v;
        first = from;
      }
      if (!end) { ghost(to); return; }
      return make(to);
    },
  };
}

export function cropTool(h: ToolHost): Tool {
  let view: ViewInfo | null = null;
  let pts: Pt[] = [];
  const paint = (cur?: Pt): void => h.env.overlay.setGhost({ line: cur ? [...pts, cur] : pts, closed: pts.length > 2 });
  const create = async (): Promise<void> => {
    if (!view || pts.length < 3) { toast(t('A crop outline needs three points.')); return; }
    const v = view;
    const res = await drawStore.run((id) => dv.patch(id, v.handle, { polygon: pts.map((q) => toLocal(v, q)) }));
    if (res) { await pickResult(res); h.disarm(); }
  };
  return {
    id: 'crop',
    title: 'Crop view',
    finishLabel: 'Crop',
    hint: () => (!view ? 'Click inside the view, then click the corners of the outline to keep.' : `Click the next corner (${pts.length} so far), then press Enter or Crop.`),
    enter: () => { view = null; pts = []; },
    leave: () => { view = null; pts = []; },
    move: (p) => { if (pts.length) paint(p); },
    click: (p) => {
      if (!view) {
        view = viewAt(p);
        if (!view) { toast(t('Click inside a view first.')); return; }
      }
      if (pts.length && lengthOf(pts[pts.length - 1], p) < 0.01) return;
      pts.push(p);
      paint();
      h.paintHint();
    },
    dblclick: () => { void create(); },
    finish: create,
    back: () => { pts.pop(); if (!pts.length) view = null; paint(); h.paintHint(); },
  };
}

export function projectDrag(h: ToolHost, v: ViewInfo, e0: PointerEvent): void {
  const host = h.env.host;
  const r = host.getBoundingClientRect();
  const world = (e: PointerEvent): Pt => { const w = h.env.canvas.worldFromScreen(e.clientX - r.left, e.clientY - r.top); return [w[0], w[1]]; };
  const [x0, y0, x1, y1] = v.bounds;
  const c: Pt = [(x0 + x1) / 2, (y0 + y1) / 2];
  const side = (p: Pt): Side | null => {
    const dx = p[0] - c[0];
    const dy = p[1] - c[1];
    const hx = (x1 - x0) / 2;
    const hy = (y1 - y0) / 2;
    if (Math.abs(dx) <= hx && Math.abs(dy) <= hy) return null;
    return Math.abs(dx) / Math.max(hx, 1e-6) >= Math.abs(dy) / Math.max(hy, 1e-6) ? (dx > 0 ? 'right' : 'left') : (dy > 0 ? 'top' : 'bottom');
  };
  const move = (e: PointerEvent): void => {
    const p = world(e);
    const s = side(p);
    h.env.overlay.setGhost({ arrows: [[c, p]], cross: s ? p : null });
  };
  const up = (e: PointerEvent): void => {
    window.removeEventListener('pointermove', move, true);
    window.removeEventListener('pointerup', up, true);
    h.env.overlay.clearGhost();
    const s = side(world(e));
    if (!s) return;
    void createdView({ type: 'projected', parent: v.name, rel: sideToRel(drawStore.projection, s) });
  };
  window.addEventListener('pointermove', move, true);
  window.addEventListener('pointerup', up, true);
  void e0;
}

export function moveDrag(h: ToolHost, v: ViewInfo, e0: PointerEvent): void {
  const r = h.env.host.getBoundingClientRect();
  const world = (e: PointerEvent): Pt => { const w = h.env.canvas.worldFromScreen(e.clientX - r.left, e.clientY - r.top); return [w[0], w[1]]; };
  const start = world(e0);
  const [x0, y0, x1, y1] = v.bounds;
  const move = (e: PointerEvent): void => {
    const p = world(e);
    const dx = p[0] - start[0];
    const dy = p[1] - start[1];
    h.env.overlay.setGhost({ rect: [[x0 + dx, y0 + dy], [x1 + dx, y1 + dy]] });
  };
  const up = (e: PointerEvent): void => {
    window.removeEventListener('pointermove', move, true);
    window.removeEventListener('pointerup', up, true);
    h.env.overlay.clearGhost();
    const p = world(e);
    const dx = p[0] - start[0];
    const dy = p[1] - start[1];
    if (Math.hypot(dx, dy) < 0.2) return;
    void drawStore.run((id) => dv.patch(id, v.handle, { changes: { position: [v.position[0] + dx, v.position[1] + dy] } }));
  };
  window.addEventListener('pointermove', move, true);
  window.addEventListener('pointerup', up, true);
}
