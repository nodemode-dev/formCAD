import { events } from '../io/events';
import { docStore } from '../ui/doc-store';
import { layoutState } from '../ui/layout-state';
import { selection } from '../ui/panels/selection-bus';
import { toast } from '../ui/toast';
import { dv, messageOf, type ViewInfo } from './api';

class DrawStore {
  views: ViewInfo[] = [];
  projection: 'first' | 'third' = 'third';
  doc: string | null = null;
  layout = '';
  private readonly listeners = new Set<() => void>();
  private timer = 0;
  private seq = 0;
  private lastKey = '';

  constructor() {
    events.on('doc', (e) => { if (e.id === docStore.activeId) this.schedule(); });
    docStore.onChange(() => this.schedule());
    layoutState.onChange(() => this.schedule());
    selection.onChange(() => this.emit());
    this.schedule();
  }

  onChange(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  private emit(): void {
    for (const fn of this.listeners) fn();
  }

  get inLayout(): boolean {
    return layoutState.inLayout && !!docStore.activeId;
  }

  get selected(): ViewInfo | null {
    for (const h of selection.handles) {
      const v = this.views.find((x) => x.handle === h);
      if (v) return v;
    }
    return null;
  }

  find(handle: number): ViewInfo | undefined {
    return this.views.find((v) => v.handle === handle);
  }

  byName(name: string): ViewInfo | undefined {
    return this.views.find((v) => v.name === name);
  }

  stale(): ViewInfo[] {
    return this.views.filter((v) => v.state.status === 'stale');
  }

  at(x: number, y: number): ViewInfo | null {
    let best: ViewInfo | null = null;
    let area = Infinity;
    for (const v of this.views) {
      const [x0, y0, x1, y1] = v.bounds;
      if (x < x0 || x > x1 || y < y0 || y > y1) continue;
      const a = (x1 - x0) * (y1 - y0);
      if (a < area) { area = a; best = v; }
    }
    return best;
  }

  schedule(): void {
    if (this.timer) return;
    this.timer = window.setTimeout(() => { this.timer = 0; void this.load(); }, 40);
  }

  async load(): Promise<void> {
    const id = docStore.activeId;
    const layout = layoutState.layout;
    if (!id) {
      if (this.views.length || this.doc) { this.views = []; this.doc = null; this.layout = ''; this.lastKey = ''; this.emit(); }
      return;
    }
    const n = ++this.seq;
    try {
      const r = await dv.list(id, layout);
      if (n !== this.seq || id !== docStore.activeId) return;
      const key = JSON.stringify([id, layout, r.views.map((v) => [v.handle, v.name, v.label, v.scaleText, v.position, v.bounds, v.state.status, v.state.sig, v.show, v.mode, v.auto, v.detail, v.section, v.broken, v.crop]), r.projection[layout]]);
      this.doc = id;
      this.layout = layout;
      this.projection = r.projection[layout] ?? 'third';
      if (key === this.lastKey) return;
      this.lastKey = key;
      this.views = r.views;
      this.emit();
    } catch {
      return;
    }
  }

  async run<T>(fn: (id: string) => Promise<T>): Promise<T | null> {
    const id = docStore.activeId;
    if (!id) return null;
    try {
      const r = await fn(id);
      void docStore.refresh();
      await this.load();
      return r;
    } catch (e) {
      toast(messageOf(e), 'error');
      return null;
    }
  }
}

export const drawStore = new DrawStore();
