import { events } from '../io/events';
import { docStore } from '../ui/doc-store';
import { DOCS, gate } from '../ui/panel-gate';
import { docUrl, req, type Json } from './kit';

export class Feed {
  data: Record<string, Json | null> = {};
  active = false;
  loaded = false;
  private readonly subs = new Set<() => void>();
  private timer = 0;
  private seq = 0;
  private doc = '';
  private readonly allow: () => boolean;

  constructor(private readonly family: string, private readonly paths: Record<string, string>) {
    this.allow = gate([family], DOCS, () => this.schedule(0));
    events.on('doc', (e) => { if (e.id === docStore.activeId) this.schedule(); });
    docStore.onChange(() => { this.data = {}; this.loaded = false; this.doc = ''; this.emit(); this.schedule(0); });
  }

  onChange(fn: () => void): void { this.subs.add(fn); }
  emit(): void { for (const f of this.subs) f(); }
  docId(): string { return docStore.activeId ?? ''; }
  url(tail = ''): string { return docUrl(this.docId(), `${this.family}${tail}`); }

  setActive(on: boolean): void { this.active = on; if (on) this.schedule(0); }

  schedule(delay = 150): void {
    if (!this.active || this.timer) return;
    this.timer = window.setTimeout(() => { this.timer = 0; if (this.allow()) void this.refresh(); }, delay);
  }

  async refresh(): Promise<void> {
    const id = this.docId();
    if (!id) { this.data = {}; this.loaded = false; this.emit(); return; }
    const seq = ++this.seq;
    const next: Record<string, Json | null> = {};
    await Promise.all(Object.entries(this.paths).map(async ([k, tail]) => {
      try { next[k] = await req<Json>('GET', this.url(tail)); } catch { next[k] = null; }
    }));
    if (seq !== this.seq || id !== this.docId()) return;
    this.data = next;
    this.loaded = true;
    this.doc = id;
    this.emit();
  }

  get(k: string): Json {
    return this.data[k] ?? {};
  }

  has(): boolean { return this.doc === this.docId() && this.loaded; }

  async post<T = Json>(tail: string, body: unknown): Promise<T> {
    const r = await req<T>('POST', this.url(tail), body);
    await this.refresh();
    return r;
  }

  async put<T = Json>(tail: string, body: unknown): Promise<T> {
    const r = await req<T>('PUT', this.url(tail), body);
    await this.refresh();
    return r;
  }

  async del<T = Json>(tail: string): Promise<T> {
    const r = await req<T>('DELETE', this.url(tail));
    await this.refresh();
    return r;
  }
}

export const harnessFeed = new Feed('harness', { list: '', report: '/report' });
export const pipeFeed = new Feed('pipes', { list: '', cutlist: '/cutlist' });
export const schemFeed = new Feed('schem', { list: '', check: '/check', wirelist: '/wirelist' });
