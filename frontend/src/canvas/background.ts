import type { Camera } from './camera';
import { css } from './color';
import { MEDIA } from './media';
import type { Theme } from './theme';
import type { Rect } from './types';

export interface GridOptions {
  on: boolean;
  unitX: number;
  unitY: number;
  major: number;
  isometric: boolean;
  axes: boolean;
}

const MIN_PX = 8;
const MAX_LINES = 2000;

function spacingFor(unit: number, scale: number): number {
  let s = unit;
  for (let i = 0; i < 40 && s * scale < MIN_PX; i++) s *= 5;
  return s;
}

function crisp(v: number): number {
  return Math.round(v) + 0.5;
}

export function drawBackground(ctx: CanvasRenderingContext2D, w: number, h: number, dpr: number, cam: Camera, th: Theme, g: GridOptions, sheet: Rect | null, printable: Rect | null): void {
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const paper = !!sheet;
  ctx.fillStyle = css(paper ? th.surround : th.bg);
  ctx.fillRect(0, 0, w, h);
  if (sheet) {
    const [ax, ay] = cam.toScreen(sheet[0], sheet[3]);
    const [bx, by] = cam.toScreen(sheet[2], sheet[1]);
    ctx.fillStyle = css(th.paperEdge);
    ctx.fillRect(ax + 5, ay + 5, bx - ax, by - ay);
    ctx.fillStyle = css(th.paper);
    ctx.fillRect(ax, ay, bx - ax, by - ay);
    if (printable) {
      const [px, py] = cam.toScreen(printable[0], printable[3]);
      const [qx, qy] = cam.toScreen(printable[2], printable[1]);
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, 0, w, h);
      ctx.clip();
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = css(MEDIA.printableEdge);
      ctx.lineWidth = 1;
      ctx.strokeRect(crisp(px), crisp(py), Math.round(qx - px), Math.round(qy - py));
      ctx.restore();
    }
    return;
  }
  const vis = cam.visible();
  if (g.on) {
    if (g.isometric) drawIso(ctx, h, cam, th, g, vis);
    else drawRect(ctx, w, h, cam, th, g, vis);
  }
  if (g.axes) {
    const [ox, oy] = cam.toScreen(0, 0);
    ctx.lineWidth = 1;
    if (oy >= 0 && oy <= h) {
      ctx.strokeStyle = css(th.axisX);
      ctx.beginPath();
      ctx.moveTo(0, crisp(oy));
      ctx.lineTo(w, crisp(oy));
      ctx.stroke();
    }
    if (ox >= 0 && ox <= w) {
      ctx.strokeStyle = css(th.axisY);
      ctx.beginPath();
      ctx.moveTo(crisp(ox), 0);
      ctx.lineTo(crisp(ox), h);
      ctx.stroke();
    }
  }
}

function drawRect(ctx: CanvasRenderingContext2D, w: number, h: number, cam: Camera, th: Theme, g: GridOptions, vis: Rect): void {
  const s = cam.scale;
  const sx = spacingFor(g.unitX, s);
  const sy = spacingFor(g.unitY, s);
  if (!(sx > 0) || !(sy > 0)) return;
  const nx = Math.floor(vis[2] / sx) - Math.ceil(vis[0] / sx) + 1;
  const ny = Math.floor(vis[3] / sy) - Math.ceil(vis[1] / sy) + 1;
  if (nx >= MAX_LINES || ny >= MAX_LINES) return;
  const major = Math.max(1, Math.round(g.major));
  const minor = new Path2D();
  const maj = new Path2D();
  for (let i = Math.ceil(vis[0] / sx); i <= Math.floor(vis[2] / sx); i++) {
    const x = crisp(cam.toScreen(i * sx, 0)[0]);
    (i % major === 0 ? maj : minor).moveTo(x, 0);
    (i % major === 0 ? maj : minor).lineTo(x, h);
  }
  for (let j = Math.ceil(vis[1] / sy); j <= Math.floor(vis[3] / sy); j++) {
    const y = crisp(cam.toScreen(0, j * sy)[1]);
    (j % major === 0 ? maj : minor).moveTo(0, y);
    (j % major === 0 ? maj : minor).lineTo(w, y);
  }
  ctx.lineWidth = 1;
  ctx.strokeStyle = css(th.grid);
  ctx.stroke(minor);
  ctx.strokeStyle = css(th.gridMajor);
  ctx.stroke(maj);
}

function drawIso(ctx: CanvasRenderingContext2D, h: number, cam: Camera, th: Theme, g: GridOptions, vis: Rect): void {
  const s = cam.scale;
  const u = spacingFor(g.unitY, s * 0.866);
  if (!(u > 0)) return;
  const t = Math.tan(Math.PI / 6);
  const path = new Path2D();
  const dx = u * 0.866;
  const n = Math.floor(vis[2] / dx) - Math.ceil(vis[0] / dx) + 1;
  if (n >= MAX_LINES) return;
  for (let i = Math.ceil(vis[0] / dx); i <= Math.floor(vis[2] / dx); i++) {
    const x = crisp(cam.toScreen(i * dx, 0)[0]);
    path.moveTo(x, 0);
    path.lineTo(x, h);
  }
  const lo = vis[1] - t * Math.max(Math.abs(vis[0]), Math.abs(vis[2]));
  const hi = vis[3] + t * Math.max(Math.abs(vis[0]), Math.abs(vis[2]));
  const kmin = Math.floor(lo / u) - 1;
  const kmax = Math.ceil(hi / u) + 1;
  if (kmax - kmin >= MAX_LINES * 2) return;
  for (let k = kmin; k <= kmax; k++) {
    const c = k * u;
    for (const sign of [1, -1]) {
      const a = cam.toScreen(vis[0], c + sign * t * vis[0]);
      const b = cam.toScreen(vis[2], c + sign * t * vis[2]);
      path.moveTo(a[0], a[1]);
      path.lineTo(b[0], b[1]);
    }
  }
  ctx.lineWidth = 1;
  ctx.strokeStyle = css(th.grid);
  ctx.stroke(path);
}
