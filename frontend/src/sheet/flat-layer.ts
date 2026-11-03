import * as THREE from 'three';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js';
import type { Palette } from '../view3d/kit';
import type { ViewLayer } from '../view3d/layer';
import type { InkColors } from '../view3d/overlay';
import type { Vec3 } from '../view3d/types';
import type { Viewport3D } from '../view3d/viewport';
import type { FlatBend, FlatData, FlatLoop, FlatSeg, Pt2 } from './api';

const ARC_STEPS = 40;
const TAU = Math.PI * 2;

function arcPoints(s: Extract<FlatSeg, { t: 'arc' }>): Pt2[] {
  let sweep = (s.a1 - s.a0) % TAU;
  if (sweep <= 0) sweep += TAU;
  const n = Math.max(6, Math.ceil((sweep / TAU) * ARC_STEPS * 2));
  const out: Pt2[] = [];
  for (let i = 0; i <= n; i++) {
    const a = s.ccw ? s.a0 + (sweep * i) / n : s.a1 - (sweep * i) / n;
    out.push([s.c[0] + s.r * Math.cos(a), s.c[1] + s.r * Math.sin(a)]);
  }
  return out;
}

function segPoints(s: FlatSeg): Pt2[] {
  if (s.t === 'line') return [s.a, s.b];
  if (s.t === 'arc') return arcPoints(s);
  if (s.t === 'poly') return s.pts;
  const out: Pt2[] = [];
  for (let i = 0; i <= ARC_STEPS; i++) {
    const a = (TAU * i) / ARC_STEPS;
    out.push([s.c[0] + s.r * Math.cos(a), s.c[1] + s.r * Math.sin(a)]);
  }
  return out;
}

export function loopPoints(l: FlatLoop): Pt2[] {
  const out: Pt2[] = [];
  for (const s of l.segs) {
    const pts = segPoints(s);
    for (let i = out.length ? 1 : 0; i < pts.length; i++) out.push(pts[i]);
  }
  return out;
}

function inside(p: Pt2, poly: Pt2[]): boolean {
  let hit = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const a = poly[i], b = poly[j];
    if ((a[1] > p[1]) !== (b[1] > p[1]) && p[0] < ((b[0] - a[0]) * (p[1] - a[1])) / (b[1] - a[1]) + a[0]) hit = !hit;
  }
  return hit;
}

function pairs(polys: Pt2[][], closed: boolean): number[] {
  const out: number[] = [];
  for (const p of polys) {
    const n = closed ? p.length : p.length - 1;
    for (let i = 0; i < n; i++) {
      const a = p[i], b = p[(i + 1) % p.length];
      out.push(a[0], a[1], 0, b[0], b[1], 0);
    }
  }
  return out;
}

const cssColor = (host: HTMLElement, name: string, fallback: string): THREE.Color => {
  const raw = getComputedStyle(host).getPropertyValue(name).trim();
  const c = new THREE.Color();
  try { c.set(raw || fallback); } catch { c.set(fallback); }
  return c;
};

export class FlatLayer implements ViewLayer {
  readonly group = new THREE.Group();
  private readonly fill: THREE.Mesh;
  private readonly fillMat: THREE.MeshBasicMaterial;
  private readonly outline: LineSegments2;
  private readonly up: LineSegments2;
  private readonly down: LineSegments2;
  private readonly outlineMat: LineMaterial;
  private readonly upMat: LineMaterial;
  private readonly downMat: LineMaterial;
  private data: FlatData | null = null;
  private sig = '';
  private bends: FlatBend[] = [];
  labels = true;

  constructor(private readonly vp: Viewport3D) {
    this.fillMat = new THREE.MeshBasicMaterial({ color: 0x888888, transparent: true, opacity: 0.16, side: THREE.DoubleSide, depthWrite: false });
    this.outlineMat = new LineMaterial({ color: 0xffffff, linewidth: 2, worldUnits: false });
    this.upMat = new LineMaterial({ color: 0x34d399, linewidth: 2, worldUnits: false, dashed: true, dashSize: 6, gapSize: 3, dashScale: 1 });
    this.downMat = new LineMaterial({ color: 0xf59e0b, linewidth: 2, worldUnits: false, dashed: true, dashSize: 6, gapSize: 3, dashScale: 1 });
    this.fill = new THREE.Mesh(new THREE.BufferGeometry(), this.fillMat);
    this.outline = new LineSegments2(new LineSegmentsGeometry(), this.outlineMat);
    this.up = new LineSegments2(new LineSegmentsGeometry(), this.upMat);
    this.down = new LineSegments2(new LineSegmentsGeometry(), this.downMat);
    this.fill.renderOrder = 3;
    this.outline.renderOrder = 5;
    this.up.renderOrder = 6;
    this.down.renderOrder = 6;
    this.group.add(this.fill, this.outline, this.up, this.down);
    this.group.visible = false;
    this.fill.frustumCulled = false;
    this.palette({} as Palette);
  }

  get shown(): boolean { return this.group.visible; }

  palette(_pal: Palette): void {
    const host = this.vp.host;
    this.upMat.color.copy(cssColor(host, '--sm-bend-up', '#34d399'));
    this.downMat.color.copy(cssColor(host, '--sm-bend-down', '#f59e0b'));
    this.outlineMat.color.copy(cssColor(host, '--canvas-selection', '#ffffff'));
    this.fillMat.color.copy(cssColor(host, '--accent-color', '#f97316'));
    this.vp.invalidate();
  }

  resolution(w: number, h: number): void {
    for (const m of [this.outlineMat, this.upMat, this.downMat]) m.resolution.set(w, h);
  }

  bounds(): { min: Vec3; max: Vec3 } | null {
    if (!this.group.visible || !this.data) return null;
    const b = this.data.bbox;
    return { min: [b[0], b[1], 0], max: [b[2], b[3], 0] };
  }

  set(data: FlatData | null, show: boolean): void {
    const next = data && show ? signature(data) : '';
    if (next !== this.sig) {
      this.sig = next;
      this.data = data && show ? data : null;
      if (this.data) this.build(this.data);
    }
    this.bends = this.data?.bends ?? [];
    if (this.group.visible !== (show && !!this.data)) this.group.visible = show && !!this.data;
    this.vp.invalidate();
  }

  private build(data: FlatData): void {
    const outers = data.loops.filter((l) => l.outer).map((l) => ({ loop: l, pts: loopPoints(l) }));
    const inners = data.loops.filter((l) => !l.outer).map((l) => loopPoints(l));
    const shapes: THREE.Shape[] = [];
    for (const o of outers) {
      const shape = new THREE.Shape(o.pts.map((p) => new THREE.Vector2(p[0], p[1])));
      for (const h of inners) if (h.length && inside(h[0], o.pts)) shape.holes.push(new THREE.Path(h.map((p) => new THREE.Vector2(p[0], p[1]))));
      shapes.push(shape);
    }
    const geo = shapes.length ? new THREE.ShapeGeometry(shapes, 8) : new THREE.BufferGeometry();
    this.fill.geometry.dispose();
    this.fill.geometry = geo;
    const all = [...outers.map((o) => o.pts), ...inners];
    this.swap(this.outline, pairs(all, true));
    const lines = (dir: string): number[] => {
      const out: number[] = [];
      for (const b of data.bends) if (b.direction === dir) out.push(b.a[0], b.a[1], 0, b.b[0], b.b[1], 0);
      return out;
    };
    this.swap(this.up, lines('up'));
    this.swap(this.down, lines('down'));
  }

  private swap(obj: LineSegments2, positions: number[]): void {
    const geo = new LineSegmentsGeometry();
    if (positions.length) geo.setPositions(positions);
    obj.geometry.dispose();
    obj.geometry = geo;
    obj.visible = positions.length > 0;
    if (positions.length) obj.computeLineDistances();
  }

  draw(g: CanvasRenderingContext2D, project: (p: Vec3) => { x: number; y: number } | null, ink: InkColors): void {
    if (!this.group.visible || !this.labels || this.bends.length === 0) return;
    g.save();
    g.font = '11px ui-sans-serif, system-ui, sans-serif';
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    for (const b of this.bends) {
      const p = project([(b.a[0] + b.b[0]) / 2, (b.a[1] + b.b[1]) / 2, 0]);
      if (!p) continue;
      const text = `${b.direction === 'up' ? 'UP' : 'DOWN'} ${b.angle_deg.toFixed(1)} R${Number(b.radius.toPrecision(3))}`;
      const w = g.measureText(text).width + 10;
      g.fillStyle = ink.tipBg;
      g.strokeStyle = ink.tipLine;
      g.beginPath();
      g.roundRect(p.x - w / 2, p.y - 9, w, 18, 4);
      g.fill();
      g.stroke();
      g.fillStyle = ink.tipText;
      g.fillText(text, p.x, p.y + 0.5);
    }
    g.restore();
  }

  dispose(): void {
    this.fill.geometry.dispose();
    for (const o of [this.outline, this.up, this.down]) o.geometry.dispose();
    this.fillMat.dispose();
    for (const m of [this.outlineMat, this.upMat, this.downMat]) m.dispose();
  }
}

function signature(d: FlatData): string {
  let s = `${d.bbox.map((v) => v.toFixed(5)).join(',')}|${d.loops.length}|${d.blank_area.toFixed(5)}|`;
  for (const b of d.bends) s += `${b.id}:${b.direction}:${b.a[0].toFixed(4)},${b.a[1].toFixed(4)},${b.b[0].toFixed(4)},${b.b[1].toFixed(4)};`;
  return s;
}
