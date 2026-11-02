import { api, type Capabilities, type KernelStatus } from '../io/api';
import { events } from '../io/events';
import type { Commands } from './commands';
import type { DocStore } from './doc-store';
import { pendingClass, q, setClass, setDisabled, setStyleVar, setText, setTitle, type Disposer } from './dom';
import { onLanguage, t } from './i18n';
import { icon } from './icons';
import { JobsList, type JobTracker } from './jobs-list';
import { loadPrefs } from './prefs';
import { DRAFT_TOGGLES, type SysvarStore } from './sysvar-store';
import { toast } from './toast';

export interface StatusDeps {
  commands: Commands;
  sysvars: SysvarStore;
  docs: DocStore;
  jobs: JobTracker;
}

export interface CursorDetail { x: number; y: number; z?: number }

const SERVICE_NOTE = 'The engine is not running, so drawings cannot be created, opened or saved. Start it with ./formCAD boot.';

const UNIT_NAMES: Record<number, [string, string]> = {
  0: ['', 'unitless'], 1: ['in', 'inches'], 2: ['ft', 'feet'], 3: ['mi', 'miles'], 4: ['mm', 'millimetres'], 5: ['cm', 'centimetres'],
  6: ['m', 'metres'], 7: ['km', 'kilometres'], 14: ['dm', 'decimetres'],
};
const LINEAR_NAMES: Record<number, string> = { 1: 'Scientific', 2: 'Decimal', 3: 'Engineering', 4: 'Architectural', 5: 'Fractional' };

interface MemoryProbe { usedJSHeapSize?: number }

export class StatusBar {
  private readonly coord: HTMLElement;
  private readonly hint: HTMLElement;
  private readonly busy: HTMLElement;
  private readonly engineState: HTMLElement;
  private readonly kernel: HTMLButtonElement;
  private readonly mem: HTMLElement;
  private readonly anno: HTMLElement;
  private readonly units: HTMLElement;
  private readonly layer: HTMLElement;
  private readonly jobsBtn: HTMLButtonElement;
  private readonly jobsCount: HTMLElement;
  private readonly list: JobsList;
  private dismiss: Disposer | null = null;
  private caps: Capabilities | null = null;
  private offline = false;
  private checked = false;
  private readonly host: HTMLElement;
  private kernelState: Pick<KernelStatus, 'available' | 'version' | 'installing' | 'progress'> | null = null;
  private hintText = '';
  private errText = '';
  private errTimer = 0;

  constructor(root: HTMLElement, private readonly d: StatusDeps) {
    const toggles = DRAFT_TOGGLES.map((x) => `<button class="cv-st-tog" type="button" data-cmd="${x.id}" aria-pressed="false">${icon(x.icon, 14)}</button>`).join('');
    root.insertAdjacentHTML('beforeend',
      '<div class="cv-st-tools" role="group" aria-label="History">' +
      `<button class="cv-icon-btn cv-st-btn" type="button" data-cmd="undo">${icon('undo', 14)}</button>` +
      `<button class="cv-icon-btn cv-st-btn" type="button" data-cmd="redo">${icon('redo', 14)}</button>` +
      '</div>' +
      '<span class="cv-st-coord" aria-live="off"></span>' +
      `<div class="cv-st-togs" role="group" aria-label="Drafting aids">${toggles}</div>` +
      '<button class="cv-st-anno" type="button" data-cmd="x:scalelistedit"></button>' +
      '<button class="cv-st-units" type="button" data-cmd="x:units"></button>' +
      `<button class="cv-st-layer" type="button" data-cmd="x:layer">${icon('layers', 14)}<span class="cv-st-layer-name"></span></button>` +
      '<span class="cv-st-hint"></span>' +
      '<span class="cv-st-engine"></span>' +
      '<button class="cv-st-kernel" type="button"><i class="cv-st-kernel-bar"></i><span class="cv-st-kernel-text"></span></button>' +
      '<span class="cv-st-mem"></span>' +
      `<span class="cv-st-busy">${icon('loading', 12)}<span class="cv-st-busy-text"></span></span>` +
      `<button class="cv-icon-btn cv-st-btn cv-st-jobs" type="button">${icon('viewList', 14)}<span class="cv-st-jobs-count"></span></button>`);
    this.host = root;
    this.coord = q(root, '.cv-st-coord');
    this.hint = q(root, '.cv-st-hint');
    this.busy = q(root, '.cv-st-busy');
    this.engineState = q(root, '.cv-st-engine');
    this.kernel = q(root, '.cv-st-kernel');
    this.mem = q(root, '.cv-st-mem');
    this.anno = q(root, '.cv-st-anno');
    this.units = q(root, '.cv-st-units');
    this.layer = q(root, '.cv-st-layer-name');
    this.jobsBtn = q(root, '.cv-st-jobs');
    this.jobsCount = q(root, '.cv-st-jobs-count');
    this.list = new JobsList(d.jobs, this.jobsBtn);

    this.jobsBtn.addEventListener('click', () => this.list.toggle());
    this.busy.addEventListener('click', () => this.list.toggle());
    this.kernel.addEventListener('click', () => this.installKernel());
    d.jobs.onChange(() => this.syncJobs());
    d.sysvars.onChange(() => this.syncToggles());
    d.docs.onChange(() => this.syncToggles());
    events.on('kernel', (e) => {
      const base = this.kernelState ?? { available: false, version: null, installing: false, progress: 0 };
      this.kernelState = {
        available: typeof e.available === 'boolean' ? e.available : base.available,
        version: e.version !== undefined ? e.version : base.version,
        installing: typeof e.installing === 'boolean' ? e.installing : base.installing,
        progress: typeof e.progress === 'number' ? e.progress : base.progress,
      };
      this.syncKernel();
    });
    events.onState((s) => {
      const gone = s === 'closed';
      if (gone !== this.offline) { this.offline = gone; this.showEngine(); }
    });
    document.addEventListener('formcad:cursor', (e) => this.setCursor((e as CustomEvent<CursorDetail | null>).detail));
    document.addEventListener('formcad:hint', (e) => this.setHint(String((e as CustomEvent<string>).detail ?? '')));
    this.syncMemory();
    window.setInterval(() => this.syncMemory(), 5000);
    this.words();
    this.syncToggles();
    this.syncJobs();
    this.showEngine();
    this.syncKernel();
    this.setCursor(null);
    onLanguage(() => {
      this.words();
      this.syncToggles();
      this.showEngine();
      this.syncKernel();
      this.syncJobs();
    });
  }

  toggleJobs(): void { this.list.toggle(); }

  get jobsOpen(): boolean { return this.list.isOpen; }

  setCapabilities(caps: Capabilities | null): void {
    this.caps = caps;
    this.checked = true;
    if (caps) this.kernelState = { available: caps.kernel.available, version: caps.kernel.version, installing: this.kernelState?.installing ?? false, progress: this.kernelState?.progress ?? 0 };
    this.showEngine();
    this.syncKernel();
  }

  setCursor(c: CursorDetail | null): void {
    if (!c) { setText(this.coord, ''); return; }
    const p = loadPrefs().precision;
    const f = (n: number): string => n.toFixed(Math.max(0, Math.min(8, p)));
    setText(this.coord, `X ${f(c.x)}  Y ${f(c.y)}  Z ${f(c.z ?? 0)}`);
  }

  setHint(text: string): void {
    this.hintText = text;
    this.syncHint();
  }

  flashError(text: string): void {
    this.errText = text;
    this.syncHint();
    window.clearTimeout(this.errTimer);
    this.errTimer = window.setTimeout(() => { this.errText = ''; this.syncHint(); }, 6000);
  }

  private syncHint(): void {
    const text = this.errText || this.hintText;
    setClass(this.hint, 'is-error', !!this.errText);
    setText(this.hint, text);
    setTitle(this.hint, text);
  }

  private words(): void {
    setText(q(this.busy, '.cv-st-busy-text'), t('Working'));
    setTitle(this.busy, t('Show the running jobs'));
    setTitle(this.jobsBtn, t('Show the running jobs'));
    this.jobsBtn.setAttribute('aria-label', t('Jobs'));
    setTitle(this.coord, t('Cursor position'));
    setTitle(this.mem, t('Memory used by the interface'));
    for (const x of DRAFT_TOGGLES) {
      const b = q(this.host, `[data-cmd="${x.id}"]`);
      const cmd = this.d.commands.get(x.id);
      const key = cmd ? this.d.commands.keyLabel(cmd) : '';
      const label = `${t(x.label)}${key ? ` (${key})` : ''}`;
      setTitle(b, label);
      b.setAttribute('aria-label', label);
    }
    setTitle(q(this.host, '[data-cmd="undo"]'), t('Undo'));
    setTitle(q(this.host, '[data-cmd="redo"]'), t('Redo'));
    setTitle(q(this.host, '[data-cmd="x:scalelistedit"]'), t('Annotation scale'));
    setTitle(q(this.host, '[data-cmd="x:layer"]'), t('Active layer: open the layer manager'));
  }

  syncToggles(): void {
    const root = this.host;
    const sv = this.d.sysvars;
    for (const x of DRAFT_TOGGLES) {
      const b = q<HTMLButtonElement>(root, `[data-cmd="${x.id}"]`);
      const on = sv.ready && x.on(sv.num(x.name, x.fallback));
      setClass(b, 'is-on', on);
      if (b.getAttribute('aria-pressed') !== String(on)) b.setAttribute('aria-pressed', String(on));
      setDisabled(b, !sv.ready);
    }
    const hasDoc = !!this.d.docs.current();
    for (const id of ['undo', 'redo']) {
      const cmd = this.d.commands.get(id);
      setDisabled(q<HTMLButtonElement>(root, `[data-cmd="${id}"]`), !cmd || !this.d.commands.enabled(cmd) || !hasDoc);
    }
    setText(this.anno, sv.ready ? sv.text('CANNOSCALE', '1:1') : '');
    const unit = UNIT_NAMES[sv.num('INSUNITS', 4)] ?? ['', 'unitless'];
    setText(this.units, sv.ready ? unit[0] || '-' : '');
    setTitle(this.units, sv.ready ? `${t('Units')}: ${t(LINEAR_NAMES[sv.num('LUNITS', 2)] ?? 'Decimal')}, ${t(unit[1])}` : '');
    setText(this.layer, sv.ready ? sv.text('CLAYER', '0') : '');
  }

  private showEngine(): void {
    const off = this.offline || (this.checked && !this.caps);
    setText(this.engineState, this.caps && !off ? `${t('Engine')} ${this.caps.version}${this.caps.desktop ? ` · ${t('desktop')}` : ''}` : off ? t('Engine offline') : '');
    setTitle(this.engineState, off ? t(SERVICE_NOTE) : '');
  }

  private syncKernel(): void {
    const k = this.kernelState;
    let text = '', title = '';
    const installing = !!k?.installing;
    if (!k) text = '';
    else if (installing) { text = `${t('Installing kernel')} ${Math.round(Math.min(1, Math.max(0, k.progress > 1 ? k.progress / 100 : k.progress)) * 100)}%`; title = t('Downloading the kernel'); }
    else if (k.available) { text = `${t('Kernel')} ${k.version ?? ''}`.trim(); title = t('The geometry kernel is installed'); }
    else { text = t('Install kernel'); title = t('Download the geometry kernel for 3D modeling'); }
    setText(q(this.kernel, '.cv-st-kernel-text'), text);
    setTitle(this.kernel, title);
    setClass(this.kernel, 'is-installing', installing);
    setClass(this.kernel, 'is-missing', !!k && !k.available && !installing);
    setClass(this.kernel, 'is-ready', !!k && k.available && !installing);
    setDisabled(this.kernel, !k || installing || k.available);
    const p = k ? Math.round(Math.min(1, Math.max(0, k.progress > 1 ? k.progress / 100 : k.progress)) * 100) : 0;
    setStyleVar(q(this.kernel, '.cv-st-kernel-bar'), '--p', `${installing ? p : 0}%`);
  }

  installKernel(): void {
    this.kernelState = { available: false, version: null, installing: true, progress: 0 };
    this.syncKernel();
    api.kernelInstall().then((s) => {
      this.kernelState = { available: s.available, version: s.version, installing: s.installing, progress: s.progress };
      this.syncKernel();
    }).catch((e: unknown) => {
      this.kernelState = { available: false, version: null, installing: false, progress: 0 };
      this.syncKernel();
      toast(e instanceof Error ? e.message : 'The kernel could not be installed', 'error');
    });
  }

  private syncJobs(): void {
    const n = this.d.jobs.count;
    setText(this.jobsCount, n ? String(n) : '');
    if (n > 0) { if (!this.dismiss) this.dismiss = pendingClass(this.busy); }
    else { this.dismiss?.(); this.dismiss = null; }
  }

  private syncMemory(): void {
    const m = (performance as Performance & { memory?: MemoryProbe }).memory;
    const used = m?.usedJSHeapSize;
    setText(this.mem, used ? `${t('Memory')} ${Math.round(used / 1048576)} MB` : '');
  }
}
