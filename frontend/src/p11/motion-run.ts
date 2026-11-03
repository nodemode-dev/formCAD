import { events } from '../io/events';
import { docStore } from '../ui/doc-store';
import { view3d } from '../view3d/mount';
import { asm } from '../u8/asm';
import { joints, showPoses, type Frame3, type Job } from './joint-store';
import { docUrl, req } from './kit';

export const FRAME_CAP = 2400;

type Sub = () => void;

class MotionRun {
  job: Job | null = null;
  frames: Frame3[] = [];
  total = 0;
  at = 0;
  playing = false;
  error = '';
  private readonly subs = new Set<Sub>();
  private poll = 0;
  private raf = 0;
  private t0 = 0;
  private from = 0;
  private loading = '';
  private doc = '';

  private url(tail: string): string { return docUrl(this.doc, tail); }

  onChange(fn: Sub): void { this.subs.add(fn); }
  private emit(): void { for (const f of this.subs) f(); }

  get duration(): number {
    const last = this.frames[this.frames.length - 1];
    return last ? last.t : 0;
  }

  async start(path: string, body: Record<string, unknown>): Promise<Job | null> {
    this.stop();
    this.error = '';
    try {
      const doc = joints.id() ?? '';
      const job = await req<Job>('POST', docUrl(doc, path), { ...body, wait: false });
      this.doc = doc;
      this.job = job;
      this.frames = [];
      this.total = 0;
      this.at = 0;
      this.emit();
      this.watch(job.id);
      return job;
    } catch (e) {
      this.error = e instanceof Error ? e.message : 'The run was refused';
      this.emit();
      return null;
    }
  }

  async cancel(): Promise<void> {
    const j = this.job;
    if (!j) return;
    try { this.job = await req<Job>('POST', this.url(`motion/jobs/${j.id}/cancel`), {}); } catch { /* the poll reports the state */ }
    this.emit();
  }

  private watch(id: string): void {
    window.clearInterval(this.poll);
    this.poll = window.setInterval(() => { void this.tick(id); }, 250);
  }

  private async tick(id: string): Promise<void> {
    try {
      const j = await req<Job>('GET', this.url(`motion/jobs/${id}`));
      if (!this.job || this.job.id !== id) { window.clearInterval(this.poll); return; }
      this.job = j;
      if (j.state === 'done' || j.state === 'cancelled' || j.state === 'failed') {
        window.clearInterval(this.poll);
        await this.load(id);
      }
      this.emit();
    } catch {
      window.clearInterval(this.poll);
    }
  }

  progress(e: { job: string; progress?: Job['progress'] }): void {
    if (!this.job || this.job.id !== e.job || !e.progress) return;
    this.job = { ...this.job, progress: { ...this.job.progress, ...e.progress } };
    this.emit();
  }

  async load(id: string): Promise<void> {
    if (this.loading === id) return;
    this.loading = id;
    const out: Frame3[] = [];
    try {
      let from = 0;
      let total = 0;
      do {
        const r = await req<{ frames: Frame3[]; total: number }>('GET', this.url(`motion/jobs/${id}/frames?from=${from}&count=200`));
        total = r.total;
        out.push(...r.frames);
        from += r.frames.length;
        if (!r.frames.length) break;
      } while (from < total && from < FRAME_CAP);
      this.total = total;
      if (this.job?.id === id) { this.frames = out; this.seek(Math.min(this.at, this.duration)); }
    } catch (e) {
      this.error = e instanceof Error ? e.message : 'The frames could not be read';
    } finally {
      this.loading = '';
    }
    this.emit();
  }

  frameAt(t: number): Frame3 | null {
    const f = this.frames;
    if (!f.length) return null;
    let lo = 0, hi = f.length - 1;
    while (lo < hi) { const m = (lo + hi + 1) >> 1; if (f[m].t <= t) lo = m; else hi = m - 1; }
    const next = f[lo + 1];
    return next && next.t - t < t - f[lo].t ? next : f[lo];
  }

  seek(t: number): void {
    this.at = Math.max(0, Math.min(t, this.duration));
    const fr = this.frameAt(this.at);
    if (fr) showPoses(fr.poses);
    this.emit();
  }

  play(): void {
    if (this.playing) { this.stop(); return; }
    if (!this.frames.length) return;
    this.playing = true;
    if (this.at >= this.duration) this.at = 0;
    this.from = this.at;
    this.t0 = performance.now();
    const step = (now: number): void => {
      if (!this.playing) return;
      const t = this.from + (now - this.t0) / 1000;
      if (t >= this.duration) { this.playing = false; this.seek(this.duration); return; }
      this.seek(t);
      this.raf = requestAnimationFrame(step);
    };
    this.raf = requestAnimationFrame(step);
    this.emit();
  }

  stop(): void {
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
    if (this.playing) { this.playing = false; this.emit(); }
  }

  release(): void {
    this.stop();
    showPoses(null);
    this.emit();
  }

  async apply(t: number): Promise<string | null> {
    const j = this.job;
    if (!j) return 'There is no run to apply';
    try {
      await req('POST', this.url(`motion/jobs/${j.id}/apply`), { t });
      this.stop();
      showPoses(null);
      await view3d()?.refresh();
      asm.schedule(0);
      joints.schedule(0);
      return null;
    } catch (e) {
      return e instanceof Error ? e.message : 'The poses could not be applied';
    }
  }

  clear(): void {
    this.stop();
    window.clearInterval(this.poll);
    this.job = null;
    this.frames = [];
    this.total = 0;
    this.at = 0;
    this.emit();
  }
}

export const run = new MotionRun();

events.on('motion', (e) => { if (e.id === docStore.activeId) run.progress(e as unknown as { job: string; progress?: Job['progress'] }); });
let last: string | null = null;
docStore.onChange(() => { if (docStore.activeId !== last) { last = docStore.activeId; run.clear(); } });
