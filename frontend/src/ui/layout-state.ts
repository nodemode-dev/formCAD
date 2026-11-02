import { drawingCanvas } from '../canvas/mount';
import { ApiError } from '../io/api';
import { cad, type LayoutSummary, type ViewportInfo } from '../io/api-cad';
import { events } from '../io/events';
import { docStore } from './doc-store';
import { toast } from './toast';

const message = (e: unknown): string => (e instanceof ApiError || e instanceof Error ? e.message : 'The engine did not answer');

class LayoutState {
  summary: LayoutSummary | null = null;
  viewports: ViewportInfo[] = [];
  private readonly listeners = new Set<() => void>();
  private raf = 0;
  private seq = 0;
  private spaceKey = '';

  constructor() {
    events.on('doc', (e) => { if (e.id === docStore.activeId) this.schedule(); });
    let last = docStore.activeId;
    docStore.onChange(() => {
      if (docStore.activeId === last) return;
      last = docStore.activeId;
      this.summary = null;
      this.viewports = [];
      this.emit();
      this.schedule();
    });
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
    return !!this.summary && this.summary.tab.startsWith('layout:');
  }

  get layout(): string {
    return this.inLayout ? this.summary?.current ?? '' : '';
  }

  schedule(): void {
    if (this.raf) return;
    this.raf = requestAnimationFrame(() => { this.raf = 0; void this.load(); });
  }

  async load(): Promise<void> {
    const id = docStore.activeId;
    if (!id) { this.summary = null; this.viewports = []; this.emit(); return; }
    const n = ++this.seq;
    try {
      const s = await cad.layouts(id);
      let vps: ViewportInfo[] = [];
      if (s.tab.startsWith('layout:')) vps = (await cad.viewports(id, s.current)).viewports;
      if (n !== this.seq || id !== docStore.activeId) return;
      this.summary = s;
      this.viewports = vps;
      this.syncCanvas();
      this.emit();
    } catch {
      return;
    }
  }

  private syncCanvas(): void {
    const s = this.summary;
    const c = drawingCanvas();
    if (!s || !c) return;
    const space = s.tab.startsWith('layout:') ? s.current : s.tab;
    const key = `${docStore.activeId}|${space}`;
    if (key === this.spaceKey) return;
    this.spaceKey = key;
    c.setSpace(space);
  }

  async run(fn: (id: string) => Promise<unknown>): Promise<boolean> {
    const id = docStore.activeId;
    if (!id) return false;
    try {
      await fn(id);
      this.schedule();
      void docStore.refresh();
      return true;
    } catch (e) {
      toast(message(e), 'error');
      this.schedule();
      return false;
    }
  }

  go(name: string): Promise<boolean> {
    return this.run((id) => cad.space(id, { tab: name }));
  }

  action(body: Record<string, unknown>): Promise<boolean> {
    return this.run((id) => cad.layoutAction(id, body));
  }

  target(): ViewportInfo | undefined {
    const active = this.summary?.viewport ?? 0;
    return this.viewports.find((v) => v.h === active) ?? this.viewports[0];
  }
}

export const layoutState = new LayoutState();
