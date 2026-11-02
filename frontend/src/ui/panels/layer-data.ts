import { cad, type LayerListing, type LayerQuery } from '../../io/api-cad';
import { ApiError } from '../../io/api';
import { events } from '../../io/events';
import { docStore } from '../doc-store';
import { toast } from '../toast';

const text = (e: unknown): string => (e instanceof ApiError || e instanceof Error ? e.message : 'The engine did not answer');

export function skippedText(l: LayerListing): string[] {
  const out: string[] = [];
  for (const s of l.skipped ?? []) {
    if (typeof s === 'string') out.push(s);
    else if (s && typeof s === 'object') out.push([s.name, s.reason].filter(Boolean).join(': '));
  }
  return out.filter(Boolean);
}

export class LayerFeed {
  data: LayerListing | null = null;
  query: LayerQuery = {};
  private readonly listeners = new Set<() => void>();
  private active = false;
  private raf = 0;
  private seq = 0;
  private doc: string | null = null;

  constructor() {
    events.on('doc', (e) => { if (this.active && e.id === docStore.activeId) this.schedule(); });
    docStore.onChange(() => {
      if (docStore.activeId === this.doc) return;
      this.doc = docStore.activeId;
      this.data = null;
      this.emit();
      if (this.active) this.schedule();
    });
  }

  onChange(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  private emit(): void {
    for (const fn of this.listeners) fn();
  }

  setActive(on: boolean): void {
    if (this.active === on) return;
    this.active = on;
    if (on) this.schedule();
  }

  setQuery(q: LayerQuery): void {
    this.query = { ...this.query, ...q };
    this.schedule();
  }

  schedule(): void {
    if (this.raf) return;
    this.raf = requestAnimationFrame(() => { this.raf = 0; void this.load(); });
  }

  async load(): Promise<void> {
    const id = docStore.activeId;
    this.doc = id;
    if (!id) { this.data = null; this.emit(); return; }
    const n = ++this.seq;
    try {
      const l = await cad.layers(id, this.query);
      if (n !== this.seq) return;
      this.data = l;
      this.emit();
    } catch {
      return;
    }
  }

  async ops(ops: Array<Record<string, unknown>>): Promise<LayerListing | null> {
    const id = docStore.activeId;
    if (!id) return null;
    try {
      const l = await cad.layerOps(id, ops, this.query);
      const notes = skippedText(l);
      if (notes.length) toast(notes.join(' · '), 'error');
      this.seq++;
      this.schedule();
      return l;
    } catch (e) {
      toast(text(e), 'error');
      this.schedule();
      return null;
    }
  }
}

export const layerFeed = new LayerFeed();
export const managerFeed = new LayerFeed();
