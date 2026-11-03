import * as THREE from 'three';
import type { Palette } from '../view3d/kit';
import type { ViewLayer } from '../view3d/layer';
import { parseScene } from '../view3d/scene-format';
import type { BodyData, Vec3 } from '../view3d/types';
import type { Viewport3D } from '../view3d/viewport';

interface Slot {
  group: THREE.Group;
  mesh: THREE.Mesh;
  lines: THREE.LineSegments;
  dots: THREE.Points;
  node: string;
  picked: boolean;
  min: Vec3;
  max: Vec3;
  tris: number;
  segs: number;
}

export interface PreviewStats { created: number; patched: number; grown: number; rounds: number; slots: number; shown: number }

const grow = (n: number): number => Math.max(64, 1 << Math.ceil(Math.log2(Math.max(1, n))));

interface Side { node: string; point: Float32Array | null; picked: boolean }

const RECORD = 128;
const FLAG_VISIBLE = 1;
const FLAG_SELECTED = 8;
const FLAG_POINT = 32;

function sidecar(buf: ArrayBuffer): Map<number, Side> {
  const out = new Map<number, Side>();
  const dv = new DataView(buf);
  const u = (i: number): number => dv.getUint32(i * 4, true);
  const rows = u(5), tableAt = u(8), metaAt = u(10), metaLen = u(11);
  let nodes = new Map<number, string>();
  try {
    const meta = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, metaAt, metaLen))) as { bodies?: Array<{ handle: number; node?: string }> };
    nodes = new Map((meta.bodies ?? []).map((b) => [b.handle, b.node ?? '']));
  } catch { nodes = new Map(); }
  for (let r = 0; r < rows; r++) {
    const o = tableAt + r * RECORD;
    const w = (i: number): number => dv.getUint32(o + i * 4, true);
    const handle = w(0), flags = w(2);
    let point: Float32Array | null = null;
    if ((flags & FLAG_POINT) && (flags & FLAG_VISIBLE) && w(8) > 0) point = new Float32Array(buf.slice(w(16), w(16) + 12));
    out.set(handle, { node: nodes.get(handle) ?? '', point, picked: (flags & FLAG_SELECTED) !== 0 });
  }
  return out;
}

export class GraphPreviewLayer implements ViewLayer {
  readonly group = new THREE.Group();
  readonly stats: PreviewStats = { created: 0, patched: 0, grown: 0, rounds: 0, slots: 0, shown: 0 };
  private readonly slots = new Map<number, Slot>();
  private readonly fill = new THREE.MeshStandardMaterial({ roughness: 0.55, metalness: 0.05, side: THREE.DoubleSide, transparent: true, opacity: 0.9, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
  private readonly hot = new THREE.MeshStandardMaterial({ roughness: 0.55, metalness: 0.05, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
  private readonly edge = new THREE.LineBasicMaterial({ transparent: true, opacity: 0.9 });
  private readonly hotEdge = new THREE.LineBasicMaterial();
  private readonly dot3 = new THREE.PointsMaterial({ size: 6, sizeAttenuation: false });
  private readonly hotDot = new THREE.PointsMaterial({ size: 9, sizeAttenuation: false });
  private selected = new Set<string>();
  private framed = false;

  constructor(private readonly vp: Viewport3D) {
    this.group.name = 'graph-preview';
    this.palette(vp.kit.palette);
  }

  palette(pal: Palette): void {
    this.fill.color.copy(pal.accent).lerp(pal.paper, 0.35);
    this.hot.color.copy(pal.select);
    this.edge.color.copy(pal.accent);
    this.hotEdge.color.copy(pal.select);
    this.dot3.color.copy(pal.accent);
    this.hotDot.color.copy(pal.select);
    this.fill.needsUpdate = true;
    this.hot.needsUpdate = true;
    this.vp.invalidate();
  }

  bounds(): { min: Vec3; max: Vec3 } | null {
    const min: Vec3 = [Infinity, Infinity, Infinity], max: Vec3 = [-Infinity, -Infinity, -Infinity];
    for (const s of this.slots.values()) {
      if (!s.group.visible || !Number.isFinite(s.min[0])) continue;
      for (let k = 0; k < 3; k++) { min[k] = Math.min(min[k], s.min[k]); max[k] = Math.max(max[k], s.max[k]); }
    }
    return Number.isFinite(min[0]) ? { min, max } : null;
  }

  private measure(slot: Slot, a: Float32Array, b: Float32Array | null): void {
    slot.min = [Infinity, Infinity, Infinity];
    slot.max = [-Infinity, -Infinity, -Infinity];
    for (const arr of b ? [a, b] : [a]) {
      for (let i = 0; i + 2 < arr.length; i += 3) {
        for (let k = 0; k < 3; k++) {
          const v = arr[i + k];
          if (v < slot.min[k]) slot.min[k] = v;
          if (v > slot.max[k]) slot.max[k] = v;
        }
      }
    }
  }

  reset(): void { this.framed = false; }

  frame(): void {
    if (this.framed || this.vp.hasBodies) return;
    const b = this.bounds();
    if (!b) return;
    this.framed = true;
    this.vp.rig.fitBox(b.min, b.max, false);
    this.vp.invalidate();
  }

  apply(buf: ArrayBuffer | null): void {
    this.stats.rounds++;
    if (!buf) { this.clear(); return; }
    const scene = parseScene(buf, false);
    const side = sidecar(buf);
    const seen = new Set<number>();
    for (const b of scene.bodies) {
      seen.add(b.id);
      this.write(b, side.get(b.id) ?? { node: '', point: null, picked: false });
    }
    for (const [handle, s] of side) {
      if (!s.point || seen.has(handle)) continue;
      seen.add(handle);
      this.dot(handle, s);
    }
    for (const [id, slot] of this.slots) {
      if (seen.has(id)) continue;
      slot.group.visible = false;
    }
    for (const id of scene.removed) { const s = this.slots.get(id); if (s) s.group.visible = false; }
    this.finish();
  }

  clear(): void {
    for (const slot of this.slots.values()) slot.group.visible = false;
    this.finish();
  }

  select(nodes: string[]): void {
    this.selected = new Set(nodes);
    for (const slot of this.slots.values()) this.paint(slot);
    this.vp.invalidate();
  }

  private paint(slot: Slot): void {
    const hot = slot.picked || this.selected.has(slot.node);
    slot.mesh.material = hot ? this.hot : this.fill;
    slot.lines.material = hot ? this.hotEdge : this.edge;
    slot.dots.material = hot ? this.hotDot : this.dot3;
  }

  private slot(id: number): Slot {
    const have = this.slots.get(id);
    if (have) return have;
    const geometry = new THREE.BufferGeometry();
    const lineGeometry = new THREE.BufferGeometry();
    const dotGeometry = new THREE.BufferGeometry();
    for (const g of [geometry, lineGeometry, dotGeometry]) {
      g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(192), 3));
      g.setDrawRange(0, 0);
    }
    geometry.setAttribute('normal', new THREE.BufferAttribute(new Float32Array(192), 3));
    geometry.setIndex(new THREE.BufferAttribute(new Uint32Array(192), 1));
    const mesh = new THREE.Mesh(geometry, this.fill);
    const lines = new THREE.LineSegments(lineGeometry, this.edge);
    const dots = new THREE.Points(dotGeometry, this.dot3);
    mesh.frustumCulled = false;
    lines.frustumCulled = false;
    dots.frustumCulled = false;
    const group = new THREE.Group();
    group.add(mesh, lines, dots);
    this.group.add(group);
    const slot: Slot = { group, mesh, lines, dots, node: '', picked: false, tris: 0, segs: 0, min: [Infinity, Infinity, Infinity], max: [-Infinity, -Infinity, -Infinity] };
    this.slots.set(id, slot);
    this.stats.created++;
    return slot;
  }

  private dot(handle: number, s: Side): void {
    const slot = this.slot(handle);
    if (!s.point) return;
    this.put(slot.dots.geometry, 'position', s.point, 3);
    slot.dots.geometry.setDrawRange(0, 1);
    this.measure(slot, s.point, null);
    slot.mesh.visible = false;
    slot.lines.visible = false;
    slot.dots.visible = true;
    slot.node = s.node;
    slot.picked = s.picked;
    slot.group.visible = true;
    this.paint(slot);
    this.stats.patched++;
  }

  private put(geometry: THREE.BufferGeometry, name: string, src: Float32Array | Uint32Array, size: number): void {
    let attr = name === 'index' ? geometry.getIndex() : geometry.getAttribute(name);
    if (!attr || attr.array.length < src.length) {
      const cap = grow(src.length);
      const array = src instanceof Uint32Array ? new Uint32Array(cap) : new Float32Array(cap);
      attr = new THREE.BufferAttribute(array, size);
      if (name === 'index') geometry.setIndex(attr as THREE.BufferAttribute); else geometry.setAttribute(name, attr);
      this.stats.grown++;
    }
    (attr.array as Float32Array | Uint32Array).set(src);
    attr.needsUpdate = true;
  }

  private write(b: BodyData, side: Side): void {
    const slot = this.slot(b.id);
    const g = slot.mesh.geometry;
    this.put(g, 'position', b.positions, 3);
    this.put(g, 'normal', b.normals, 3);
    this.put(g, 'index', b.indices, 1);
    g.setDrawRange(0, b.indices.length);
    const lg = slot.lines.geometry;
    this.put(lg, 'position', b.edges.positions, 3);
    lg.setDrawRange(0, b.edges.positions.length / 3);
    slot.tris = b.indices.length / 3;
    slot.segs = b.edges.positions.length / 6;
    this.measure(slot, b.positions, b.edges.positions);
    slot.node = side.node;
    slot.picked = side.picked;
    slot.mesh.visible = slot.tris > 0;
    slot.lines.visible = slot.segs > 0;
    slot.dots.visible = false;
    slot.group.visible = true;
    this.paint(slot);
    this.stats.patched++;
  }

  private finish(): void {
    let shown = 0;
    for (const s of this.slots.values()) if (s.group.visible) shown++;
    this.stats.slots = this.slots.size;
    this.stats.shown = shown;
    this.vp.invalidate();
  }

  dispose(): void {
    for (const s of this.slots.values()) { s.mesh.geometry.dispose(); s.lines.geometry.dispose(); s.dots.geometry.dispose(); }
    this.slots.clear();
    for (const m of [this.fill, this.hot, this.edge, this.hotEdge, this.dot3, this.hotDot]) m.dispose();
  }
}
