import { ApiError } from '../io/api';
import { events } from '../io/events';
import { docStore } from '../ui/doc-store';
import { toast } from '../ui/toast';
import { part, type Feature, type PartTree, type TypeSchema } from './api';

export const messageOf = (e: unknown): string => (e instanceof ApiError || e instanceof Error ? e.message : 'The engine did not answer');

class PartStore {
  tree: PartTree | null = null;
  types = new Map<string, TypeSchema>();
  doc = '';
  selected: string | null = null;
  hover: string | null = null;
  private readonly listeners = new Set<() => void>();
  private timer = 0;
  private seq = 0;
  private typesDoc = '';

  constructor() {
    events.on('doc', (e) => { if (e.id === docStore.activeId) this.refresh(); });
    let last = docStore.activeId;
    docStore.onChange(() => {
      if (docStore.activeId === last) return;
      last = docStore.activeId;
      this.tree = null;
      this.selected = null;
      this.hover = null;
      this.emit();
      this.refresh(0);
    });
    this.refresh(0);
  }

  onChange(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  emit(): void {
    for (const fn of this.listeners) fn();
  }

  get features(): Feature[] { return this.tree?.features ?? []; }

  find(fid: string | null): Feature | undefined {
    return fid ? this.features.find((f) => f.id === fid) : undefined;
  }

  refresh(delay = 90): void {
    if (this.timer) return;
    this.timer = window.setTimeout(() => { this.timer = 0; void this.load(); }, delay);
  }

  async load(): Promise<void> {
    const id = docStore.activeId;
    const n = ++this.seq;
    if (!id) {
      if (this.tree) { this.tree = null; this.emit(); }
      return;
    }
    try {
      if (this.typesDoc !== id || this.types.size === 0) {
        const list = await part.types(id);
        this.types = new Map(list.map((t) => [t.type, t]));
        this.typesDoc = id;
      }
      const tree = await part.tree(id);
      if (n !== this.seq || id !== docStore.activeId) return;
      this.doc = id;
      if (this.tree && this.tree.rev === tree.rev && JSON.stringify(this.tree.features) === JSON.stringify(tree.features) && this.tree.rollback === tree.rollback) return;
      this.tree = tree;
      if (this.selected && !tree.features.some((f) => f.id === this.selected)) this.selected = null;
      this.emit();
    } catch {
      return;
    }
  }

  async run<T>(fn: (doc: string) => Promise<T>, quiet = false): Promise<T | null> {
    const id = docStore.activeId;
    if (!id) return null;
    try {
      const out = await fn(id);
      this.refresh(0);
      return out;
    } catch (e) {
      if (!quiet) toast(messageOf(e), 'error');
      this.refresh(0);
      return null;
    }
  }
}

export const partStore = new PartStore();
