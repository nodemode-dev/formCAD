import { el, patchList, q, setClass, setDisabled, setHidden, setText } from '../ui/dom';
import { icon } from '../ui/icons';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { events } from '../io/events';
import { graphEditor } from '../graph';
import { optimizeCancel, optimizeStart, optimizeStatus, statusOf, type OptimizeStatus } from './net';
import { scalar } from './wutil';

interface Gene { id: string; title: string; range: string }
interface Target { key: string; label: string }

const NUMERIC = new Set(['number', 'integer']);
const CHART = { w: 240, h: 64, pad: 4 };

function genes(): Gene[] {
  const rec = graphEditor.record();
  if (!rec) return [];
  return rec.nodes.filter((n) => graphEditor.store.entries.get(n.type)?.widget === 'slider' || n.type === 'input.slider').map((n) => {
    const s = n.settings;
    return { id: n.id, title: n.nickname || `${t('Slider')} ${n.id.slice(0, 4)}`, range: `${String(s.min ?? 0)} .. ${String(s.max ?? 10)}` };
  });
}

function holdsNumber(id: string, port: string): boolean {
  const s = graphEditor.store.states.get(id)?.outputs[port];
  return !!s && s.items === 1 && s.first.length > 0 && Number.isFinite(Number(s.first[0]));
}

function targets(): Target[] {
  const rec = graphEditor.record();
  if (!rec) return [];
  const out: Target[] = [];
  for (const n of rec.nodes) {
    const entry = graphEditor.store.entries.get(n.type);
    for (const p of entry?.outputs ?? []) {
      if (!NUMERIC.has(p.kind) && !(p.kind === 'any' && holdsNumber(n.id, p.name))) continue;
      out.push({ key: `${n.id}\u0001${p.name}`, label: `${n.nickname || entry?.name || n.type} · ${p.name}` });
    }
  }
  return out;
}

export class OptimizerPanel {
  readonly root: HTMLElement;
  private readonly geneList: HTMLElement;
  private readonly fit: HTMLSelectElement;
  private readonly dir: HTMLSelectElement;
  private readonly pop: HTMLInputElement;
  private readonly gens: HTMLInputElement;
  private readonly seed: HTMLInputElement;
  private readonly anneal: HTMLInputElement;
  private readonly start: HTMLButtonElement;
  private readonly cancel: HTMLButtonElement;
  private readonly apply: HTMLButtonElement;
  private readonly line: HTMLElement;
  private readonly best: HTMLElement;
  private readonly path: SVGPathElement;
  private readonly picked = new Set<string>();
  private poll = 0;
  private running = false;
  private job = '';
  private trace: number[] = [];
  private last: OptimizeStatus | null = null;

  constructor() {
    this.root = el(
      '<aside class="gp-opt" aria-label="Optimizer" hidden><div class="gp-phead"><span class="gp-ptitle"></span></div><div class="gp-obody is-scroll">' +
      '<p class="cv-note gp-onote"></p><div class="gp-olabel gp-ogl"></div><div class="gp-ogenes is-scroll" role="group"></div>' +
      '<label class="gp-ofield"><span class="gp-ofit"></span><select class="cv-input gp-ofitsel"></select></label>' +
      '<label class="gp-ofield"><span class="gp-odir"></span><select class="cv-input gp-odirsel"><option value="minimise"></option><option value="maximise"></option></select></label>' +
      '<label class="gp-ofield"><span class="gp-opop"></span><input class="cv-input" data-f="pop" type="number" min="4" max="500" step="1" value="20"></label>' +
      '<label class="gp-ofield"><span class="gp-ogen"></span><input class="cv-input" data-f="gens" type="number" min="1" max="2000" step="1" value="30"></label>' +
      '<label class="gp-ofield"><span class="gp-oseed"></span><input class="cv-input" data-f="seed" type="number" min="0" step="1" value="1"></label>' +
      '<label class="gp-ofield gp-ocheck"><span class="gp-oanneal"></span><input type="checkbox" data-f="anneal"></label>' +
      '<div class="gp-obtns"></div>' +
      `<div class="gp-ostat"><div class="gp-oline" role="status"></div><div class="gp-obest"></div>` +
      `<svg class="gp-ochart" viewBox="0 0 ${CHART.w} ${CHART.h}" preserveAspectRatio="none" aria-hidden="true"><path class="gp-oaxis" d="M${CHART.pad} ${CHART.h - CHART.pad}H${CHART.w - CHART.pad}M${CHART.pad} ${CHART.pad}V${CHART.h - CHART.pad}"/><path class="gp-oline-path" d=""/></svg></div>` +
      '</div></aside>');
    setText(q(this.root, '.gp-ptitle'), t('Optimizer'));
    setText(q(this.root, '.gp-onote'), t('Moves the chosen sliders to push one number output down or up. It re-solves the graph for every candidate, so keep the graph light.'));
    setText(q(this.root, '.gp-ogl'), t('Sliders to move'));
    setText(q(this.root, '.gp-ofit'), t('Fitness output'));
    setText(q(this.root, '.gp-odir'), t('Goal'));
    setText(q(this.root, '.gp-opop'), t('Population'));
    setText(q(this.root, '.gp-ogen'), t('Generations'));
    setText(q(this.root, '.gp-oseed'), t('Seed'));
    setText(q(this.root, '.gp-oanneal'), t('Use annealing'));
    const opts = q(this.root, '.gp-odirsel').children;
    setText(opts[0], t('Minimise'));
    setText(opts[1], t('Maximise'));
    this.geneList = q(this.root, '.gp-ogenes');
    this.fit = q<HTMLSelectElement>(this.root, '.gp-ofitsel');
    this.dir = q<HTMLSelectElement>(this.root, '.gp-odirsel');
    this.pop = q<HTMLInputElement>(this.root, '[data-f="pop"]');
    this.gens = q<HTMLInputElement>(this.root, '[data-f="gens"]');
    this.seed = q<HTMLInputElement>(this.root, '[data-f="seed"]');
    this.anneal = q<HTMLInputElement>(this.root, '[data-f="anneal"]');
    const btns = q(this.root, '.gp-obtns');
    const mk = (name: string, label: string, run: () => void): HTMLButtonElement => {
      const b = el<HTMLButtonElement>(`<button class="gp-obtn" type="button">${icon(name, 14)}<span></span></button>`);
      setText(q(b, 'span:not(.icon)'), t(label));
      b.addEventListener('click', run);
      btns.appendChild(b);
      return b;
    };
    this.start = mk('gcRun', 'Start', () => { void this.begin(); });
    this.cancel = mk('gcStop', 'Cancel', () => { void this.stop(); });
    this.apply = mk('check', 'Apply best', () => { this.take(); });
    this.line = q(this.root, '.gp-oline');
    this.best = q(this.root, '.gp-obest');
    this.path = q<SVGPathElement>(this.root, '.gp-oline-path');
    this.geneList.addEventListener('change', (e) => {
      const box = e.target as HTMLInputElement;
      const id = (box.closest('.gp-orow') as HTMLElement | null)?.dataset.key;
      if (!id) return;
      if (box.checked) this.picked.add(id); else this.picked.delete(id);
      this.buttons();
    });
    this.root.addEventListener('keydown', (e) => { e.stopPropagation(); });
    this.paintStatus(null);
    this.buttons();
    events.on('graph', (e) => {
      if (e.graph !== graphEditor.gid() || e.reason !== 'optimize' || !this.job || e.job !== this.job) return;
      this.take2(statusOf({ id: e.job, state: e.state, progress: e.progress }));
    });
  }

  get shown(): boolean { return !this.root.hidden; }

  toggle(on?: boolean): void {
    setHidden(this.root, on === undefined ? !this.root.hidden : !on);
    if (this.shown) this.sync();
  }

  sync(): void {
    const gs = genes();
    patchList(this.geneList, gs, {
      key: (g) => g.id,
      create: () => el('<label class="gp-orow"><input type="checkbox"><span class="gp-otitle"></span><span class="gp-orange"></span></label>'),
      update: (node, g) => {
        setText(q(node, '.gp-otitle'), g.title);
        setText(q(node, '.gp-orange'), g.range);
        const box = q<HTMLInputElement>(node, 'input');
        if (box.checked !== this.picked.has(g.id)) box.checked = this.picked.has(g.id);
      },
    });
    for (const id of [...this.picked]) if (!gs.some((g) => g.id === id)) this.picked.delete(id);
    const keep = this.fit.value;
    patchList(this.fit, targets(), {
      key: (x) => x.key,
      create: () => document.createElement('option'),
      update: (o, x) => { (o as HTMLOptionElement).value = x.key; setText(o, x.label); },
    });
    if (keep && Array.from(this.fit.options).some((o) => o.value === keep)) this.fit.value = keep;
    this.buttons();
  }

  private buttons(): void {
    setDisabled(this.start, this.running || this.picked.size === 0 || this.fit.options.length === 0);
    setDisabled(this.cancel, !this.running);
    setDisabled(this.apply, this.running || !this.last || this.last.best === null || Object.keys(this.last.genome).length === 0);
    for (const c of [this.fit, this.dir, this.pop, this.gens, this.seed, this.anneal]) setDisabled(c, this.running);
  }

  private async begin(): Promise<void> {
    const [node, port] = this.fit.value.split('\u0001');
    if (!node || this.picked.size === 0) return;
    const int = (i: HTMLInputElement, lo: number, hi: number, d: number): number => Math.min(hi, Math.max(lo, Math.round(Number(i.value)) || d));
    try {
      await graphEditor.store.flush();
      this.last = null;
      this.trace = [];
      this.job = '';
      this.running = true;
      this.buttons();
      this.paintStatus(null);
      const st = await optimizeStart(graphEditor.gid(), {
        genes: [...this.picked],
        fitness_node: node,
        fitness_port: port,
        direction: this.dir.value === 'maximise' ? 'maximise' : 'minimise',
        method: this.anneal.checked ? 'annealing' : 'evolution',
        population: int(this.pop, 5, 500, 20),
        generations: int(this.gens, 1, 2000, 30),
        seed: int(this.seed, 0, 2147483647, 1),
        commit: false,
      });
      this.job = st.id;
      this.watch();
    } catch (e) {
      this.running = false;
      this.buttons();
      toast(e instanceof Error ? e.message : t('The optimizer could not start.'), 'error');
    }
  }

  private watch(): void {
    window.clearInterval(this.poll);
    this.poll = window.setInterval(() => {
      if (!this.job) return;
      void optimizeStatus(graphEditor.gid(), this.job).then((s) => { this.take2(s); }).catch(() => { return; });
    }, 400);
  }

  private take2(s: OptimizeStatus): void {
    const live = s.state === 'running' || s.state === 'queued';
    const prev = this.last;
    if (s.history.length === 0 && s.best !== null && (!prev || prev.generation !== s.generation || this.trace.length === 0)) this.trace.push(s.best);
    this.last = { ...s, history: s.history.length ? s.history : this.trace.slice(), genome: Object.keys(s.genome).length === 0 && prev ? prev.genome : s.genome };
    if (this.running && !live) {
      window.clearInterval(this.poll);
      this.running = false;
      if (s.state === 'failed') toast(s.message || t('The optimizer failed.'), 'error');
      if (Object.keys(s.genome).length === 0 && this.job) void optimizeStatus(graphEditor.gid(), this.job).then((f) => { this.take2(f); }).catch(() => { return; });
    }
    this.paintStatus(this.last);
    this.buttons();
  }

  private async stop(): Promise<void> {
    if (!this.job) return;
    try { await optimizeCancel(graphEditor.gid(), this.job); } catch (e) { toast(e instanceof Error ? e.message : t('Cancel failed.'), 'error'); }
  }

  private take(): void {
    const best = this.last?.genome ?? {};
    const ids = Object.keys(best);
    if (!ids.length) return;
    const changed = graphEditor.store.apply((rec) => ({
      ...rec,
      nodes: rec.nodes.map((n) => (best[n.id] === undefined ? n : { ...n, inputs: n.inputs.map((p) => (p.name === 'value' ? { ...p, persistent: scalar('number', best[n.id]) } : p)) })),
    }));
    toast(changed ? t('Applied the best values to the sliders.') : t('The sliders could not be changed.'), changed ? 'info' : 'error');
  }

  private paintStatus(s: OptimizeStatus | null): void {
    if (!s) {
      setText(this.line, this.running ? t('Starting') : t('Not run yet.'));
      setText(this.best, '');
      this.path.setAttribute('d', '');
      return;
    }
    const gens = Number(this.gens.value) || s.generation;
    setText(this.line, `${t(stateWord(s.state))} · ${t('generation')} ${s.generation}/${gens} · ${s.evaluations} ${t('evaluations')}`);
    setText(this.best, s.best === null ? '' : `${t('Best')} ${s.best.toPrecision(8)}`);
    const d = chartPath(s.history);
    if (this.path.getAttribute('d') !== d) this.path.setAttribute('d', d);
    setClass(this.root, 'is-running', this.running);
  }
}

const stateWord = (s: string): string => (s === 'done' || s === 'finished' ? 'Finished' : s === 'cancelled' ? 'Cancelled' : s === 'failed' || s === 'error' ? 'Failed' : 'Running');

export function chartPath(history: number[]): string {
  if (history.length === 0) return '';
  let lo = Infinity, hi = -Infinity;
  for (const v of history) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  const span = hi - lo || 1;
  const w = CHART.w - CHART.pad * 2, h = CHART.h - CHART.pad * 2;
  const n = Math.max(1, history.length - 1);
  return history.map((v, i) => `${i ? 'L' : 'M'}${(CHART.pad + (i / n) * w).toFixed(1)} ${(CHART.pad + (1 - (v - lo) / span) * h).toFixed(1)}`).join('');
}
