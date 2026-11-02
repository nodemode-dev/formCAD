import * as THREE from 'three';
import type { Palette } from './kit';
import type { SnapKind } from './types';

export interface InkColors {
  tipBg: string;
  tipText: string;
  tipLine: string;
  text: string;
}

export function resolveInk(probe: HTMLElement): InkColors {
  const read = (prop: string, fallback: string): string => {
    probe.style.color = '';
    probe.style.color = `var(${prop})`;
    const c = getComputedStyle(probe).color;
    probe.style.color = '';
    return c || fallback;
  };
  return {
    tipBg: read('--surface-1', '#1e1e22'),
    tipText: read('--text-primary', '#e6e6e6'),
    tipLine: read('--line-2', '#44444a'),
    text: read('--text-secondary', '#a4a4a4'),
  };
}

export class Overlay {
  readonly canvas = document.createElement('canvas');
  private readonly ctx: CanvasRenderingContext2D;
  private dpr = 1;
  private w = 1;
  private h = 1;
  ink: InkColors = { tipBg: '#1e1e22', tipText: '#e6e6e6', tipLine: '#44444a', text: '#a4a4a4' };

  constructor() {
    this.canvas.className = 'v3-overlay';
    this.canvas.setAttribute('aria-hidden', 'true');
    const c = this.canvas.getContext('2d');
    if (!c) throw new Error('canvas2d unavailable');
    this.ctx = c;
  }

  size(w: number, h: number, dpr: number): void {
    this.w = w; this.h = h; this.dpr = dpr;
    const bw = Math.max(1, Math.round(w * dpr)), bh = Math.max(1, Math.round(h * dpr));
    if (this.canvas.width !== bw) this.canvas.width = bw;
    if (this.canvas.height !== bh) this.canvas.height = bh;
  }

  begin(): CanvasRenderingContext2D {
    const g = this.ctx;
    g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    g.clearRect(0, 0, this.w, this.h);
    return g;
  }

  marker(g: CanvasRenderingContext2D, kind: SnapKind, x: number, y: number, color: string): void {
    const r = 6;
    g.save();
    g.lineWidth = 2;
    g.strokeStyle = color;
    g.beginPath();
    if (kind === 'vertex') g.rect(x - r, y - r, r * 2, r * 2);
    else if (kind === 'midpoint') { g.moveTo(x, y - r); g.lineTo(x + r, y + r * 0.8); g.lineTo(x - r, y + r * 0.8); g.closePath(); }
    else if (kind === 'center') g.arc(x, y, r, 0, Math.PI * 2);
    else { g.moveTo(x - r, y - r); g.lineTo(x + r, y - r); g.lineTo(x - r, y + r); g.lineTo(x + r, y + r); g.closePath(); }
    g.stroke();
    g.restore();
  }

  tip(g: CanvasRenderingContext2D, text: string, x: number, y: number): void {
    if (!text) return;
    g.save();
    g.font = '11px -apple-system, "Segoe UI", Inter, system-ui, sans-serif';
    g.textBaseline = 'middle';
    const tw = Math.ceil(g.measureText(text).width);
    const bw = tw + 12, bh = 20;
    let bx = x + 14, by = y + 14;
    if (bx + bw > this.w - 4) bx = x - bw - 10;
    if (by + bh > this.h - 4) by = y - bh - 10;
    g.fillStyle = this.ink.tipBg;
    g.strokeStyle = this.ink.tipLine;
    g.lineWidth = 1;
    g.beginPath();
    g.roundRect(bx + 0.5, by + 0.5, bw, bh, 4);
    g.fill();
    g.stroke();
    g.fillStyle = this.ink.tipText;
    g.fillText(text, bx + 6, by + bh / 2 + 0.5);
    g.restore();
  }

  triad(g: CanvasRenderingContext2D, q: THREE.Quaternion, pal: Palette): void {
    const ox = 46, oy = this.h - 46, len = 28;
    const inv = q.clone().invert();
    const axes: Array<[THREE.Vector3, THREE.Color, string]> = [
      [new THREE.Vector3(1, 0, 0), pal.axisX, 'X'],
      [new THREE.Vector3(0, 1, 0), pal.axisY, 'Y'],
      [new THREE.Vector3(0, 0, 1), pal.axisZ, 'Z'],
    ];
    const proj = axes.map(([a, c, l]) => ({ v: a.clone().applyQuaternion(inv), c, l })).sort((a, b) => a.v.z - b.v.z);
    g.save();
    g.lineWidth = 2;
    g.lineCap = 'round';
    g.font = '600 10px -apple-system, "Segoe UI", Inter, system-ui, sans-serif';
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    for (const p of proj) {
      const ex = ox + p.v.x * len, ey = oy - p.v.y * len;
      g.strokeStyle = `#${p.c.getHexString()}`;
      g.globalAlpha = p.v.z < -0.2 ? 0.55 : 1;
      g.beginPath();
      g.moveTo(ox, oy);
      g.lineTo(ex, ey);
      g.stroke();
      g.fillStyle = `#${p.c.getHexString()}`;
      g.fillText(p.l, ox + p.v.x * (len + 9), oy - p.v.y * (len + 9));
    }
    g.restore();
  }

  points(g: CanvasRenderingContext2D, pts: Array<[number, number]>, color: string): void {
    g.save();
    g.fillStyle = color;
    pts.forEach(([x, y], i) => {
      g.beginPath();
      g.arc(x, y, 4, 0, Math.PI * 2);
      g.fill();
      g.fillStyle = this.ink.tipText;
      g.font = '600 10px -apple-system, "Segoe UI", Inter, system-ui, sans-serif';
      g.fillText(String(i + 1), x + 7, y - 7);
      g.fillStyle = color;
    });
    g.restore();
  }
}
