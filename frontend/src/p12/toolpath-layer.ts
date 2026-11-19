import * as THREE from 'three';
import { parseCss } from '../canvas/color';
import { tokenHexCss } from '../canvas/ink';
import type { ViewLayer } from '../view3d/layer';
import type { Vec3 } from '../view3d/types';
import type { Viewport3D } from '../view3d/viewport';

export interface Flat { rapid: number[]; cut: number[] }
export interface Wcs { origin?: number[]; x?: number[]; z?: number[] }

const FALLBACK = { cut: '#22c55e', rapid: '#9ca3af', pick: '#f59e0b', stale: '#6b7280', tool: '#f43f5e' };

export function wcsMatrix(w: Wcs | null | undefined): THREE.Matrix4 {
  const m = new THREE.Matrix4();
  if (!w) return m;
  const o = w.origin ?? [0, 0, 0];
  const z = new THREE.Vector3(...((w.z && w.z.length === 3 ? w.z : [0, 0, 1]) as [number, number, number])).normalize();
  const x = new THREE.Vector3(...((w.x && w.x.length === 3 ? w.x : [1, 0, 0]) as [number, number, number]));
  x.sub(z.clone().multiplyScalar(x.dot(z)));
  if (x.lengthSq() < 1e-12) x.set(1, 0, 0);
  x.normalize();
  const y = new THREE.Vector3().crossVectors(z, x);
  return m.makeBasis(x, y, z).setPosition(o[0], o[1], o[2]);
}

interface Item { cut: THREE.LineSegments; rapid: THREE.LineSegments; segs: number; wcs: THREE.Matrix4; bounds: THREE.Box3 | null; stale: boolean }

export class ToolpathLayer implements ViewLayer {
  readonly group = new THREE.Group();
  private readonly items = new Map<string, Item>();
  private selected = '';
  private fraction = 1;
  private showRapid = true;
  private readonly marker: THREE.Mesh;
  private colors = FALLBACK;

  constructor(private readonly vp: Viewport3D) {
    const cone = new THREE.ConeGeometry(0.5, 1.6, 12);
    cone.rotateX(Math.PI);
    cone.translate(0, 0, 0.8);
    cone.rotateX(Math.PI / 2);
    this.marker = new THREE.Mesh(cone, new THREE.MeshBasicMaterial({ color: FALLBACK.tool }));
    this.marker.visible = false;
    this.marker.frustumCulled = false;
    this.group.add(this.marker);
  }

  get count(): number { return this.items.size; }
  ids(): string[] { return Array.from(this.items.keys()); }
  has(id: string): boolean { return this.items.has(id); }
  get playFraction(): number { return this.fraction; }

  setColors(host: HTMLElement): void {
    const pick = (n: string, d: string): string => tokenHexCss(n, parseCss(d), host);
    this.colors = { cut: pick('--cam-cut', FALLBACK.cut), rapid: pick('--cam-rapid', FALLBACK.rapid), pick: pick('--cam-pick', FALLBACK.pick), stale: pick('--cam-stale', FALLBACK.stale), tool: pick('--cam-tool', FALLBACK.tool) };
    (this.marker.material as THREE.MeshBasicMaterial).color.set(this.colors.tool);
    for (const [id, it] of this.items) this.paint(id, it);
    this.vp.invalidate();
  }

  private paint(id: string, it: Item): void {
    const on = id === this.selected;
    (it.cut.material as THREE.LineBasicMaterial).color.set(it.stale ? this.colors.stale : on ? this.colors.pick : this.colors.cut);
    (it.rapid.material as THREE.LineBasicMaterial).color.set(this.colors.rapid);
  }

  set(id: string, flat: Flat, wcs: Wcs | null, stale: boolean): void {
    this.drop(id, false);
    const cutArr = new Float32Array(flat.cut);
    const rapArr = new Float32Array(flat.rapid);
    const mk = (arr: Float32Array, dashed: boolean): THREE.LineSegments => {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(arr, 3));
      const mat = new THREE.LineBasicMaterial({ color: FALLBACK.cut, transparent: dashed, opacity: dashed ? 0.55 : 1 });
      const l = new THREE.LineSegments(g, mat);
      l.frustumCulled = false;
      return l;
    };
    const cut = mk(cutArr, false), rapid = mk(rapArr, true);
    const m = wcsMatrix(wcs);
    for (const l of [cut, rapid]) { l.matrixAutoUpdate = false; l.matrix.copy(m); }
    rapid.visible = this.showRapid;
    const box = new THREE.Box3();
    const take = (a: Float32Array): void => { for (let i = 0; i + 2 < a.length; i += 3) box.expandByPoint(new THREE.Vector3(a[i], a[i + 1], a[i + 2])); };
    take(cutArr); take(rapArr);
    box.applyMatrix4(m);
    const it: Item = { cut, rapid, segs: Math.floor(cutArr.length / 6), wcs: m, bounds: box.isEmpty() ? null : box, stale };
    this.items.set(id, it);
    this.group.add(cut, rapid);
    this.paint(id, it);
    this.range(it);
    this.vp.invalidate();
  }

  drop(id: string, redraw = true): void {
    const it = this.items.get(id);
    if (!it) return;
    for (const l of [it.cut, it.rapid]) { this.group.remove(l); l.geometry.dispose(); (l.material as THREE.Material).dispose(); }
    this.items.delete(id);
    if (redraw) this.vp.invalidate();
  }

  clear(): void {
    for (const id of Array.from(this.items.keys())) this.drop(id, false);
    this.marker.visible = false;
    this.vp.invalidate();
  }

  setStale(id: string, stale: boolean): void {
    const it = this.items.get(id);
    if (!it || it.stale === stale) return;
    it.stale = stale;
    this.paint(id, it);
    this.vp.invalidate();
  }

  select(id: string): void {
    if (this.selected === id) return;
    const before = this.selected;
    this.selected = id;
    for (const k of [before, id]) { const it = this.items.get(k); if (it) this.paint(k, it); }
    this.play(this.fraction);
  }

  setRapid(on: boolean): void {
    this.showRapid = on;
    for (const it of this.items.values()) it.rapid.visible = on;
    this.vp.invalidate();
  }

  private range(it: Item): void {
    const n = it.segs;
    it.cut.geometry.setDrawRange(0, 2 * Math.round(n * this.fraction));
  }

  play(fraction: number): void {
    this.fraction = Math.max(0, Math.min(1, fraction));
    for (const [id, it] of this.items) {
      if (id === this.selected) this.range(it);
      else it.cut.geometry.setDrawRange(0, 2 * it.segs);
    }
    const it = this.items.get(this.selected);
    if (it && it.segs > 0 && this.fraction < 1) {
      const k = Math.max(0, Math.round(it.segs * this.fraction) - 1);
      const a = it.cut.geometry.getAttribute('position') as THREE.BufferAttribute;
      const p = new THREE.Vector3(a.getX(2 * k + 1), a.getY(2 * k + 1), a.getZ(2 * k + 1));
      this.marker.matrix.copy(it.wcs).multiply(new THREE.Matrix4().makeTranslation(p.x, p.y, p.z));
      this.marker.matrixAutoUpdate = false;
      this.marker.visible = true;
    } else this.marker.visible = false;
    this.vp.invalidate();
  }

  drawRange(id: string): [number, number] | null {
    const it = this.items.get(id);
    if (!it) return null;
    const r = it.cut.geometry.drawRange;
    return [r.start, r.count];
  }

  setWcs(id: string, wcs: Wcs | null): void {
    const it = this.items.get(id);
    if (!it) return;
    const m = wcsMatrix(wcs);
    it.wcs.copy(m);
    for (const l of [it.cut, it.rapid]) l.matrix.copy(m);
    this.vp.invalidate();
  }

  bounds(): { min: Vec3; max: Vec3 } | null {
    const box = new THREE.Box3();
    for (const it of this.items.values()) if (it.bounds) box.union(it.bounds);
    if (box.isEmpty() || !this.group.visible) return null;
    return { min: [box.min.x, box.min.y, box.min.z], max: [box.max.x, box.max.y, box.max.z] };
  }

  setShown(on: boolean): void { if (this.group.visible !== on) { this.group.visible = on; this.vp.invalidate(); } }
  get shown(): boolean { return this.group.visible; }

  dispose(): void { this.clear(); this.marker.geometry.dispose(); (this.marker.material as THREE.Material).dispose(); }
}
