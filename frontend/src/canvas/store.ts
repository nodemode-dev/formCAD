import { BatchData } from './batch';
import { Emitter, type BuildCtx } from './build';
import { barOf } from './cmarks';
import { RTree } from './spatial';
import type { ConstraintBar, DisplayItem, DisplayPayload, Handle, LayerState, LayoutPayload, Rect } from './types';

const CHUNK_SPAN = 4096;
const MAX_CHUNKS = 256;
const LIMIT_ITEMS = 8000;

export interface BuildOptions {
  lwOn: boolean;
  lwScale: number;
  fillOn: boolean;
  trOn: boolean;
  dashOn: boolean;
  ltScale: number;
}

export interface Chunk {
  key: number;
  ids: Set<Handle>;
  dirty: boolean;
  stale: boolean;
  built: boolean;
  sensitive: boolean;
  deep: boolean;
  band: number;
  ox: number;
  oy: number;
  bounds: Rect | null;
  area: Rect | null;
  refH: number;
  data: BatchData | null;
  version: number;
  uploaded: number;
  gpu: unknown;
}

export interface ViewForBuild {
  cx: number;
  cy: number;
  height: number;
  wpp: number;
}

const union = (a: Rect | null, b: Rect): Rect => (a ? [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])] : [b[0], b[1], b[2], b[3]]);

const finite = (r: Rect | undefined): boolean => !!r && r.every((n) => Number.isFinite(n));

export class DisplayStore {
  rev = -1;
  space = 'model';
  readonly items = new Map<Handle, DisplayItem>();
  readonly chunks = new Map<number, Chunk>();
  readonly infinite = new Map<Handle, DisplayItem>();
  readonly bars = new Map<Handle, ConstraintBar>();
  readonly pics = new Map<Handle, DisplayItem>();
  layers: Record<string, LayerState> = {};
  extentsHint: Rect | null = null;
  sheet: Rect | null = null;
  printable: Rect | null = null;
  layout: LayoutPayload | null = null;
  layoutVersion = 0;
  builds = 0;
  opts: BuildOptions = { lwOn: false, lwScale: 1, fillOn: true, trOn: true, dashOn: true, ltScale: 1 };
  private span = CHUNK_SPAN;
  private tree: RTree | null = null;
  private list: DisplayItem[] = [];
  private seq = 0;
  private readonly seqOf = new Map<Handle, number>();
  private listeners = new Set<() => void>();

  onChange(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  private fire(): void {
    for (const fn of this.listeners) fn();
  }

  dead: unknown[] = [];

  private dropChunks(): void {
    for (const c of this.chunks.values()) if (c.gpu) this.dead.push(c.gpu);
    this.chunks.clear();
  }

  clear(): void {
    this.items.clear();
    this.bars.clear();
    this.pics.clear();
    this.dropChunks();
    this.infinite.clear();
    this.seqOf.clear();
    this.tree = null;
    this.list = [];
    this.layers = {};
    this.extentsHint = null;
    this.sheet = null;
    this.printable = null;
    this.layout = null;
    this.rev = -1;
    this.span = CHUNK_SPAN;
    this.fire();
  }

  private hidden(item: DisplayItem): boolean {
    const l = this.layers[item.layer];
    return !!l && (l.on === false || l.frozen === true);
  }

  private keyOf(item: DisplayItem): number {
    return Math.floor((Number.isFinite(item.order) ? item.order : 0) / this.span);
  }

  private chunk(key: number): Chunk {
    let c = this.chunks.get(key);
    if (!c) {
      c = { key, ids: new Set(), dirty: true, stale: false, built: false, sensitive: false, deep: false, band: 0, ox: 0, oy: 0, bounds: null, area: null, refH: 0, data: null, version: 0, uploaded: -1, gpu: null };
      this.chunks.set(key, c);
    }
    return c;
  }

  private isInfinite(item: DisplayItem): boolean {
    return !!item.geom && (item.geom.type === 'xline' || item.geom.type === 'ray');
  }

  private detach(h: Handle): void {
    const old = this.items.get(h);
    if (!old) return;
    this.infinite.delete(h);
    const c = this.chunks.get(this.keyOf(old));
    if (c) {
      c.ids.delete(h);
      c.dirty = true;
      if (c.ids.size === 0) {
        if (c.gpu) this.dead.push(c.gpu);
        this.chunks.delete(c.key);
      }
    }
    this.items.delete(h);
    this.bars.delete(h);
    this.pics.delete(h);
    this.seqOf.delete(h);
  }

  hiddenLayer(name: string): boolean {
    const l = this.layers[name];
    return !!l && (l.on === false || l.frozen === true);
  }

  apply(p: DisplayPayload): void {
    if (p.full) {
      this.items.clear();
      this.bars.clear();
      this.pics.clear();
      this.dropChunks();
      this.infinite.clear();
      this.seqOf.clear();
      this.span = CHUNK_SPAN;
    }
    if (p.layers) this.setLayers(p.layers, false);
    for (const h of p.removed ?? []) this.detach(h);
    for (const it of p.items ?? []) {
      if (it.h === null || it.h === undefined || !it.geom && !it.prims) continue;
      if (!finite(it.bounds) && !this.isInfinite(it)) it.bounds = [0, 0, 0, 0];
      this.detach(it.h);
      this.items.set(it.h, it);
      const bar = barOf(it.prims);
      if (bar) this.bars.set(it.h, bar);
      if (it.prims?.some((q) => q.t === 'img')) this.pics.set(it.h, it);
      this.seqOf.set(it.h, this.seq++);
      if (this.isInfinite(it)) this.infinite.set(it.h, it);
      else {
        const ch = this.chunk(this.keyOf(it));
        ch.ids.add(it.h);
        ch.dirty = true;
      }
    }
    if (this.chunks.size > MAX_CHUNKS) this.recut();
    this.rev = p.rev;
    if (p.space) this.space = p.space;
    if (p.extents && finite(p.extents)) this.extentsHint = p.extents;
    this.layout = p.layout ?? null;
    this.layoutVersion++;
    this.sheet = p.sheet ?? (p.layout ? [0, 0, p.layout.paper.width, p.layout.paper.height] : null);
    this.printable = p.printable ?? p.layout?.printable ?? null;
    this.tree = null;
    this.fire();
  }

  private recut(): void {
    let lo = Infinity;
    let hi = -Infinity;
    for (const it of this.items.values()) {
      if (it.order < lo) lo = it.order;
      if (it.order > hi) hi = it.order;
    }
    while ((hi - lo) / this.span + 1 > MAX_CHUNKS) this.span *= 2;
    this.dropChunks();
    for (const it of this.items.values()) if (!this.isInfinite(it)) this.chunk(this.keyOf(it)).ids.add(it.h as Handle);
  }

  setLayers(next: Record<string, LayerState>, notify = true): void {
    const changed = new Set<string>();
    const all = new Set([...Object.keys(this.layers), ...Object.keys(next)]);
    for (const name of all) {
      const a = this.layers[name];
      const b = next[name];
      const ha = !!a && (a.on === false || a.frozen === true);
      const hb = !!b && (b.on === false || b.frozen === true);
      if (ha !== hb) changed.add(name);
    }
    this.layers = next;
    if (changed.size === 0) return;
    for (const it of this.items.values()) {
      if (!changed.has(it.layer)) continue;
      const c = this.chunks.get(this.keyOf(it));
      if (c) c.dirty = true;
    }
    this.tree = null;
    if (notify) this.fire();
  }

  setOptions(o: BuildOptions): boolean {
    const a = this.opts;
    if (a.lwOn === o.lwOn && a.lwScale === o.lwScale && a.fillOn === o.fillOn && a.trOn === o.trOn && a.dashOn === o.dashOn && a.ltScale === o.ltScale) return false;
    this.opts = o;
    for (const c of this.chunks.values()) c.dirty = true;
    this.fire();
    return true;
  }

  private ctxFor(c: Chunk, v: ViewForBuild, band: number): { ctx: BuildCtx; deep: boolean } {
    const w = c.bounds ? Math.max(c.bounds[2] - c.bounds[0], c.bounds[3] - c.bounds[1]) : 0;
    const deep = w > 0 && v.height * 2000 < w;
    let ox = c.bounds ? (c.bounds[0] + c.bounds[2]) / 2 : 0;
    let oy = c.bounds ? (c.bounds[1] + c.bounds[3]) / 2 : 0;
    if (deep) {
      let cell = 1;
      const want = v.height * 64;
      while (cell < want) cell *= 2;
      while (cell / 2 >= want && cell > 1e-12) cell /= 2;
      ox = Math.round(v.cx / cell) * cell;
      oy = Math.round(v.cy / cell) * cell;
    }
    const wpp = Math.pow(2, band);
    return {
      deep,
      ctx: { ox, oy, tol: wpp * 0.5, wpp, lwOn: this.opts.lwOn, lwK: 3.78 * this.opts.lwScale, fillOn: this.opts.fillOn, trOn: this.opts.trOn, dashOn: this.opts.dashOn, ltScale: this.opts.ltScale },
    };
  }

  makeCtx(ox: number, oy: number, band: number): BuildCtx {
    const wpp = Math.pow(2, band);
    return { ox, oy, tol: wpp * 0.5, wpp, lwOn: this.opts.lwOn, lwK: 3.78 * this.opts.lwScale, fillOn: this.opts.fillOn, trOn: this.opts.trOn, dashOn: this.opts.dashOn, ltScale: this.opts.ltScale };
  }

  private build(c: Chunk, v: ViewForBuild, band: number, visible: Rect): void {
    const limited = this.items.size > LIMIT_ITEMS;
    const margin = Math.max(visible[2] - visible[0], visible[3] - visible[1]);
    let area: Rect | null = limited ? [visible[0] - margin, visible[1] - margin, visible[2] + margin, visible[3] + margin] : null;
    let list: DisplayItem[] = [];
    let shown: Rect | null = null;
    let total = 0;
    for (const h of c.ids) {
      const it = this.items.get(h);
      if (!it || this.hidden(it)) continue;
      total++;
      const b = it.bounds;
      if (area && (b[0] > area[2] || b[2] < area[0] || b[1] > area[3] || b[3] < area[1])) continue;
      list.push(it);
      shown = union(shown, b);
    }
    if (area && list.length > total * 0.6) {
      area = null;
      list = [];
      shown = null;
      for (const h of c.ids) {
        const it = this.items.get(h);
        if (!it || this.hidden(it)) continue;
        list.push(it);
        shown = union(shown, it.bounds);
      }
    }
    c.bounds = shown;
    c.area = area;
    c.refH = visible[3] - visible[1];
    const { ctx, deep } = this.ctxFor(c, v, band);
    list.sort((a, b) => a.order - b.order || (this.seqOf.get(a.h as Handle) ?? 0) - (this.seqOf.get(b.h as Handle) ?? 0));
    const data = new BatchData();
    const em = new Emitter(ctx);
    let sensitive = false;
    for (const it of list) if (em.emit(it, data)) sensitive = true;
    data.close();
    c.data = data;
    c.sensitive = sensitive;
    c.deep = deep;
    c.band = band;
    c.ox = ctx.ox;
    c.oy = ctx.oy;
    c.built = true;
    c.dirty = false;
    c.stale = false;
    c.version++;
    this.builds++;
  }

  refreshStale(v: ViewForBuild, band: number, visible: Rect): void {
    for (const c of this.chunks.values()) {
      if (!c.built || c.dirty) continue;
      const a = c.area;
      const limited = this.items.size > LIMIT_ITEMS;
      if (limited && visible[3] - visible[1] < c.refH / 5) {
        c.stale = true;
        continue;
      }
      if (a && (visible[0] < a[0] || visible[1] < a[1] || visible[2] > a[2] || visible[3] > a[3])) {
        c.stale = true;
        continue;
      }
      if (!c.bounds) continue;
      if (c.sensitive && c.band !== band) c.stale = true;
      const w = Math.max(c.bounds[2] - c.bounds[0], c.bounds[3] - c.bounds[1]);
      if (w > 0 && v.height * 2000 < w) {
        const want = v.height * 64;
        if (!c.deep || Math.abs(v.cx - c.ox) > want * 24 || Math.abs(v.cy - c.oy) > want * 24) c.stale = true;
      }
    }
  }

  pending(): boolean {
    for (const c of this.chunks.values()) if (c.dirty || c.stale) return true;
    return false;
  }

  work(budgetMs: number, v: ViewForBuild, band: number, visible: Rect): boolean {
    const todo: Chunk[] = [];
    for (const c of this.chunks.values()) if (c.dirty || c.stale) todo.push(c);
    if (todo.length === 0) return false;
    const inView = (c: Chunk): number => (c.bounds && c.bounds[0] <= visible[2] && c.bounds[2] >= visible[0] && c.bounds[1] <= visible[3] && c.bounds[3] >= visible[1] ? 0 : 1);
    todo.sort((a, b) => inView(a) - inView(b) || a.key - b.key);
    const t0 = performance.now();
    for (const c of todo) {
      this.build(c, v, band, visible);
      if (performance.now() - t0 > budgetMs) break;
    }
    return todo.some((c) => c.dirty || c.stale);
  }

  extents(): Rect | null {
    let b: Rect | null = null;
    for (const it of this.items.values()) {
      if (this.isInfinite(it) || this.hidden(it) || !finite(it.bounds)) continue;
      b = union(b, it.bounds);
    }
    return b ?? this.extentsHint;
  }

  index(): { tree: RTree; list: DisplayItem[] } {
    if (!this.tree) {
      this.list = [];
      const bounds: Rect[] = [];
      for (const it of this.items.values()) {
        if (this.isInfinite(it) || this.hidden(it)) continue;
        this.list.push(it);
        bounds.push(it.bounds);
      }
      this.tree = RTree.build(bounds);
    }
    return { tree: this.tree, list: this.list };
  }

  visibleInfinite(): DisplayItem[] {
    const out: DisplayItem[] = [];
    for (const it of this.infinite.values()) if (!this.hidden(it)) out.push(it);
    return out;
  }
}
