import { events } from '../io/events';
import { partStore, messageOf } from '../part/store';
import { docStore } from '../ui/doc-store';
import { toast } from '../ui/toast';
import { sheet, type BendRecord, type CutList, type FlatData, type FlatState } from './api';

class SheetStore {
  isSheet = false;
  state: FlatState | null = null;
  flat: FlatData | null = null;
  cut: CutList | null = null;
  bends: BendRecord[] = [];
  error = '';
  busy = false;
  private readonly listeners = new Set<() => void>();
  private timer = 0;
  private seq = 0;
  private doc = '';

  constructor() {
    events.on('doc', (e) => { if (e.id === docStore.activeId) this.refresh(); });
    partStore.onChange(() => this.refresh());
    docStore.onChange(() => {
      if (docStore.activeId === this.doc) return;
      this.doc = docStore.activeId ?? '';
      this.reset();
      this.refresh(0);
    });
  }

  onChange(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  private emit(): void {
    for (const fn of this.listeners) fn();
  }

  private reset(): void {
    this.isSheet = false;
    this.state = null;
    this.flat = null;
    this.cut = null;
    this.bends = [];
    this.error = '';
    this.emit();
  }

  get on(): boolean { return !!this.state?.on && this.isSheet; }

  rootFeature(): { id: string; type: string; params: Record<string, unknown> } | null {
    for (const f of partStore.features) {
      if ((f.type === 'base_flange' || f.type === 'convert_sheet') && !f.suppressed) return { id: f.id, type: f.type, params: f.params };
    }
    return null;
  }

  refresh(delay = 140): void {
    if (this.timer) return;
    this.timer = window.setTimeout(() => { this.timer = 0; void this.load(); }, delay);
  }

  async load(): Promise<void> {
    const id = docStore.activeId;
    const n = ++this.seq;
    if (!id) { if (this.isSheet) this.reset(); return; }
    const sheetFeatures = partStore.features.some((f) => f.group === 'sheetmetal' && !f.suppressed);
    if (!sheetFeatures) {
      if (this.isSheet || this.state) this.reset();
      return;
    }
    let state: FlatState | null = this.state;
    let flat: FlatData | null = null;
    let error = '';
    try {
      const r = await sheet.flat(id, true);
      state = r.state;
      flat = r.flat ?? null;
    } catch (e) {
      error = messageOf(e);
      try { state = (await sheet.flat(id, false)).state; } catch { state = this.state; }
    }
    let cut: CutList | null = null;
    try { cut = await sheet.props(id); } catch (e) { if (!error) error = messageOf(e); }
    let bends: BendRecord[] = this.bends;
    try {
      const b = await sheet.bends(id);
      bends = Array.isArray(b) ? b : b.bends;
    } catch {
      bends = [];
    }
    if (n !== this.seq || id !== docStore.activeId) return;
    const same = this.isSheet && JSON.stringify(this.state) === JSON.stringify(state) && JSON.stringify(this.flat) === JSON.stringify(flat) && JSON.stringify(this.cut) === JSON.stringify(cut) && JSON.stringify(this.bends) === JSON.stringify(bends) && this.error === error;
    this.isSheet = true;
    this.state = state;
    this.flat = flat;
    this.cut = cut;
    this.bends = bends;
    this.error = error;
    if (!same) this.emit();
  }

  async set(changes: Record<string, unknown>): Promise<boolean> {
    const id = docStore.activeId;
    if (!id || this.busy) return false;
    this.busy = true;
    try {
      const r = await sheet.setFlat(id, changes);
      this.state = r.state;
      this.flat = r.flat ?? null;
      this.error = '';
      this.emit();
      this.refresh(0);
      return true;
    } catch (e) {
      toast(messageOf(e), 'error');
      this.refresh(0);
      return false;
    } finally {
      this.busy = false;
    }
  }

  toggle(): Promise<boolean> {
    return this.set({ on: !this.on });
  }
}

export const sheetStore = new SheetStore();
