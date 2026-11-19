import type { Camera } from './camera';
import { drawMarks } from './cmarks';
import { css } from './color';
import { MEDIA } from './media';
import { itemRuns } from './pick';
import type { DisplayStore } from './store';
import type { Theme } from './theme';
import type { BoxMark, GripMark, HighlightMark, SnapMark, TrackMark } from './types';

export interface OverlayEnv {
  cam: Camera;
  th: Theme;
  store: DisplayStore;
  marker: number;
  gripSize: number;
  pointer: { px: number; py: number } | null;
  width: number;
  height: number;
}

export const SNAP_NAMES: Record<string, string> = {
  end: 'Endpoint',
  mid: 'Midpoint',
  cen: 'Center',
  gcen: 'Geometric Center',
  qua: 'Quadrant',
  int: 'Intersection',
  app: 'Apparent Intersection',
  per: 'Perpendicular',
  tan: 'Tangent',
  nod: 'Node',
  ins: 'Insertion',
  nea: 'Nearest',
  ext: 'Extension',
  par: 'Parallel',
};

const FONT = '12px Inter, system-ui, sans-serif';

export function tipBox(ctx: CanvasRenderingContext2D, x: number, y: number, text: string, fill: string, ink: string, border = css(MEDIA.tipBorder)): void {
  ctx.font = FONT;
  const w = Math.ceil(ctx.measureText(text).width) + 12;
  const h = 20;
  ctx.fillStyle = fill;
  ctx.strokeStyle = border;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.roundRect(Math.round(x) + 0.5, Math.round(y) + 0.5, w, h, 4);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = ink;
  ctx.textBaseline = 'middle';
  ctx.fillText(text, Math.round(x) + 6, Math.round(y) + h / 2 + 1);
}

function stroke(ctx: CanvasRenderingContext2D, color: string, width: number, dash: number[]): void {
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.setLineDash(dash);
}

function highlight(ctx: CanvasRenderingContext2D, e: OverlayEnv, marks: HighlightMark[]): void {
  const { cam, store } = e;
  const tol = 0.5 / cam.scale;
  const vis = cam.visible(8 / cam.scale);
  for (const m of marks) {
    const sel = m.kind === 'selected';
    stroke(ctx, css(sel ? e.th.selection : MEDIA.previewEdge), sel ? 1.5 : 1, sel ? [6, 4] : [6, 4]);
    ctx.lineCap = 'butt';
    let budget = 6000;
    ctx.beginPath();
    for (const h of m.handles) {
      const it = store.items.get(h);
      if (!it || budget-- < 0) continue;
      const b = it.bounds;
      if (it.geom?.type !== 'xline' && it.geom?.type !== 'ray' && (b[0] > vis[2] || b[2] < vis[0] || b[1] > vis[3] || b[3] < vis[1])) continue;
      for (const run of itemRuns(it, tol)) {
        if (run.length === 2) {
          const [sx, sy] = cam.toScreen(run[0], run[1]);
          ctx.moveTo(sx + 3, sy);
          ctx.arc(sx, sy, 3, 0, Math.PI * 2);
          continue;
        }
        const [x0, y0] = cam.toScreen(run[0], run[1]);
        ctx.moveTo(x0, y0);
        for (let i = 2; i < run.length; i += 2) {
          const [x, y] = cam.toScreen(run[i], run[i + 1]);
          ctx.lineTo(x, y);
        }
      }
    }
    ctx.stroke();
  }
  ctx.setLineDash([]);
}

function selectionBox(ctx: CanvasRenderingContext2D, e: OverlayEnv, boxes: BoxMark[]): void {
  for (const b of boxes) {
    const [ax, ay] = e.cam.toScreen(b.x0, b.y0);
    const [bx, by] = e.cam.toScreen(b.x1, b.y1);
    const x = Math.round(Math.min(ax, bx)) + 0.5;
    const y = Math.round(Math.min(ay, by)) + 0.5;
    const w = Math.round(Math.abs(bx - ax));
    const h = Math.round(Math.abs(by - ay));
    ctx.fillStyle = css(b.crossing ? e.th.selCross : e.th.selWindow);
    ctx.fillRect(x, y, w, h);
    if (b.crossing) stroke(ctx, css(MEDIA.crossingEdge), 1, [5, 3]);
    else stroke(ctx, css(MEDIA.windowEdge), 1, []);
    ctx.strokeRect(x, y, w, h);
    ctx.setLineDash([]);
  }
}

function grips(ctx: CanvasRenderingContext2D, e: OverlayEnv, list: GripMark[]): void {
  const side = Math.max(4, e.gripSize * 2);
  const half = side / 2;
  ctx.lineWidth = 1;
  ctx.setLineDash([]);
  for (const g of list) {
    const [sx, sy] = e.cam.toScreen(g.p[0], g.p[1]);
    if (sx < -side || sy < -side || sx > e.width + side || sy > e.height + side) continue;
    const x = Math.round(sx - half) + 0.5;
    const y = Math.round(sy - half) + 0.5;
    const flat = g.kind === 'mid';
    const hh = flat ? half : side;
    const yy = flat ? Math.round(sy - half / 2) + 0.5 : y;
    ctx.fillStyle = css(g.dyn ? MEDIA.gripDynamic : g.state === 'hot' ? MEDIA.gripHot : g.state === 'warm' ? MEDIA.gripWarm : MEDIA.gripCold);
    ctx.strokeStyle = css(MEDIA.gripEdge);
    ctx.fillRect(x, yy, side, flat ? hh : side);
    ctx.strokeRect(x, yy, side, flat ? hh : side);
  }
}

export function snapGlyph(ctx: CanvasRenderingContext2D, mode: string, x: number, y: number, r: number): void {
  ctx.beginPath();
  switch (mode) {
    case 'end':
      ctx.rect(x - r, y - r, r * 2, r * 2);
      break;
    case 'mid':
      ctx.moveTo(x, y - r);
      ctx.lineTo(x + r, y + r);
      ctx.lineTo(x - r, y + r);
      ctx.closePath();
      break;
    case 'cen':
    case 'gcen':
      ctx.arc(x, y, r, 0, Math.PI * 2);
      break;
    case 'qua':
      ctx.moveTo(x, y - r);
      ctx.lineTo(x + r, y);
      ctx.lineTo(x, y + r);
      ctx.lineTo(x - r, y);
      ctx.closePath();
      break;
    case 'int':
      ctx.moveTo(x - r, y - r);
      ctx.lineTo(x + r, y + r);
      ctx.moveTo(x - r, y + r);
      ctx.lineTo(x + r, y - r);
      break;
    case 'app':
      ctx.rect(x - r, y - r, r * 2, r * 2);
      ctx.moveTo(x - r, y - r);
      ctx.lineTo(x + r, y + r);
      ctx.moveTo(x - r, y + r);
      ctx.lineTo(x + r, y - r);
      break;
    case 'per':
      ctx.moveTo(x - r, y - r);
      ctx.lineTo(x - r, y + r);
      ctx.lineTo(x + r, y + r);
      ctx.moveTo(x - r, y);
      ctx.lineTo(x, y);
      ctx.lineTo(x, y + r);
      break;
    case 'tan':
      ctx.arc(x, y, r * 0.8, 0, Math.PI * 2);
      ctx.moveTo(x - r, y - r);
      ctx.lineTo(x + r, y - r);
      break;
    case 'nod':
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.moveTo(x - r * 0.7, y - r * 0.7);
      ctx.lineTo(x + r * 0.7, y + r * 0.7);
      ctx.moveTo(x - r * 0.7, y + r * 0.7);
      ctx.lineTo(x + r * 0.7, y - r * 0.7);
      break;
    case 'ins':
      ctx.rect(x - r, y - r, r * 1.2, r * 1.2);
      ctx.rect(x - r * 0.2, y - r * 0.2, r * 1.2, r * 1.2);
      break;
    default:
      ctx.moveTo(x - r, y - r);
      ctx.lineTo(x + r, y - r);
      ctx.lineTo(x - r, y + r);
      ctx.lineTo(x + r, y + r);
      break;
  }
  ctx.stroke();
}

function snapMarks(ctx: CanvasRenderingContext2D, e: OverlayEnv, list: SnapMark[]): void {
  const r = Math.max(3, e.marker / 2);
  for (const m of list) {
    const [sx, sy] = e.cam.toScreen(m.p[0], m.p[1]);
    stroke(ctx, css(MEDIA.trackPath), 2, []);
    snapGlyph(ctx, m.mode, Math.round(sx), Math.round(sy), r);
    const label = m.label ?? SNAP_NAMES[m.mode];
    if (label) tipBox(ctx, sx + 10, sy + 10, label, css(MEDIA.noteFill), css(MEDIA.noteInk));
  }
}

function tracking(ctx: CanvasRenderingContext2D, e: OverlayEnv, list: TrackMark[]): void {
  const snap = css(e.th.snap);
  for (const t of list) {
    if (t.type === 'path' && t.p && t.q) {
      const [ax, ay] = e.cam.toScreen(t.p[0], t.p[1]);
      const [bx, by] = e.cam.toScreen(t.q[0], t.q[1]);
      stroke(ctx, snap, 1, [1, 5]);
      ctx.beginPath();
      ctx.moveTo(ax, ay);
      ctx.lineTo(bx, by);
      ctx.stroke();
    } else if (t.type === 'cross' && t.p) {
      const [sx, sy] = e.cam.toScreen(t.p[0], t.p[1]);
      stroke(ctx, snap, 1.5, []);
      ctx.beginPath();
      ctx.moveTo(sx - 4, sy - 4);
      ctx.lineTo(sx + 4, sy + 4);
      ctx.moveTo(sx - 4, sy + 4);
      ctx.lineTo(sx + 4, sy - 4);
      ctx.stroke();
    } else if (t.type === 'acquired' && t.p) {
      const [sx, sy] = e.cam.toScreen(t.p[0], t.p[1]);
      stroke(ctx, snap, 1.5, []);
      ctx.beginPath();
      if (t.parallel) {
        ctx.moveTo(sx - 4, sy + 2);
        ctx.lineTo(sx + 2, sy - 4);
        ctx.moveTo(sx - 2, sy + 4);
        ctx.lineTo(sx + 4, sy - 2);
      } else {
        ctx.moveTo(sx - 4, sy);
        ctx.lineTo(sx + 4, sy);
        ctx.moveTo(sx, sy - 4);
        ctx.lineTo(sx, sy + 4);
      }
      ctx.stroke();
    } else if (t.type === 'tip' && t.text) {
      const base = t.p ? e.cam.toScreen(t.p[0], t.p[1]) : e.pointer ? [e.pointer.px, e.pointer.py] : null;
      if (base) tipBox(ctx, base[0] + 16, base[1] + 18, t.text, css(MEDIA.tipPaper), css(MEDIA.tipPaperInk));
    }
  }
  ctx.setLineDash([]);
}

export class OverlayStore {
  private readonly map = new Map<string, unknown[]>();

  set(name: string, items: unknown[] | null): void {
    if (!items || items.length === 0) this.map.delete(name);
    else this.map.set(name, items);
  }

  get<T>(name: string): T[] {
    return (this.map.get(name) as T[] | undefined) ?? [];
  }

  has(name: string): boolean { return this.map.has(name); }
}

export function drawOverlays(ctx: CanvasRenderingContext2D, e: OverlayEnv, o: OverlayStore): void {
  ctx.lineCap = 'butt';
  ctx.lineJoin = 'miter';
  const h = o.get<HighlightMark>('highlight');
  if (h.length) highlight(ctx, e, h);
  const b = o.get<BoxMark>('selection-box');
  if (b.length) selectionBox(ctx, e, b);
  drawMarks(ctx, e.cam, e.th, e.store, e.width, e.height);
  const g = o.get<GripMark>('grips');
  if (g.length) grips(ctx, e, g);
  const t = o.get<TrackMark>('tracking');
  if (t.length) tracking(ctx, e, t);
  const s = o.get<SnapMark>('snap-marker');
  if (s.length) snapMarks(ctx, e, s);
  ctx.setLineDash([]);
}
