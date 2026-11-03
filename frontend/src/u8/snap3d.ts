import { docStore } from '../ui/doc-store';
import type { InkColors } from '../view3d/overlay';
import type { ViewLayer } from '../view3d/layer';
import type { Palette } from '../view3d/kit';
import type { Vec3 } from '../view3d/types';
import type { Viewport3D } from '../view3d/viewport';
import { worldPerPixel } from './geo';
import { docUrl, req } from './net';
import * as THREE from 'three';

export interface SnapCandidate {
  kind: string;
  code: number;
  point: Vec3;
  dist: number;
  handle?: number | null;
  element?: string;
  index?: number | null;
  pid?: number | null;
  normal?: Vec3;
}

const NAMES: Record<string, string> = {
  vertex: 'Vertex', end: 'End', mid: 'Midpoint', centre: 'Centre', quadrant: 'Quadrant', intersection: 'Intersection',
  perpendicular: 'Perpendicular', nearest: 'Nearest', surface: 'On surface', curve: 'On curve',
};

export async function askSnaps(vp: Viewport3D, px: number, py: number, modes?: string[], base?: Vec3, limit = 12): Promise<SnapCandidate[]> {
  const id = docStore.activeId;
  if (!id) return [];
  const ray = vp.rayAt(px, py);
  const wpp = worldPerPixel(vp, vp.rig.target.toArray() as Vec3);
  const res = await req<{ candidates: SnapCandidate[] }>('POST', docUrl(id, 'snap3d'), {
    ray: { origin: ray.origin, dir: ray.direction }, aperture: 10 * wpp, modes: modes ?? null, base: base ?? null, limit,
  });
  return res.candidates;
}

function mark(g: CanvasRenderingContext2D, kind: string, x: number, y: number, r: number): void {
  g.beginPath();
  switch (kind) {
    case 'vertex': case 'end': g.rect(x - r, y - r, 2 * r, 2 * r); break;
    case 'mid': g.moveTo(x, y - r); g.lineTo(x + r, y + r); g.lineTo(x - r, y + r); g.closePath(); break;
    case 'centre': case 'curve': g.arc(x, y, r, 0, Math.PI * 2); break;
    case 'quadrant': g.moveTo(x, y - r); g.lineTo(x + r, y); g.lineTo(x, y + r); g.lineTo(x - r, y); g.closePath(); break;
    case 'intersection': g.moveTo(x - r, y - r); g.lineTo(x + r, y + r); g.moveTo(x + r, y - r); g.lineTo(x - r, y + r); break;
    case 'perpendicular': g.moveTo(x - r, y - r); g.lineTo(x - r, y + r); g.lineTo(x + r, y + r); g.moveTo(x - r, y); g.lineTo(x, y); g.lineTo(x, y + r); break;
    case 'nearest': g.moveTo(x - r, y - r); g.lineTo(x + r, y - r); g.lineTo(x - r, y + r); g.lineTo(x + r, y + r); g.closePath(); break;
    default: g.arc(x, y, r * 0.7, 0, Math.PI * 2); g.moveTo(x - 1, y); g.lineTo(x + 1, y); break;
  }
  g.stroke();
}

export class Snap3dLayer implements ViewLayer {
  readonly group = new THREE.Group();
  enabled = true;
  candidates: SnapCandidate[] = [];
  pick = 0;
  private busy = false;
  private want: { x: number; y: number } | null = null;
  private last = 0;
  private readonly off: Array<() => void> = [];

  constructor(private readonly vp: Viewport3D, private readonly redraw: () => void) {
    const c = vp.canvas;
    const move = (e: PointerEvent): void => {
      if (!this.enabled || (e.buttons & 7) !== 0) return;
      const r = c.getBoundingClientRect();
      this.ask(e.clientX - r.left, e.clientY - r.top);
    };
    const leave = (): void => { this.clear(); };
    const key = (e: KeyboardEvent): void => {
      if (e.key === 'Tab' && this.enabled && this.candidates.length > 1) { this.pick = (this.pick + 1) % this.candidates.length; this.redraw(); }
    };
    c.addEventListener('pointermove', move);
    c.addEventListener('pointerleave', leave);
    c.addEventListener('keydown', key);
    this.off.push(() => c.removeEventListener('pointermove', move), () => c.removeEventListener('pointerleave', leave), () => c.removeEventListener('keydown', key));
  }

  get current(): SnapCandidate | null { return this.candidates.length ? this.candidates[this.pick % this.candidates.length] : null; }

  setEnabled(on: boolean): void {
    this.enabled = on;
    if (!on) this.clear();
  }

  clear(): void {
    this.want = null;
    if (!this.candidates.length) return;
    this.candidates = [];
    this.pick = 0;
    this.redraw();
  }

  private ask(x: number, y: number): void {
    this.want = { x, y };
    if (this.busy || performance.now() - this.last < 40) { if (!this.busy) window.setTimeout(() => this.drain(), 45); return; }
    this.drain();
  }

  private drain(): void {
    const w = this.want;
    if (!w || this.busy || !this.enabled) return;
    this.want = null;
    this.busy = true;
    this.last = performance.now();
    askSnaps(this.vp, w.x, w.y).then((list) => {
      this.busy = false;
      if (!this.enabled) return;
      const same = list.length === this.candidates.length && list.every((c, i) => c.kind === this.candidates[i].kind && c.point.every((v, k) => v === this.candidates[i].point[k]));
      if (!same) { this.candidates = list; this.pick = 0; this.redraw(); }
      if (this.want) this.drain();
    }).catch(() => {
      this.busy = false;
      if (this.candidates.length) { this.candidates = []; this.redraw(); }
    });
  }

  draw(g: CanvasRenderingContext2D, project: (p: Vec3) => { x: number; y: number } | null, ink: InkColors, pal: Palette): void {
    if (!this.enabled || !this.candidates.length) return;
    const cur = this.current;
    g.save();
    g.lineWidth = 1.5;
    this.candidates.forEach((c, i) => {
      const q = project(c.point);
      if (!q) return;
      const top = c === cur;
      g.strokeStyle = top ? `#${pal.snap.getHexString()}` : ink.tipText;
      g.globalAlpha = top ? 1 : 0.55;
      mark(g, c.kind, q.x, q.y, top ? 7 : 4.5);
      if (top) {
        const text = `${NAMES[c.kind] ?? c.kind}${this.candidates.length > 1 ? ` ${i + 1}/${this.candidates.length}` : ''}`;
        g.globalAlpha = 1;
        g.font = '11px -apple-system, "Segoe UI", Inter, system-ui, sans-serif';
        const w = Math.ceil(g.measureText(text).width) + 10;
        g.fillStyle = ink.tipBg;
        g.beginPath();
        g.roundRect(Math.round(q.x + 12) + 0.5, Math.round(q.y + 12) + 0.5, w, 18, 4);
        g.fill();
        g.fillStyle = ink.tipText;
        g.textBaseline = 'middle';
        g.fillText(text, Math.round(q.x + 17), Math.round(q.y + 21));
      }
    });
    g.restore();
  }

  dispose(): void {
    for (const o of this.off) o();
  }
}
