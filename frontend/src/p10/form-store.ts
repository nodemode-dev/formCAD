import { events } from '../io/events';
import { commands } from '../ui/commands';
import { docStore } from '../ui/doc-store';
import { toast } from '../ui/toast';
import { view3d } from '../view3d/mount';
import type { Vec3 } from '../view3d/types';
import { EngineError } from '../u8/net';
import { docUrl, req, runCmd, type Json } from './kit';

export type Mode = 'vertex' | 'edge' | 'face';
export type Tool = 'select' | 'move' | 'rotate' | 'scale';

export interface CageItem { handle: number; name: string; display: string; level: number; summary: Json; version: number }
export interface Cage {
  handle: number;
  name: string;
  offset: Vec3;
  v: Vec3[];
  f: number[][];
  crease: number[][];
  sym: { mirror: Array<{ axis: string; at: number }>; radial: { axis: string; count: number; center: number[] } | null; tol: number };
  display: string;
  level: number;
  summary: Json;
  version: number;
  edges: number[][];
  edge_faces: number[][];
  valence: number[];
  boundary_edges: number[];
  unit_mm: number;
}

export interface Soft { on: boolean; radius: number; falloff: string; symmetry: boolean }

type Listener = (what: 'cage' | 'sel' | 'tool' | 'soft') => void;

class FormStore {
  cages: CageItem[] = [];
  active: number | null = null;
  cage: Cage | null = null;
  mode: Mode = 'vertex';
  tool: Tool = 'move';
  sel = new Set<number>();
  soft: Soft = { on: false, radius: 10, falloff: 'smooth', symmetry: true };
  weights: number[] | null = null;
  images = new Set<number>();
  busy = false;
  private absent = false;
  private radiusTouched = false;
  private readonly listeners = new Set<Listener>();
  private timer = 0;
  private softSeq = 0;

  onChange(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  private emit(what: Parameters<Listener>[0]): void {
    for (const fn of this.listeners) fn(what);
  }

  get on(): boolean { return this.cage !== null; }

  queue(): void {
    window.clearTimeout(this.timer);
    this.timer = window.setTimeout(() => { void this.refresh(); }, 120);
  }

  async refresh(): Promise<void> {
    const id = docStore.activeId;
    if (!id) { this.cages = []; this.cage = null; this.active = null; this.emit('cage'); return; }
    if (this.absent) { this.cages = []; this.cage = null; this.active = null; return; }
    try {
      const r = await req<{ cages: CageItem[] }>('GET', docUrl(id, 'subd'));
      this.cages = r.cages;
    } catch (e) {
      this.cages = [];
      if (e instanceof EngineError && e.status === 404 && e.message === 'Not Found') this.absent = true;
    }
    if (this.active === null || !this.cages.some((c) => c.handle === this.active)) this.active = this.cages.length ? this.cages[this.cages.length - 1].handle : null;
    await this.load();
  }

  async load(): Promise<void> {
    const id = docStore.activeId;
    if (!id || this.active === null) { this.cage = null; this.sel.clear(); this.weights = null; this.emit('cage'); return; }
    try {
      const cage = await req<Cage>('GET', docUrl(id, `subd/${this.active}`));
      const same = this.cage && this.cage.handle === cage.handle;
      const topo = same && this.cage && this.cage.v.length === cage.v.length && this.cage.f.length === cage.f.length;
      this.cage = cage;
      const bb = cage.summary.bbox as number[] | undefined;
      if (!this.radiusTouched && bb && bb.length >= 6) {
        const ext = Math.max(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]);
        if (ext > 0) this.soft = { ...this.soft, radius: Number((ext * 0.75).toPrecision(2)) };
      }
      if (!topo) this.sel.clear();
      else this.sel = new Set([...this.sel].filter((i) => i < this.count()));
    } catch { this.cage = null; this.sel.clear(); }
    this.weights = null;
    this.emit('cage');
    this.emit('sel');
    void this.pullSoft();
  }

  setActive(handle: number | null): void {
    if (handle === this.active) return;
    this.active = handle;
    this.sel.clear();
    void this.load();
  }

  count(): number {
    const c = this.cage;
    if (!c) return 0;
    return this.mode === 'vertex' ? c.v.length : this.mode === 'edge' ? c.edges.length : c.f.length;
  }

  setMode(m: Mode): void {
    if (m === this.mode) return;
    const verts = this.vertices();
    this.mode = m;
    this.sel.clear();
    if (m === 'vertex') this.sel = new Set(verts);
    commands.get(`v3-level-${m === 'vertex' ? 'any' : m}`)?.run();
    this.weights = null;
    this.emit('sel');
    void this.pullSoft();
  }

  setTool(t: Tool): void {
    if (this.tool === t) return;
    this.tool = t;
    this.emit('tool');
  }

  setSoft(change: Partial<Soft>): void {
    if (change.radius !== undefined) this.radiusTouched = true;
    this.soft = { ...this.soft, ...change };
    this.emit('soft');
    void this.pullSoft();
  }

  set(indices: number[], add = false): void {
    if (!add) this.sel.clear();
    for (const i of indices) {
      if (add && this.sel.has(i)) this.sel.delete(i); else this.sel.add(i);
    }
    this.emit('sel');
    void this.pullSoft();
  }

  replace(indices: number[]): void {
    this.sel = new Set(indices);
    this.emit('sel');
    void this.pullSoft();
  }

  clear(): void {
    this.sel.clear();
    this.weights = null;
    this.emit('sel');
  }

  all(): void {
    const n = this.count();
    this.sel = new Set(Array.from({ length: n }, (_, i) => i));
    this.emit('sel');
    void this.pullSoft();
  }

  vertices(): number[] {
    const c = this.cage;
    if (!c) return [];
    if (this.mode === 'vertex') return [...this.sel];
    const out = new Set<number>();
    if (this.mode === 'edge') for (const e of this.sel) { const p = c.edges[e]; if (p) { out.add(p[0]); out.add(p[1]); } }
    else for (const fi of this.sel) for (const v of c.f[fi] ?? []) out.add(v);
    return [...out];
  }

  args(): Json {
    const c = this.cage;
    if (!c || !this.sel.size) return {};
    const list = [...this.sel].sort((a, b) => a - b);
    if (this.mode === 'vertex') return { vertices: list };
    if (this.mode === 'edge') return { edges: list.map((e) => c.edges[e]).filter(Boolean) };
    return { faces: list };
  }

  centroid(): Vec3 | null {
    const c = this.cage;
    const vs = this.vertices();
    if (!c || !vs.length) return null;
    let x = 0, y = 0, z = 0;
    for (const i of vs) { x += c.v[i][0]; y += c.v[i][1]; z += c.v[i][2]; }
    const n = vs.length;
    return [x / n + c.offset[0], y / n + c.offset[1], z / n + c.offset[2]];
  }

  world(i: number): Vec3 {
    const c = this.cage as Cage;
    const p = c.v[i];
    return [p[0] + c.offset[0], p[1] + c.offset[1], p[2] + c.offset[2]];
  }

  softArgs(): Json {
    return this.soft.on ? { soft: { radius: this.soft.radius, falloff: this.soft.falloff } } : {};
  }

  async pullSoft(): Promise<void> {
    const id = docStore.activeId;
    const seq = ++this.softSeq;
    if (!id || !this.cage || this.active === null || !this.sel.size || !this.soft.on) {
      if (this.weights) { this.weights = null; this.images = new Set(); this.emit('soft'); }
      return;
    }
    try {
      const r = await req<{ weights: number[]; images?: unknown }>('POST', docUrl(id, `subd/${this.active}/soft`), { ...this.args(), radius: this.soft.radius, falloff: this.soft.falloff, symmetry: this.soft.symmetry });
      if (seq !== this.softSeq) return;
      this.weights = r.weights;
      const imgs = new Set<number>();
      const walk = (x: unknown): void => { if (typeof x === 'number') imgs.add(x); else if (Array.isArray(x)) x.forEach(walk); else if (x && typeof x === 'object') Object.values(x as Json).forEach(walk); };
      walk(r.images);
      this.images = imgs;
    } catch { if (seq === this.softSeq) { this.weights = null; this.images = new Set(); } }
    this.emit('soft');
  }

  async run(command: string, extra: Json = {}, needsSelection = true): Promise<Json | null> {
    if (this.active === null) { toast('Create or select a form first.', 'info'); return null; }
    if (needsSelection && !this.sel.size) { toast('Select vertices, edges or faces first.', 'info'); return null; }
    if (this.busy) return null;
    this.busy = true;
    try {
      const r = await runCmd<Json>(command, { handle: this.active, ...(needsSelection ? this.args() : {}), ...extra });
      await this.load();
      await view3d()?.with3d(() => undefined);
      return r;
    } finally { this.busy = false; }
  }

  readViewSelection(): void {
    const c = this.cage;
    const vp = view3d()?.vp;
    if (!c || !vp || this.mode === 'vertex') return;
    const want = this.mode === 'face' ? vp.sel.faces.filter((f) => f.body === this.active).map((f) => f.face - 1) : vp.sel.edges.filter((e) => e.body === this.active).map((e) => e.edge - 1);
    const next = want.filter((i) => i >= 0 && i < this.count());
    if (next.length === this.sel.size && next.every((i) => this.sel.has(i))) return;
    this.replace(next);
  }

  adoptViewBody(): void {
    const vp = view3d()?.vp;
    if (!vp) return;
    const h = vp.sel.bodies.find((b) => this.cages.some((c) => c.handle === b));
    if (h !== undefined) this.setActive(h);
  }
}

export const form = new FormStore();

events.on('doc', (e) => { if (e.id === docStore.activeId) form.queue(); });
docStore.onChange(() => { form.queue(); });
document.addEventListener('formcad:selection', () => { form.adoptViewBody(); form.readViewSelection(); });
