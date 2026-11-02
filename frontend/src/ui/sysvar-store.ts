import { api, ApiError } from '../io/api';
import { events } from '../io/events';
import { toast } from './toast';

export class SysvarStore {
  ready = false;
  private readonly values = new Map<string, unknown>();
  private readonly listeners = new Set<() => void>();

  constructor() {
    events.on('sysvar', (e) => {
      if (typeof e.name !== 'string') return;
      this.values.set(e.name.toUpperCase(), e.value);
      this.emit();
    });
    events.onState((s) => { if (s === 'open') void this.load(); });
  }

  onChange(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  private emit(): void {
    for (const fn of this.listeners) fn();
  }

  async load(): Promise<void> {
    try {
      const { vars } = await api.sysvars();
      for (const v of vars) this.values.set(v.name.toUpperCase(), v.value);
      this.ready = true;
    } catch {
      this.ready = false;
    }
    this.emit();
  }

  get(name: string): unknown {
    return this.values.get(name.toUpperCase());
  }

  num(name: string, fallback: number): number {
    const v = this.values.get(name.toUpperCase());
    const n = typeof v === 'number' ? v : typeof v === 'string' ? Number(v) : typeof v === 'boolean' ? Number(v) : NaN;
    return Number.isFinite(n) ? n : fallback;
  }

  text(name: string, fallback = ''): string {
    const v = this.values.get(name.toUpperCase());
    return typeof v === 'string' ? v : typeof v === 'number' ? String(v) : fallback;
  }

  async set(name: string, value: unknown): Promise<boolean> {
    try {
      const r = await api.setSysvar(name, value);
      this.values.set(name.toUpperCase(), r.value);
      this.emit();
      return true;
    } catch (e) {
      toast(e instanceof ApiError || e instanceof Error ? e.message : 'The engine did not answer', 'error');
      return false;
    }
  }
}

export const sysvars = new SysvarStore();

export interface DraftToggle {
  id: string;
  label: string;
  short: string;
  icon: string;
  keys?: string[];
  name: string;
  fallback: number;
  on: (v: number) => boolean;
  flip: (v: number) => number;
}

const bit = (mask: number): Pick<DraftToggle, 'on' | 'flip'> => ({ on: (v) => (v & mask) !== 0, flip: (v) => v ^ mask });
const flag: Pick<DraftToggle, 'on' | 'flip'> = { on: (v) => v !== 0, flip: (v) => (v ? 0 : 1) };

export const DRAFT_TOGGLES: readonly DraftToggle[] = [
  { id: 'toggle-grid', label: 'Grid', short: 'Grid', icon: 'grid', keys: ['F7'], name: 'GRIDMODE', fallback: 1, ...flag },
  { id: 'toggle-snap', label: 'Snap Mode', short: 'Snap', icon: 'snap', keys: ['F9'], name: 'SNAPMODE', fallback: 0, ...flag },
  { id: 'toggle-ortho', label: 'Ortho Mode', short: 'Ortho', icon: 'ortho', keys: ['F8'], name: 'ORTHOMODE', fallback: 0, ...flag },
  { id: 'toggle-polar', label: 'Polar Tracking', short: 'Polar', icon: 'polar', keys: ['F10'], name: 'AUTOSNAP', fallback: 61, ...bit(8) },
  { id: 'toggle-osnap', label: 'Object Snap', short: 'Osnap', icon: 'osnap', keys: ['F3'], name: 'OSMODE', fallback: 4133, on: (v) => (v & 16384) === 0 && (v & 16383) !== 0, flip: (v) => ((v & 16384) === 0 ? v | 16384 : (v & 16383) === 0 ? 4133 : v & ~16384) },
  { id: 'toggle-otrack', label: 'Object Snap Tracking', short: 'Otrack', icon: 'otrack', keys: ['F11'], name: 'AUTOSNAP', fallback: 61, ...bit(16) },
  { id: 'toggle-dynin', label: 'Dynamic Input', short: 'Dyn', icon: 'dynInput', keys: ['F12'], name: 'DYNMODE', fallback: 1, ...flag },
  { id: 'toggle-lineweight', label: 'Show/Hide Lineweight', short: 'LWT', icon: 'lineweight', name: 'LWDISPLAY', fallback: 0, ...flag },
  { id: 'toggle-transparency', label: 'Show/Hide Transparency', short: 'Trans', icon: 'pfTransparency', name: 'TRANSPARENCYDISPLAY', fallback: 1, ...flag },
  { id: 'toggle-cycling', label: 'Selection Cycling', short: 'Cycle', icon: 'pfSelection', name: 'SELECTIONCYCLING', fallback: -2, on: (v) => v > 0, flip: (v) => (v === 0 ? 2 : -v) },
  { id: 'toggle-iso', label: 'Isometric Drafting', short: 'Iso', icon: 'cube', name: 'SNAPSTYL', fallback: 0, ...flag },
];
