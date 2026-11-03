import * as THREE from 'three';
import type { ViewLayer } from '../view3d/layer';
import type { Vec3 } from '../view3d/types';
import type { Viewport3D } from '../view3d/viewport';
import type { DisplayPayload, MeshPayload, RampSpec } from './sim-store';

const GREY = new THREE.Color('#8a8f98');
const MAX_PINS = 16;

function parseRamp(r: RampSpec): Array<[number, THREE.Color]> {
  const stops = (r.stops ?? []).map((s) => [s[0], new THREE.Color(s[1])] as [number, THREE.Color]);
  return stops.length >= 2 ? stops : [[0, new THREE.Color('#1a365d')], [1, new THREE.Color('#f7fafc')]];
}

export function rampColor(stops: Array<[number, THREE.Color]>, kind: string, t: number, out: THREE.Color): THREE.Color {
  let u = Math.min(1, Math.max(0, t));
  if (kind === 'bands') u = Math.min(0.999, Math.floor(u * 12) / 12 + 1 / 24);
  if (u <= stops[0][0]) return out.copy(stops[0][1]);
  for (let i = 1; i < stops.length; i++) {
    if (u <= stops[i][0]) {
      if (kind === 'zones') return out.copy(stops[i - 1][1]);
      const a = stops[i - 1], b = stops[i];
      const f = b[0] > a[0] ? (u - a[0]) / (b[0] - a[0]) : 0;
      return out.copy(a[1]).lerp(b[1], f);
    }
  }
  return out.copy(stops[stops.length - 1][1]);
}

export const rampCss = (r: RampSpec): string => {
  const stops = r.stops ?? [];
  if (stops.length < 2) return 'linear-gradient(to right, #1a365d, #f7fafc)';
  if (r.kind === 'zones') {
    const parts: string[] = [];
    stops.forEach((s, i) => { const a = Math.round(s[0] * 100), b = Math.round((stops[i + 1]?.[0] ?? 1) * 100); parts.push(`${s[1]} ${a}%`, `${s[1]} ${b}%`); });
    return `linear-gradient(to right, ${parts.join(', ')})`;
  }
  return `linear-gradient(to right, ${stops.map((s) => `${s[1]} ${Math.round(s[0] * 100)}%`).join(', ')})`;
};

export class ResultLayer implements ViewLayer {
  readonly group = new THREE.Group();
  readonly amp = { value: 0 };
  private readonly geo = new THREE.BufferGeometry();
  private readonly mat: THREE.MeshLambertMaterial;
  private readonly body: THREE.Mesh;
  private readonly wire: THREE.Mesh;
  private readonly wireMat: THREE.MeshBasicMaterial;
  private readonly meshGeo = new THREE.BufferGeometry();
  private readonly meshLines: THREE.LineSegments;
  private readonly pinGeo = new THREE.BufferGeometry();
  private readonly pins: THREE.Points;
  private pinCount = 0;
  private pos: THREE.BufferAttribute | null = null;
  private disp: THREE.BufferAttribute | null = null;
  private col: THREE.BufferAttribute | null = null;
  private idx: THREE.BufferAttribute | null = null;
  private values: Float32Array = new Float32Array(0);
  private stops: Array<[number, THREE.Color]> = parseRamp({ stops: [] });
  private rampKind = 'gradient';
  private lo = 0;
  private hi = 1;
  private serverScale = 1;
  private center: number | null = null;
  private box: { min: Vec3; max: Vec3 } | null = null;
  patched = 0;
  rebuilt = 0;

  constructor(private readonly vp: Viewport3D) {
    const amp = this.amp;
    const inject = (m: THREE.Material): void => {
      m.onBeforeCompile = (sh) => {
        sh.uniforms.uAmp = amp as unknown as THREE.IUniform;
        sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nattribute vec3 disp;\nuniform float uAmp;').replace('#include <begin_vertex>', '#include <begin_vertex>\ntransformed += disp * uAmp;');
      };
      m.customProgramCacheKey = () => 'formcad-sim-disp';
    };
    this.mat = new THREE.MeshLambertMaterial({ vertexColors: true, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
    inject(this.mat);
    this.wireMat = new THREE.MeshBasicMaterial({ color: '#000000', wireframe: true, transparent: true, opacity: 0.25 });
    inject(this.wireMat);
    this.body = new THREE.Mesh(this.geo, this.mat);
    this.wire = new THREE.Mesh(this.geo, this.wireMat);
    this.body.frustumCulled = false;
    this.wire.frustumCulled = false;
    this.wire.visible = false;
    this.meshLines = new THREE.LineSegments(this.meshGeo, new THREE.LineBasicMaterial({ color: '#4b9fe1', transparent: true, opacity: 0.7 }));
    this.meshLines.frustumCulled = false;
    this.meshLines.visible = false;
    const pa = new THREE.BufferAttribute(new Float32Array(MAX_PINS * 3), 3);
    pa.setUsage(THREE.DynamicDrawUsage);
    this.pinGeo.setAttribute('position', pa);
    this.pinGeo.setDrawRange(0, 0);
    this.pins = new THREE.Points(this.pinGeo, new THREE.PointsMaterial({ color: '#ffffff', size: 9, sizeAttenuation: false, depthTest: false }));
    this.pins.frustumCulled = false;
    this.pins.renderOrder = 10;
    this.group.add(this.body, this.wire, this.meshLines, this.pins);
    this.group.visible = false;
  }

  get ready(): boolean { return !!this.pos; }
  get hasMesh(): boolean { return this.meshLines.visible; }
  get lower(): number { return this.lo; }
  get upper(): number { return this.hi; }
  get pickTarget(): THREE.Mesh { return this.body; }

  bounds(): { min: Vec3; max: Vec3 } | null { return this.group.visible ? this.box : null; }

  setColors(host: HTMLElement): void {
    const cs = getComputedStyle(host);
    const pin = cs.getPropertyValue('--text-primary').trim();
    if (pin) (this.pins.material as THREE.PointsMaterial).color.set(pin);
    const line = cs.getPropertyValue('--accent-color').trim();
    if (line) (this.meshLines.material as THREE.LineBasicMaterial).color.set(line);
  }

  private fit(n: number, i: number): void {
    const same = this.pos && this.pos.count === n && this.idx && this.idx.count === i;
    if (same) return;
    this.rebuilt++;
    this.pos = new THREE.BufferAttribute(new Float32Array(n * 3), 3);
    this.disp = new THREE.BufferAttribute(new Float32Array(n * 3), 3);
    this.col = new THREE.BufferAttribute(new Float32Array(n * 3), 3);
    this.idx = new THREE.BufferAttribute(new Uint32Array(i), 1);
    for (const a of [this.pos, this.disp, this.col]) a.setUsage(THREE.DynamicDrawUsage);
    this.geo.setAttribute('position', this.pos);
    this.geo.setAttribute('disp', this.disp);
    this.geo.setAttribute('color', this.col);
    this.geo.setAttribute('normal', new THREE.BufferAttribute(new Float32Array(n * 3), 3));
    this.geo.setIndex(this.idx);
  }

  setData(d: DisplayPayload): void {
    const n = Math.floor(d.positions.length / 3);
    const ni = d.indices.length;
    this.fit(n, ni);
    const pos = this.pos as THREE.BufferAttribute, disp = this.disp as THREE.BufferAttribute, idx = this.idx as THREE.BufferAttribute;
    (pos.array as Float32Array).set(d.positions);
    const da = disp.array as Float32Array;
    if (d.deformed && d.deformed.length === d.positions.length) for (let k = 0; k < da.length; k++) da[k] = d.deformed[k] - d.positions[k]; else da.fill(0);
    (idx.array as Uint32Array).set(d.indices);
    pos.needsUpdate = true; disp.needsUpdate = true; idx.needsUpdate = true;
    this.serverScale = d.scale && d.scale > 0 ? d.scale : 1;
    this.stops = parseRamp(d.ramp);
    this.rampKind = d.ramp.kind ?? 'gradient';
    this.values = Float32Array.from(d.values);
    this.lo = d.ramp.min ?? d.min;
    this.hi = d.ramp.max ?? d.max;
    if (!(this.hi > this.lo)) this.hi = this.lo + 1;
    this.center = null;
    this.paint();
    const nrm = this.geo.getAttribute('normal') as THREE.BufferAttribute;
    this.normals(nrm, pos, idx);
    this.updateBox();
    this.group.visible = true;
    this.patched++;
    this.vp.invalidate();
  }

  private normals(nrm: THREE.BufferAttribute, pos: THREE.BufferAttribute, idx: THREE.BufferAttribute): void {
    const p = pos.array as Float32Array, ix = idx.array as Uint32Array, nr = nrm.array as Float32Array;
    nr.fill(0);
    const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3(), e1 = new THREE.Vector3(), e2 = new THREE.Vector3();
    for (let t = 0; t + 2 < ix.length; t += 3) {
      const i0 = ix[t] * 3, i1 = ix[t + 1] * 3, i2 = ix[t + 2] * 3;
      a.set(p[i0], p[i0 + 1], p[i0 + 2]); b.set(p[i1], p[i1 + 1], p[i1 + 2]); c.set(p[i2], p[i2 + 1], p[i2 + 2]);
      e1.subVectors(b, a); e2.subVectors(c, a); e1.cross(e2);
      for (const i of [i0, i1, i2]) { nr[i] += e1.x; nr[i + 1] += e1.y; nr[i + 2] += e1.z; }
    }
    for (let i = 0; i + 2 < nr.length; i += 3) {
      const l = Math.hypot(nr[i], nr[i + 1], nr[i + 2]) || 1;
      nr[i] /= l; nr[i + 1] /= l; nr[i + 2] /= l;
    }
    nrm.needsUpdate = true;
  }

  private paint(): void {
    if (!this.col) return;
    const c = this.col.array as Float32Array, v = this.values;
    const span = this.hi - this.lo;
    const tmp = new THREE.Color();
    for (let i = 0; i < v.length && i * 3 + 2 < c.length; i++) {
      const x = v[i];
      const col = Number.isFinite(x) ? rampColor(this.stops, this.rampKind, (x - this.lo) / span, tmp) : GREY;
      c[i * 3] = col.r; c[i * 3 + 1] = col.g; c[i * 3 + 2] = col.b;
    }
    this.col.needsUpdate = true;
  }

  setRange(lo: number | null, hi: number | null, fallbackLo: number, fallbackHi: number): void {
    this.lo = lo ?? fallbackLo;
    this.hi = hi ?? fallbackHi;
    if (!(this.hi > this.lo)) this.hi = this.lo + 1;
    this.paint();
    this.patched++;
    this.vp.invalidate();
  }

  private updateBox(): void {
    if (!this.pos) return;
    const p = this.pos.array as Float32Array, d = this.disp?.array as Float32Array | undefined;
    const min: Vec3 = [Infinity, Infinity, Infinity], max: Vec3 = [-Infinity, -Infinity, -Infinity];
    for (let i = 0; i + 2 < p.length; i += 3) for (let k = 0; k < 3; k++) {
      const x = p[i + k], y = x + (d ? d[i + k] * this.amp.value : 0);
      min[k] = Math.min(min[k], x, y); max[k] = Math.max(max[k], x, y);
    }
    this.box = Number.isFinite(min[0]) ? { min, max } : null;
  }

  setDeformation(on: boolean, scale: number): void {
    this.amp.value = on ? scale / this.serverScale : 0;
    this.vp.invalidate();
  }

  setPhase(phase: number, on: boolean, scale: number): void {
    this.amp.value = on ? (scale / this.serverScale) * phase : 0;
    this.vp.invalidate();
  }

  get serverScaleValue(): number { return this.serverScale; }

  setShown(on: boolean): void { if (this.group.visible !== on) { this.group.visible = on; this.vp.invalidate(); } }
  get shown(): boolean { return this.group.visible; }
  setBodyShown(on: boolean): void { if (this.body.visible !== on) { this.body.visible = on; this.vp.invalidate(); } }
  setWire(on: boolean): void { if (this.wire.visible !== on) { this.wire.visible = on; this.vp.invalidate(); } }

  setClip(planes: THREE.Plane[]): void {
    const next = planes.length ? planes : null;
    for (const m of [this.mat, this.wireMat, this.meshLines.material as THREE.Material]) { m.clippingPlanes = next; m.needsUpdate = true; }
    this.vp.invalidate();
  }

  setMesh(m: MeshPayload | null): void {
    if (!m || !m.positions?.length || !m.indices?.length) { if (this.meshLines.visible) { this.meshLines.visible = false; this.vp.invalidate(); } return; }
    const seen = new Set<number>();
    const out: number[] = [];
    const ix = m.indices;
    const key = (a: number, b: number): number => (a < b ? a * 4194304 + b : b * 4194304 + a);
    for (let t = 0; t + 2 < ix.length; t += 3) for (let e = 0; e < 3; e++) {
      const a = ix[t + e], b = ix[t + ((e + 1) % 3)], k = key(a, b);
      if (!seen.has(k)) { seen.add(k); out.push(a, b); }
    }
    const pos = this.meshGeo.getAttribute('position') as THREE.BufferAttribute | undefined;
    if (!pos || pos.count !== m.positions.length / 3) {
      this.meshGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(m.positions), 3));
      this.rebuilt++;
    } else { (pos.array as Float32Array).set(m.positions); pos.needsUpdate = true; this.patched++; }
    this.meshGeo.setIndex(out);
    this.meshLines.visible = true;
    this.group.visible = true;
    this.vp.invalidate();
  }

  hideMesh(): void { if (this.meshLines.visible) { this.meshLines.visible = false; this.vp.invalidate(); } }

  setPins(points: number[][]): void {
    const a = this.pinGeo.getAttribute('position') as THREE.BufferAttribute;
    const arr = a.array as Float32Array;
    const n = Math.min(points.length, MAX_PINS);
    for (let i = 0; i < n; i++) { arr[i * 3] = points[i][0]; arr[i * 3 + 1] = points[i][1]; arr[i * 3 + 2] = points[i][2]; }
    a.needsUpdate = true;
    this.pinGeo.setDrawRange(0, n);
    this.pinCount = n;
    this.vp.invalidate();
  }

  get pinTotal(): number { return this.pinCount; }

  clear(): void {
    this.group.visible = false;
    this.amp.value = 0;
    this.vp.invalidate();
  }

  dispose(): void {
    for (const g of [this.geo, this.meshGeo, this.pinGeo]) g.dispose();
    for (const m of [this.mat, this.wireMat, this.meshLines.material as THREE.Material, this.pins.material as THREE.Material]) m.dispose();
  }
}
