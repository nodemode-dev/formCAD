import { api, type PropertiesPayload } from '../../io/api';
import { events } from '../../io/events';
import { docStore } from '../doc-store';
import { toast } from '../toast';
import { failure } from './engine-run';
import type { Props, RowDef } from './props-kinds';
import { selection } from './selection-bus';

class PropertyStore {
  payload: PropertiesPayload | null = null;
  doc: string | null = null;
  rev = -1;
  private seq = 0;
  private queued = false;
  private readonly listeners = new Set<() => void>();

  constructor() {
    selection.onChange(() => this.queue());
    events.on('doc', (e) => {
      if (e.id === docStore.activeId && selection.handles.length && e.rev !== this.rev) this.queue();
    });
  }

  onChange(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  private emit(): void {
    for (const fn of this.listeners) fn();
  }

  queue(): void {
    if (this.queued) return;
    this.queued = true;
    requestAnimationFrame(() => { this.queued = false; void this.load(); });
  }

  async load(): Promise<void> {
    const doc = selection.doc ?? docStore.activeId;
    const handles = selection.handles;
    const mine = ++this.seq;
    if (!doc || !handles.length) {
      if (this.payload !== null) { this.payload = null; this.doc = doc; this.emit(); }
      return;
    }
    try {
      const next = await api.properties(doc, handles);
      if (mine !== this.seq) return;
      this.payload = next;
      this.doc = doc;
      this.rev = next.rev ?? -1;
    } catch {
      if (mine !== this.seq) return;
      this.payload = null;
    }
    this.emit();
  }

  editRow(p: PropertiesPayload | null, scope: string, def: RowDef, value: unknown): string | null {
    if (!p) return null;
    const props: Props = scope === 'general' ? p.general : p.kinds[scope]?.props ?? {};
    const handles = scope === 'general' ? p.handles : p.kinds[scope]?.handles ?? [];
    const out = def.write ? def.write(value, props) : null;
    if (typeof out === 'string') return out;
    if (out && handles.length) void this.apply(handles, out);
    return null;
  }

  async apply(handles: number[], changes: Record<string, unknown>): Promise<boolean> {
    const doc = this.doc ?? docStore.activeId;
    if (!doc || !handles.length) return false;
    try {
      const r = await api.setProperties(doc, handles, changes);
      if (r.locked > 0) toast(`${r.locked} ${r.locked === 1 ? 'object is' : 'objects are'} on a locked layer and ${r.locked === 1 ? 'was' : 'were'} not changed.`, 'info');
      this.rev = r.rev;
      this.queue();
      return true;
    } catch (e) {
      toast(failure(e), 'error');
      this.queue();
      return false;
    }
  }
}

export const properties = new PropertyStore();
