import { onThemeChange, tokenCss } from '../canvas/ink';
import { MEDIA } from '../canvas/media';

export type Pt = [number, number];
export interface Box { x0: number; y0: number; x1: number; y1: number }

export interface Ink {
  bg: string; grid: string; text: string; muted: string; accent: string; danger: string; warn: string; ok: string;
  wire: string; bus: string; sym: string; pin: string; label: string; paper: string;
  fcu: string; bcu: string; fsilk: string; bsilk: string; edge: string; zone: string; keepout: string; rat: string; hole: string; court: string;
}

const VARS: Record<keyof Ink, string> = {
  bg: '--ec-bg', grid: '--ec-grid', text: '--text-primary', muted: '--text-muted', accent: '--accent-color', danger: '--danger', warn: '--warn', ok: '--ok',
  wire: '--ec-wire', bus: '--ec-bus', sym: '--ec-sym', pin: '--ec-pin', label: '--ec-label', paper: '--ec-paper',
  fcu: '--ec-fcu', bcu: '--ec-bcu', fsilk: '--ec-fsilk', bsilk: '--ec-bsilk', edge: '--ec-edge', zone: '--ec-zone', keepout: '--ec-keepout', rat: '--ec-rat', hole: '--ec-hole', court: '--ec-court',
};

let cache: Ink | null = null;
let watching = false;

export function ink(): Ink {
  if (cache) return cache;
  const scope = document.querySelector('.ec-root') ?? document.body;
  const out = {} as Ink;
  for (const k of Object.keys(VARS) as Array<keyof Ink>) out[k] = tokenCss(VARS[k], MEDIA.ecadFallback, scope);
  cache = out;
  if (!watching) {
    watching = true;
    onThemeChange(() => { cache = null; document.dispatchEvent(new CustomEvent('formcad:ec-ink')); });
  }
  return out;
}

export interface Pointer { x: number; y: number; wx: number; wy: number; ev: PointerEvent; button: number }

export class View2d {
  readonly canvas = document.createElement('canvas');
  readonly g: CanvasRenderingContext2D;
  scale = 6;
  cx = 0;
  cy = 0;
  w = 1;
  h = 1;
  dpr = 1;
  private raf = 0;
  private pan: { x: number; y: number; cx: number; cy: number } | null = null;
  private spaceDown = false;
  paint: (v: View2d, g: CanvasRenderingContext2D) => void = () => undefined;
  down: (p: Pointer) => void = () => undefined;
  move: (p: Pointer) => void = () => undefined;
  up: (p: Pointer) => void = () => undefined;
  dbl: (p: Pointer) => void = () => undefined;
  key: (e: KeyboardEvent) => void = () => undefined;
  onView: () => void = () => undefined;

  constructor(readonly host: HTMLElement) {
    this.canvas.className = 'ec-cv';
    this.canvas.tabIndex = 0;
    this.canvas.setAttribute('aria-label', 'Electronics canvas');
    const g = this.canvas.getContext('2d');
    if (!g) throw new Error('No 2D canvas');
    this.g = g;
    host.appendChild(this.canvas);
    new ResizeObserver(() => this.size()).observe(host);
    document.addEventListener('formcad:ec-ink', () => this.request());
    this.canvas.addEventListener('wheel', (e) => this.wheel(e), { passive: false });
    this.canvas.addEventListener('pointerdown', (e) => this.onDown(e));
    this.canvas.addEventListener('pointermove', (e) => this.onMove(e));
    this.canvas.addEventListener('pointerup', (e) => this.onUp(e));
    this.canvas.addEventListener('pointercancel', (e) => this.onUp(e));
    this.canvas.addEventListener('dblclick', (e) => this.dbl(this.point(e as unknown as PointerEvent)));
    this.canvas.addEventListener('contextmenu', (e) => e.preventDefault());
    this.canvas.addEventListener('keydown', (e) => { if (e.code === 'Space') { this.spaceDown = true; e.preventDefault(); } this.key(e); });
    this.canvas.addEventListener('keyup', (e) => { if (e.code === 'Space') this.spaceDown = false; });
  }

  size(): void {
    const r = this.host.getBoundingClientRect();
    const w = Math.max(1, Math.round(r.width)), h = Math.max(1, Math.round(r.height));
    const dpr = window.devicePixelRatio || 1;
    if (w === this.w && h === this.h && dpr === this.dpr && this.canvas.width) return;
    this.w = w; this.h = h; this.dpr = dpr;
    this.canvas.width = Math.round(w * dpr);
    this.canvas.height = Math.round(h * dpr);
    this.request();
  }

  sx(x: number): number { return (x - this.cx) * this.scale + this.w / 2; }
  sy(y: number): number { return this.h / 2 - (y - this.cy) * this.scale; }
  wx(px: number): number { return (px - this.w / 2) / this.scale + this.cx; }
  wy(py: number): number { return this.cy - (py - this.h / 2) / this.scale; }

  request(): void {
    if (this.raf) return;
    this.raf = requestAnimationFrame(() => {
      this.raf = 0;
      const g = this.g;
      g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      g.clearRect(0, 0, this.w, this.h);
      this.paint(this, g);
    });
  }

  fit(b: Box, pad = 0.12): void {
    this.size();
    const bw = Math.max(b.x1 - b.x0, 1), bh = Math.max(b.y1 - b.y0, 1);
    this.scale = Math.max(0.5, Math.min(this.w / (bw * (1 + pad * 2)), this.h / (bh * (1 + pad * 2))));
    this.cx = (b.x0 + b.x1) / 2;
    this.cy = (b.y0 + b.y1) / 2;
    this.onView();
    this.request();
  }

  zoomBy(f: number, px = this.w / 2, py = this.h / 2): void {
    const wx = this.wx(px), wy = this.wy(py);
    this.scale = Math.min(400, Math.max(0.3, this.scale * f));
    this.cx = wx - (px - this.w / 2) / this.scale;
    this.cy = wy + (py - this.h / 2) / this.scale;
    this.onView();
    this.request();
  }

  centerOn(x: number, y: number): void { this.cx = x; this.cy = y; this.onView(); this.request(); }

  private wheel(e: WheelEvent): void {
    e.preventDefault();
    const r = this.canvas.getBoundingClientRect();
    this.zoomBy(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
  }

  private point(e: PointerEvent): Pointer {
    const r = this.canvas.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;
    return { x, y, wx: this.wx(x), wy: this.wy(y), ev: e, button: e.button };
  }

  private onDown(e: PointerEvent): void {
    this.canvas.focus({ preventScroll: true });
    if (e.button === 1 || e.button === 2 || (e.button === 0 && this.spaceDown)) {
      const p = this.point(e);
      this.pan = { x: p.x, y: p.y, cx: this.cx, cy: this.cy };
      this.canvas.setPointerCapture(e.pointerId);
      return;
    }
    this.canvas.setPointerCapture(e.pointerId);
    this.down(this.point(e));
  }

  private onMove(e: PointerEvent): void {
    const p = this.point(e);
    if (this.pan) {
      this.cx = this.pan.cx - (p.x - this.pan.x) / this.scale;
      this.cy = this.pan.cy + (p.y - this.pan.y) / this.scale;
      this.onView();
      this.request();
      return;
    }
    this.move(p);
  }

  private onUp(e: PointerEvent): void {
    if (this.canvas.hasPointerCapture(e.pointerId)) this.canvas.releasePointerCapture(e.pointerId);
    if (this.pan) { this.pan = null; return; }
    this.up(this.point(e));
  }
}

export const snap = (v: number, grid: number): number => Math.round(v / grid) * grid;
export const round4 = (v: number): number => Math.round(v * 10000) / 10000;

export function segDist(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax, dy = by - ay;
  const l2 = dx * dx + dy * dy;
  const t = l2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / l2));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

export function inPoly(x: number, y: number, poly: Pt[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export function boxOf(pts: Pt[]): Box {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const [x, y] of pts) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
  return { x0, y0, x1, y1 };
}
