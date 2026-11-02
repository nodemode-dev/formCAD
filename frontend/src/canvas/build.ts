import { BatchData } from './batch';
import { opacityOf, pack, packRaw } from './color';
import { dashRun, dashable, polylineLength } from './dash';
import { bandTriangles, fillRings } from './fill';
import { arcPoints, ccwSweep, ellipsePoints, polyPoints, splinePoints } from './tess';
import type { DisplayItem, Geom, Prim, Rect } from './types';

export interface BuildCtx {
  ox: number;
  oy: number;
  tol: number;
  wpp: number;
  lwOn: boolean;
  lwK: number;
  fillOn: boolean;
  trOn: boolean;
  dashOn: boolean;
  ltScale: number;
}

const TAU = Math.PI * 2;

export class Emitter {
  sensitive = false;
  private col = 0;
  private flag = 0;
  private width = 0;
  private thick = false;
  private data!: BatchData;
  private item!: DisplayItem;

  constructor(private readonly ctx: BuildCtx) {}

  emit(item: DisplayItem, data: BatchData): boolean {
    this.sensitive = false;
    this.data = data;
    this.item = item;
    const a = opacityOf(item.tr || 0, this.ctx.trOn);
    const mask = item.kind === 'wipeout';
    if (mask) {
      this.flag = 2;
      this.col = packRaw(0, 0, 0, 255);
      data.split();
    } else if (item.color7) {
      this.flag = 1;
      this.col = packRaw(255, 255, 255, a);
    } else {
      this.flag = 0;
      this.col = pack(item.color[0], item.color[1], item.color[2], a);
    }
    const w = this.ctx.lwOn ? (item.lw || 0) * this.ctx.lwK : 0;
    this.thick = w > 1.001;
    this.width = Math.min(12, Math.max(1, w));
    if (item.geom && item.geom.type !== 'text' && item.geom.type !== 'xline' && item.geom.type !== 'ray') this.geom(item.geom);
    if (item.geom && (item.geom.type === 'xline' || item.geom.type === 'ray')) return false;
    if (item.prims) this.prims(item.prims, item.geom?.type === 'text' ? item.bounds : null);
    if (mask) data.split();
    return this.sensitive;
  }

  private rel(x: number): number { return x - this.ctx.ox; }

  private relY(y: number): number { return y - this.ctx.oy; }

  private tri(x0: number, y0: number, x1: number, y1: number, x2: number, y2: number): void {
    const t = this.data.tri;
    t.vertex(this.rel(x0), this.relY(y0), this.col, this.flag);
    t.vertex(this.rel(x1), this.relY(y1), this.col, this.flag);
    t.vertex(this.rel(x2), this.relY(y2), this.col, this.flag);
  }

  private seg(x0: number, y0: number, x1: number, y1: number): void {
    if (this.thick) {
      this.data.quad.quad(this.rel(x0), this.relY(y0), this.rel(x1), this.relY(y1), this.width, this.col, this.flag);
    } else {
      this.data.line.vertex(this.rel(x0), this.relY(y0), this.col, this.flag);
      this.data.line.vertex(this.rel(x1), this.relY(y1), this.col, this.flag);
    }
  }

  private hair(x0: number, y0: number, x1: number, y1: number): void {
    this.data.line.vertex(this.rel(x0), this.relY(y0), this.col, this.flag);
    this.data.line.vertex(this.rel(x1), this.relY(y1), this.col, this.flag);
  }

  private dot(x: number, y: number): void {
    this.data.quad.quad(this.rel(x), this.relY(y), this.rel(x), this.relY(y), Math.max(2, this.width), this.col, this.flag);
  }

  private chain(pts: number[], closed: boolean): void {
    const n = pts.length;
    if (n < 4) {
      if (n === 2) this.dot(pts[0], pts[1]);
      return;
    }
    for (let i = 2; i < n; i += 2) this.seg(pts[i - 2], pts[i - 1], pts[i], pts[i + 1]);
    if (closed) this.seg(pts[n - 2], pts[n - 1], pts[0], pts[1]);
  }

  private run(pts: number[], closed: boolean, dashed: boolean): void {
    const lt = this.item.lt;
    if (dashed && lt && this.ctx.dashOn && lt.pattern.length > 0) {
      const scale = lt.scale * this.ctx.ltScale;
      const len = polylineLength(pts, closed);
      if (dashable(lt.pattern, scale, len, this.ctx.wpp * 2)) {
        this.sensitive = true;
        dashRun(pts, closed, lt.pattern, scale, (piece) => this.chain(piece, false), (x, y) => this.dot(x, y));
        return;
      }
      if (lt.pattern.every((v) => v <= 0)) return;
    }
    this.chain(pts, closed);
  }

  private geom(g: Geom): void {
    const tol = this.ctx.tol;
    switch (g.type) {
      case 'line':
        this.run([g.p1[0], g.p1[1], g.p2[0], g.p2[1]], false, true);
        break;
      case 'circle': {
        const out: number[] = [];
        arcPoints(g.c[0], g.c[1], g.r, 0, TAU, tol, out);
        this.sensitive = true;
        this.run(out, false, true);
        break;
      }
      case 'arc': {
        const out: number[] = [];
        arcPoints(g.c[0], g.c[1], g.r, g.a0, ccwSweep(g.a0, g.a1), tol, out);
        this.sensitive = true;
        this.run(out, false, true);
        break;
      }
      case 'ellipse': {
        const out: number[] = [];
        const sweep = Math.abs(g.a1 - g.a0) >= TAU - 1e-9 ? TAU : ccwSweep(g.a0, g.a1);
        ellipsePoints(g.c, g.major, g.ratio, g.a0, sweep, tol, out);
        this.sensitive = true;
        this.run(out, false, true);
        break;
      }
      case 'poly': {
        const out: number[] = [];
        polyPoints(g.verts, g.closed, tol, out);
        if (g.verts.some((v) => v.length > 2 && (v[2] ?? 0) !== 0)) this.sensitive = true;
        const hasPrimFill = this.item.prims?.some((p) => p.t === 'fill') ?? false;
        if (this.ctx.fillOn && !hasPrimFill && bandTriangles(g.verts, g.closed, tol, (a, b, c, d, e, f) => this.tri(a, b, c, d, e, f))) {
          if (this.item.tr === 0 || !this.ctx.trOn) this.hair2(out);
        } else this.run(out, false, true);
        break;
      }
      case 'spline': {
        const out: number[] = [];
        splinePoints(g, tol, out);
        if (g.closed && out.length >= 4 && (out[0] !== out[out.length - 2] || out[1] !== out[out.length - 1])) out.push(out[0], out[1]);
        this.sensitive = true;
        this.run(out, false, true);
        break;
      }
      case 'point':
        this.point(g.p[0], g.p[1], g.mode, g.size);
        break;
      case 'compound':
        for (const part of g.parts) if (part.type !== 'xline' && part.type !== 'ray' && part.type !== 'text') this.geom(part);
        break;
      default:
        break;
    }
  }

  private hair2(pts: number[]): void {
    for (let i = 2; i < pts.length; i += 2) this.hair(pts[i - 2], pts[i - 1], pts[i], pts[i + 1]);
  }

  private point(x: number, y: number, mode: number, size: number): void {
    this.sensitive = true;
    const base = mode & 7;
    const usable = size > 0 && size / this.ctx.wpp >= 3;
    if (!usable) {
      this.dot(x, y);
      return;
    }
    const h = size / 2;
    if (base === 0) this.dot(x, y);
    if (base === 2) {
      this.seg(x - h, y, x + h, y);
      this.seg(x, y - h, x, y + h);
    } else if (base === 3) {
      this.seg(x - h, y - h, x + h, y + h);
      this.seg(x - h, y + h, x + h, y - h);
    } else if (base === 4) {
      this.seg(x, y, x, y + h);
    }
    if (mode & 32) {
      const out: number[] = [];
      arcPoints(x, y, h, 0, TAU, this.ctx.tol, out);
      this.chain(out, false);
    }
    if (mode & 64) this.chain([x - h, y - h, x + h, y - h, x + h, y + h, x - h, y + h], true);
  }

  private prims(list: Prim[], textBounds: Rect | null): void {
    if (textBounds) {
      const px = Math.max(textBounds[2] - textBounds[0], textBounds[3] - textBounds[1]) / this.ctx.wpp;
      this.sensitive = true;
      if (px < 2) {
        const [x0, y0, x1, y1] = textBounds;
        this.chain([x0, y0, x1, y0, x1, y1, x0, y1], true);
        return;
      }
    }
    const solid = this.item.kind !== 'hatch' || this.ctx.fillOn;
    for (const p of list) {
      if (p.t === 'pl') {
        if (p.pts.length >= 2) this.chain(p.pts, !!p.closed);
      } else if (p.t === 'tri') {
        if (!solid) continue;
        const a = p.pts;
        for (let i = 0; i + 5 < a.length; i += 6) this.tri(a[i], a[i + 1], a[i + 2], a[i + 3], a[i + 4], a[i + 5]);
      } else if (p.t === 'fill') {
        if (this.ctx.fillOn) fillRings(p.rings, (a, b, c, d, e, f) => this.tri(a, b, c, d, e, f));
        else for (const ring of p.rings) this.chain(ring, true);
      }
    }
  }

  infinite(item: DisplayItem, view: Rect, data: BatchData): void {
    const g = item.geom;
    if (!g || (g.type !== 'xline' && g.type !== 'ray')) return;
    this.data = data;
    this.item = item;
    const a = opacityOf(item.tr || 0, this.ctx.trOn);
    if (item.color7) {
      this.flag = 1;
      this.col = packRaw(255, 255, 255, a);
    } else {
      this.flag = 0;
      this.col = pack(item.color[0], item.color[1], item.color[2], a);
    }
    this.thick = false;
    this.width = 1;
    const ext = (view[2] - view[0] + view[3] - view[1]) * 2;
    const t0 = g.type === 'ray' ? 0 : -ext;
    const dx = g.dir[0];
    const dy = g.dir[1];
    this.hair(g.p[0] + dx * t0, g.p[1] + dy * t0, g.p[0] + dx * ext, g.p[1] + dy * ext);
  }
}
