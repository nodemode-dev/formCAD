import type { BatchData } from './batch';
import type { DynLayer, PaintView, Painter } from './painter';
import type { PicDraw } from './pictures';
import type { Chunk } from './store';

export class CpuPainter implements Painter {
  readonly kind = 'canvas2d' as const;
  readonly retains = true;
  private readonly ctx: CanvasRenderingContext2D;
  private readonly canvas: HTMLCanvasElement;
  private dpr = 1;
  private w = 1;
  private h = 1;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    const ctx = canvas.getContext('2d', { alpha: true });
    if (!ctx) throw new Error('canvas2d');
    this.ctx = ctx;
  }

  onLost(): void {}

  release(): void {}

  dispose(): void {}

  resize(cssW: number, cssH: number, dpr: number): void {
    const w = Math.max(1, Math.round(cssW * dpr));
    const h = Math.max(1, Math.round(cssH * dpr));
    if (this.canvas.width !== w) this.canvas.width = w;
    if (this.canvas.height !== h) this.canvas.height = h;
    this.dpr = dpr;
    this.w = cssW;
    this.h = cssH;
  }

  private style(col: number, flag: number, v: PaintView): string {
    const a = col >>> 24;
    if (flag === 2) return `rgb(${Math.round(v.bg[0] * 255)},${Math.round(v.bg[1] * 255)},${Math.round(v.bg[2] * 255)})`;
    if (flag === 1) {
      const c = Math.round(v.contrast * 255);
      return `rgba(${c},${c},${c},${(a / 255).toFixed(3)})`;
    }
    if (a === 0) return 'rgba(0,0,0,0)';
    const k = 255 / a;
    return `rgba(${Math.min(255, Math.round((col & 255) * k))},${Math.min(255, Math.round(((col >> 8) & 255) * k))},${Math.min(255, Math.round(((col >> 16) & 255) * k))},${(a / 255).toFixed(3)})`;
  }

  private draw(d: BatchData, ox: number, oy: number, v: PaintView): void {
    const ctx = this.ctx;
    const s = v.scale;
    const bx = (ox - v.cx) * s + this.w / 2;
    const by = this.h / 2 - (oy - v.cy) * s;
    const m = d.marks;
    const t = d.tri;
    const l = d.line;
    const q = d.quad;
    for (let i = 0; i + 1 < m.length; i++) {
      const a = m[i];
      const b = m[i + 1];
      let cur = '';
      ctx.beginPath();
      for (let k = a.t; k < b.t; k += 3) {
        const o = k * 4;
        const st = this.style(t.u[o + 2], t.u[o + 3], v);
        if (st !== cur) {
          if (cur) ctx.fill();
          ctx.beginPath();
          ctx.fillStyle = st;
          cur = st;
        }
        ctx.moveTo(bx + t.f[o] * s, by - t.f[o + 1] * s);
        ctx.lineTo(bx + t.f[o + 4] * s, by - t.f[o + 5] * s);
        ctx.lineTo(bx + t.f[o + 8] * s, by - t.f[o + 9] * s);
        ctx.closePath();
      }
      if (cur) ctx.fill();
      cur = '';
      ctx.lineCap = 'butt';
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let k = a.l; k < b.l; k += 2) {
        const o = k * 4;
        const st = this.style(l.u[o + 2], l.u[o + 3], v);
        if (st !== cur) {
          if (cur) ctx.stroke();
          ctx.beginPath();
          ctx.strokeStyle = st;
          cur = st;
        }
        ctx.moveTo(bx + l.f[o] * s, by - l.f[o + 1] * s);
        ctx.lineTo(bx + l.f[o + 4] * s, by - l.f[o + 5] * s);
      }
      if (cur) ctx.stroke();
      cur = '';
      ctx.lineCap = 'square';
      ctx.beginPath();
      for (let k = a.q; k < b.q; k++) {
        const o = k * 7;
        const st = `${this.style(q.u[o + 5], q.u[o + 6], v)}|${q.f[o + 4]}`;
        if (st !== cur) {
          if (cur) ctx.stroke();
          ctx.beginPath();
          ctx.strokeStyle = this.style(q.u[o + 5], q.u[o + 6], v);
          ctx.lineWidth = Math.max(1, q.f[o + 4]);
          cur = st;
        }
        ctx.moveTo(bx + q.f[o] * s, by - q.f[o + 1] * s);
        ctx.lineTo(bx + q.f[o + 2] * s, by - q.f[o + 3] * s);
      }
      if (cur) ctx.stroke();
    }
  }

  dropPicture(_b: ImageBitmap): void {}

  private ringPath(poly: number[], v: PaintView): void {
    const ctx = this.ctx;
    ctx.beginPath();
    for (let i = 0; i + 1 < poly.length; i += 2) {
      const x = (poly[i] - v.cx) * v.scale + this.w / 2;
      const y = this.h / 2 - (poly[i + 1] - v.cy) * v.scale;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.closePath();
  }

  private picture(p: PicDraw, v: PaintView): void {
    const ctx = this.ctx;
    const sx = (x: number) => (x - v.cx) * v.scale + this.w / 2;
    const sy = (y: number) => this.h / 2 - (y - v.cy) * v.scale;
    const [ox, oy, rx, ry, tx, ty] = p.pts;
    const W = p.bitmap.width;
    const H = p.bitmap.height;
    ctx.save();
    if (p.area) {
      this.ringPath(p.area, v);
      ctx.clip('evenodd');
    }
    if (p.clip) {
      this.ringPath(p.clip, v);
      ctx.clip('evenodd');
    }
    ctx.globalAlpha = 1 - p.fade;
    const d = this.dpr;
    ctx.setTransform(d * (sx(rx) - sx(ox)) / W, d * (sy(ry) - sy(oy)) / W, d * (sx(ox) - sx(tx)) / H, d * (sy(oy) - sy(ty)) / H, d * sx(tx), d * sy(ty));
    ctx.drawImage(p.bitmap, 0, 0);
    ctx.restore();
  }

  frame(v: PaintView, chunks: Iterable<Chunk>, dyn: DynLayer[], under: DynLayer[] = [], pics: PicDraw[] = []): void {
    const ctx = this.ctx;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, this.w, this.h);
    for (const p of pics) this.picture(p, v);
    for (const d of under) {
      if (!d.data) continue;
      ctx.save();
      if (d.clip) {
        ctx.beginPath();
        for (let i = 0; i + 1 < d.clip.length; i += 2) {
          const x = (d.clip[i] - v.cx) * v.scale + this.w / 2;
          const y = this.h / 2 - (d.clip[i + 1] - v.cy) * v.scale;
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.clip('evenodd');
      }
      this.draw(d.data, d.ox, d.oy, v);
      ctx.restore();
    }
    const r = v.visible;
    for (const c of chunks) {
      if (!c.built || !c.data) continue;
      const b = c.bounds;
      if (b && (b[0] > r[2] || b[2] < r[0] || b[1] > r[3] || b[3] < r[1])) continue;
      this.draw(c.data, c.ox, c.oy, v);
    }
    for (const d of dyn) if (d.data) this.draw(d.data, d.ox, d.oy, v);
  }
}
