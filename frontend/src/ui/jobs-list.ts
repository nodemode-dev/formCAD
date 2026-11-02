import { events } from '../io/events';
import { el, patchList, q, setHidden, setStyleVar, setText, setTitle } from './dom';
import { onLanguage, t } from './i18n';
import { toast } from './toast';

export interface JobInfo { id: string; label: string; progress: number | null; message: string }

const ENDED = /^(done|finished|complete|completed|success|succeeded|error|failed|cancelled|canceled)$/i;
const FAILED = /^(error|failed)$/i;

export class JobTracker {
  readonly jobs = new Map<string, JobInfo>();
  private readonly listeners = new Set<() => void>();

  constructor() {
    events.on('job', (e) => {
      const id = String(e.id);
      const state = typeof e.state === 'string' ? e.state : '';
      if (ENDED.test(state)) {
        const had = this.jobs.delete(id);
        if (had && FAILED.test(state)) toast(e.message || `${e.label ?? 'Job'} failed`, 'error');
        this.emit();
        return;
      }
      const prev = this.jobs.get(id);
      const raw = typeof e.progress === 'number' ? e.progress : null;
      const progress = raw === null ? prev?.progress ?? null : Math.min(1, Math.max(0, raw > 1 ? raw / 100 : raw));
      this.jobs.set(id, { id, label: e.label ?? prev?.label ?? 'Job', progress, message: e.message ?? prev?.message ?? '' });
      this.emit();
    });
    events.onState((s) => { if (s !== 'open' && this.jobs.size) { this.jobs.clear(); this.emit(); } });
  }

  get count(): number { return this.jobs.size; }

  onChange(fn: () => void): void { this.listeners.add(fn); }

  private emit(): void {
    for (const fn of this.listeners) fn();
  }
}

export class JobsList {
  private readonly root = el<HTMLElement>(
    '<div class="cv-jobs" role="dialog" aria-label="Jobs" hidden><div class="cv-jobs-head"><span class="cv-jobs-title"></span><span class="cv-jobs-count"></span></div>' +
    '<div class="cv-jobs-list" role="list"></div><p class="cv-jobs-empty"></p></div>');
  private readonly list = q(this.root, '.cv-jobs-list');
  private readonly empty = q(this.root, '.cv-jobs-empty');
  private readonly count = q(this.root, '.cv-jobs-count');

  constructor(private readonly tracker: JobTracker, private readonly anchor: HTMLElement) {
    document.getElementById('overlay-root')?.appendChild(this.root);
    this.words();
    tracker.onChange(() => this.sync());
    onLanguage(() => { this.words(); this.sync(); });
    this.root.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); this.hide(); } });
  }

  get isOpen(): boolean { return !this.root.hidden; }

  toggle(): void { if (this.isOpen) this.hide(); else this.show(); }

  show(): void {
    if (this.isOpen) return;
    const r = this.anchor.getBoundingClientRect();
    this.root.hidden = false;
    this.root.style.left = `${Math.max(8, Math.min(window.innerWidth - 8 - this.root.offsetWidth, r.right - this.root.offsetWidth))}px`;
    this.root.style.bottom = `${Math.max(8, window.innerHeight - r.top + 6)}px`;
    this.sync();
    document.addEventListener('pointerdown', this.outside, true);
    document.addEventListener('keydown', this.escape, true);
  }

  hide(): void {
    if (!this.isOpen) return;
    this.root.hidden = true;
    document.removeEventListener('pointerdown', this.outside, true);
    document.removeEventListener('keydown', this.escape, true);
  }

  private readonly escape = (e: KeyboardEvent): void => {
    if (e.key === 'Escape' && !e.defaultPrevented) { e.preventDefault(); this.hide(); }
  };

  private readonly outside = (e: PointerEvent): void => {
    if (e.target instanceof Node && !this.root.contains(e.target) && !this.anchor.contains(e.target)) this.hide();
  };

  private words(): void {
    setText(q(this.root, '.cv-jobs-title'), t('Jobs'));
    this.root.setAttribute('aria-label', t('Jobs'));
    setText(this.empty, t('No background jobs are running.'));
  }

  private sync(): void {
    if (!this.isOpen) return;
    const jobs = [...this.tracker.jobs.values()];
    patchList<JobInfo>(this.list, jobs, {
      key: (j) => j.id,
      create: (j) => {
        const row = el('<div class="cv-jobs-row" role="listitem"><span class="cv-jobs-name"></span><span class="cv-jobs-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100"><i></i></span><span class="cv-jobs-pct"></span></div>');
        this.fill(row, j);
        return row;
      },
      update: (row, j) => this.fill(row, j),
    });
    setHidden(this.empty, jobs.length > 0);
    setText(this.count, jobs.length ? String(jobs.length) : '');
  }

  private fill(row: HTMLElement, j: JobInfo): void {
    const name = q(row, '.cv-jobs-name'), bar = q(row, '.cv-jobs-bar');
    const pct = j.progress === null ? 0 : Math.round(j.progress * 100);
    setText(name, j.label);
    setTitle(name, j.message ? `${j.label}: ${j.message}` : j.label);
    setStyleVar(bar, '--p', `${pct}%`);
    if (bar.getAttribute('aria-valuenow') !== String(pct)) bar.setAttribute('aria-valuenow', String(pct));
    setText(q(row, '.cv-jobs-pct'), j.progress === null ? '' : `${pct}%`);
  }
}
