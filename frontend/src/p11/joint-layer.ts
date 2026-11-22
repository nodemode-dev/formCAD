import * as THREE from 'three';
import { parseCss } from '../canvas/color';
import { tokenHex } from '../canvas/ink';
import type { Palette } from '../view3d/kit';
import type { ViewLayer, Projector } from '../view3d/layer';
import type { InkColors } from '../view3d/overlay';
import type { Vec3 } from '../view3d/types';
import type { Viewport3D } from '../view3d/viewport';
import { asm } from '../u8/asm';
import { matrixOf } from '../u8/geo';
import type { Joint, JointType } from './joint-store';

type Kind = 'free' | 'limit' | 'outside' | 'off' | 'hot';
const KINDS: Kind[] = ['free', 'limit', 'outside', 'off', 'hot'];

const circle = (out: number[], plane: 'xy' | 'yz' | 'xz', r: number, a0: number, a1: number, n: number): Vec3[] => {
  const pts: Vec3[] = [];
  for (let i = 0; i <= n; i++) {
    const a = a0 + ((a1 - a0) * i) / n;
    const c = Math.cos(a) * r, s = Math.sin(a) * r;
    pts.push(plane === 'xy' ? [c, s, 0] : plane === 'yz' ? [0, c, s] : [c, 0, s]);
  }
  for (let i = 0; i + 1 < pts.length; i++) out.push(...pts[i], ...pts[i + 1]);
  return pts;
};

const seg = (out: number[], a: Vec3, b: Vec3): void => { out.push(...a, ...b); };

const arrow = (out: number[], tip: Vec3, dir: Vec3, size: number): void => {
  const d = new THREE.Vector3(...dir).normalize();
  const helper = Math.abs(d.z) < 0.9 ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(1, 0, 0);
  const side = new THREE.Vector3().crossVectors(d, helper).normalize().multiplyScalar(size * 0.4);
  const t = new THREE.Vector3(...tip);
  const back = t.clone().addScaledVector(d, -size);
  const l = back.clone().add(side), r = back.clone().sub(side);
  out.push(t.x, t.y, t.z, l.x, l.y, l.z, t.x, t.y, t.z, r.x, r.y, r.z);
};

const square = (out: number[], h: number, plane: 'xy' | 'xz' = 'xy'): void => {
  const c: Vec3[] = plane === 'xy' ? [[-h, -h, 0], [h, -h, 0], [h, h, 0], [-h, h, 0]] : [[-h, 0, -h], [h, 0, -h], [h, 0, h], [-h, 0, h]];
  for (let i = 0; i < 4; i++) seg(out, c[i], c[(i + 1) % 4]);
};

const ringArrow = (out: number[], r: number, size: number): void => {
  const end = Math.PI * 1.6;
  circle(out, 'xy', r, 0, end, 28);
  arrow(out, [Math.cos(end) * r, Math.sin(end) * r, 0], [-Math.sin(end), Math.cos(end), 0], size);
};

export function glyph(type: JointType, s: number): Float32Array {
  const o: number[] = [];
  const ah = s * 0.22;
  const axis = (lo: number, hi: number, both: boolean): void => {
    seg(o, [0, 0, lo * s], [0, 0, hi * s]);
    arrow(o, [0, 0, hi * s], [0, 0, 1], ah);
    if (both) arrow(o, [0, 0, lo * s], [0, 0, -1], ah);
  };
  const base = (): void => { seg(o, [-0.12 * s, 0, 0], [0.12 * s, 0, 0]); seg(o, [0, -0.12 * s, 0], [0, 0.12 * s, 0]); };
  base();
  switch (type) {
    case 'rigid': {
      const h = 0.25 * s;
      square(o, h, 'xy');
      const top: Vec3[] = [[-h, -h, h], [h, -h, h], [h, h, h], [-h, h, h]];
      for (let i = 0; i < 4; i++) { seg(o, top[i], top[(i + 1) % 4]); const b: Vec3 = [top[i][0], top[i][1], -h]; seg(o, b, top[i]); }
      break;
    }
    case 'revolute': {
      axis(-1, 1.2, false);
      const ring: number[] = [];
      ringArrow(ring, 0.7 * s, ah);
      o.push(...ring);
      break;
    }
    case 'slider':
      axis(-1.2, 1.2, true);
      square(o, 0.18 * s, 'xy');
      break;
    case 'cylindrical':
      axis(-1.2, 1.2, true);
      ringArrow(o, 0.6 * s, ah);
      break;
    case 'pinslot':
      seg(o, [-1.2 * s, 0, 0], [1.2 * s, 0, 0]);
      arrow(o, [1.2 * s, 0, 0], [1, 0, 0], ah);
      arrow(o, [-1.2 * s, 0, 0], [-1, 0, 0], ah);
      seg(o, [0, 0, -0.2 * s], [0, 0, 0.9 * s]);
      ringArrow(o, 0.55 * s, ah);
      break;
    case 'planar':
      square(o, 0.9 * s, 'xy');
      arrow(o, [0.9 * s, 0, 0], [1, 0, 0], ah);
      arrow(o, [0, 0.9 * s, 0], [0, 1, 0], ah);
      seg(o, [0, 0, 0], [0, 0, 0.7 * s]);
      ringArrow(o, 0.4 * s, ah * 0.8);
      break;
    case 'ball':
      circle(o, 'xy', 0.6 * s, 0, Math.PI * 2, 28);
      circle(o, 'yz', 0.6 * s, 0, Math.PI * 2, 28);
      circle(o, 'xz', 0.6 * s, 0, Math.PI * 2, 28);
      break;
  }
  return new Float32Array(o);
}

const cssColor = (host: HTMLElement, name: string, fallback: string): THREE.Color => new THREE.Color().setHex(tokenHex(name, parseCss(fallback), host));

const frameMatrix = (f: { origin?: number[]; o?: number[]; z: number[]; x?: number[] }): THREE.Matrix4 => {
  const p = f.origin ?? f.o ?? [0, 0, 0];
  const z = new THREE.Vector3(f.z[0], f.z[1], f.z[2]);
  if (z.lengthSq() < 1e-12) z.set(0, 0, 1);
  z.normalize();
  const x = f.x ? new THREE.Vector3(f.x[0], f.x[1], f.x[2]) : Math.abs(z.z) < 0.9 ? new THREE.Vector3(0, 0, 1).cross(z) : new THREE.Vector3(1, 0, 0);
  x.sub(z.clone().multiplyScalar(x.dot(z)));
  if (x.lengthSq() < 1e-12) x.set(1, 0, 0).sub(z.clone().multiplyScalar(z.x));
  x.normalize();
  const y = new THREE.Vector3().crossVectors(z, x);
  return new THREE.Matrix4().makeBasis(x, y, z).setPosition(p[0], p[1], p[2]);
};

const stateOf = (j: Joint): Kind => {
  if (j.suppressed) return 'off';
  let k: Kind = 'free';
  for (const c of j.coords) {
    if (c.state === 'outside') return 'outside';
    if (c.state === 'at_min' || c.state === 'at_max') k = 'limit';
  }
  return k;
};

interface Item { joint: Joint; obj: THREE.LineSegments; kind: Kind; sig: string; label: string }

export class JointLayer implements ViewLayer {
  readonly group = new THREE.Group();
  private readonly mats = new Map<Kind, THREE.LineBasicMaterial>();
  private readonly items = new Map<string, Item>();
  private shownOn = true;
  private picked = '';
  private size = 10;
  private poses: Record<string, number[]> | null = null;
  private ink: Record<Kind, string> = { free: '#9a7bd8', limit: '#f59e0b', outside: '#ef4444', off: '#888888', hot: '#ffffff' };

  constructor(private readonly vp: Viewport3D) {
    for (const k of KINDS) this.mats.set(k, new THREE.LineBasicMaterial({ color: 0xffffff, depthTest: false, transparent: true }));
    this.group.visible = false;
    this.palette({} as Palette);
  }

  get shown(): boolean { return this.shownOn; }

  palette(_pal: Palette): void {
    const host = this.vp.host;
    const colours: Record<Kind, THREE.Color> = {
      free: cssColor(host, '--accent-color', '#9a7bd8'),
      limit: cssColor(host, '--warn', '#f59e0b'),
      outside: cssColor(host, '--danger', '#ef4444'),
      off: cssColor(host, '--text-muted', '#888888'),
      hot: cssColor(host, '--text-primary', '#ffffff'),
    };
    for (const k of KINDS) {
      this.mats.get(k)?.color.copy(colours[k]);
      this.ink[k] = `#${colours[k].getHexString()}`;
    }
    this.vp.invalidate();
  }

  bounds(): { min: Vec3; max: Vec3 } | null { return null; }

  setShown(on: boolean): void {
    this.shownOn = on;
    this.sync();
  }

  highlight(id: string): void {
    if (this.picked === id) return;
    this.picked = id;
    for (const [k, it] of this.items) this.paintItem(k, it);
    this.vp.invalidate();
  }

  private paintItem(k: string, it: Item): void {
    const kind: Kind = k === this.picked && it.kind !== 'off' ? 'hot' : it.kind;
    const mat = this.mats.get(kind);
    if (mat && it.obj.material !== mat) it.obj.material = mat;
  }

  private measure(): number {
    let lo = Infinity, hi = -Infinity;
    for (const v of this.vp.bodyViews.values()) for (let k = 0; k < 3; k++) { lo = Math.min(lo, v.min[k]); hi = Math.max(hi, v.max[k]); }
    return hi > lo ? Math.max((hi - lo) * 0.07, 0.5) : 10;
  }

  private worldOf(comp: string | null): THREE.Matrix4 {
    if (!comp || comp === 'world') return new THREE.Matrix4();
    const p = this.poses?.[comp];
    if (p) return matrixOf(p);
    return asm.worlds.get(comp)?.clone() ?? new THREE.Matrix4();
  }

  private place(it: Item): void {
    const m = this.worldOf(it.joint.b.comp).multiply(frameMatrix(it.joint.b.frame));
    it.obj.matrixAutoUpdate = false;
    it.obj.matrix.copy(m);
    it.obj.matrixWorldNeedsUpdate = true;
  }

  follow(poses: Record<string, number[]> | null): void {
    this.poses = poses;
    for (const it of this.items.values()) this.place(it);
    this.vp.invalidate();
  }

  set(list: Joint[]): void {
    const size = this.measure();
    const seen = new Set<string>();
    for (const j of list) {
      const k = String(j.id);
      seen.add(k);
      const kind = stateOf(j);
      const sig = `${j.type}|${size.toFixed(3)}`;
      let it = this.items.get(k);
      if (!it || it.sig !== sig) {
        if (it) { it.obj.geometry.dispose(); this.group.remove(it.obj); }
        const geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.BufferAttribute(glyph(j.type, size), 3));
        const obj = new THREE.LineSegments(geo, this.mats.get(kind));
        obj.renderOrder = 9;
        obj.frustumCulled = false;
        it = { joint: j, obj, kind, sig, label: j.name };
        this.items.set(k, it);
        this.group.add(obj);
      }
      it.joint = j;
      it.kind = kind;
      it.label = j.label || j.name;
      this.paintItem(k, it);
      this.place(it);
    }
    for (const [k, it] of this.items) {
      if (seen.has(k)) continue;
      it.obj.geometry.dispose();
      this.group.remove(it.obj);
      this.items.delete(k);
    }
    this.size = size;
    this.sync();
  }

  private sync(): void {
    const on = this.shownOn && this.items.size > 0;
    if (this.group.visible !== on) this.group.visible = on;
    this.vp.invalidate();
  }

  sceneChanged(): void {
    const size = this.measure();
    if (Math.abs(size - this.size) > 1e-6 && this.items.size) this.set([...this.items.values()].map((i) => i.joint));
  }

  draw(g: CanvasRenderingContext2D, project: Projector, ink: InkColors): void {
    if (!this.group.visible) return;
    g.save();
    g.font = '11px -apple-system, "Segoe UI", Inter, system-ui, sans-serif';
    g.textBaseline = 'middle';
    g.textAlign = 'left';
    const v = new THREE.Vector3();
    for (const [k, it] of this.items) {
      v.setFromMatrixPosition(it.obj.matrix);
      const p = project([v.x, v.y, v.z]);
      if (!p) continue;
      const text = k === this.picked ? `${it.label} ${it.joint.coords.map((c) => `${c.key} ${Number(c.value.toFixed(2))}`).join(' ')}` : it.label;
      const w = Math.ceil(g.measureText(text).width) + 8;
      g.fillStyle = ink.tipBg;
      g.strokeStyle = this.ink[k === this.picked ? 'hot' : it.kind];
      g.lineWidth = k === this.picked ? 2 : 1;
      g.beginPath();
      g.roundRect(p.x + 8.5, p.y - 16.5, w, 16, 3);
      g.fill();
      g.stroke();
      g.fillStyle = ink.tipText;
      g.fillText(text, p.x + 12, p.y - 8);
    }
    g.restore();
  }

  dispose(): void {
    for (const it of this.items.values()) it.obj.geometry.dispose();
    for (const m of this.mats.values()) m.dispose();
  }
}
