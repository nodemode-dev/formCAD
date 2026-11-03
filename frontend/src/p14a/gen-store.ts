import { events } from '../io/events';
import { docStore } from '../ui/doc-store';
import { toast } from '../ui/toast';
import { sim, type DisplayPayload, type Rec } from '../p13/sim-store';
import { docUrl, req, text, type Json } from './kit';

export interface Outcome {
  id: string; method: string; label: string; params: Json; mass_kg: number; voxel_mass_kg?: number; volume_fraction: number; safety_factor: number; safety_factor_p99?: number;
  meets_safety_factor: boolean; manufacturable: boolean; peak_stress_mpa: number; p99_stress_mpa?: number; max_displacement_mm?: number; mesh_triangles?: number;
  manufacturing?: { violations?: Record<string, number>; holes?: number }; notes?: string[]; thumbnail_png_base64?: string; seconds?: number;
}
export interface Outcomes {
  study: string; result: string; objective: string; required_safety_factor: number; stress_limit_mpa: number; baseline: Json; outcomes: Outcome[]; notes: string[]; seconds?: number; safety_factor_basis?: string;
}
export interface GenJobState { job: string; study: string; state: string; phase: string; progress: number; message: string }

const ACTIVE = new Set(['queued', 'running', 'start', 'progress']);
const RAMP: Array<[number, string]> = [[0, '#2b6cb0'], [0.5, '#ecc94b'], [1, '#e53e3e']];

class GenStore {
  studyId = '';
  data: Outcomes | null = null;
  dataFor = '';
  outcomeId = '';
  job: GenJobState | null = null;
  preview: Json | null = null;
  limits: Json | null = null;
  shown = '';
  private readonly subs = new Set<() => void>();
  private poll = 0;
  private seq = 0;

  onChange(fn: () => void): void { this.subs.add(fn); }
  emit(): void { for (const f of this.subs) f(); }
  docId(): string { return docStore.activeId ?? ''; }
  url(tail = ''): string { return docUrl(this.docId(), `gen${tail}`); }
  studies(): Rec[] { return sim.of('study').filter((s) => s.type === 'generative'); }
  study(id = this.studyId): Rec | undefined { const s = sim.get(id); return s?.kind === 'study' && s.type === 'generative' ? s : undefined; }
  get running(): boolean { return !!this.job && ACTIVE.has(this.job.state); }
  outcome(): Outcome | undefined { return this.data?.outcomes.find((o) => o.id === this.outcomeId); }

  select(id: string): void {
    if (this.studyId === id) return;
    this.studyId = id;
    this.data = null;
    this.dataFor = '';
    this.outcomeId = '';
    this.preview = null;
    this.hide();
    this.emit();
    void this.loadOutcomes();
  }

  reset(): void {
    this.studyId = ''; this.data = null; this.dataFor = ''; this.outcomeId = ''; this.job = null; this.preview = null; this.hide();
    window.clearInterval(this.poll);
    this.emit();
  }

  async loadLimits(): Promise<void> {
    if (this.limits || !this.docId()) return;
    try { this.limits = await req<Json>('GET', this.url('/limits')); this.emit(); } catch { return; }
  }

  async loadOutcomes(): Promise<void> {
    const id = this.studyId;
    const s = this.study(id);
    if (!id || !s || !s.result) { this.data = null; this.dataFor = ''; this.emit(); return; }
    const seq = ++this.seq;
    try {
      const d = await req<Outcomes>('GET', this.url(`/studies/${encodeURIComponent(id)}/outcomes?thumbnails=true`));
      if (seq !== this.seq || id !== this.studyId) return;
      this.data = d;
      this.dataFor = String(s.result);
      if (!d.outcomes.some((o) => o.id === this.outcomeId)) this.outcomeId = '';
    } catch { if (seq === this.seq) { this.data = null; this.dataFor = ''; } }
    this.emit();
  }

  async loadPreview(): Promise<void> {
    if (!this.studyId) return;
    try { this.preview = await req<Json>('GET', this.url(`/studies/${encodeURIComponent(this.studyId)}/preview`)); } catch (e) { this.preview = { error: text(e) }; }
    this.emit();
  }

  async run(options?: Json): Promise<boolean> {
    if (!this.studyId) return false;
    try {
      const r = await req<Json>('POST', this.url(`/studies/${encodeURIComponent(this.studyId)}/run`), options ? { options } : {});
      const j = (r.job ?? {}) as Json;
      const id = String(j.job ?? '');
      if (!id) return false;
      this.job = { job: id, study: this.studyId, state: 'running', phase: '', progress: 0, message: '' };
      this.emit();
      this.watch(id);
      return true;
    } catch (e) { toast(text(e), 'error'); return false; }
  }

  async cancel(): Promise<void> {
    const j = this.job;
    if (!j) return;
    try { await req('POST', this.url(`/jobs/${encodeURIComponent(j.job)}/cancel`)); } catch (e) { toast(text(e), 'error'); }
  }

  private take(raw: Json): void {
    const j = (raw.job && typeof raw.job === 'object' ? raw.job as Json : raw);
    const cur = this.job;
    this.job = {
      job: String(j.job ?? cur?.job ?? ''), study: String(j.study ?? cur?.study ?? this.studyId), state: String(j.state ?? cur?.state ?? ''),
      phase: String(j.phase ?? cur?.phase ?? ''), progress: typeof j.progress === 'number' ? j.progress : cur?.progress ?? 0, message: String(j.message ?? cur?.message ?? ''),
    };
  }

  private watch(id: string): void {
    window.clearInterval(this.poll);
    this.poll = window.setInterval(() => {
      void req<Json>('GET', this.url(`/jobs/${encodeURIComponent(id)}`)).then((j) => { if (this.job?.job === id) { this.take(j); this.settle(); } }).catch(() => undefined);
    }, 700);
  }

  private settle(): void {
    this.emit();
    if (this.job && !ACTIVE.has(this.job.state)) {
      window.clearInterval(this.poll);
      void sim.refresh().then(() => this.loadOutcomes());
    }
  }

  onEvent(e: Json): void {
    if (e.id !== this.docId() || e.kind !== 'generative') return;
    if (typeof e.job === 'string' && (!this.job || this.job.job === e.job)) {
      if (!this.job) this.job = { job: e.job, study: String(e.study ?? this.studyId), state: 'running', phase: '', progress: 0, message: '' };
      this.take(e);
      this.settle();
    }
  }

  async show(oid: string): Promise<void> {
    const layer = sim.layer;
    if (!layer || !this.studyId) return;
    this.outcomeId = oid;
    this.emit();
    try {
      const d = await req<Json>('GET', this.url(`/studies/${encodeURIComponent(this.studyId)}/outcomes/${encodeURIComponent(oid)}/display?smooth=6&sigma=0.6&max_triangles=40000`));
      if (this.outcomeId !== oid) return;
      const lo = Number(d.min), hi = Number(d.max);
      const payload: DisplayPayload = {
        field: 'von_mises', unit: 'MPa', label: 'von Mises', min: lo, max: hi, positions: d.positions as number[], indices: d.indices as number[], values: d.values as number[],
        ramp: { kind: 'gradient', stops: RAMP, min: lo, max: typeof d.limit === 'number' ? Math.max(hi, d.limit) : hi },
      };
      layer.setData(payload);
      layer.setShown(true);
      this.shown = `${this.studyId}:${oid}`;
      this.emit();
    } catch (e) { toast(text(e), 'error'); }
  }

  hide(): void { if (this.shown) { sim.layer?.setShown(false); this.shown = ''; } }
}

export const gen = new GenStore();

events.on('topojob', (e) => { gen.onEvent(e as Json); });
let seenDoc = docStore.activeId;
docStore.onChange(() => { if (docStore.activeId !== seenDoc) { seenDoc = docStore.activeId; gen.reset(); } });
sim.onChange(() => {
  const list = gen.studies();
  if (gen.studyId && !gen.study()) { gen.reset(); }
  if (!gen.studyId && list[0]) gen.select(list[0].id);
  else if (gen.studyId) {
    const r = String(gen.study()?.result ?? '');
    if (r && r !== gen.dataFor && !gen.running) void gen.loadOutcomes();
  }
});
