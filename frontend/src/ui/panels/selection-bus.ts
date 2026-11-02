import { api } from '../../io/api';
import { events } from '../../io/events';
import { docStore } from '../doc-store';

export interface SelectionState { doc: string | null; handles: number[] }

const same = (a: number[], b: number[]): boolean => a.length === b.length && a.every((h, i) => h === b[i]);
const numbers = (list: Array<string | number>): number[] => list.map(Number).filter((n) => Number.isFinite(n));

class SelectionBus {
  doc: string | null = null;
  handles: number[] = [];
  commandActive = false;
  private readonly listeners = new Set<(s: SelectionState) => void>();
  private readonly commandListeners = new Set<() => void>();

  constructor() {
    document.addEventListener('formcad:selection', (e) => {
      const d = (e as CustomEvent<{ doc: string | null; handles: Array<string | number> }>).detail;
      this.take(d.doc, numbers(d.handles));
    });
    for (const name of ['formcad:command-state', 'formcad:cmdline-applied']) {
      document.addEventListener(name, (e) => {
        const d = (e as CustomEvent<{ doc: string; state: { active: boolean } }>).detail;
        if (d.doc !== docStore.activeId) return;
        if (d.state.active !== this.commandActive) {
          this.commandActive = d.state.active;
          for (const fn of this.commandListeners) fn();
        }
      });
    }
    events.on('doc', (e) => {
      if (e.id !== docStore.activeId || e.reason !== 'selection') return;
      void api.getSelection(e.id).then((r) => {
        if (docStore.activeId !== e.id) return;
        const next = numbers(r.handles);
        if (!same(next, this.handles)) document.dispatchEvent(new CustomEvent('formcad:set-selection', { detail: { handles: next, commit: false } }));
      }).catch(() => undefined);
    });
  }

  onChange(fn: (s: SelectionState) => void): () => void {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  onCommand(fn: () => void): () => void {
    this.commandListeners.add(fn);
    return () => { this.commandListeners.delete(fn); };
  }

  select(handles: number[], mode: 'set' | 'add' | 'remove' = 'set'): void {
    document.dispatchEvent(new CustomEvent('formcad:set-selection', { detail: { handles, mode } }));
  }

  private take(doc: string | null, handles: number[]): void {
    if (doc === this.doc && same(handles, this.handles)) return;
    this.doc = doc;
    this.handles = handles;
    for (const fn of this.listeners) fn({ doc, handles });
  }
}

export const selection = new SelectionBus();
