import { parseCss } from '../canvas/color';
import { tokenCss } from '../canvas/ink';
import { el, q, setText } from '../ui/dom';

export interface Series { name: string; t: number[]; v: number[]; unit: string }

const TOKENS = ['--accent-color', '--canvas-axis-z', '--ok', '--warn', '--canvas-axis-x', '--canvas-axis-y'];

export class PlotView {
  readonly el: HTMLElement;
  private readonly canvas: HTMLCanvasElement;
  private readonly legend: HTMLElement;
  private series: Series[] = [];
  private cursor: number | null = null;
  private stop: number | null = null;
  onScrub: (t: number) => void = () => undefined;
  private box = { x0: 0, x1: 1, t0: 0, t1: 1 };

  constructor(height = 168) {
    this.el = el('<div class="p11-plot"><canvas class="p11-plot-canvas"></canvas><div class="p11-plot-legend"></div></div>');
    this.canvas = q<HTMLCanvasElement>(this.el, 'canvas');
    this.legend = q(this.el, '.p11-plot-legend');
    this.canvas.style.height = `${height}px`;
    new ResizeObserver(() => this.draw()).observe(this.canvas);
    const move = (e: PointerEvent): void => {
      const r = this.canvas.getBoundingClientRect();
      const f = (e.clientX - r.left - this.box.x0) / Math.max(this.box.x1 - this.box.x0, 1);
      this.onScrub(this.box.t0 + Math.max(0, Math.min(1, f)) * (this.box.t1 - this.box.t0));
    };
    this.canvas.addEventListener('pointerdown', (e) => { this.canvas.setPointerCapture(e.pointerId); move(e); });
    this.canvas.addEventListener('pointermove', (e) => { if (this.canvas.hasPointerCapture(e.pointerId)) move(e); });
  }

  set(series: Series[], cursor: number | null, stop: number | null): void {
    this.series = series;
    this.cursor = cursor;
    this.stop = stop;
    const text = series.map((s, i) => `${i + 1}. ${s.name}${s.unit ? ` (${s.unit})` : ''}`).join('   ');
    setText(this.legend, text);
    if (this.legend.title !== text) this.legend.title = text;
    this.draw();
  }

  setCursor(cursor: number | null): void {
    this.cursor = cursor;
    this.draw();
  }

  private draw(): void {
    const c = this.canvas;
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, Math.round(c.clientWidth * dpr)), h = Math.max(1, Math.round(c.clientHeight * dpr));
    if (c.width !== w) c.width = w;
    if (c.height !== h) c.height = h;
    const g = c.getContext('2d');
    if (!g) return;
    const col = (n: string, d: string): string => tokenCss(n, parseCss(d), this.el);
    g.clearRect(0, 0, w, h);
    g.save();
    g.scale(dpr, dpr);
    const W = c.clientWidth, H = c.clientHeight;
    const padL = 44, padR = 8, padT = 8, padB = 18;
    let t0 = Infinity, t1 = -Infinity, v0 = Infinity, v1 = -Infinity;
    for (const s of this.series) {
      for (const x of s.t) { t0 = Math.min(t0, x); t1 = Math.max(t1, x); }
      for (const y of s.v) { v0 = Math.min(v0, y); v1 = Math.max(v1, y); }
    }
    g.font = '10px "JetBrains Mono", ui-monospace, monospace';
    g.fillStyle = col('--text-muted', '#888');
    g.strokeStyle = col('--border-light', '#444');
    g.lineWidth = 1;
    g.strokeRect(padL + 0.5, padT + 0.5, W - padL - padR, H - padT - padB);
    if (!(t1 > t0)) { g.fillText('-', padL + 6, padT + 14); g.restore(); this.box = { x0: padL, x1: W - padR, t0: 0, t1: 1 }; return; }
    if (!(v1 > v0)) { v0 -= 1; v1 += 1; }
    const span = v1 - v0;
    v0 -= span * 0.05; v1 += span * 0.05;
    const X = (t: number): number => padL + ((t - t0) / (t1 - t0)) * (W - padL - padR);
    const Y = (v: number): number => padT + (1 - (v - v0) / (v1 - v0)) * (H - padT - padB);
    this.box = { x0: padL, x1: W - padR, t0, t1 };
    g.strokeStyle = col('--border-soft', 'rgba(255,255,255,0.08)');
    for (let i = 0; i <= 4; i++) {
      const v = v0 + ((v1 - v0) * i) / 4;
      g.beginPath(); g.moveTo(padL, Y(v) + 0.5); g.lineTo(W - padR, Y(v) + 0.5); g.stroke();
      g.fillStyle = col('--text-muted', '#888');
      g.textAlign = 'right';
      g.fillText(Math.abs(v) >= 1000 || (Math.abs(v) < 0.01 && v !== 0) ? v.toExponential(1) : String(Number(v.toFixed(2))), padL - 4, Y(v) + 3);
    }
    g.textAlign = 'center';
    for (let i = 0; i <= 4; i++) {
      const t = t0 + ((t1 - t0) * i) / 4;
      g.fillText(`${Number(t.toFixed(2))}s`, X(t), H - 4);
    }
    this.series.forEach((s, k) => {
      g.strokeStyle = col(TOKENS[k % TOKENS.length], '#f97316');
      g.lineWidth = 1.6;
      g.beginPath();
      s.t.forEach((t, i) => { const x = X(t), y = Y(s.v[i]); if (i) g.lineTo(x, y); else g.moveTo(x, y); });
      g.stroke();
    });
    if (this.stop !== null && this.stop >= t0 && this.stop <= t1) {
      g.strokeStyle = col('--danger', '#ef4444');
      g.setLineDash([4, 3]);
      g.beginPath(); g.moveTo(X(this.stop) + 0.5, padT); g.lineTo(X(this.stop) + 0.5, H - padB); g.stroke();
      g.setLineDash([]);
    }
    if (this.cursor !== null && this.cursor >= t0 && this.cursor <= t1) {
      g.strokeStyle = col('--text-primary', '#fff');
      g.beginPath(); g.moveTo(X(this.cursor) + 0.5, padT); g.lineTo(X(this.cursor) + 0.5, H - padB); g.stroke();
    }
    g.restore();
  }
}
