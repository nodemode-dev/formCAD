import * as THREE from 'three';
import type { Palette } from './kit';
import type { Vec3 } from './types';

export interface RefGeometryData {
  origin?: Vec3;
  x?: Vec3;
  y?: Vec3;
  z?: Vec3;
  direction?: Vec3;
  point?: Vec3;
}

export interface RefItem {
  name: string;
  kind: 'plane' | 'axis' | 'point' | 'cs';
  visible: boolean;
  status?: string;
  geometry: RefGeometryData;
}

interface Label { p: Vec3; text: string }

const add = (a: Vec3, b: Vec3, k: number): Vec3 => [a[0] + b[0] * k, a[1] + b[1] * k, a[2] + b[2] * k];

export class RefGeometry {
  readonly group = new THREE.Group();
  private labels: Label[] = [];
  private readonly owned: Array<{ dispose(): void }> = [];

  constructor() {
    this.group.visible = false;
    this.group.renderOrder = 2;
  }

  get count(): number { return this.labels.length; }

  private clear(): void {
    for (const o of this.owned) o.dispose();
    this.owned.length = 0;
    this.group.clear();
    this.labels = [];
  }

  private line(points: Vec3[], color: THREE.Color, loop = false): THREE.Object3D {
    const g = new THREE.BufferGeometry().setFromPoints(points.map((p) => new THREE.Vector3(p[0], p[1], p[2])));
    const m = new THREE.LineBasicMaterial({ color, depthTest: false, transparent: true });
    this.owned.push(g, m);
    const l = loop ? new THREE.LineLoop(g, m) : new THREE.Line(g, m);
    l.renderOrder = 2;
    return l;
  }

  set(items: RefItem[], size: number, pal: Palette): void {
    this.clear();
    const shown = items.filter((i) => i.visible && i.status !== 'error');
    for (const it of shown) {
      const g = it.geometry;
      if (it.kind === 'plane' && g.origin && g.x && g.y) {
        const o = g.origin;
        const c0 = add(add(o, g.x, -size), g.y, -size), c1 = add(add(o, g.x, size), g.y, -size);
        const c2 = add(add(o, g.x, size), g.y, size), c3 = add(add(o, g.x, -size), g.y, size);
        const geo = new THREE.BufferGeometry().setFromPoints([c0, c1, c2, c0, c2, c3].map((p) => new THREE.Vector3(p[0], p[1], p[2])));
        const mat = new THREE.MeshBasicMaterial({ color: pal.accent, transparent: true, opacity: 0.12, side: THREE.DoubleSide, depthWrite: false, depthTest: false });
        this.owned.push(geo, mat);
        const mesh = new THREE.Mesh(geo, mat);
        mesh.renderOrder = 1;
        this.group.add(mesh, this.line([c0, c1, c2, c3], pal.accent, true));
        this.labels.push({ p: add(add(o, g.x, size * 0.98), g.y, size * 0.98), text: it.name });
      } else if (it.kind === 'axis' && g.origin && g.direction) {
        this.group.add(this.line([add(g.origin, g.direction, -size * 1.2), add(g.origin, g.direction, size * 1.2)], pal.axisZ));
        this.labels.push({ p: add(g.origin, g.direction, size * 1.2), text: it.name });
      } else if (it.kind === 'point' && g.point) {
        const p = g.point, r = size * 0.04;
        this.group.add(
          this.line([add(p, [1, 0, 0], -r), add(p, [1, 0, 0], r)], pal.select),
          this.line([add(p, [0, 1, 0], -r), add(p, [0, 1, 0], r)], pal.select),
          this.line([add(p, [0, 0, 1], -r), add(p, [0, 0, 1], r)], pal.select));
        this.labels.push({ p, text: it.name });
      } else if (it.kind === 'cs' && g.origin && g.x && g.y && g.z) {
        const r = size * 0.25;
        this.group.add(this.line([g.origin, add(g.origin, g.x, r)], pal.axisX), this.line([g.origin, add(g.origin, g.y, r)], pal.axisY), this.line([g.origin, add(g.origin, g.z, r)], pal.axisZ));
        this.labels.push({ p: g.origin, text: it.name });
      }
    }
    this.group.visible = shown.length > 0;
  }

  drawLabels(g: CanvasRenderingContext2D, project: (p: Vec3) => { x: number; y: number } | null, color: string): void {
    if (!this.group.visible) return;
    g.save();
    g.font = '11px system-ui, sans-serif';
    g.fillStyle = color;
    g.textBaseline = 'middle';
    for (const l of this.labels) {
      const q = project(l.p);
      if (q) g.fillText(l.text, q.x + 6, q.y);
    }
    g.restore();
  }

  dispose(): void {
    this.clear();
  }
}
