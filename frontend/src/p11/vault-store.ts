import { events } from '../io/events';
import { docStore } from '../ui/doc-store';
import { req, vault, type Json } from './kit';

export type LifeState = 'wip' | 'review' | 'released' | 'obsolete';
export interface Branch { name: string; head: string; state: string; ts: number; revision?: string }
export interface Lock { doc: string; owner: string; machine: string; since: number; base: string; path: string; note: string }
export interface VDoc {
  id: string; name: string; kind: string; created: number; default_branch: string; branches: Branch[]; tags: Branch[]; head: string; head_state: string; head_revision: string;
  lock: Lock | null; paths: string[]; versions: number; latest_ts: number; merging?: boolean;
}
export interface VVersion {
  id: string; short: string; doc: string; parents: string[]; author: string; ts: number; message: string; size: number; members: number; identical: boolean;
  container: string; sha256: string; state: LifeState | string; revision: string; branches: string[]; tags: string[]; lane?: number;
}
export interface VaultRec { id: string; name: string; folder: string; default: boolean; created: number; docs: number; versions: number; objects: number; bytes: number; author: string; machine: string }
export interface Binding { path: string; doc: string; branch: string; base: string; hash: string; edit: boolean; ts: number; status: 'clean' | 'modified' | 'missing' | 'behind' | string }
export interface Conflict {
  id: string; kind: string; entity: string; name: string; path: string; base: unknown; ours: unknown; theirs: unknown; suggested: string; choice: unknown; value?: unknown;
}
export interface MergeRec { doc: string; branch: string; ours: string; theirs: string; base: string; status: string; conflicts: Conflict[]; merged: Json; unresolved: number; started?: number; author?: string }
export interface Comment {
  id: number; doc: string; version: string; entity: string; anchor: Json; author: string; ts: number; parent: number | null; status: 'open' | 'resolved'; body: string;
  markup: string | null; camera: Json | null; attached: boolean; orphan_note: string;
}
export interface DiffRec { added?: unknown[]; removed?: unknown[]; changed?: unknown[]; [k: string]: unknown }

export const arr = <T>(r: unknown, key: string): T[] => {
  if (Array.isArray(r)) return r as T[];
  const v = r && typeof r === 'object' ? (r as Json)[key] : undefined;
  return Array.isArray(v) ? v as T[] : [];
};

class VaultStore {
  vid = 'default';
  vaults: VaultRec[] = [];
  docs: VDoc[] = [];
  docId = '';
  nodes: VVersion[] = [];
  lanes = 1;
  total = 0;
  heads: Array<{ name: string; version: string }> = [];
  selected = '';
  compare = '';
  merge: MergeRec | null = null;
  comments: Comment[] = [];
  commentStatus = '';
  whereUsed: unknown[] = [];
  uses: unknown[] = [];
  audit: Array<Json> = [];
  binding: { binding: Binding | null; lock: Lock | null } | null = null;
  ready = false;
  active = false;
  lastError = '';
  private readonly subs = new Set<() => void>();
  private busy = false;
  private again = false;
  private timer = 0;

  onChange(fn: () => void): void { this.subs.add(fn); }
  emit(): void { for (const f of this.subs) f(); }
  doc(): VDoc | undefined { return this.docs.find((d) => d.id === this.docId); }
  node(id: string): VVersion | undefined { return this.nodes.find((n) => n.id === id); }
  base(tail = ''): string { return vault(`/${encodeURIComponent(this.vid)}${tail}`); }

  schedule(delay = 120): void {
    if (this.timer) return;
    this.timer = window.setTimeout(() => { this.timer = 0; void this.refresh(); }, delay);
  }

  async refresh(): Promise<void> {
    if (this.busy) { this.again = true; return; }
    this.busy = true;
    try {
      do {
        this.again = false;
        this.lastError = '';
        const list = await req<unknown>('GET', vault('')).catch((e: unknown) => { this.lastError = e instanceof Error ? e.message : ''; return null; });
        this.ready = list !== null;
        if (list) {
          this.vaults = arr<VaultRec>(list, 'vaults');
          if (!this.vaults.some((v) => v.id === this.vid) && this.vaults[0]) this.vid = this.vaults.find((v) => v.default)?.id ?? this.vaults[0].id;
          const docs = await req<unknown>('GET', this.base('/docs')).catch(() => null);
          this.docs = docs ? arr<VDoc>(docs, 'docs') : [];
          if (!this.docs.some((d) => d.id === this.docId)) this.docId = this.boundDoc() || this.docs[0]?.id || '';
          await this.history();
          await this.side();
        }
        await this.bound();
        this.emit();
      } while (this.again);
    } finally {
      this.busy = false;
    }
  }

  boundDoc(): string {
    const b = this.binding?.binding;
    return b && this.docs.some((d) => d.id === b.doc) ? b.doc : '';
  }

  async bound(): Promise<void> {
    const id = docStore.activeId;
    if (!id) { this.binding = null; return; }
    this.binding = await req<{ binding: Binding | null; lock: Lock | null }>('GET', `/api/docs/${encodeURIComponent(id)}/vault`).catch(() => null);
  }

  async history(): Promise<void> {
    if (!this.docId) { this.nodes = []; this.heads = []; this.total = 0; this.lanes = 1; this.merge = null; return; }
    const g = await req<{ nodes: VVersion[]; heads: Array<{ name: string; version: string }>; total: number; lanes: number }>('GET', this.base(`/docs/${this.docId}/graph?limit=200`)).catch(() => null);
    if (g) { this.nodes = g.nodes; this.heads = g.heads; this.total = g.total; this.lanes = g.lanes; }
    if (!this.node(this.selected)) this.selected = this.nodes[0]?.id ?? '';
    if (this.compare && !this.node(this.compare)) this.compare = '';
    this.merge = this.doc()?.merging ? await req<MergeRec | null>('GET', this.base(`/docs/${this.docId}/merge`)).then((m) => (m && typeof m === 'object' && 'status' in m ? m : null)).catch(() => null) : null;
  }

  async side(): Promise<void> {
    if (!this.docId) { this.comments = []; this.whereUsed = []; this.uses = []; this.audit = []; return; }
    const pick = this.node(this.selected) ? this.selected : '';
    const sel = pick ? `version=${pick}&` : '';
    const [c, w, u, a] = await Promise.all([
      req<unknown>('GET', this.base(`/docs/${this.docId}/comments?${sel}${this.commentStatus ? `status=${this.commentStatus}` : ''}`)).catch(() => null),
      req<unknown>('GET', this.base(`/docs/${this.docId}/whereused?scope=heads`)).catch(() => null),
      req<unknown>('GET', this.base(`/docs/${this.docId}/uses${pick ? `?version=${pick}` : ''}`)).catch(() => null),
      req<unknown>('GET', this.base(`/audit?doc=${this.docId}&limit=30`)).catch(() => null),
    ]);
    this.comments = c ? arr<Comment>(c, 'comments') : [];
    this.whereUsed = w ? arr<unknown>(w, 'used_by').concat(arr<unknown>(w, 'items'), arr<unknown>(w, 'whereused')) : [];
    this.uses = u ? arr<unknown>(u, 'uses').concat(arr<unknown>(u, 'items')) : [];
    this.audit = a ? arr<Json>(a, 'audit').concat(arr<Json>(a, 'entries'), arr<Json>(a, 'items')) : [];
  }

  async pickDoc(id: string): Promise<void> {
    this.docId = id;
    this.selected = '';
    this.compare = '';
    this.nodes = [];
    await this.history();
    await this.side();
    this.emit();
  }

  async pickVersion(id: string): Promise<void> {
    this.selected = id;
    await this.side();
    this.emit();
  }
}

export const vstore = new VaultStore();

events.on('doc', (e) => { if (vstore.active && e.id === docStore.activeId) vstore.schedule(400); });
docStore.onChange(() => { if (vstore.active) vstore.schedule(60); });
