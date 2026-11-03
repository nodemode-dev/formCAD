import * as THREE from 'three';
import type { ViewLayer } from '../view3d/layer';
import type { Vec3 } from '../view3d/types';
import type { Viewport3D } from '../view3d/viewport';

const MAX = 60000;

class Strip {
  readonly geo = new THREE.BufferGeometry();
  readonly obj: THREE.LineSegments;
  private readonly attr = new THREE.BufferAttribute(new Float32Array(MAX * 3), 3);

  constructor(color: string, width: number) {
    this.attr.setUsage(THREE.DynamicDrawUsage);
    this.geo.setAttribute('position', this.attr);
    this.geo.setDrawRange(0, 0);
    this.obj = new THREE.LineSegments(this.geo, new THREE.LineBasicMaterial({ color, linewidth: width, depthTest: false, transparent: true }));
    this.obj.frustumCulled = false;
    this.obj.renderOrder = 8;
  }

  set(lines: number[][][]): void {
    const a = this.attr.array as Float32Array;
    let n = 0;
    for (const pl of lines) {
      for (let i = 0; i + 1 < pl.length && n + 2 <= MAX; i++) {
        const p = pl[i], r = pl[i + 1];
        a[n * 3] = p[0]; a[n * 3 + 1] = p[1]; a[n * 3 + 2] = p[2]; n++;
        a[n * 3] = r[0]; a[n * 3 + 1] = r[1]; a[n * 3 + 2] = r[2]; n++;
      }
    }
    this.attr.needsUpdate = true;
    this.geo.setDrawRange(0, n);
  }

  get count(): number { return this.geo.drawRange.count; }
}

export class RouteLayer implements ViewLayer {
  readonly group = new THREE.Group();
  readonly ok = new Strip('#4b9fe1', 2);
  readonly bad = new Strip('#e5534b', 2);
  readonly pipe = new Strip('#e0a43a', 2);
  readonly nodes = new THREE.Points(new THREE.BufferGeometry(), new THREE.PointsMaterial({ color: '#ffffff', size: 7, sizeAttenuation: false, depthTest: false }));
  private readonly nodeAttr = new THREE.BufferAttribute(new Float32Array(3000 * 3), 3);
  private box: { min: Vec3; max: Vec3 } | null = null;

  constructor(private readonly vp: Viewport3D) {
    this.nodeAttr.setUsage(THREE.DynamicDrawUsage);
    this.nodes.geometry.setAttribute('position', this.nodeAttr);
    this.nodes.geometry.setDrawRange(0, 0);
    this.nodes.frustumCulled = false;
    this.nodes.renderOrder = 9;
    this.group.add(this.ok.obj, this.bad.obj, this.pipe.obj, this.nodes);
  }

  bounds(): { min: Vec3; max: Vec3 } | null { return this.box; }

  private fit(): void {
    const min: Vec3 = [Infinity, Infinity, Infinity], max: Vec3 = [-Infinity, -Infinity, -Infinity];
    for (const s of [this.ok, this.bad, this.pipe]) {
      const a = (s.geo.getAttribute('position') as THREE.BufferAttribute).array as Float32Array;
      for (let i = 0; i < s.count * 3; i += 3) for (let k = 0; k < 3; k++) { min[k] = Math.min(min[k], a[i + k]); max[k] = Math.max(max[k], a[i + k]); }
    }
    this.box = Number.isFinite(min[0]) ? { min, max } : null;
  }

  setHarness(ok: number[][][], bad: number[][][], points: number[][]): void {
    this.ok.set(ok);
    this.bad.set(bad);
    const a = this.nodeAttr.array as Float32Array;
    const n = Math.min(points.length, 3000);
    for (let i = 0; i < n; i++) { a[i * 3] = points[i][0]; a[i * 3 + 1] = points[i][1]; a[i * 3 + 2] = points[i][2]; }
    this.nodeAttr.needsUpdate = true;
    this.nodes.geometry.setDrawRange(0, n);
    this.fit();
    this.vp.invalidate();
  }

  setPipe(lines: number[][][]): void {
    this.pipe.set(lines);
    this.fit();
    this.vp.invalidate();
  }

  setShown(on: boolean): void { if (this.group.visible !== on) { this.group.visible = on; this.vp.invalidate(); } }

  dispose(): void {
    for (const s of [this.ok, this.bad, this.pipe]) { s.geo.dispose(); (s.obj.material as THREE.Material).dispose(); }
    this.nodes.geometry.dispose();
    (this.nodes.material as THREE.Material).dispose();
  }
}

export const sampleArc = (c: number[], a: number[], b: number[], steps = 10): number[][] => {
  const u = [a[0] - c[0], a[1] - c[1], a[2] - c[2]];
  const v = [b[0] - c[0], b[1] - c[1], b[2] - c[2]];
  const ru = Math.hypot(...u), rv = Math.hypot(...v);
  const cos = Math.min(1, Math.max(-1, (u[0] * v[0] + u[1] * v[1] + u[2] * v[2]) / (ru * rv || 1)));
  const ang = Math.acos(cos);
  const sn = Math.sin(ang) || 1;
  const out: number[][] = [];
  for (let i = 0; i <= steps; i++) {
    const f = i / steps;
    const wa = Math.sin((1 - f) * ang) / sn, wb = Math.sin(f * ang) / sn;
    const r = ru + (rv - ru) * f;
    const d = [wa * u[0] / ru + wb * v[0] / rv, wa * u[1] / ru + wb * v[1] / rv, wa * u[2] / ru + wb * v[2] / rv];
    out.push([c[0] + d[0] * r, c[1] + d[1] * r, c[2] + d[2] * r]);
  }
  return out;
};
