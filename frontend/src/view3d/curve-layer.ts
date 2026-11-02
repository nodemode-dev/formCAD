import * as THREE from 'three';
import { Line2 } from 'three/examples/jsm/lines/Line2.js';
import { LineGeometry } from 'three/examples/jsm/lines/LineGeometry.js';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { api } from '../io/api';
import { events } from '../io/events';
import { docStore } from '../ui/doc-store';
import { selection } from '../ui/panels/selection-bus';
import { toast } from '../ui/toast';
import type { Palette } from './kit';
import { readPalette } from './kit';
import type { ViewLayer } from './layer';
import type { InkColors } from './overlay';
import { fetchCurves, type CurveRow } from './nurbs-api';
import type { Vec3 } from './types';
import type { Viewport3D } from './viewport';

export type PointMode = 'off' | 'cv' | 'ep';

interface GripRef { id: string; at: Vec3 }

interface Item {
  row: CurveRow;
  key: string;
  line: Line2;
  poly: THREE.Line;
  cv: GripRef[];
  ep: GripRef[];
}

interface Drag {
  handle: number;
  grip: GripRef;
  kind: 'cv' | 'ep';
  index: number;
  px: number;
  py: number;
  moved: boolean;
}

const HIT = 9;
const rgb = (c: THREE.Color): string => `#${c.getHexString()}`;

function expandKnots(row: CurveRow): number[] {
  const out: number[] = [];
  row.knots.forEach((k, i) => { for (let m = 0; m < row.mults[i]; m++) out.push(k); });
  return out;
}

function evaluate(row: CurveRow, per: number): Vec3[] | null {
  if (row.periodic) return null;
  const p = row.degree;
  const U = expandKnots(row);
  const n = row.poles.length;
  if (U.length !== n + p + 1) return null;
  const rational = row.weights.length === n;
  const at = (u: number): Vec3 => {
    let s = p;
    while (s < n - 1 && u >= U[s + 1]) s++;
    const d: number[][] = [];
    for (let j = 0; j <= p; j++) {
      const i = s - p + j;
      const w = rational ? row.weights[i] : 1;
      d.push([row.poles[i][0] * w, row.poles[i][1] * w, row.poles[i][2] * w, w]);
    }
    for (let r = 1; r <= p; r++) {
      for (let j = p; j >= r; j--) {
        const den = U[s + 1 + j - r] - U[s - p + j];
        const a = den > 0 ? (u - U[s - p + j]) / den : 0;
        for (let c = 0; c < 4; c++) d[j][c] = (1 - a) * d[j - 1][c] + a * d[j][c];
      }
    }
    const h = d[p];
    return [h[0] / h[3], h[1] / h[3], h[2] / h[3]];
  };
  const out: Vec3[] = [];
  for (let i = 0; i < row.knots.length - 1; i++) {
    const a = row.knots[i], b = row.knots[i + 1];
    for (let k = 0; k < per; k++) out.push(at(a + ((b - a) * k) / per));
  }
  const last = row.knots[row.knots.length - 1];
  out.push(at(last - (last - row.knots[row.knots.length - 2]) * 1e-12));
  return out;
}

const flat = (pts: Vec3[]): number[] => pts.flatMap((p) => p);

export class CurveLayer implements ViewLayer {
  readonly group = new THREE.Group();
  mode: PointMode = 'off';
  private readonly items = new Map<number, Item>();
  private readonly lineMat: LineMaterial;
  private readonly selMat: LineMaterial;
  private readonly polyMat: THREE.LineBasicMaterial;
  private pal: Palette;
  private selected = new Set<number>();
  private hover: { handle: number; kind: 'cv' | 'ep'; index: number } | null = null;
  private drag: Drag | null = null;
  private down: { x: number; y: number } | null = null;
  private timer = 0;
  private busy = false;
  private again = false;
  private loaded = false;
  private fitted = false;
  private readonly off: Array<() => void> = [];

  constructor(private readonly vp: Viewport3D) {
    this.pal = readPalette(vp.host);
    this.lineMat = new LineMaterial({ color: this.pal.accent.getHex(), linewidth: 2.2, worldUnits: false });
    this.selMat = new LineMaterial({ color: this.pal.select.getHex(), linewidth: 3, worldUnits: false });
    this.polyMat = new THREE.LineBasicMaterial({ color: this.pal.snap, transparent: true, opacity: 0.55, depthTest: false });
    this.group.renderOrder = 4;
    const host = vp.host;
    const add = <K extends keyof HTMLElementEventMap>(type: K, fn: (e: HTMLElementEventMap[K]) => void): void => {
      host.addEventListener(type, fn as EventListener, { capture: true });
      this.off.push(() => host.removeEventListener(type, fn as EventListener, { capture: true }));
    };
    add('pointerdown', (e) => this.onDown(e));
    add('pointermove', (e) => this.onMove(e));
    add('pointerup', (e) => this.onUp(e));
    this.off.push(selection.onChange((s) => { this.setSelected(s.handles); }));
    const ev = events.on('doc', (e) => {
      if (e.id !== docStore.activeId) return;
      if (!this.on) this.loaded = false;
      else if (!this.drag) this.schedule();
    });
    this.off.push(ev);
    this.setSelected(selection.handles);
  }

  private get on(): boolean { return this.vp.active; }

  reset(): void {
    this.loaded = false;
    this.fitted = false;
    this.clear();
  }

  setMode(m: PointMode): void {
    if (m === this.mode) return;
    this.mode = m;
    this.syncVisible();
    this.vp.invalidate();
  }

  private syncVisible(): void {
    for (const [h, it] of this.items) {
      const v = this.showsPoints(h) && this.kindFor() === 'cv';
      if (it.poly.visible !== v) it.poly.visible = v;
    }
  }

  get count(): number { return this.items.size; }
  get shown(): number { return [...this.items.keys()].filter((h) => this.showsPoints(h)).length; }

  gripsOf(handle: number): { cv: GripRef[]; ep: GripRef[] } | null {
    const it = this.items.get(handle);
    return it ? { cv: it.cv, ep: it.ep } : null;
  }

  private setSelected(handles: number[]): void {
    const next = new Set(handles);
    if (next.size === this.selected.size && [...next].every((h) => this.selected.has(h))) return;
    this.selected = next;
    for (const [h, it] of this.items) it.line.material = next.has(h) ? this.selMat : this.lineMat;
    this.syncVisible();
    this.vp.invalidate();
  }

  private showsPoints(handle: number): boolean {
    return this.mode !== 'off' || this.selected.has(handle);
  }

  private kindFor(): 'cv' | 'ep' {
    return this.mode === 'ep' ? 'ep' : 'cv';
  }

  schedule(): void {
    if (this.timer) return;
    this.timer = window.setTimeout(() => { this.timer = 0; void this.refresh(); }, 100);
  }

  async refresh(): Promise<void> {
    const doc = docStore.activeId;
    if (!doc) { this.clear(); return; }
    if (this.busy) { this.again = true; return; }
    this.busy = true;
    try {
      do {
        this.again = false;
        const list = await fetchCurves(doc, 16);
        if (docStore.activeId !== doc) break;
        const handles = list.curves.filter((c) => !c.error).map((c) => c.handle);
        const sets = handles.length ? await api.gripSets(doc, handles).catch(() => ({ sets: [] })) : { sets: [] };
        this.apply(list.curves, sets.sets);
      } while (this.again);
    } catch {
      return;
    } finally {
      this.busy = false;
    }
  }

  private apply(rows: CurveRow[], sets: Array<{ h: string | number; grips: Array<{ id: string | number; p: [number, number]; kind?: string }> }>): void {
    const gripBy = new Map<number, Array<{ id: string; kind: string }>>();
    for (const s of sets) gripBy.set(Number(s.h), s.grips.map((g) => ({ id: String(g.id), kind: g.kind ?? '' })));
    const seen = new Set<number>();
    for (const row of rows) {
      if (row.error) continue;
      seen.add(row.handle);
      const gl = gripBy.get(row.handle) ?? [];
      const cvIds = gl.filter((g) => g.id.startsWith('c')).map((g) => g.id);
      const epIds = gl.filter((g) => g.id.startsWith('e')).map((g) => g.id);
      const key = JSON.stringify([row.poles, row.weights, row.knots, row.mults, row.samples.length, row.samples[0], row.samples[row.samples.length - 1], row.samples[row.samples.length >> 1]]);
      let it = this.items.get(row.handle);
      if (!it) {
        const line = new Line2(new LineGeometry(), this.selected.has(row.handle) ? this.selMat : this.lineMat);
        line.frustumCulled = false;
        const poly = new THREE.Line(new THREE.BufferGeometry(), this.polyMat);
        poly.frustumCulled = false;
        poly.renderOrder = 4;
        this.group.add(line, poly);
        it = { row, key: '', line, poly, cv: [], ep: [] };
        this.items.set(row.handle, it);
      }
      it.row = row;
      it.cv = row.poles.map((at, i) => ({ id: cvIds[i] ?? `c${i}`, at }));
      it.ep = row.edit_points.map((at, i) => ({ id: epIds[i] ?? `e${i}`, at }));
      if (it.key !== key) {
        it.key = key;
        this.paint(it, row.samples);
      }
    }
    for (const [h, it] of this.items) {
      if (seen.has(h)) continue;
      this.drop(it);
      this.items.delete(h);
    }
    this.syncVisible();
    if (!this.fitted && this.items.size && !this.vp.hasBodies) { this.fitted = true; this.vp.fitLayers(); }
    this.vp.invalidate();
  }

  bounds(): { min: Vec3; max: Vec3 } | null {
    const min: Vec3 = [Infinity, Infinity, Infinity], max: Vec3 = [-Infinity, -Infinity, -Infinity];
    for (const it of this.items.values()) for (const p of it.row.poles) for (let k = 0; k < 3; k++) { min[k] = Math.min(min[k], p[k]); max[k] = Math.max(max[k], p[k]); }
    return Number.isFinite(min[0]) ? { min, max } : null;
  }

  private paint(it: Item, samples: Vec3[]): void {
    if (samples.length >= 2) {
      it.line.geometry.dispose();
      it.line.geometry = new LineGeometry();
      it.line.geometry.setPositions(flat(samples));
      it.line.computeLineDistances();
    }
    it.poly.geometry.setFromPoints(it.row.poles.map((p) => new THREE.Vector3(p[0], p[1], p[2])));
    it.poly.geometry.computeBoundingSphere();
  }

  private drop(it: Item): void {
    this.group.remove(it.line, it.poly);
    it.line.geometry.dispose();
    it.poly.geometry.dispose();
  }

  private clear(): void {
    for (const it of this.items.values()) this.drop(it);
    this.items.clear();
    this.vp.invalidate();
  }

  resolution(w: number, h: number): void {
    this.lineMat.resolution.set(w, h);
    this.selMat.resolution.set(w, h);
  }

  palette(p: Palette): void {
    this.pal = p;
    this.lineMat.color.copy(p.accent);
    this.selMat.color.copy(p.select);
    this.polyMat.color.copy(p.snap);
  }

  private local(e: PointerEvent): { x: number; y: number } {
    const r = this.vp.canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  private hitGrip(x: number, y: number): { handle: number; kind: 'cv' | 'ep'; index: number; grip: GripRef } | null {
    let best: { handle: number; kind: 'cv' | 'ep'; index: number; grip: GripRef } | null = null;
    let bestD = HIT;
    const kind = this.kindFor();
    for (const [handle, it] of this.items) {
      if (!this.showsPoints(handle)) continue;
      const list = kind === 'cv' ? it.cv : it.ep;
      list.forEach((grip, index) => {
        const q = this.vp.project(grip.at);
        if (!q) return;
        const d = Math.hypot(q.x - x, q.y - y);
        if (d < bestD) { bestD = d; best = { handle, kind, index, grip }; }
      });
    }
    return best;
  }

  private hitCurve(x: number, y: number): number | null {
    let best: number | null = null;
    let bestD = 6;
    for (const [handle, it] of this.items) {
      const pts = it.row.samples;
      let prev: { x: number; y: number } | null = null;
      for (const p of pts) {
        const q = this.vp.project(p);
        if (q && prev) {
          const dx = q.x - prev.x, dy = q.y - prev.y;
          const l2 = dx * dx + dy * dy;
          const t = l2 > 0 ? Math.max(0, Math.min(1, ((x - prev.x) * dx + (y - prev.y) * dy) / l2)) : 0;
          const d = Math.hypot(prev.x + t * dx - x, prev.y + t * dy - y);
          if (d < bestD) { bestD = d; best = handle; }
        }
        prev = q;
      }
    }
    return best;
  }

  private onDown(e: PointerEvent): void {
    if (!this.on || e.button !== 0 || e.shiftKey || e.ctrlKey || e.metaKey) return;
    const p = this.local(e);
    this.down = p;
    const hit = this.hitGrip(p.x, p.y);
    if (!hit) return;
    e.stopPropagation();
    e.preventDefault();
    this.drag = { handle: hit.handle, grip: hit.grip, kind: hit.kind, index: hit.index, px: p.x, py: p.y, moved: false };
    const move = (ev: PointerEvent): void => this.dragMove(ev);
    const up = (ev: PointerEvent): void => {
      window.removeEventListener('pointermove', move, true);
      window.removeEventListener('pointerup', up, true);
      void this.dragEnd(ev);
    };
    window.addEventListener('pointermove', move, true);
    window.addEventListener('pointerup', up, true);
  }

  private onMove(e: PointerEvent): void {
    if (!this.on || this.drag || (e.buttons & 7) !== 0) return;
    const p = this.local(e);
    const h = this.hitGrip(p.x, p.y);
    const next = h ? { handle: h.handle, kind: h.kind, index: h.index } : null;
    const same = (!next && !this.hover) || (!!next && !!this.hover && next.handle === this.hover.handle && next.index === this.hover.index && next.kind === this.hover.kind);
    if (!same) {
      this.hover = next;
      this.vp.canvas.style.cursor = next ? 'grab' : '';
      this.vp.invalidate();
    }
  }

  private onUp(e: PointerEvent): void {
    const d = this.down;
    this.down = null;
    if (!this.on || !d || this.drag || e.button !== 0) return;
    const p = this.local(e);
    if (Math.hypot(p.x - d.x, p.y - d.y) > 4) return;
    const hit = this.hitCurve(p.x, p.y);
    if (hit === null) return;
    e.stopPropagation();
    selection.select([hit], e.shiftKey ? 'add' : 'set');
  }

  private planePoint(px: number, py: number, at: Vec3): Vec3 | null {
    const ray = this.vp.rayAt(px, py);
    const dir = ray.direction;
    const n: Vec3 = Math.abs(dir[2]) > 0.2 ? [0, 0, 1] : [-dir[0], -dir[1], -dir[2]];
    const den = dir[0] * n[0] + dir[1] * n[1] + dir[2] * n[2];
    if (Math.abs(den) < 1e-9) return null;
    const t = ((at[0] - ray.origin[0]) * n[0] + (at[1] - ray.origin[1]) * n[1] + (at[2] - ray.origin[2]) * n[2]) / den;
    if (!Number.isFinite(t)) return null;
    return [ray.origin[0] + dir[0] * t, ray.origin[1] + dir[1] * t, ray.origin[2] + dir[2] * t];
  }

  private dragMove(e: PointerEvent): void {
    const d = this.drag;
    if (!d) return;
    const p = this.local(e);
    if (!d.moved && Math.hypot(p.x - d.px, p.y - d.py) < 3) return;
    d.moved = true;
    const q = this.planePoint(p.x, p.y, d.grip.at);
    if (!q) return;
    const it = this.items.get(d.handle);
    if (!it) return;
    const to: Vec3 = [q[0], q[1], d.grip.at[2]];
    d.grip.at = to;
    if (d.kind === 'cv') {
      it.row.poles[d.index] = to;
      it.cv[d.index].at = to;
      const s = evaluate(it.row, 16);
      if (s) { it.row.samples = s; this.paint(it, s); } else this.paint(it, it.row.samples);
    }
    this.vp.invalidate();
  }

  private async dragEnd(e: PointerEvent): Promise<void> {
    const d = this.drag;
    this.drag = null;
    this.down = null;
    if (!d) return;
    const doc = docStore.activeId;
    const target = d.grip.at;
    if (!d.moved || !doc) { await this.refresh(); return; }
    e.stopPropagation();
    try {
      await api.grip(doc, { handle: d.handle, grip: d.grip.id, mode: 'stretch', to: [target[0], target[1]] });
    } catch (err) {
      toast(err instanceof Error ? err.message : 'The point could not be moved', 'error');
    }
    await this.refresh();
    void docStore.refresh();
  }

  draw(g: CanvasRenderingContext2D, project: (p: Vec3) => { x: number; y: number } | null, ink: InkColors): void {
    if (!this.on) return;
    if (!this.loaded) { this.loaded = true; this.schedule(); }
    const cvColor = rgb(this.pal.snap), epColor = rgb(this.pal.accent), hotColor = ink.tipText;
    g.save();
    g.lineWidth = 1.6;
    const kind = this.kindFor();
    for (const [handle, it] of this.items) {
      if (!this.showsPoints(handle)) continue;
      const list = kind === 'cv' ? it.cv : it.ep;
      list.forEach((grip, index) => {
        const q = project(grip.at);
        if (!q) return;
        const hot = (this.drag && this.drag.handle === handle && this.drag.kind === kind && this.drag.index === index) || (this.hover && this.hover.handle === handle && this.hover.kind === kind && this.hover.index === index);
        const r = hot ? 6 : 4.5;
        g.fillStyle = hot ? hotColor : kind === 'cv' ? cvColor : epColor;
        g.strokeStyle = this.pal.bg.getStyle();
        g.beginPath();
        if (kind === 'cv') g.rect(q.x - r, q.y - r, r * 2, r * 2); else g.arc(q.x, q.y, r, 0, Math.PI * 2);
        g.fill();
        g.stroke();
      });
    }
    g.restore();
  }

  dispose(): void {
    for (const o of this.off) o();
    window.clearTimeout(this.timer);
    this.clear();
    this.lineMat.dispose();
    this.selMat.dispose();
    this.polyMat.dispose();
  }
}
