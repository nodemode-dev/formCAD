import { events } from '../io/events';
import { docStore } from '../ui/doc-store';
import { docUrl, req, text } from '../u8/net';
import { gate, MODEL } from '../ui/panel-gate';
import { toast } from '../ui/toast';
import type { ResultLayer } from './result-layer';

export type Json = Record<string, unknown>;
export interface Rec { id: string; kind: string; name?: string; type?: string; [k: string]: unknown }
export interface Solver { type: string; label: string; options: unknown; order: number }
export interface MesherInfo { available?: boolean; version?: string; message?: string; installing?: boolean; progress?: number }
export interface ResultField { name: string; unit?: string; location?: string; components?: number; modes?: number }
export interface SimJob { job: string; study: string; state: string; phase: string; progress: number; message: string; mode: string }
export interface Probe { point: number[]; values: Array<[string, string]> }
export interface RampSpec { kind?: string; stops: Array<[number, string]>; min?: number | null; max?: number | null; symmetric?: boolean }
export interface DisplayPayload {
  field: string; unit: string; display_unit?: string; display_factor?: number; label: string; min: number; max: number; mean?: number; location?: string;
  fields?: ResultField[]; mode?: number;
  positions: number[]; deformed?: number[] | null; scale?: number; indices: number[]; values: number[];
  ramp: RampSpec; modes?: Array<{ index: number; frequency_hz?: number; load_factor?: number }>; summary?: Json;
}
export interface MeshPayload { positions: number[]; indices: number[]; nodes?: number; elements?: number; [k: string]: unknown }

const asObj = (v: unknown): Json | null => (v && typeof v === 'object' && !Array.isArray(v) ? v as Json : null);
const isRec = (v: unknown): v is Rec => { const o = asObj(v); return !!o && typeof o.id === 'string' && typeof o.kind === 'string'; };

function collect(raw: unknown, out: Map<string, Rec>, depth = 0): void {
  if (Array.isArray(raw)) { for (const r of raw) if (isRec(r)) out.set(r.id, r); return; }
  const o = asObj(raw);
  if (!o || depth > 2) return;
  for (const v of Object.values(o)) collect(v, out, depth + 1);
}

function solverList(raw: unknown): Solver[] {
  const rows: Solver[] = [];
  const add = (type: string, o: Json): void => { rows.push({ type, label: typeof o.label === 'string' ? o.label : type, options: o.options ?? null, order: typeof o.order === 'number' ? o.order : 100 }); };
  if (Array.isArray(raw)) for (const r of raw) { const o = asObj(r); if (o && typeof (o.type ?? o.key ?? o.id) === 'string') add(String(o.type ?? o.key ?? o.id), o); }
  else { const o = asObj(raw); if (o) for (const [k, v] of Object.entries(o)) add(k, asObj(v) ?? {}); }
  return rows.sort((a, b) => a.order - b.order);
}

const num = (v: unknown, d = 0): number => (typeof v === 'number' && Number.isFinite(v) ? v : d);
const ACTIVE = new Set(['queued', 'running', 'start', 'progress']);

class SimStore {
  records = new Map<string, Rec>();
  recordsDoc = '';
  solvers: Solver[] = [];
  mesher: MesherInfo = {};
  limits: Json = {};
  library: Json[] = [];
  studyId = '';
  recId = '';
  job: SimJob | null = null;
  meshInfo = new Map<string, Json>();
  results = new Map<string, Json>();
  layer: ResultLayer | null = null;
  error = '';
  loaded = false;
  private readonly subs = new Set<() => void>();
  private timer = 0;
  private poll = 0;
  private busy = false;
  private inflight: Promise<void> = Promise.resolve();
  private seq = 0;
  private libDoc = '';
  readonly overviewSeen: { raw: Json | null } = { raw: null };

  onChange(fn: () => void): void { this.subs.add(fn); }
  emit(): void { for (const f of this.subs) f(); }
  docId(): string | null { return docStore.activeId; }
  url(tail = ''): string { return docUrl(this.docId() ?? '', `sim${tail}`); }
  of(kind: string): Rec[] { return [...this.records.values()].filter((r) => r.kind === kind); }
  get(id: string): Rec | undefined { return this.records.get(id); }
  study(id = this.studyId): Rec | undefined { const r = this.records.get(id); return r?.kind === 'study' ? r : undefined; }
  solver(type: string): Solver | undefined { return this.solvers.find((s) => s.type === type); }
  ids(rec: Rec | undefined, key: string): string[] { const v = rec?.[key]; return Array.isArray(v) ? v.map(String) : []; }
  get running(): boolean { return !!this.job && ACTIVE.has(this.job.state); }

  switchDoc(): void {
    this.seq += 1;
    this.records = new Map();
    this.recordsDoc = '';
    this.studyId = '';
    this.recId = '';
    this.job = null;
    this.results.clear();
    this.meshInfo.clear();
    this.library = [];
    this.libDoc = '';
    this.layer?.clear();
    this.emit();
    this.schedule(0);
  }

  schedule(delay = 120): void {
    if (this.timer) return;
    this.timer = window.setTimeout(() => { this.timer = 0; void this.refresh(); }, delay);
  }

  refresh(): Promise<void> {
    if (this.busy) return this.inflight.then(() => this.refresh());
    this.inflight = this.fetchAll();
    return this.inflight;
  }

  private async fetchAll(): Promise<void> {
    if (!this.docId()) { this.records.clear(); this.studyId = ''; this.recId = ''; this.loaded = false; this.emit(); return; }
    this.busy = true;
    const seq = ++this.seq;
    const doc = this.docId() ?? '';
    try {
      const raw = await req<Json>('GET', this.url());
      if (seq !== this.seq || doc !== this.docId()) return;
      this.overviewSeen.raw = raw;
      const next = new Map<string, Rec>();
      collect(raw.records ?? raw.rows ?? raw, next);
      this.records = next;
      this.recordsDoc = doc;
      const s = solverList(raw.solvers);
      if (s.length) this.solvers = s;
      this.mesher = asObj(raw.mesher) ?? this.mesher;
      this.limits = asObj(raw.limits) ?? this.limits;
      if (this.studyId && !this.study()) this.studyId = '';
      if (!this.studyId) { const first = this.of('study')[0]; if (first) this.studyId = first.id; }
      if (this.recId && !this.records.has(this.recId)) this.recId = '';
      this.error = '';
      this.loaded = true;
    } catch (e) {
      this.error = text(e);
      this.loaded = true;
    } finally {
      this.busy = false;
      this.emit();
    }
  }

  async installMesher(): Promise<void> {
    const doc = this.docId();
    if (!doc || this.mesher.installing) return;
    try {
      this.mesher = asObj(await req<Json>('POST', this.url('/mesher/install'))) ?? this.mesher;
      this.emit();
      while (this.mesher.installing && doc === this.docId()) {
        await new Promise((done) => window.setTimeout(done, 1000));
        this.mesher = asObj(await req<Json>('GET', this.url('/status'))) ?? this.mesher;
        this.emit();
      }
    } catch (e) {
      toast(text(e), 'error');
    }
  }

  async loadLibrary(): Promise<void> {
    const id = this.docId();
    if (this.library.length || !id || this.libDoc === id) return;
    this.libDoc = id;
    try {
      const raw = await req<unknown>('GET', this.url('/materials/library'));
      const arr = Array.isArray(raw) ? raw : asObj(raw) ? (asObj(raw)?.materials ?? asObj(raw)?.library ?? asObj(raw)?.items ?? []) : [];
      this.library = (Array.isArray(arr) ? arr : []).filter((x): x is Json => !!asObj(x));
      this.emit();
    } catch { return; }
  }

  select(studyId: string, recId = ''): void {
    if (this.studyId === studyId && this.recId === recId) return;
    this.studyId = studyId;
    this.recId = recId;
    this.emit();
  }

  async create(kind: string, fields: Json): Promise<Rec | null> {
    try {
      const r = await req<Json>('POST', this.url('/records'), { kind, ...fields });
      const rec = (asObj(r.record) ?? asObj(r.row) ?? r) as Json;
      await this.refresh();
      return typeof rec.id === 'string' ? this.records.get(rec.id) ?? ({ ...rec, kind } as Rec) : null;
    } catch (e) { toast(text(e), 'error'); return null; }
  }

  async update(id: string, fields: Json): Promise<boolean> {
    try { await req('PUT', this.url(`/records/${encodeURIComponent(id)}`), fields); await this.refresh(); return true; } catch (e) { toast(text(e), 'error'); return false; }
  }

  async remove(id: string): Promise<void> {
    try { await req('DELETE', this.url(`/records/${encodeURIComponent(id)}`)); if (this.recId === id) this.recId = ''; await this.refresh(); } catch (e) { toast(text(e), 'error'); }
  }

  async mesh(studyId: string): Promise<boolean> { return this.start(studyId, 'mesh'); }

  async meshDisplay(studyId: string): Promise<MeshPayload | null> {
    try { return await req<MeshPayload>('GET', this.url(`/studies/${encodeURIComponent(studyId)}/mesh/display`)); } catch (e) { toast(text(e), 'error'); return null; }
  }

  async faces(studyId: string): Promise<Json[]> {
    try { const r = await req<unknown>('GET', this.url(`/studies/${encodeURIComponent(studyId)}/faces`)); const o = asObj(r); const a = Array.isArray(r) ? r : o && Array.isArray(o.faces) ? o.faces : []; return a as Json[]; } catch { return []; }
  }

  async run(studyId: string): Promise<boolean> { return this.start(studyId, 'run'); }

  topo(studyId: string): boolean { const t = String(this.study(studyId)?.type ?? ''); return t === 'topology' || t === 'shape'; }
  private fam(studyId: string): string { return this.topo(studyId) ? 'topo' : 'sim'; }
  private furl(studyId: string, tail: string): string { return docUrl(this.docId() ?? '', `${this.fam(studyId)}${tail}`); }

  private async start(studyId: string, mode: string): Promise<boolean> {
    try {
      const verb = this.topo(studyId) && mode === 'run' && this.study(studyId)?.type === 'shape' ? 'shape' : mode;
      const r = await req<Json>('POST', this.furl(studyId, `/studies/${encodeURIComponent(studyId)}/${verb}`), {});
      const id = typeof r.job === 'string' ? r.job : String(asObj(r.job)?.job ?? r.id ?? '');
      if (!id) return false;
      this.job = { job: id, study: studyId, state: 'running', phase: '', progress: 0, message: '', mode };
      this.emit();
      this.watch(id);
      return true;
    } catch (e) { toast(text(e), 'error'); return false; }
  }

  async cancel(): Promise<void> {
    const j = this.job;
    if (!j) return;
    try { await req('POST', this.furl(j.study, `/jobs/${encodeURIComponent(j.job)}/cancel`)); } catch (e) { toast(text(e), 'error'); }
  }

  private take(raw: Json): void {
    const cur = this.job;
    const j = asObj(raw.job) ?? raw;
    const prog = j.progress;
    const f = typeof prog === 'number' ? prog : asObj(prog) ? num(asObj(prog)?.fraction) : cur?.progress ?? 0;
    this.job = {
      job: String(j.job ?? j.id ?? cur?.job ?? ''), study: String(j.study ?? cur?.study ?? ''), state: String(j.state ?? cur?.state ?? ''),
      phase: String(j.phase ?? cur?.phase ?? ''), progress: f, message: String(j.message ?? j.error ?? cur?.message ?? ''),
      mode: String(j.mode ?? cur?.mode ?? ''),
    };
    const res = asObj(j.result);
    const mesh = asObj(asObj(res?.summary)?.mesh);
    if (mesh && this.job.study) this.meshInfo.set(this.job.study, mesh);
  }

  private watch(id: string): void {
    window.clearInterval(this.poll);
    this.poll = window.setInterval(() => {
      void req<Json>('GET', this.furl(this.job?.study ?? '', `/jobs/${encodeURIComponent(id)}`)).then((j) => {
        if (this.job?.job !== id) return;
        this.take(j);
        this.finish(id);
      }).catch(() => undefined);
    }, 400);
  }

  private finish(id: string): void {
    this.emit();
    if (this.job && !ACTIVE.has(this.job.state)) {
      window.clearInterval(this.poll);
      this.results.delete(this.job.study);
      this.schedule(0);
      void id;
    }
  }

  onEvent(e: Json): void {
    if (e.id !== this.docId() || e.kind === 'generative') return;
    if (typeof e.job === 'string' && (this.job?.job === e.job || !this.job)) {
      this.take(e);
      if (!this.job?.study && typeof e.study === 'string') this.job = { ...(this.job as SimJob), study: e.study };
      this.finish(e.job);
    }
  }

  async result(studyId: string, force = false): Promise<Json | null> {
    if (!force && this.results.has(studyId)) return this.results.get(studyId) ?? null;
    try {
      const r = await req<Json>('GET', this.furl(studyId, `/studies/${encodeURIComponent(studyId)}/result`));
      if (this.topo(studyId)) {
        const sum = asObj(r.summary) ?? {};
        const hist = asObj(r.history);
        this.results.set(studyId, { result: { fields: [{ name: 'stress', unit: 'MPa', location: 'node', components: 1, modes: 0 }], summary: { ...sum, iterations_logged: Array.isArray(hist?.rows) ? (hist?.rows as unknown[]).length : 0 } }, history: Array.isArray(hist?.rows) ? hist?.rows : [] });
        return this.results.get(studyId) ?? null;
      }
      this.results.set(studyId, r);
      return r;
    } catch { return null; }
  }

  async display(studyId: string, q: { field: string; mode: number; ramp: string; scale: string }): Promise<DisplayPayload | null> {
    if (this.topo(studyId)) {
      try {
        const r = await req<Json>('GET', this.furl(studyId, `/studies/${encodeURIComponent(studyId)}/result/display?field=stress`));
        const lim = typeof r.limit === 'number' ? r.limit : null;
        return {
          field: 'stress', unit: String(r.unit ?? 'MPa'), label: 'Von Mises stress of the outcome', min: Number(r.min ?? 0), max: lim !== null ? Math.max(Number(r.max ?? 0), lim) : Number(r.max ?? 1),
          positions: r.positions as number[], indices: r.indices as number[], values: r.values as number[], deformed: null, scale: 1,
          ramp: { kind: 'gradient', stops: [[0, '#1a365d'], [0.35, '#2c7a7b'], [0.7, '#d69e2e'], [1, '#f7fafc']] }, summary: asObj(r.summary) ?? {},
        };
      } catch (e) { toast(text(e), 'error'); return null; }
    }
    const p = new URLSearchParams({ field: q.field, mode: String(q.mode), scale: q.scale || 'auto', ramp: q.ramp });
    try { return await req<DisplayPayload>('GET', this.url(`/studies/${encodeURIComponent(studyId)}/result/display?${p.toString()}`)); } catch (e) { toast(text(e), 'error'); return null; }
  }

  async probe(studyId: string, at: number[], mode: number): Promise<Json | null> {
    try {
      const r = await req<Json>('POST', this.url(`/studies/${encodeURIComponent(studyId)}/result/probe`), { points: [at], mode });
      const list = Array.isArray(r.probes) ? r.probes as Json[] : [];
      return list[0] ?? null;
    } catch (e) { toast(text(e), 'error'); return null; }
  }

  async report(studyId: string, path: string, format: string): Promise<Json | null> {
    try { return await req<Json>('POST', this.url(`/studies/${encodeURIComponent(studyId)}/report`), { path, format }); } catch (e) { toast(text(e), 'error'); return null; }
  }
}

export const sim = new SimStore();

const simGate = gate(['sim', 'simresult', 'simcalc', 'gen'], MODEL, () => sim.schedule());
events.on('doc', (e) => { if (e.id === docStore.activeId && simGate()) sim.schedule(); });
let seenDoc = docStore.activeId;
docStore.onChange(() => {
  if (docStore.activeId === seenDoc) return;
  seenDoc = docStore.activeId;
  sim.switchDoc();
});
events.on('simjob', (e) => { sim.onEvent(e as Json); });
events.on('topojob', (e) => { sim.onEvent(e as Json); });
