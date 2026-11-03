import { events } from '../io/events';
import { docStore } from '../ui/doc-store';
import { camUrl, docCam, guard, req, type Json } from './kit';
import type { FieldSpec } from './fields';
import type { Flat, Wcs } from './toolpath-layer';
import type { ToolpathLayer } from './toolpath-layer';

export interface OpState { status: 'never' | 'ok' | 'stale' | 'failed' | 'empty'; sig?: string; message?: string; warnings?: string[]; summary?: { moves?: number; cut_length?: number; rapid_length?: number; time_s?: number; min?: number[]; max?: number[]; z_min?: number; wcs?: Wcs } }
export interface Setup { id: string; label?: string; name?: string; machine: string; wcs: Json & Wcs & { slot?: number; origin_on?: string }; stock: Json; bodies: unknown[]; fixtures: unknown[]; ops: string[]; safe: { clearance?: number; retract?: number; feed?: number } }
export interface Op { id: string; label?: string; name?: string; type: string; setup: string; tool: number; enabled: boolean; geometry: Json; params: Json; feeds: Json; heights: Json; state: OpState }
export interface OpType { kind: string; label: string; group: string; tool_kinds?: string[]; fields: FieldSpec[]; geometry?: string[] }
export interface LibTool { id?: string; number: number; name: string; kind: string; diameter: number; flutes?: number; flute_length?: number; overall_length?: number; shank_diameter?: number; corner_radius?: number; tip_angle?: number; taper_angle?: number; stickout?: number; length_offset?: number; diameter_offset?: number; rpm_max?: number; coolant?: string; holder?: { name?: string; profile?: number[][]; collet_length?: number; gauge_length?: number }; cutting?: Record<string, { vc?: number; fz?: number; plunge_factor?: number; ramp_factor?: number }>; notes?: string; [k: string]: unknown }
export interface PostInfo { id: string; name: string; extension?: string; description?: string; shipped?: boolean; caps?: Json }
export interface MachineInfo { id: string; name: string; kind: string; shipped?: boolean }
export interface CamJob { id?: string; job?: string; state: string; progress?: number | { fraction?: number }; phase?: string; message?: string; result?: Json; error?: string }

export const labelOf = (r: { label?: string; name?: string; id: string }): string => r.label || r.name || r.id;
export const toolName = (tl: LibTool): string => String(typeof tl.name_label === 'string' && tl.name_label ? tl.name_label : tl.name);
export const frac =(p: CamJob['progress']): number => (typeof p === 'number' ? p : p && typeof p === 'object' ? Number(p.fraction ?? 0) : 0);

const arr = <T>(v: unknown, key: string): T[] => (Array.isArray(v) ? v as T[] : v && typeof v === 'object' && Array.isArray((v as Json)[key]) ? (v as Json)[key] as T[] : []);

class CamStore {
  setups: Setup[] = [];
  ops: Op[] = [];
  docTools: LibTool[] = [];
  registry: OpType[] = [];
  library: LibTool[] = [];
  posts: PostInfo[] = [];
  machines: MachineInfo[] = [];
  limits: Json = {};
  setupId = '';
  opId = '';
  error = '';
  layer: ToolpathLayer | null = null;
  private readonly shown = new Map<string, string>();
  private readonly subs = new Set<() => void>();
  private timer = 0;
  private busy = false;
  private again = false;
  private loadedGlobal = false;
  private autoDoc = '';
  private seq = 0;

  onChange(fn: () => void): void { this.subs.add(fn); }
  private emit(): void { for (const f of this.subs) f(); }
  id(): string | null { return docStore.activeId; }
  setup(id = this.setupId): Setup | undefined { return this.setups.find((s) => s.id === id); }
  op(id = this.opId): Op | undefined { return this.ops.find((o) => o.id === id); }
  opsOf(sid = this.setupId): Op[] {
    const s = this.setup(sid);
    const by = new Map(this.ops.map((o) => [o.id, o]));
    const ordered = (s?.ops ?? []).map((i) => by.get(i)).filter((o): o is Op => !!o);
    const rest = this.ops.filter((o) => o.setup === sid && !ordered.includes(o));
    return [...ordered, ...rest];
  }
  wcsOf(sid: string): Wcs | null {
    const hit = this.opsOf(sid).find((o) => o.state?.summary?.wcs);
    return hit?.state.summary?.wcs ?? this.setup(sid)?.wcs ?? null;
  }
  type(kind: string): OpType | undefined { return this.registry.find((r) => r.kind === kind); }
  tool(n: number): LibTool | undefined { return this.docTools.find((t) => Number(t.number) === Number(n)); }

  select(setupId: string, opId = ''): void {
    if (this.setupId === setupId && this.opId === opId) return;
    this.setupId = setupId;
    this.opId = opId;
    this.layer?.select(opId);
    this.emit();
    this.showOp(opId);
  }

  schedule(delay = 150): void {
    if (this.timer) return;
    this.timer = window.setTimeout(() => { this.timer = 0; void this.refresh(); }, delay);
  }

  async loadGlobal(force = false): Promise<void> {
    if (this.loadedGlobal && !force) return;
    this.loadedGlobal = true;
    const [r, l, p, m, lim] = await Promise.all([
      req<unknown>('GET', camUrl('/ops')).catch(() => null),
      req<unknown>('GET', camUrl('/tools')).catch(() => null),
      req<unknown>('GET', camUrl('/posts')).catch(() => null),
      req<unknown>('GET', camUrl('/machines')).catch(() => null),
      req<Json>('GET', camUrl('/limits')).catch(() => null),
    ]);
    if (r) this.registry = arr<OpType>(r, 'ops').length ? arr<OpType>(r, 'ops') : arr<OpType>(r, 'kinds');
    if (l) this.library = arr<LibTool>(l, 'tools');
    if (p) this.posts = arr<PostInfo>(p, 'posts');
    if (m) this.machines = arr<MachineInfo>(m, 'machines');
    if (lim) this.limits = lim;
    this.emit();
  }

  async loadLibrary(): Promise<void> {
    const l = await req<unknown>('GET', camUrl('/tools')).catch(() => null);
    if (l) { this.library = arr<LibTool>(l, 'tools'); this.emit(); }
  }

  async refresh(): Promise<void> {
    if (this.busy) { this.again = true; return; }
    const id = this.id();
    if (!id) {
      if (this.setups.length || this.ops.length) { this.setups = []; this.ops = []; this.docTools = []; this.layer?.clear(); this.shown.clear(); this.emit(); }
      return;
    }
    this.busy = true;
    try {
      do {
        this.again = false;
        await this.loadGlobal();
        const d = await req<Json>('GET', docCam()).catch((e: unknown) => { this.error = e instanceof Error ? e.message : ''; return null; });
        if (id !== this.id()) break;
        if (d) {
          this.setups = arr<Setup>(d, 'setups');
          this.ops = arr<Op>(d, 'ops');
          this.docTools = arr<LibTool>(d, 'tools');
          this.error = '';
          if (!this.setup() ) { this.setupId = this.setups[0]?.id ?? ''; this.opId = ''; }
          if (this.opId && !this.op()) this.opId = '';
          this.syncStale();
          this.emit();
          if (this.autoDoc !== id && this.layer) {
            this.autoDoc = id;
            this.layer.clear();
            this.shown.clear();
            for (const s of this.setups) void this.showSetup(s.id);
          }
        }
      } while (this.again);
    } finally {
      this.busy = false;
    }
  }

  private syncStale(): void {
    for (const o of this.ops) {
      const stale = o.state?.status === 'stale';
      this.layer?.setStale(o.id, stale);
      if (!this.shown.has(o.id)) continue;
      if (o.state?.status === 'never' || o.state?.status === 'failed' || o.state?.status === 'empty') { this.layer?.drop(o.id); this.shown.delete(o.id); }
      else if (o.state?.sig && this.shown.get(o.id) !== o.state.sig && o.state.status === 'ok') void this.showOp(o.id, true);
    }
    for (const k of Array.from(this.shown.keys())) if (!this.op(k)) { this.layer?.drop(k); this.shown.delete(k); }
  }

  async showOp(oid: string, force = false): Promise<void> {
    const o = this.op(oid);
    if (!o || !this.layer) return;
    const st = o.state;
    if (!st || st.status === 'never' || st.status === 'failed' || st.status === 'empty') return;
    const sig = st.sig ?? String(st.summary?.moves ?? '');
    if (!force && this.shown.get(oid) === sig && this.layer.has(oid)) return;
    const seq = ++this.seq;
    const got = await req<{ segments?: Flat }>('GET', docCam(`/ops/${encodeURIComponent(oid)}/toolpath?flat=1&tol=0.05`)).catch(() => null);
    const flat = got?.segments;
    if (!flat || seq > this.seq + 100) return;
    this.layer.set(oid, { cut: flat.cut ?? [], rapid: flat.rapid ?? [] }, this.wcsOf(o.setup), st.status === 'stale');
    this.shown.set(oid, sig);
    this.layer.select(this.opId);
  }

  async showSetup(sid: string): Promise<void> {
    for (const o of this.opsOf(sid)) if (o.state?.status === 'ok' || o.state?.status === 'stale') await this.showOp(o.id);
  }

  forget(oid: string): void { this.shown.delete(oid); this.layer?.drop(oid); }

  async put<T = Json>(method: 'POST' | 'PUT' | 'DELETE', tail: string, body?: unknown): Promise<T | null> {
    const r = await guard(() => req<T>(method, docCam(tail), body));
    this.schedule(0);
    return r;
  }
}

export const cam = new CamStore();

events.on('doc', (e) => { if (e.id === docStore.activeId) cam.schedule(); });
events.on('cam', (e) => { if (e.id === docStore.activeId && e.reason !== 'simulate') cam.schedule(); });
docStore.onChange(() => cam.schedule(50));
