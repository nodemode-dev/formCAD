import type { BoolReport, NakedResult } from './nurbs-api';

export interface DiagState {
  source: 'boolean' | 'naked' | 'none';
  report: BoolReport | null;
  naked: NakedResult | null;
  highlight: boolean;
  checkOnly: boolean;
  stamp: number;
}

class DiagStore {
  state: DiagState = { source: 'none', report: null, naked: null, highlight: true, checkOnly: false, stamp: 0 };
  private readonly listeners = new Set<(s: DiagState) => void>();

  onChange(fn: (s: DiagState) => void): () => void {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  private emit(): void {
    for (const fn of this.listeners) fn(this.state);
  }

  setBoolean(report: BoolReport, checkOnly: boolean): void {
    this.state = { ...this.state, source: 'boolean', report, naked: null, checkOnly, stamp: this.state.stamp + 1 };
    this.emit();
  }

  setNaked(naked: NakedResult): void {
    this.state = { ...this.state, source: 'naked', report: null, naked, checkOnly: false, stamp: this.state.stamp + 1 };
    this.emit();
  }

  setHighlight(on: boolean): void {
    if (on === this.state.highlight) return;
    this.state = { ...this.state, highlight: on };
    this.emit();
  }

  clear(): void {
    this.state = { ...this.state, source: 'none', report: null, naked: null, stamp: this.state.stamp + 1 };
    this.emit();
  }
}

export const diag = new DiagStore();
