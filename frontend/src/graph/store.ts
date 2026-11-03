import { call, ApiError } from '../io/api';
import { events } from '../io/events';
import { docStore } from '../ui/doc-store';
import { store as persist, stored } from '../ui/dom';
import { decodeGraph, decodeState, decodeTreePage, encodeGraph } from './codec';
import type { CatalogueEntry, CataloguePort, GraphListItem, GraphRecord, NodeState, TreePage } from './types';

export type StoreEvent = 'graph' | 'states' | 'open' | 'list' | 'error' | 'busy';
type Dict = Record<string, unknown>;

const enc = encodeURIComponent;
const LIVE_MS = 50;
const PAGE = 24;
const STALE_MS = 250;
const blankState = (): NodeState => ({ state: 'blank', messages: [], outputs: {} });

function entryOf(raw: Dict): CatalogueEntry {
  const ports = (list: unknown): CataloguePort[] => (Array.isArray(list) ? list : []).map((p: Dict) => ({
    name: String(p.name), nick: typeof p.nick === 'string' ? p.nick : undefined, kind: String(p.kind ?? 'any'), access: (p.access as CataloguePort['access']) ?? 'item', description: typeof p.description === 'string' ? p.description : undefined, optional: p.optional === true,
  }));
  return {
    id: String(raw.id), name: String(raw.name ?? raw.id), nick: typeof raw.nick === 'string' ? raw.nick : undefined, category: String(raw.category ?? ''), group: String(raw.group ?? ''), description: String(raw.description ?? ''),
    inputs: ports(raw.inputs), outputs: ports(raw.outputs), widget: typeof raw.widget === 'string' && raw.widget ? raw.widget : undefined, icon: typeof raw.icon === 'string' ? raw.icon : undefined, obsolete: raw.obsolete === true,
    settings: raw.settings && typeof raw.settings === 'object' ? (raw.settings as Dict) : {},
  };
}

export class GraphStore {
  rec: GraphRecord | null = null;
  states = new Map<string, NodeState>();
  catalogue: CatalogueEntry[] = [];
  entries = new Map<string, CatalogueEntry>();
  list: GraphListItem[] = [];
  gid = '';
  docId = '';
  error = '';
  busy = false;
  lastMs = 0;
  readonly = false;
  problems: string[] = [];
  private revision = -1;
  private readonly listeners = new Set<(what: StoreEvent) => void>();
  private sendTimer = 0;
  private putting = false;
  private again = false;
  private liveFlag = false;
  private stateTimer = 0;
  private expireTimer = 0;
  private readonly busyTimers = new Map<string, number>();
  private reading = 0;
  private view = { x: 60, y: 60, zoom: 1 };

  constructor() {
    events.on('graph', (e) => this.onEvent(e));
    docStore.onChange(() => {
      if (docStore.activeId !== this.docId && this.docId !== '') this.leave();
    });
  }

  onChange(fn: (what: StoreEvent) => void): () => void {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  private emit(what: StoreEvent): void {
    for (const fn of this.listeners) fn(what);
  }

  private base(): string { return `/api/docs/${enc(this.docId)}/graphs`; }

  private fail(err: unknown): void {
    this.error = err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err);
    this.emit('error');
  }

  async ensureCatalogue(force = false): Promise<void> {
    if (this.catalogue.length && !force) return;
    const res = await call<{ revision: number; nodes: Dict[] }>('GET', '/api/graph/catalogue');
    if (res.revision === this.revision && this.catalogue.length) return;
    this.revision = res.revision;
    this.catalogue = res.nodes.map(entryOf);
    this.entries = new Map(this.catalogue.map((e) => [e.id, e]));
  }

  async refreshList(): Promise<GraphListItem[]> {
    const id = docStore.activeId;
    if (!id) { this.list = []; this.emit('list'); return []; }
    const res = await call<{ graphs: Array<{ id: string; label: string }> }>('GET', `/api/docs/${enc(id)}/graphs`);
    this.list = res.graphs.map((g) => ({ id: g.id, name: g.label }));
    this.emit('list');
    return this.list;
  }

  private leave(): void {
    window.clearTimeout(this.sendTimer);
    this.rec = null;
    this.gid = '';
    this.docId = '';
    this.states.clear();
    this.list = [];
    this.emit('graph');
    this.emit('list');
    this.emit('open');
  }

  async enter(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    this.docId = id;
    try {
      await this.ensureCatalogue();
      const list = await this.refreshList();
      if (list.length === 0) return;
      const last = stored(`formCAD.graph.last.${id}`);
      const pick = list.find((g) => g.id === last) ?? list[0];
      await this.open(pick.id);
    } catch (e) { this.fail(e); }
  }

  async open(gid: string): Promise<void> {
    if (!this.docId) return;
    await this.flush();
    this.reading++;
    try {
      const res = await call<{ id: string; label: string; definition: Dict; readonly: boolean; problems: string[]; busy: boolean }>('GET', `${this.base()}/${enc(gid)}`);
      this.gid = res.id;
      this.rec = decodeGraph({ ...res.definition, id: res.id, name: res.label }, res.id);
      this.readonly = res.readonly;
      this.problems = res.problems ?? [];
      this.states.clear();
      persist(`formCAD.graph.last.${this.docId}`, res.id);
      this.view = this.loadView();
      this.emit('open');
      this.emit('graph');
      await this.pullState();
      const blank = this.rec.nodes.length > 0 && [...this.states.values()].every((s) => s.state === 'blank');
      if (blank && !res.busy) void this.solve(false);
    } catch (e) { this.fail(e); } finally { this.reading--; }
  }

  async create(name: string): Promise<void> {
    if (!this.docId) return;
    try {
      const res = await call<{ id: string }>('POST', this.base(), { name });
      await this.refreshList();
      await this.open(res.id);
    } catch (e) { this.fail(e); }
  }

  async remove(): Promise<void> {
    if (!this.docId || !this.gid) return;
    const gid = this.gid;
    try {
      await this.flush();
      await call('DELETE', `${this.base()}/${enc(gid)}`);
      this.rec = null;
      this.gid = '';
      this.states.clear();
      const list = await this.refreshList();
      this.emit('graph');
      if (list.length) await this.open(list[0].id);
      else this.emit('open');
    } catch (e) { this.fail(e); }
  }

  async rename(name: string): Promise<void> {
    if (!this.rec || !name.trim()) return;
    this.apply((r) => ({ ...r, name: name.trim() }));
    await this.flush();
    await this.refreshList();
  }

  apply(fn: (rec: GraphRecord) => GraphRecord, opts: { send?: boolean; live?: boolean } = {}): boolean {
    if (!this.rec || this.readonly) return false;
    const next = fn(this.rec);
    if (next === this.rec) return false;
    this.rec = next;
    this.emit('graph');
    if (opts.send !== false) this.schedule(opts.live === true);
    else this.pendingSend = true;
    return true;
  }

  private pendingSend = false;

  commit(): void {
    this.pendingSend = false;
    this.schedule(false);
  }

  private schedule(live: boolean): void {
    this.liveFlag = live;
    if (this.sendTimer) { if (live) return; window.clearTimeout(this.sendTimer); }
    this.sendTimer = window.setTimeout(() => { this.sendTimer = 0; void this.send(); }, live ? LIVE_MS : 0);
  }

  async flush(): Promise<void> {
    if (this.sendTimer) { window.clearTimeout(this.sendTimer); this.sendTimer = 0; await this.send(); }
    while (this.putting) await new Promise((r) => setTimeout(r, 10));
  }

  private async send(): Promise<void> {
    if (!this.rec || !this.gid) return;
    if (this.putting) { this.again = true; return; }
    this.putting = true;
    const rec = this.rec;
    const live = this.liveFlag;
    this.liveFlag = false;
    try {
      const definition = encodeGraph({ ...rec, extra: { ...rec.extra, view: { zoom: this.view.zoom, origin: [this.view.x, this.view.y] } } });
      const res = await call<{ expired: string[]; busy: boolean }>('PUT', `${this.base()}/${enc(this.gid)}`, { definition, label: rec.name, live, solve: true });
      this.setBusy(res.busy);
      window.clearTimeout(this.expireTimer);
      const expired = res.expired ?? [];
      if (expired.length && res.busy) {
        this.expireTimer = window.setTimeout(() => {
          if (!this.busy) return;
          for (const id of expired) this.states.set(id, blankState());
          this.emit('states');
        }, STALE_MS);
      } else if (expired.length) this.queueState();
    } catch (e) {
      this.fail(e);
      this.putting = false;
      this.again = false;
      await this.reload();
      return;
    }
    this.putting = false;
    if (this.again) { this.again = false; this.schedule(this.liveFlag); }
  }

  async reload(): Promise<void> {
    if (!this.docId || !this.gid) return;
    const gid = this.gid;
    try {
      const res = await call<{ id: string; label: string; definition: Dict }>('GET', `${this.base()}/${enc(gid)}`);
      this.rec = decodeGraph({ ...res.definition, id: res.id, name: res.label }, res.id);
      this.emit('graph');
      await this.pullState();
    } catch (e) { this.fail(e); }
  }

  private setBusy(b: boolean): void {
    if (b === this.busy) return;
    this.busy = b;
    this.emit('busy');
  }

  async solve(all: boolean): Promise<void> {
    if (!this.gid) return;
    await this.flush();
    try {
      const res = await call<{ busy: boolean }>('POST', `${this.base()}/${enc(this.gid)}/solve`, { all, wait: false });
      this.setBusy(res.busy);
    } catch (e) { this.fail(e); }
  }

  async cancel(): Promise<void> {
    if (!this.gid) return;
    try { await call('POST', `${this.base()}/${enc(this.gid)}/cancel`, {}); } catch (e) { this.fail(e); }
  }

  async pullState(): Promise<void> {
    if (!this.gid || !this.rec) return;
    const gid = this.gid;
    const res = await call<{ nodes: Record<string, Dict>; busy: boolean; error: string; report: { ms?: number } | null; problems: string[] }>('GET', `${this.base()}/${enc(gid)}/state?first=6`);
    if (gid !== this.gid || !this.rec) return;
    const enabled = new Map(this.rec.nodes.map((n) => [n.id, n.enabled]));
    const next = new Map<string, NodeState>();
    for (const [id, raw] of Object.entries(res.nodes ?? {})) next.set(id, decodeState(raw, enabled.get(id) !== false));
    let changed = next.size !== this.states.size;
    if (!changed) for (const [id, st] of next) { const old = this.states.get(id); if (!old || JSON.stringify(old) !== JSON.stringify(st)) { changed = true; break; } }
    if (changed) {
      const merged = new Map<string, NodeState>();
      for (const [id, st] of next) {
        const old = this.states.get(id);
        merged.set(id, old && JSON.stringify(old) === JSON.stringify(st) ? old : st);
      }
      this.states = merged;
      this.emit('states');
    }
    if (res.report && typeof res.report.ms === 'number') this.lastMs = res.report.ms;
    if (res.problems?.length) this.problems = res.problems;
    this.setBusy(res.busy);
    if (res.error) { this.error = res.error; this.emit('error'); }
  }

  private queueState(): void {
    window.clearTimeout(this.stateTimer);
    this.stateTimer = window.setTimeout(() => { void this.pullState().catch((e) => this.fail(e)); }, 30);
  }

  private onEvent(e: Dict): void {
    if (e.id !== this.docId || e.graph !== this.gid || !this.gid) return;
    const reason = String(e.reason ?? '');
    if (reason === 'node') {
      const id = String(e.node);
      window.clearTimeout(this.busyTimers.get(id));
      this.busyTimers.delete(id);
      if (e.phase === 'computing' && this.rec) {
        this.busyTimers.set(id, window.setTimeout(() => {
          this.busyTimers.delete(id);
          const old = this.states.get(id) ?? blankState();
          this.states.set(id, { ...old, state: 'busy' });
          this.emit('states');
        }, STALE_MS));
      }
    } else if (reason === 'start') {
      this.setBusy(true);
    } else if (reason === 'solved') {
      window.clearTimeout(this.expireTimer);
      for (const h of this.busyTimers.values()) window.clearTimeout(h);
      this.busyTimers.clear();
      if (typeof e.ms === 'number') this.lastMs = e.ms;
      this.setBusy(false);
      this.queueState();
    } else if (reason === 'definition') {
      if (this.putting || this.sendTimer || this.pendingSend) return;
      void this.syncDefinition();
    } else if (reason === 'error') {
      this.fail(String(e.message ?? 'The solve failed.'));
    }
  }

  private async syncDefinition(): Promise<void> {
    if (!this.docId || !this.gid || !this.rec) return;
    const gid = this.gid;
    try {
      const res = await call<{ id: string; label: string; definition: Dict }>('GET', `${this.base()}/${enc(gid)}`);
      if (gid !== this.gid || this.putting || this.sendTimer || this.pendingSend || !this.rec) return;
      const fresh = decodeGraph({ ...res.definition, id: res.id, name: res.label }, res.id);
      const mine = encodeGraph(this.rec);
      const theirs = encodeGraph(fresh);
      mine.view = undefined;
      theirs.view = undefined;
      if (JSON.stringify(mine) === JSON.stringify(theirs)) return;
      this.rec = reuse(this.rec, fresh);
      this.emit('graph');
      await this.pullState();
    } catch (err) { this.fail(err); }
  }

  treePage(node: string, port: string, page: number): Promise<TreePage> {
    return call<Dict>('GET', `${this.base()}/${enc(this.gid)}/tree/${enc(node)}/${enc(port)}?offset=${page * PAGE}&limit=${PAGE}`).then(decodeTreePage);
  }

  private viewKey(): string { return `formCAD.graph.view.${this.docId}.${this.gid}`; }

  private loadView(): { x: number; y: number; zoom: number } {
    try {
      const v = JSON.parse(stored(this.viewKey()) ?? 'null') as { x: number; y: number; zoom: number } | null;
      if (v && Number.isFinite(v.x) && Number.isFinite(v.y) && Number.isFinite(v.zoom)) return v;
    } catch { return { x: 60, y: 60, zoom: 1 }; }
    return { x: 60, y: 60, zoom: 1 };
  }

  viewOf(): { x: number; y: number; zoom: number } { return this.view; }

  setView(x: number, y: number, zoom: number): void {
    this.view = { x, y, zoom };
    if (this.gid) persist(this.viewKey(), JSON.stringify(this.view));
  }
}

function reuse(old: GraphRecord, fresh: GraphRecord): GraphRecord {
  const byId = new Map(old.nodes.map((x) => [x.id, x]));
  const nodes = fresh.nodes.map((n) => {
    const o = byId.get(n.id);
    return o && JSON.stringify(o) === JSON.stringify(n) ? o : n;
  });
  return { ...fresh, nodes };
}
