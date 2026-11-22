import * as THREE from 'three';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js';
import { api } from '../io/api';
import { events } from '../io/events';
import { docStore } from '../ui/doc-store';
import { toast } from '../ui/toast';
import { DEFAULT_BODY_COLOR, EDGES_VISIBLE, FACE_VISIBLE, readPalette, type Palette } from './kit';
import type { ViewLayer } from './layer';
import type { InkColors } from './overlay';
import { fetchNet, type SurfaceNet } from './nurbs-api';
import { SurfaceEval } from './surface-eval';
import type { Vec3 } from './types';
import type { Viewport3D } from './viewport';

export interface StripeSource {
  applied: number;
  stripesFor(id: number, normals: Float32Array, reversed: boolean): { values: Float32Array; size: number; mat: THREE.Material } | null;
}

interface Live {
  handle: number;
  net: SurfaceNet;
  ev: SurfaceEval;
  poles: Float64Array;
  mesh: THREE.Mesh;
  edges: LineSegments2;
  cage: THREE.LineSegments;
  paint: THREE.Material | null;
  stamp: number;
}

interface Drag {
  index: number;
  px: number;
  py: number;
  origin: Vec3;
  normal: Vec3;
  grab: Vec3;
  start: Float64Array;
  delta: Vec3;
  moved: boolean;
}

const HIT = 9;
const rgb = (c: THREE.Color): string => `#${c.getHexString()}`;
const sameList = (a: number[], b: number[]): boolean => a.length === b.length && a.every((v, i) => v === b[i]);

function sameShape(a: SurfaceNet, b: SurfaceNet): boolean {
  return a.count[0] === b.count[0] && a.count[1] === b.count[1] && a.degree[0] === b.degree[0] && a.degree[1] === b.degree[1] && a.reversed === b.reversed
    && sameList(a.uknots, b.uknots) && sameList(a.vknots, b.vknots) && sameList(a.weights, b.weights)
    && sameList(a.grid.u, b.grid.u) && sameList(a.grid.v, b.grid.v) && sameList(a.grid.mask, b.grid.mask);
}

export class SurfaceLayer implements ViewLayer {
  readonly group = new THREE.Group();
  private on = false;
  private target: number | null = null;
  private live: Live | null = null;
  private picked = new Set<number>();
  private hover = -1;
  private drag: Drag | null = null;
  private raf = 0;
  private timer = 0;
  private busy = false;
  private again = false;
  private saving = false;
  private refused: number | null = null;
  private pal: Palette;
  private readonly cageMat: THREE.LineBasicMaterial;
  private readonly off: Array<() => void> = [];

  constructor(private readonly vp: Viewport3D, private readonly stripes: () => StripeSource | null) {
    this.pal = readPalette(vp.host);
    this.cageMat = new THREE.LineBasicMaterial({ color: this.pal.snap, transparent: true, opacity: 0.55, depthTest: false });
    const host = vp.host;
    const add = <K extends keyof HTMLElementEventMap>(type: K, fn: (e: HTMLElementEventMap[K]) => void): void => {
      host.addEventListener(type, fn as EventListener, { capture: true });
      this.off.push(() => host.removeEventListener(type, fn as EventListener, { capture: true }));
    };
    add('pointerdown', (e) => this.onDown(e));
    add('pointermove', (e) => this.onMove(e));
    add('keydown', (e) => this.onKey(e));
    this.off.push(events.on('doc', (e) => {
      if (e.id === docStore.activeId && this.target !== null && !this.drag && !this.saving) this.schedule();
    }));
  }

  get shown(): boolean { return this.on; }
  get handle(): number | null { return this.live?.handle ?? null; }
  get dragging(): boolean { return this.drag !== null; }
  get striped(): boolean { return !!this.live?.paint; }
  get pickedPoints(): number[] { return [...this.picked].sort((a, b) => a - b); }

  polesOf(): Vec3[] {
    const L = this.live;
    if (!L) return [];
    const out: Vec3[] = [];
    for (let k = 0; k < L.poles.length; k += 3) out.push([L.poles[k], L.poles[k + 1], L.poles[k + 2]]);
    return out;
  }

  setOn(on: boolean): void {
    if (on === this.on) return;
    this.on = on;
    if (!on) { this.target = null; this.refused = null; this.release(); }
    this.vp.invalidate();
  }

  reset(): void {
    this.target = null;
    this.refused = null;
    this.release();
  }

  private wanted(): number | null {
    const s = this.vp.sel;
    const views = this.vp.bodyViews;
    for (const id of s.bodies) if (views.has(id)) return id;
    for (const f of s.faces) if (views.has(f.body)) return f.body;
    for (const e of s.edges) if (views.has(e.body)) return e.body;
    return this.target !== null && views.has(this.target) ? this.target : null;
  }

  frame(): void {
    if (!this.vp.active) return;
    const want = this.on ? this.wanted() : null;
    if (want !== this.target && !this.drag && !this.saving) {
      this.target = want;
      this.refused = null;
      if (want === null || (this.live && this.live.handle !== want)) this.release();
      if (want !== null) void this.load();
    }
    const L = this.live;
    if (!L) return;
    const src = this.stripes();
    if ((src?.applied ?? -1) !== L.stamp) this.restripe(L);
    this.dress(L);
  }

  private schedule(): void {
    if (this.timer) return;
    this.timer = window.setTimeout(() => { this.timer = 0; void this.load(); }, 120);
  }

  private async load(): Promise<void> {
    if (this.busy) { this.again = true; return; }
    this.busy = true;
    try {
      do {
        this.again = false;
        const doc = docStore.activeId;
        const h = this.target;
        if (!doc || h === null || h === this.refused) break;
        let net: SurfaceNet;
        try {
          net = await fetchNet(doc, h);
        } catch (err) {
          if (this.target === h) {
            this.refused = h;
            this.release();
            toast(err instanceof Error ? err.message : 'The control points could not be read', 'info');
          }
          continue;
        }
        if (this.target !== h || docStore.activeId !== doc) { this.again = this.target !== null; continue; }
        if (this.drag || this.saving) break;
        this.adopt(net);
      } while (this.again);
    } finally {
      this.busy = false;
    }
  }

  private adopt(net: SurfaceNet): void {
    let L = this.live;
    if (L && L.handle === net.handle && sameShape(L.net, net)) {
      if (L.net.blob === net.blob) return;
      L.net = net;
    } else {
      this.release();
      L = this.build(net);
      this.live = L;
      this.group.add(L.mesh, L.edges, L.cage);
    }
    const poles = L.poles;
    net.poles.forEach((p, k) => { poles[k * 3] = p[0]; poles[k * 3 + 1] = p[1]; poles[k * 3 + 2] = p[2]; });
    this.evaluate(L);
    this.dress(L);
    this.vp.setProxyBody(L.handle);
  }

  private build(net: SurfaceNet): Live {
    const ev = new SurfaceEval(net);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(ev.positions, 3));
    geo.setAttribute('normal', new THREE.BufferAttribute(ev.normals, 3));
    geo.setIndex(new THREE.BufferAttribute(ev.indices, 1));
    const mesh = new THREE.Mesh(geo);
    mesh.frustumCulled = false;
    const edges = new LineSegments2(new LineSegmentsGeometry());
    edges.frustumCulled = false;
    const [nu, nv] = net.count;
    const cageGeo = new THREE.BufferGeometry();
    cageGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array((nu * (nv - 1) + nv * (nu - 1)) * 6), 3));
    const cage = new THREE.LineSegments(cageGeo, this.cageMat);
    cage.frustumCulled = false;
    cage.renderOrder = 4;
    return { handle: net.handle, net, ev, poles: new Float64Array(nu * nv * 3), mesh, edges, cage, paint: null, stamp: -2 };
  }

  private evaluate(L: Live): void {
    L.ev.update(L.poles);
    const geo = L.mesh.geometry;
    geo.getAttribute('position').needsUpdate = true;
    geo.getAttribute('normal').needsUpdate = true;
    const border = L.ev.border;
    if (border.length) {
      const start = L.edges.geometry.getAttribute('instanceStart') as THREE.InterleavedBufferAttribute | undefined;
      if (!start) L.edges.geometry.setPositions(border);
      else {
        if (start.data.array !== border) (start.data.array as Float32Array).set(border);
        start.data.needsUpdate = true;
      }
    }
    const [nu, nv] = L.net.count;
    const at = L.cage.geometry.getAttribute('position') as THREE.BufferAttribute;
    const out = at.array as Float32Array;
    const p = L.poles;
    let o = 0;
    const seg = (a: number, b: number): void => {
      out[o++] = p[a * 3]; out[o++] = p[a * 3 + 1]; out[o++] = p[a * 3 + 2];
      out[o++] = p[b * 3]; out[o++] = p[b * 3 + 1]; out[o++] = p[b * 3 + 2];
    };
    for (let i = 0; i < nu; i++) for (let j = 0; j + 1 < nv; j++) seg(i * nv + j, i * nv + j + 1);
    for (let j = 0; j < nv; j++) for (let i = 0; i + 1 < nu; i++) seg(i * nv + j, (i + 1) * nv + j);
    at.needsUpdate = true;
    this.restripe(L);
    this.vp.invalidate();
  }

  private restripe(L: Live): void {
    const src = this.stripes();
    const st = src?.stripesFor(L.handle, L.ev.normals, L.net.reversed) ?? null;
    const geo = L.mesh.geometry;
    if (st) {
      const cur = geo.getAttribute('aval') as THREE.BufferAttribute | undefined;
      if (cur && cur.itemSize === st.size && cur.array.length === st.values.length) {
        (cur.array as Float32Array).set(st.values);
        cur.needsUpdate = true;
      } else {
        geo.setAttribute('aval', new THREE.BufferAttribute(st.values, st.size));
      }
      L.paint = st.mat;
    } else if (L.paint) {
      geo.deleteAttribute('aval');
      L.paint = null;
    }
    L.stamp = src?.applied ?? -1;
  }

  private dress(L: Live): void {
    const vp = this.vp;
    const mode = vp.mode;
    const color = vp.bodyViews.get(L.handle)?.data.color || DEFAULT_BODY_COLOR;
    const base = vp.kit.face(mode, color);
    const mat = L.paint && FACE_VISIBLE[mode] ? L.paint : base;
    const faces = FACE_VISIBLE[mode] && !!mat;
    if (L.mesh.visible !== faces) L.mesh.visible = faces;
    if (mat && L.mesh.material !== mat) L.mesh.material = mat;
    const lines = EDGES_VISIBLE[mode] && L.ev.border.length > 0;
    if (L.edges.visible !== lines) L.edges.visible = lines;
    const lineMat = vp.kit.edge(mode);
    if (L.edges.material !== lineMat) L.edges.material = lineMat;
    const lifted = mode === 'ghosted' || mode === 'xray';
    L.mesh.renderOrder = lifted ? 1 : 0;
    L.edges.renderOrder = lifted ? 2 : 1;
  }

  private release(): void {
    const L = this.live;
    this.live = null;
    this.picked.clear();
    this.hover = -1;
    if (L) {
      this.group.remove(L.mesh, L.edges, L.cage);
      L.mesh.geometry.dispose();
      L.edges.geometry.dispose();
      L.cage.geometry.dispose();
    }
    this.vp.setProxyBody(null);
  }

  palette(p: Palette): void {
    this.pal = p;
    this.cageMat.color.copy(p.snap);
  }

  private local(e: PointerEvent): { x: number; y: number } {
    const r = this.vp.canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  private poleAt(L: Live, k: number): Vec3 {
    return [L.poles[k * 3], L.poles[k * 3 + 1], L.poles[k * 3 + 2]];
  }

  private hitPole(x: number, y: number): number {
    const L = this.live;
    if (!L) return -1;
    let best = -1;
    let bestD = HIT;
    const n = L.poles.length / 3;
    for (let k = 0; k < n; k++) {
      const q = this.vp.project(this.poleAt(L, k));
      if (!q) continue;
      const d = Math.hypot(q.x - x, q.y - y);
      if (d < bestD) { bestD = d; best = k; }
    }
    return best;
  }

  private planePoint(px: number, py: number, origin: Vec3, n: Vec3): Vec3 | null {
    const ray = this.vp.rayAt(px, py);
    const dir = ray.direction;
    const den = dir[0] * n[0] + dir[1] * n[1] + dir[2] * n[2];
    if (Math.abs(den) < 1e-9) return null;
    const t = ((origin[0] - ray.origin[0]) * n[0] + (origin[1] - ray.origin[1]) * n[1] + (origin[2] - ray.origin[2]) * n[2]) / den;
    if (!Number.isFinite(t)) return null;
    return [ray.origin[0] + dir[0] * t, ray.origin[1] + dir[1] * t, ray.origin[2] + dir[2] * t];
  }

  private onDown(e: PointerEvent): void {
    const L = this.live;
    if (!this.vp.active || !L || this.saving || e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey) return;
    const p = this.local(e);
    const hit = this.hitPole(p.x, p.y);
    if (hit < 0) return;
    e.stopImmediatePropagation();
    e.preventDefault();
    if (e.shiftKey) {
      if (this.picked.has(hit)) this.picked.delete(hit); else this.picked.add(hit);
      this.vp.invalidate();
      return;
    }
    if (!this.picked.has(hit)) this.picked = new Set([hit]);
    const fwd = this.vp.camera.getWorldDirection(new THREE.Vector3());
    const normal: Vec3 = [fwd.x, fwd.y, fwd.z];
    const origin = this.poleAt(L, hit);
    const grab = this.planePoint(p.x, p.y, origin, normal) ?? origin;
    this.drag = { index: hit, px: p.x, py: p.y, origin, normal, grab, start: L.poles.slice(), delta: [0, 0, 0], moved: false };
    const move = (ev: PointerEvent): void => this.dragMove(ev);
    const up = (ev: PointerEvent): void => {
      window.removeEventListener('pointermove', move, true);
      window.removeEventListener('pointerup', up, true);
      void this.dragEnd(ev);
    };
    window.addEventListener('pointermove', move, true);
    window.addEventListener('pointerup', up, true);
    this.vp.dropHover();
  }

  private onMove(e: PointerEvent): void {
    if (!this.vp.active || !this.live || this.drag || (e.buttons & 7) !== 0) return;
    const p = this.local(e);
    const next = this.hitPole(p.x, p.y);
    if (next === this.hover) return;
    this.hover = next;
    this.vp.canvas.style.cursor = next >= 0 ? 'grab' : '';
    this.vp.invalidate();
  }

  private onKey(e: KeyboardEvent): void {
    if (e.key !== 'Escape' || !this.live || this.drag || this.saving) return;
    if (this.picked.size) {
      this.picked.clear();
      e.stopPropagation();
      e.preventDefault();
      this.vp.invalidate();
      return;
    }
    this.target = null;
    this.release();
  }

  private dragMove(e: PointerEvent): void {
    const d = this.drag;
    if (!d) return;
    const p = this.local(e);
    if (!d.moved && Math.hypot(p.x - d.px, p.y - d.py) < 3) return;
    const q = this.planePoint(p.x, p.y, d.origin, d.normal);
    if (!q) return;
    d.moved = true;
    d.delta = [q[0] - d.grab[0], q[1] - d.grab[1], q[2] - d.grab[2]];
    if (!this.raf) this.raf = requestAnimationFrame(() => { this.raf = 0; this.flush(); });
  }

  private flush(): void {
    const d = this.drag;
    const L = this.live;
    if (!d || !L) return;
    for (const k of this.picked) for (let c = 0; c < 3; c++) L.poles[k * 3 + c] = d.start[k * 3 + c] + d.delta[c];
    this.evaluate(L);
  }

  private async dragEnd(e: PointerEvent): Promise<void> {
    const d = this.drag;
    const L = this.live;
    if (!d) return;
    e.stopPropagation();
    if (this.raf) { cancelAnimationFrame(this.raf); this.raf = 0; }
    if (d.moved) this.flush();
    this.drag = null;
    const doc = docStore.activeId;
    if (!L || !doc || !d.moved) {
      if (!d.moved) this.picked = new Set([d.index]);
      this.vp.invalidate();
      return;
    }
    const nv = L.net.count[1];
    const moves = [...this.picked].map((k) => ({ i: Math.floor(k / nv), j: k % nv, to: this.poleAt(L, k) }));
    this.saving = true;
    let failed = '';
    try {
      const state = await api.runCommand(doc, 'srfpoints', { handle: L.handle, moves });
      failed = state.error ?? '';
    } catch (err) {
      failed = err instanceof Error ? err.message : 'The control points could not be moved';
    }
    this.saving = false;
    if (failed) {
      toast(failed, 'error');
      if (this.live === L) { L.poles.set(d.start); this.evaluate(L); }
    }
    await this.load();
    void docStore.refresh();
  }

  draw(g: CanvasRenderingContext2D, project: (p: Vec3) => { x: number; y: number } | null, ink: InkColors): void {
    const L = this.live;
    if (!L || !this.vp.active) return;
    const plain = rgb(this.pal.snap), chosen = rgb(this.pal.select), hot = ink.tipText;
    const edge = this.pal.bg.getStyle();
    const n = L.poles.length / 3;
    g.save();
    g.lineWidth = 1.6;
    g.strokeStyle = edge;
    for (let k = 0; k < n; k++) {
      const q = project(this.poleAt(L, k));
      if (!q) continue;
      const isHot = k === this.hover || (this.drag !== null && this.drag.index === k);
      const r = isHot ? 6 : 4.5;
      g.fillStyle = isHot ? hot : this.picked.has(k) ? chosen : plain;
      g.beginPath();
      g.rect(q.x - r, q.y - r, r * 2, r * 2);
      g.fill();
      g.stroke();
    }
    g.restore();
  }

  dispose(): void {
    for (const o of this.off) o();
    window.clearTimeout(this.timer);
    if (this.raf) cancelAnimationFrame(this.raf);
    this.release();
    this.cageMat.dispose();
  }
}
