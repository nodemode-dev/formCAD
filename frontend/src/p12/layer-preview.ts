import * as THREE from 'three';
import type { ViewLayer } from '../view3d/layer';
import type { Vec3 } from '../view3d/types';
import type { Viewport3D } from '../view3d/viewport';

export interface PackLayer { index: number; z: number; height: number; first_vertex: number; vertex_count: number; first_segment: number; segment_count: number; time_s: number; filament_mm: number }
export interface PackHeader {
  version: number; units: string; layer_count: number; layers: PackLayer[]; feature_codes: Record<string, number>;
  arrays: Record<string, { offset: number; count: number; type: string; stride?: number; unit_mm?: number }>;
  bbox: number[]; totals: { time_s: number; filament_mm: number; layers: number; support_volume_mm3: number }; profile?: string; plate?: string; hash?: string; source?: string;
}
export interface Pack { header: PackHeader; positions: Float32Array; indices: Uint32Array; features: Uint8Array; widths: Uint8Array }

export const FEATURE_NAMES = ['Travel', 'Outer wall', 'Inner wall', 'Sparse infill', 'Solid infill', 'Top skin', 'Bridge', 'Support', 'Support interface', 'Skirt and brim', 'Gap fill'];
export const FEATURE_TOKENS = ['--lp-travel', '--lp-outer', '--lp-inner', '--lp-sparse', '--lp-solid', '--lp-top', '--lp-bridge', '--lp-support', '--lp-interface', '--lp-skirt', '--lp-gap'];
const FALLBACK = ['#6b7280', '#f59e0b', '#fbbf24', '#ef4444', '#a855f7', '#22c55e', '#06b6d4', '#3b82f6', '#60a5fa', '#9ca3af', '#f472b6'];

export const MAX_INSTANCES = 120000;

export function parsePack(buf: ArrayBuffer): Pack {
  const dv = new DataView(buf);
  const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
  if (magic !== 'FCL1') throw new Error('The layer data is not in a known format.');
  const hl = dv.getUint32(4, true);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 8, hl))) as PackHeader;
  const base = 8 + hl;
  const a = header.arrays;
  const n = (k: string): number => a[k].count * (a[k].stride ?? 1);
  const f32 = (k: string): Float32Array => new Float32Array(buf.slice(base + a[k].offset, base + a[k].offset + n(k) * 4));
  const u32 = (k: string): Uint32Array => new Uint32Array(buf.slice(base + a[k].offset, base + a[k].offset + n(k) * 4));
  const u8 = (k: string): Uint8Array => new Uint8Array(buf.slice(base + a[k].offset, base + a[k].offset + n(k)));
  return { header, positions: f32('positions'), indices: u32('indices'), features: u8('features'), widths: u8('widths') };
}

export type PreviewMode = 'lines' | 'solid';
type Group = 'part' | 'support' | 'travel';
const GROUPS: Group[] = ['part', 'support', 'travel'];
const groupOf = (f: number): Group => (f === 0 ? 'travel' : f === 7 || f === 8 ? 'support' : 'part');

interface Built { lines: THREE.LineSegments; ends: Uint32Array; count: number; seg: Uint32Array }

export class LayerPreview implements ViewLayer {
  readonly group = new THREE.Group();
  private pack: Pack | null = null;
  private built = new Map<Group, Built>();
  private solid: { mesh: THREE.InstancedMesh; per: Uint32Array; from: number } | null = null;
  private bed: THREE.LineSegments | null = null;
  private mode: PreviewMode = 'lines';
  private lo = 0;
  private hi = 0;
  private shownGroups: Record<Group, boolean> = { part: true, support: true, travel: false };
  private colors: THREE.Color[] = FALLBACK.map((c) => new THREE.Color(c));
  private dirty = false;

  constructor(private readonly vp: Viewport3D) {
    this.group.visible = false;
  }

  get has(): boolean { return !!this.pack; }
  get layers(): number { return this.pack?.header.layer_count ?? 0; }
  get header(): PackHeader | null { return this.pack?.header ?? null; }
  get solidAllowed(): boolean { return !!this.pack; }
  get currentMode(): PreviewMode { return this.mode; }
  get range(): [number, number] { return [this.lo, this.hi]; }
  get shown(): boolean { return this.group.visible; }

  layerInfo(i: number): PackLayer | null { return this.pack?.header.layers[Math.max(0, Math.min(i, this.layers - 1))] ?? null; }

  private partSegments(): number {
    if (!this.pack) return 0;
    let n = 0;
    for (let i = 0; i < this.pack.features.length; i++) if (this.pack.features[i] !== 0) n++;
    return n;
  }

  setColors(host: HTMLElement): void {
    const cs = getComputedStyle(host);
    this.colors = FEATURE_TOKENS.map((tok, i) => {
      const c = new THREE.Color();
      try { c.set(cs.getPropertyValue(tok).trim() || FALLBACK[i]); } catch { c.set(FALLBACK[i]); }
      return c;
    });
  }

  colorOf(f: number): string { return `#${(this.colors[f] ?? this.colors[1]).getHexString()}`; }

  load(pack: Pack): void {
    this.clear();
    this.pack = pack;
    this.buildLines();
    this.lo = 0;
    this.hi = Math.max(0, pack.header.layer_count - 1);
    this.mode = 'lines';
    this.apply();
    this.group.visible = true;
    this.vp.invalidate();
  }

  clear(): void {
    for (const b of this.built.values()) { this.group.remove(b.lines); b.lines.geometry.dispose(); (b.lines.material as THREE.Material).dispose(); }
    this.built.clear();
    if (this.solid) { this.group.remove(this.solid.mesh); this.solid.mesh.geometry.dispose(); (this.solid.mesh.material as THREE.Material).dispose(); this.solid.mesh.dispose(); this.solid = null; }
    if (this.bed) { this.group.remove(this.bed); this.bed.geometry.dispose(); (this.bed.material as THREE.Material).dispose(); this.bed = null; }
    this.pack = null;
    this.group.visible = false;
    this.vp.invalidate();
  }

  private buildLines(): void {
    const p = this.pack;
    if (!p) return;
    const nSeg = p.features.length;
    const counts: Record<Group, number> = { part: 0, support: 0, travel: 0 };
    for (let s = 0; s < nSeg; s++) counts[groupOf(p.features[s])]++;
    const pos: Record<Group, Float32Array> = { part: new Float32Array(counts.part * 6), support: new Float32Array(counts.support * 6), travel: new Float32Array(counts.travel * 6) };
    const col: Record<Group, Uint8Array> = { part: new Uint8Array(counts.part * 6), support: new Uint8Array(counts.support * 6), travel: new Uint8Array(counts.travel * 6) };
    const seg: Record<Group, Uint32Array> = { part: new Uint32Array(counts.part), support: new Uint32Array(counts.support), travel: new Uint32Array(counts.travel) };
    const at: Record<Group, number> = { part: 0, support: 0, travel: 0 };
    const rgb = this.colors.map((c) => [Math.round(c.r * 255), Math.round(c.g * 255), Math.round(c.b * 255)]);
    for (let s = 0; s < nSeg; s++) {
      const f = p.features[s];
      const g = groupOf(f);
      const k = at[g]++;
      seg[g][k] = s;
      const a = p.indices[2 * s] * 3, b = p.indices[2 * s + 1] * 3;
      const o = k * 6;
      pos[g][o] = p.positions[a]; pos[g][o + 1] = p.positions[a + 1]; pos[g][o + 2] = p.positions[a + 2];
      pos[g][o + 3] = p.positions[b]; pos[g][o + 4] = p.positions[b + 1]; pos[g][o + 5] = p.positions[b + 2];
      const c = rgb[f] ?? rgb[1];
      col[g][o] = c[0]; col[g][o + 1] = c[1]; col[g][o + 2] = c[2]; col[g][o + 3] = c[0]; col[g][o + 4] = c[1]; col[g][o + 5] = c[2];
    }
    const layers = p.header.layers;
    for (const g of GROUPS) {
      if (counts[g] === 0) continue;
      const ends = new Uint32Array(layers.length + 1);
      let k = 0;
      for (let i = 0; i < layers.length; i++) {
        const limit = layers[i].first_segment + layers[i].segment_count;
        while (k < counts[g] && seg[g][k] < limit) k++;
        ends[i + 1] = k;
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(pos[g], 3));
      geo.setAttribute('color', new THREE.BufferAttribute(col[g], 3, true));
      const mat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: g === 'travel', opacity: g === 'travel' ? 0.45 : 1 });
      const lines = new THREE.LineSegments(geo, mat);
      lines.frustumCulled = false;
      lines.visible = this.shownGroups[g];
      this.group.add(lines);
      this.built.set(g, { lines, ends, count: counts[g], seg: seg[g] });
    }
  }

  private bedKey = '';

  setBed(w: number, d: number): void {
    const key = `${w}x${d}`;
    if (key === this.bedKey && this.bed) return;
    this.bedKey = key;
    if (this.bed) { this.group.remove(this.bed); this.bed.geometry.dispose(); (this.bed.material as THREE.Material).dispose(); this.bed = null; }
    if (!(w > 0 && d > 0)) return;
    const v = new Float32Array([0, 0, 0, w, 0, 0, w, 0, 0, w, d, 0, w, d, 0, 0, d, 0, 0, d, 0, 0, 0, 0]);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(v, 3));
    this.bed = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: this.colors[9] }));
    this.group.add(this.bed);
    this.vp.invalidate();
  }

  setMode(mode: PreviewMode): void {
    if (!this.pack || mode === this.mode) return;
    if (mode === 'solid') {
      if (!this.solidAllowed) return;
      if (!this.solid) this.buildSolid();
    }
    this.mode = mode;
    this.apply();
  }

  private buildSolid(): void {
    const p = this.pack;
    if (!p) return;
    const geo = new THREE.BoxGeometry(1, 1, 1);
    const mat = new THREE.MeshLambertMaterial({ color: 0xffffff });
    const mesh = new THREE.InstancedMesh(geo, mat, MAX_INSTANCES);
    mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(MAX_INSTANCES * 3), 3);
    mesh.instanceColor.setUsage(THREE.DynamicDrawUsage);
    mesh.frustumCulled = false;
    mesh.count = 0;
    const layers = p.header.layers;
    const per = new Uint32Array(layers.length);
    for (const l of layers) { let c = 0; for (let s = l.first_segment; s < l.first_segment + l.segment_count; s++) if (p.features[s] !== 0) c++; per[l.index] = c; }
    this.group.add(mesh);
    this.solid = { mesh, per, from: 0 };
  }

  private fillSolid(): void {
    const p = this.pack, sd = this.solid;
    if (!p || !sd) return;
    const layers = p.header.layers;
    let first = this.hi, n = sd.per[this.hi];
    while (first > this.lo && n + sd.per[first - 1] <= MAX_INSTANCES) { first--; n += sd.per[first]; }
    const m = sd.mesh.instanceMatrix.array as Float32Array;
    const c = (sd.mesh.instanceColor as THREE.InstancedBufferAttribute).array as Float32Array;
    let k = 0;
    for (let li = first; li <= this.hi && k < MAX_INSTANCES; li++) {
      const l = layers[li];
      for (let s = l.first_segment; s < l.first_segment + l.segment_count && k < MAX_INSTANCES; s++) {
        const f = p.features[s];
        if (f === 0) continue;
        const a = p.indices[2 * s] * 3, b = p.indices[2 * s + 1] * 3;
        const ax = p.positions[a], ay = p.positions[a + 1], bx = p.positions[b], by = p.positions[b + 1];
        const dx = bx - ax, dy = by - ay;
        const len = Math.hypot(dx, dy);
        const w = Math.max(0.05, p.widths[s] * 0.01);
        const cs = len > 1e-9 ? dx / len : 1, sn = len > 1e-9 ? dy / len : 0;
        const sx = len + w, o = k * 16;
        m[o] = cs * sx; m[o + 1] = sn * sx; m[o + 2] = 0; m[o + 3] = 0;
        m[o + 4] = -sn * w; m[o + 5] = cs * w; m[o + 6] = 0; m[o + 7] = 0;
        m[o + 8] = 0; m[o + 9] = 0; m[o + 10] = l.height; m[o + 11] = 0;
        m[o + 12] = (ax + bx) / 2; m[o + 13] = (ay + by) / 2; m[o + 14] = p.positions[a + 2] - l.height / 2; m[o + 15] = 1;
        const col = this.colors[f] ?? this.colors[1];
        c[k * 3] = col.r; c[k * 3 + 1] = col.g; c[k * 3 + 2] = col.b;
        k++;
      }
    }
    sd.mesh.count = k;
    sd.from = first;
    sd.mesh.instanceMatrix.needsUpdate = true;
    (sd.mesh.instanceColor as THREE.InstancedBufferAttribute).needsUpdate = true;
  }

  get solidFrom(): number { return this.solid?.from ?? 0; }

  setRange(lo: number, hi: number): void {
    if (!this.pack) return;
    const max = this.layers - 1;
    const a = Math.max(0, Math.min(lo, max)), b = Math.max(a, Math.min(hi, max));
    if (a === this.lo && b === this.hi) return;
    this.lo = a; this.hi = b;
    this.apply();
  }

  setGroup(g: Group, on: boolean): void {
    if (this.shownGroups[g] === on) return;
    this.shownGroups[g] = on;
    this.apply();
  }

  groupShown(g: Group): boolean { return this.shownGroups[g]; }

  setShown(on: boolean): void {
    if (this.group.visible === on) return;
    this.group.visible = on && !!this.pack;
    this.vp.invalidate();
  }

  private apply(): void {
    const lines = this.mode === 'lines';
    for (const g of GROUPS) {
      const b = this.built.get(g);
      if (!b) continue;
      const vis = lines && this.shownGroups[g];
      if (b.lines.visible !== vis) b.lines.visible = vis;
      const s = b.ends[this.lo], e = b.ends[this.hi + 1];
      b.lines.geometry.setDrawRange(2 * s, 2 * (e - s));
    }
    if (this.solid) {
      const on = this.mode === 'solid';
      if (this.solid.mesh.visible !== on) this.solid.mesh.visible = on;
      if (on) this.fillSolid();
    }
    this.vp.invalidate();
  }

  drawRanges(): Record<string, [number, number]> {
    const out: Record<string, [number, number]> = {};
    for (const g of GROUPS) { const b = this.built.get(g); if (b) { const r = b.lines.geometry.drawRange; out[g] = [r.start, r.count]; } }
    if (this.solid) out.solid = [0, this.solid.mesh.count];
    return out;
  }

  bounds(): { min: Vec3; max: Vec3 } | null {
    const b = this.pack?.header.bbox;
    if (!b || !this.group.visible) return null;
    return { min: [b[0], b[1], b[2]], max: [b[3], b[4], b[5]] };
  }

  palette(): void { this.setColors(document.body); this.dirty = true; }

  dispose(): void { this.clear(); }
}
