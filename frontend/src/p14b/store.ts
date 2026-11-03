import { events } from '../io/events';
import { docStore } from '../ui/doc-store';
import { toast } from '../ui/toast';
import { docUrl, req, text } from '../u8/net';

export type Json = Record<string, any>;
export type Tab = 'sch' | 'pcb' | 'b3d';

export interface PcbJob { state: string; phase: string; progress: number; message: string; command: string }

const ACTIVE = new Set(['start', 'progress', 'running', 'queued']);

class EcadStore {
  docId = '';
  rev = -1;
  sum: Json | null = null;
  sheetId = '';
  scene: Json | null = null;
  erc: Json | null = null;
  net: Json | null = null;
  pcb: Json | null = null;
  fills: Json[] = [];
  rat: Json[] = [];
  drc: Json | null = null;
  drcRev = -1;
  link: Json | null = null;
  b3d: Json | null = null;
  rules: Json | null = null;
  symbols: Json[] = [];
  footprints: Json[] = [];
  job: PcbJob | null = null;
  error = '';
  loaded = false;
  tab: Tab = 'sch';
  private readonly subs = new Set<() => void>();
  private timer = 0;
  private seq = 0;
  private busy: Promise<void> = Promise.resolve();
  private running = false;

  onChange(fn: () => void): void { this.subs.add(fn); }
  emit(): void { for (const f of this.subs) f(); }

  isEcad(): boolean { return docStore.current()?.kind === 'ecad'; }
  url(tail = ''): string { return docUrl(this.docId, tail); }
  get idle(): boolean { return this.pending === 0 && !this.running && !this.timer; }
  get jobRunning(): boolean { return !!this.job && ACTIVE.has(this.job.state); }

  switchDoc(): void {
    const id = docStore.activeId ?? '';
    if (id === this.docId) {
      if (!this.loaded && this.isEcad()) this.schedule(0);
      return;
    }
    this.docId = id;
    this.rev = -1;
    this.sum = null; this.scene = null; this.erc = null; this.net = null; this.pcb = null;
    this.fills = []; this.rat = []; this.drc = null; this.link = null; this.b3d = null; this.rules = null;
    this.sheetId = ''; this.job = null; this.loaded = false; this.error = '';
    this.emit();
    if (this.isEcad()) this.schedule(0);
  }

  schedule(delay = 100): void {
    if (this.timer || !this.isEcad()) return;
    this.timer = window.setTimeout(() => { this.timer = 0; void this.refresh(); }, delay);
  }

  refresh(): Promise<void> {
    if (this.running) return this.busy.then(() => this.refresh());
    this.running = true;
    this.busy = this.fetchAll().finally(() => { this.running = false; });
    return this.busy;
  }

  private async fetchAll(): Promise<void> {
    if (!this.docId || !this.isEcad()) return;
    const seq = ++this.seq;
    const id = this.docId;
    try {
      const sum = await req<Json>('GET', this.url('ecad'));
      if (seq !== this.seq || id !== this.docId) return;
      const sheets = (sum.sheets ?? []) as Json[];
      if (!sheets.some((s) => s.id === this.sheetId)) this.sheetId = String(sum.root ?? sheets[0]?.id ?? '');
      const [scene, erc, net, pcb, fills, rat] = await Promise.all([
        req<Json>('GET', this.url(`ecad/sheets/${encodeURIComponent(this.sheetId)}/scene`)),
        req<Json>('GET', this.url('ecad/erc')),
        req<Json>('GET', this.url('ecad/netlist')),
        req<Json>('GET', this.url('pcb')),
        req<Json>('GET', this.url('pcb/zones/fill')).catch(() => ({ fills: [] })),
        req<Json>('GET', this.url('pcb/ratsnest')).catch(() => ({ ratsnest: [] })),
      ]);
      if (seq !== this.seq || id !== this.docId) return;
      if (scene.rev !== sum.rev || net.rev !== undefined && net.rev !== sum.rev) { this.schedule(0); return; }
      this.sum = sum;
      this.scene = scene; this.erc = erc; this.net = net; this.pcb = pcb;
      this.fills = (fills.fills ?? []) as Json[];
      this.rat = (rat.ratsnest ?? []) as Json[];
      this.rev = Number(sum.rev ?? 0);
      void this.fetchLink(id);
      this.error = '';
      this.loaded = true;
    } catch (e) {
      this.error = text(e);
      this.loaded = true;
    }
    this.emit();
  }

  async fetchLink(id: string): Promise<void> {
    try {
      const l = await req<Json>('GET', this.url('ecad/link'));
      if (id === this.docId) { this.link = l; this.emit(); }
    } catch { if (id === this.docId && this.link) { this.link = null; this.emit(); } }
  }

  async loadLibraries(): Promise<void> {
    if (!this.docId || this.symbols.length) return;
    try {
      const [s, f] = await Promise.all([req<Json>('GET', this.url('ecad/library/symbols')), req<Json>('GET', this.url('ecad/library/footprints'))]);
      this.symbols = (s.symbols ?? []) as Json[];
      this.footprints = (f.footprints ?? []) as Json[];
      this.emit();
    } catch (e) { this.error = text(e); }
  }

  async setSheet(id: string): Promise<void> {
    if (id === this.sheetId) return;
    this.sheetId = id;
    this.scene = null;
    this.emit();
    await this.refresh();
  }

  pending = 0;

  private async restoreActive(prev: string): Promise<void> {
    for (let i = 0; i < 16; i++) {
      await new Promise((r) => window.setTimeout(r, 250));
      if (docStore.activeId !== prev) { docStore.switchTo(prev); return; }
    }
  }

  async call<T = Json>(method: string, tail: string, body?: unknown, quiet = false): Promise<T | null> {
    this.pending++;
    if (tail.startsWith('ecad/link')) void this.restoreActive(this.docId);
    try {
      const r = await req<T>(method, this.url(tail), body);
      await this.refresh();
      return r;
    } catch (e) {
      if (!quiet) toast(text(e), 'error');
      await this.refresh();
      return null;
    } finally {
      this.pending--;
    }
  }

  async ops(list: Json[]): Promise<Json | null> {
    const withSheet = list.map((o) => (o.sheet === undefined && o.op !== 'add_sheet' && o.op !== 'annotate' && o.op !== 'set_design' && o.op !== 'set_erc' ? { ...o, sheet: this.sheetId } : o));
    return this.call('POST', 'ecad/batch', { ops: withSheet });
  }

  async undo(): Promise<void> { this.pending++; try { await req('POST', this.url('undo')); } catch (e) { toast(text(e), 'error'); } await this.refresh(); this.pending--; }
  async redo(): Promise<void> { this.pending++; try { await req('POST', this.url('redo')); } catch (e) { toast(text(e), 'error'); } await this.refresh(); this.pending--; }

  async runDrc(): Promise<Json | null> {
    try {
      const r = await req<Json>('POST', this.url('pcb/drc'));
      this.drc = r;
      this.drcRev = this.rev;
      this.emit();
      await this.refresh();
      this.drcRev = this.rev;
      this.emit();
      return r;
    } catch (e) { toast(text(e), 'error'); return null; }
  }

  async route(body: Json): Promise<Json | null> {
    this.job = { state: 'start', phase: 'Starting', progress: 0, message: '', command: 'route' };
    this.emit();
    try {
      const r = await req<Json>('POST', this.url('pcb/route'), body);
      this.job = null;
      await this.refresh();
      this.emit();
      return r;
    } catch (e) {
      this.job = null;
      toast(text(e), 'error');
      await this.refresh();
      this.emit();
      return null;
    }
  }

  async cancel(): Promise<void> { try { await req('POST', this.url('pcb/cancel')); } catch (e) { toast(text(e), 'error'); } }

  onJob(e: { id: string; state?: string; phase?: string; progress?: number; message?: string; command?: string }): void {
    if (e.id !== this.docId) return;
    const state = e.state ?? 'progress';
    if (state === 'end' || state === 'done' || state === 'error' || state === 'cancelled') {
      if (this.job) this.job = { ...this.job, state: 'end', progress: 1 };
      this.emit();
      return;
    }
    if (!this.job && e.command === 'drc') return;
    this.job = { state, phase: e.phase ?? '', progress: e.progress ?? 0, message: e.message ?? '', command: e.command ?? 'route' };
    this.emit();
  }

  net_of(refdes: string, pin: string): string {
    for (const n of (this.pcb?.netlist?.nets ?? []) as Json[]) for (const p of n.pins as string[][]) if (p[0] === refdes && p[1] === pin) return String(n.name);
    return '';
  }
}

export const ec = new EcadStore();

events.on('doc', (e) => { if (e.id === docStore.activeId) ec.schedule(); });
events.on('pcbjob', (e) => { ec.onJob(e); });
docStore.onChange(() => ec.switchDoc());
