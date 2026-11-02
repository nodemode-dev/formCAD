import type { Pt, Rect, ViewState } from './types';

export const MIN_HEIGHT = 1e-9;
export const MAX_HEIGHT = 1e12;

const clampHeight = (h: number): number => Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, h));

export class Camera {
  cx = 0;
  cy = 0;
  height = 297;
  width = 1;
  heightPx = 1;

  get scale(): number { return this.heightPx / this.height; }

  get aspect(): number { return this.width / this.heightPx; }

  setSize(w: number, h: number): void {
    this.width = Math.max(1, w);
    this.heightPx = Math.max(1, h);
  }

  set(cx: number, cy: number, height: number): boolean {
    if (!Number.isFinite(cx) || !Number.isFinite(cy) || !Number.isFinite(height) || height <= 0) return false;
    this.cx = cx;
    this.cy = cy;
    this.height = clampHeight(height);
    return true;
  }

  state(): ViewState {
    return { cx: this.cx, cy: this.cy, height: this.height, scale: this.scale, width: this.width, heightPx: this.heightPx };
  }

  toWorld(px: number, py: number): Pt {
    const s = this.scale;
    return [this.cx + (px - this.width / 2) / s, this.cy - (py - this.heightPx / 2) / s];
  }

  toScreen(x: number, y: number): Pt {
    const s = this.scale;
    return [(x - this.cx) * s + this.width / 2, (this.cy - y) * s + this.heightPx / 2];
  }

  panBy(dxPx: number, dyPx: number): void {
    const s = this.scale;
    this.set(this.cx - dxPx / s, this.cy + dyPx / s, this.height);
  }

  zoomAt(factor: number, px: number, py: number): void {
    if (!Number.isFinite(factor) || factor <= 0) return;
    const [wx, wy] = this.toWorld(px, py);
    const next = clampHeight(this.height / factor);
    const ratio = next / this.height;
    this.set(wx + (this.cx - wx) * ratio, wy + (this.cy - wy) * ratio, next);
  }

  fit(rect: Rect): void {
    const w = Math.max(rect[2] - rect[0], 0);
    const h = Math.max(rect[3] - rect[1], 0);
    const height = Math.max(h, w / this.aspect, 1e-6) * 1.05;
    this.set((rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2, height);
  }

  window(rect: Rect): void {
    this.fit(rect);
  }

  visible(margin = 0): Rect {
    const hw = (this.width / this.scale) / 2;
    const hh = this.height / 2;
    return [this.cx - hw - margin, this.cy - hh - margin, this.cx + hw + margin, this.cy + hh + margin];
  }

  band(): number {
    return Math.floor(Math.log2(Math.max(1e-30, 1 / this.scale)));
  }
}

export function zoomFactorFor(deltaPoints: number, zoomFactor: number): number {
  const k = zoomFactor / 60;
  const e = Math.max(-40, Math.min(40, (deltaPoints / 300) * k));
  return Math.exp(e);
}
