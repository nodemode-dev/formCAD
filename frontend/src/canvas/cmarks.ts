import type { Camera } from './camera';
import { css } from './color';
import { MEDIA } from './media';
import { itemRuns } from './pick';
import type { DisplayStore } from './store';
import type { Theme } from './theme';
import type { ConstraintBar, ConstraintDim, ConstraintGlyph, Handle, MarkHit } from './types';

export const GLYPH = 18;
const GAP = 2;
const LABEL_H = 18;
const MAX_MARKS = 600;
const FONT = '11px Inter, system-ui, sans-serif';
const RED = css(MEDIA.markError);
const YELLOW = css(MEDIA.markWarn);

export interface Placed {
  kind: 'glyph' | 'dim';
  id: number;
  handle: Handle;
  x: number;
  y: number;
  w: number;
  h: number;
  glyph?: ConstraintGlyph;
  dim?: ConstraintDim;
  state: ConstraintBar['state'];
  text?: string;
}

export interface MarkState {
  hover: MarkHit | null;
  key: string;
  placed: Placed[];
}

export const markState: MarkState = { hover: null, key: '', placed: [] };

export const KIND_NAMES: Record<string, string> = {
  coincident: 'Coincident', collinear: 'Collinear', concentric: 'Concentric', fix: 'Fix', parallel: 'Parallel', perpendicular: 'Perpendicular',
  horizontal: 'Horizontal', vertical: 'Vertical', tangent: 'Tangent', smooth: 'Smooth', symmetric: 'Symmetric', equal: 'Equal',
};

export function barOf(prims: ReadonlyArray<{ t: string }> | undefined): ConstraintBar | null {
  if (!prims) return null;
  for (const p of prims) if (p.t === 'cbar') return p as ConstraintBar;
  return null;
}

export function shownValue(v: number | null): string {
  if (v === null || !Number.isFinite(v)) return '?';
  return String(Number(v.toFixed(4)));
}

export function dimText(d: ConstraintDim): string {
  const body = `${d.name} = ${shownValue(d.value)}`;
  return d.driving ? body : `(${body})`;
}

let measure: CanvasRenderingContext2D | null = null;

function textWidth(text: string): number {
  measure ??= document.createElement('canvas').getContext('2d');
  if (!measure) return text.length * 6;
  measure.font = FONT;
  return Math.ceil(measure.measureText(text).width);
}

function free(placed: Placed[], x: number, y: number, w: number, h: number): boolean {
  for (const p of placed) if (x < p.x + p.w + 1 && x + w + 1 > p.x && y < p.y + p.h + 1 && y + h + 1 > p.y) return false;
  return true;
}

export function layoutMarks(cam: Camera, store: DisplayStore, width: number, height: number): Placed[] {
  const key = `${store.rev}:${store.layoutVersion}:${cam.cx}:${cam.cy}:${cam.scale}:${width}:${height}`;
  if (key === markState.key) return markState.placed;
  const out: Placed[] = [];
  const glyphs = new Map<number, { g: ConstraintGlyph; handle: Handle; state: ConstraintBar['state'] }>();
  const dims = new Map<number, { d: ConstraintDim; handle: Handle; state: ConstraintBar['state'] }>();
  for (const [h, bar] of store.bars) {
    const it = store.items.get(h);
    if (!it) continue;
    const l = store.layers[it.layer];
    if (l && (l.on === false || l.frozen === true)) continue;
    for (const g of bar.glyphs) {
      const have = glyphs.get(g.id);
      if (!have || g.slot < have.g.slot) glyphs.set(g.id, { g, handle: h, state: bar.state });
    }
    for (const d of bar.dims) if (!dims.has(d.id)) dims.set(d.id, { d, handle: h, state: bar.state });
  }
  const margin = 40;
  const onScreen = (sx: number, sy: number): boolean => sx > -margin && sy > -margin && sx < width + margin && sy < height + margin;
  const gl = [...glyphs.values()].sort((a, b) => a.g.id - b.g.id);
  for (const { g, handle, state } of gl) {
    if (out.length >= MAX_MARKS) break;
    const [sx, sy] = cam.toScreen(g.p[0], g.p[1]);
    if (!onScreen(sx, sy)) continue;
    let x = Math.round(sx + 6 + g.slot * (GLYPH + GAP));
    const y = Math.round(sy - GLYPH - 6);
    for (let i = 0; i < 16 && !free(out, x, y, GLYPH, GLYPH); i++) x += GLYPH + GAP;
    out.push({ kind: 'glyph', id: g.id, handle, x, y, w: GLYPH, h: GLYPH, glyph: g, state });
  }
  const dl = [...dims.values()].sort((a, b) => a.d.id - b.d.id);
  for (const { d, handle, state } of dl) {
    if (out.length >= MAX_MARKS) break;
    const [sx, sy] = cam.toScreen(d.p[0], d.p[1]);
    if (!onScreen(sx, sy)) continue;
    const text = dimText(d);
    const w = textWidth(text) + 12 + (d.driving ? 12 : 0);
    const x = Math.round(sx - w / 2);
    let y = Math.round(sy + 10);
    for (let i = 0; i < 16 && !free(out, x, y, w, LABEL_H); i++) y += LABEL_H + 2;
    out.push({ kind: 'dim', id: d.id, handle, x, y, w, h: LABEL_H, dim: d, state, text });
  }
  markState.key = key;
  markState.placed = out;
  return out;
}

export function hitMark(cam: Camera, store: DisplayStore, width: number, height: number, px: number, py: number): MarkHit | null {
  if (store.bars.size === 0) return null;
  const list = layoutMarks(cam, store, width, height);
  for (let i = list.length - 1; i >= 0; i--) {
    const p = list[i];
    if (px >= p.x && px <= p.x + p.w && py >= p.y && py <= p.y + p.h) {
      return { kind: p.kind, id: p.id, handle: p.handle, glyph: p.glyph, dim: p.dim, px: p.x, py: p.y };
    }
  }
  return null;
}

export function handlesOf(store: DisplayStore, id: number): Handle[] {
  const out: Handle[] = [];
  for (const [h, bar] of store.bars) {
    if (bar.glyphs.some((g) => g.id === id) || bar.dims.some((d) => d.id === id)) out.push(h);
  }
  return out;
}

function glyphIcon(ctx: CanvasRenderingContext2D, kind: string, cx: number, cy: number): void {
  const r = 5.5;
  ctx.beginPath();
  switch (kind) {
    case 'coincident':
      ctx.arc(cx, cy, 2, 0, Math.PI * 2);
      ctx.moveTo(cx - r, cy - r);
      ctx.lineTo(cx + r, cy + r);
      break;
    case 'collinear':
      ctx.moveTo(cx - r, cy + 3);
      ctx.lineTo(cx - 1, cy + 3);
      ctx.moveTo(cx + 1, cy - 3);
      ctx.lineTo(cx + r, cy - 3);
      ctx.moveTo(cx - r, cy + r);
      ctx.lineTo(cx + r, cy - r);
      break;
    case 'concentric':
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.moveTo(cx + 2.5, cy);
      ctx.arc(cx, cy, 2.5, 0, Math.PI * 2);
      break;
    case 'fix':
      ctx.rect(cx - 4, cy - 1, 8, 6);
      ctx.moveTo(cx - 2.5, cy - 1);
      ctx.arc(cx, cy - 2, 2.5, Math.PI, 0);
      break;
    case 'parallel':
      ctx.moveTo(cx - 3, cy + r);
      ctx.lineTo(cx + 1, cy - r);
      ctx.moveTo(cx + 1, cy + r);
      ctx.lineTo(cx + 5, cy - r);
      break;
    case 'perpendicular':
      ctx.moveTo(cx - r, cy + r - 1);
      ctx.lineTo(cx + r, cy + r - 1);
      ctx.moveTo(cx, cy + r - 1);
      ctx.lineTo(cx, cy - r);
      break;
    case 'horizontal':
      ctx.moveTo(cx - r, cy);
      ctx.lineTo(cx + r, cy);
      break;
    case 'vertical':
      ctx.moveTo(cx, cy - r);
      ctx.lineTo(cx, cy + r);
      break;
    case 'tangent':
      ctx.arc(cx, cy + 2, 4, 0, Math.PI * 2);
      ctx.moveTo(cx - r, cy - 2);
      ctx.lineTo(cx + r, cy - 2);
      break;
    case 'smooth':
      ctx.moveTo(cx - r, cy + 3);
      ctx.bezierCurveTo(cx - 1, cy + 3, cx + 1, cy - 3, cx + r, cy - 3);
      break;
    case 'symmetric':
      ctx.moveTo(cx, cy - r);
      ctx.lineTo(cx, cy + r);
      ctx.moveTo(cx - 5, cy - 2);
      ctx.lineTo(cx - 2, cy);
      ctx.lineTo(cx - 5, cy + 2);
      ctx.moveTo(cx + 5, cy - 2);
      ctx.lineTo(cx + 2, cy);
      ctx.lineTo(cx + 5, cy + 2);
      break;
    case 'equal':
      ctx.moveTo(cx - r, cy - 2);
      ctx.lineTo(cx + r, cy - 2);
      ctx.moveTo(cx - r, cy + 2);
      ctx.lineTo(cx + r, cy + 2);
      break;
    default:
      ctx.arc(cx, cy, 2.5, 0, Math.PI * 2);
      break;
  }
  ctx.stroke();
}

function lockIcon(ctx: CanvasRenderingContext2D, x: number, y: number): void {
  ctx.beginPath();
  ctx.rect(x - 3, y, 6, 5);
  ctx.moveTo(x - 2, y);
  ctx.arc(x, y - 0.5, 2, Math.PI, 0);
  ctx.stroke();
}

function stateStroke(p: Placed, th: Theme): string {
  if (p.glyph?.dangling) return YELLOW;
  if (p.state === 'over') return RED;
  return css(th.line);
}

export function drawMarks(ctx: CanvasRenderingContext2D, cam: Camera, th: Theme, store: DisplayStore, width: number, height: number): void {
  if (store.bars.size === 0) return;
  const list = layoutMarks(cam, store, width, height);
  if (list.length === 0 && !markState.hover) return;
  const hover = markState.hover;
  if (hover) {
    const tol = 0.5 / cam.scale;
    ctx.strokeStyle = css(th.accent);
    ctx.lineWidth = 2.5;
    ctx.lineCap = 'round';
    ctx.setLineDash([]);
    ctx.beginPath();
    for (const h of handlesOf(store, hover.id)) {
      const it = store.items.get(h);
      if (!it) continue;
      for (const run of itemRuns(it, tol)) {
        if (run.length < 4) continue;
        const [x0, y0] = cam.toScreen(run[0], run[1]);
        ctx.moveTo(x0, y0);
        for (let i = 2; i < run.length; i += 2) {
          const [x, y] = cam.toScreen(run[i], run[i + 1]);
          ctx.lineTo(x, y);
        }
      }
    }
    ctx.stroke();
    ctx.lineCap = 'butt';
  }
  ctx.font = FONT;
  ctx.textBaseline = 'middle';
  ctx.lineWidth = 1;
  ctx.setLineDash([]);
  const ink = css(th.text);
  for (const p of list) {
    const on = !!hover && hover.id === p.id && hover.kind === p.kind;
    ctx.fillStyle = css(th.panel);
    ctx.strokeStyle = on ? css(th.accent) : stateStroke(p, th);
    ctx.lineWidth = on ? 2 : 1;
    ctx.beginPath();
    ctx.roundRect(p.x + 0.5, p.y + 0.5, p.w - 1, p.h - 1, 4);
    ctx.fill();
    ctx.stroke();
    ctx.lineWidth = 1.3;
    if (p.kind === 'glyph' && p.glyph) {
      ctx.strokeStyle = p.glyph.dangling ? YELLOW : ink;
      glyphIcon(ctx, p.glyph.k, p.x + p.w / 2, p.y + p.h / 2);
    } else if (p.dim && p.text) {
      let tx = p.x + 6;
      if (p.dim.driving) {
        ctx.strokeStyle = ink;
        lockIcon(ctx, p.x + 11, p.y + 6);
        tx = p.x + 20;
      }
      ctx.fillStyle = p.dim.value === null ? RED : ink;
      ctx.fillText(p.text, tx, p.y + p.h / 2 + 1);
    }
  }
}
