import { auto, type ScriptInfo } from '../../io/api-auto';
import { events } from '../../io/events';
import { docStore } from '../doc-store';

export interface AutoSnapshot {
  script: ScriptInfo | null;
  recording: boolean;
  recordName: string;
  steps: number;
}

const EMPTY: AutoSnapshot = { script: null, recording: false, recordName: '', steps: 0 };

class Watcher {
  snap: AutoSnapshot = EMPTY;
  private readonly fns = new Set<(s: AutoSnapshot) => void>();
  private timer = 0;
  private poll = 0;
  private seq = 0;
  private started = false;

  start(): void {
    if (this.started) return;
    this.started = true;
    events.on('doc', (e) => { if (e.id === docStore.activeId) this.later(); });
    docStore.onChange(() => this.later());
    for (const n of ['formcad:command-state', 'formcad:cmdline-applied']) document.addEventListener(n, () => this.later());
    this.later();
  }

  on(fn: (s: AutoSnapshot) => void): () => void {
    this.fns.add(fn);
    return () => { this.fns.delete(fn); };
  }

  watching(on: boolean): void {
    window.clearInterval(this.poll);
    this.poll = on ? window.setInterval(() => { void this.pull(); }, 350) : 0;
    if (!on) this.later();
  }

  later(ms = 250): void {
    window.clearTimeout(this.timer);
    this.timer = window.setTimeout(() => { void this.pull(); }, ms);
  }

  async pull(): Promise<void> {
    const id = docStore.activeId;
    const mine = ++this.seq;
    if (!id) { this.set(EMPTY); return; }
    try {
      const [s, m] = await Promise.all([auto.scriptInfo(id), auto.macroStatus(id)]);
      if (mine !== this.seq) return;
      this.set({ script: s.script, recording: m.recording, recordName: m.name, steps: m.steps });
      if (s.script?.state === 'running' && !this.poll) this.later(400);
    } catch {
      if (mine === this.seq) this.set(EMPTY);
    }
  }

  private set(next: AutoSnapshot): void {
    const a = this.snap;
    const same = a.recording === next.recording && a.recordName === next.recordName && a.steps === next.steps &&
      JSON.stringify(a.script) === JSON.stringify(next.script);
    if (same) return;
    this.snap = next;
    for (const fn of this.fns) fn(next);
  }
}

export const watcher = new Watcher();
