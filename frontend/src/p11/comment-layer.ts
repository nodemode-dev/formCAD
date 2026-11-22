import * as THREE from 'three';
import { parseCss } from '../canvas/color';
import { tokenCss, tokenHexCss } from '../canvas/ink';
import { token } from '../io/api';
import type { Palette } from '../view3d/kit';
import type { ViewLayer, Projector } from '../view3d/layer';
import type { InkColors } from '../view3d/overlay';
import type { Vec3 } from '../view3d/types';
import type { Viewport3D } from '../view3d/viewport';
import { el, q, setClass } from '../ui/dom';
import { vstore, type Comment } from './vault-store';

const NS = 'http://www.w3.org/2000/svg';

export const entityHandle = (entity: string): number | null => {
  const m = /^entity:(\d+)$/.exec(entity);
  return m ? Number(m[1]) : null;
};

export class CommentLayer implements ViewLayer {
  readonly group = new THREE.Group();
  private list: Comment[] = [];
  private shownOn = true;
  private focus = 0;
  private ink = { open: '#9a7bd8', resolved: '#22c55e' };
  readonly overlay: MarkupOverlay;

  constructor(private readonly vp: Viewport3D) {
    this.overlay = new MarkupOverlay(vp);
  }

  palette(_pal: Palette): void {
    this.ink = { open: tokenCss('--accent-color', parseCss('#9a7bd8'), this.vp.host), resolved: tokenCss('--ok', parseCss('#22c55e'), this.vp.host) };
    this.vp.invalidate();
  }

  bounds(): { min: Vec3; max: Vec3 } | null { return null; }

  set(list: Comment[]): void {
    const sig = list.map((c) => `${c.id}${c.status}${c.entity}${c.attached}`).join('|');
    const prev = this.list.map((c) => `${c.id}${c.status}${c.entity}${c.attached}`).join('|');
    this.list = list;
    if (sig !== prev) this.vp.invalidate();
  }

  setShown(on: boolean): void { this.shownOn = on; this.vp.invalidate(); }
  highlight(id: number): void { if (this.focus !== id) { this.focus = id; this.vp.invalidate(); } }

  centre(entity: string): Vec3 | null {
    const h = entityHandle(entity);
    if (h === null) return null;
    const v = this.vp.bodyViews.get(h);
    if (!v) return null;
    return [(v.min[0] + v.max[0]) / 2, (v.min[1] + v.max[1]) / 2, (v.min[2] + v.max[2]) / 2];
  }

  draw(g: CanvasRenderingContext2D, project: Projector, ink: InkColors): void {
    if (!this.shownOn) return;
    g.save();
    g.font = '600 11px -apple-system, "Segoe UI", Inter, system-ui, sans-serif';
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    const used = new Map<string, number>();
    this.list.forEach((c, i) => {
      if (c.parent !== null || !c.attached) return;
      const at = this.centre(c.entity);
      if (!at) return;
      const p = project(at);
      if (!p) return;
      const n = used.get(c.entity) ?? 0;
      used.set(c.entity, n + 1);
      const x = p.x + n * 20, y = p.y;
      g.fillStyle = ink.tipBg;
      g.strokeStyle = c.status === 'resolved' ? this.ink.resolved : this.ink.open;
      g.lineWidth = c.id === this.focus ? 3 : 1.5;
      g.beginPath();
      g.arc(x, y, 10, 0, Math.PI * 2);
      g.fill();
      g.stroke();
      g.fillStyle = ink.tipText;
      g.fillText(String(i + 1), x, y + 0.5);
    });
    g.restore();
  }

  dispose(): void { this.overlay.dispose(); }
}

export class MarkupOverlay {
  readonly root: HTMLElement;
  private readonly svg: SVGSVGElement;
  private readonly strokes: SVGPathElement[] = [];
  private current: { path: SVGPathElement; pts: number[][] } | null = null;
  drawing = false;
  onStroke: () => void = () => undefined;

  constructor(private readonly vp: Viewport3D) {
    this.root = el('<div class="p11-markup" hidden><svg class="p11-markup-svg"></svg></div>');
    this.svg = q<SVGSVGElement>(this.root, 'svg');
    vp.host.appendChild(this.root);
    this.root.addEventListener('pointerdown', (e) => {
      if (!this.drawing) return;
      const r = this.root.getBoundingClientRect();
      this.sizeBox();
      const path = document.createElementNS(NS, 'path');
      path.setAttribute('class', 'p11-stroke');
      this.svg.appendChild(path);
      this.strokes.push(path);
      this.current = { path, pts: [[e.clientX - r.left, e.clientY - r.top]] };
      this.root.setPointerCapture(e.pointerId);
      this.paint();
    });
    this.root.addEventListener('pointermove', (e) => {
      if (!this.current) return;
      const r = this.root.getBoundingClientRect();
      this.current.pts.push([e.clientX - r.left, e.clientY - r.top]);
      this.paint();
    });
    this.root.addEventListener('pointerup', () => { if (this.current) { this.current = null; this.onStroke(); } });
  }

  private sizeBox(): void {
    const r = this.root.getBoundingClientRect();
    const vb = `0 0 ${Math.round(r.width)} ${Math.round(r.height)}`;
    if (this.svg.getAttribute('viewBox') !== vb) this.svg.setAttribute('viewBox', vb);
  }

  private paint(): void {
    if (!this.current) return;
    this.current.path.setAttribute('d', this.current.pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(''));
  }

  setDrawing(on: boolean): void {
    this.drawing = on;
    setClass(this.root, 'is-drawing', on);
    if (on) { this.root.hidden = false; this.sizeBox(); } else if (!this.strokes.length) this.root.hidden = true;
  }

  hasStrokes(): boolean { return this.strokes.length > 0; }

  clear(): void {
    for (const s of this.strokes) s.remove();
    this.strokes.length = 0;
    this.current = null;
    if (!this.drawing) this.root.hidden = true;
  }

  svgText(): string {
    const r = this.root.getBoundingClientRect();
    const stroke = tokenHexCss('--accent-color', parseCss('#9a7bd8'), this.vp.host);
    const paths = this.strokes.map((p) => `<path d="${p.getAttribute('d') ?? ''}" fill="none" stroke="${stroke}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`).join('');
    return `<svg xmlns="${NS}" viewBox="0 0 ${Math.round(r.width)} ${Math.round(r.height)}">${paths}</svg>`;
  }

  async show(base: string, id: number): Promise<boolean> {
    const tok = token();
    let text = '';
    try {
      const res = await fetch(`${base}/comments/${id}/markup`, { headers: tok ? { 'X-FormCAD-Token': tok } : {} });
      if (!res.ok) return false;
      text = await res.text();
    } catch { return false; }
    const doc = new DOMParser().parseFromString(text, 'image/svg+xml');
    const root = doc.documentElement;
    const vb = root.getAttribute('viewBox') ?? '';
    if (!/^[\d.\s-]+$/.test(vb)) return false;
    this.clear();
    this.svg.setAttribute('viewBox', vb);
    for (const p of Array.from(doc.querySelectorAll('path'))) {
      const d = p.getAttribute('d') ?? '';
      if (!/^[MLCQZ\d.\s,-]+$/i.test(d)) continue;
      const path = document.createElementNS(NS, 'path');
      path.setAttribute('class', 'p11-stroke');
      path.setAttribute('d', d);
      this.svg.appendChild(path);
      this.strokes.push(path);
    }
    this.root.hidden = false;
    return this.strokes.length > 0;
  }

  dispose(): void { this.root.remove(); }
}
