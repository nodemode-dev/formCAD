import { onShellMounted } from '../app';
import { call, token, type CommandLineState } from '../io/api';
import { api } from '../io/api';
import { events } from '../io/events';
import { commands } from '../ui/commands';
import { docStore } from '../ui/doc-store';
import { delayedIndicator, el, q, setClass, setDisabled, setTitle, store, stored } from '../ui/dom';
import { onLanguage, t } from '../ui/i18n';
import { icon } from '../ui/icons';
import { layoutState } from '../ui/layout-state';
import { sysvars } from '../ui/sysvar-store';
import { toast } from '../ui/toast';
import { LEVEL_IDS, PLANE_IDS, STD_VIEW_IDS } from './menu-ids';
import { parseScene } from './scene-format';
import type { AngleConvention, BodyData, DisplayMode, PickLevel, Projection, SceneModel, SelectionState } from './types';
import { MODE_LABELS, MODE_ORDER } from './types';
import { NamedViews3dDialog } from './views-dialog';
import { Viewport3D } from './viewport';

const PREF_KEY = 'formCAD.view3d';
const enc = encodeURIComponent;

interface Prefs { mode: DisplayMode; projection: Projection; level: PickLevel; grid: boolean; cube: boolean; angle: AngleConvention }
const DEFAULTS: Prefs = { mode: 'shadedEdges', projection: 'perspective', level: 'any', grid: true, cube: true, angle: 'third' };

function loadPrefs(): Prefs {
  try {
    const v = JSON.parse(stored(PREF_KEY) ?? '{}') as Partial<Prefs>;
    return {
      mode: MODE_ORDER.includes(v.mode as DisplayMode) ? v.mode as DisplayMode : DEFAULTS.mode,
      projection: v.projection === 'parallel' ? 'parallel' : 'perspective',
      level: ['any', 'body', 'face', 'edge'].includes(v.level as string) ? v.level as PickLevel : 'any',
      grid: v.grid !== false,
      cube: v.cube !== false,
      angle: v.angle === 'first' ? 'first' : 'third',
    };
  } catch {
    return { ...DEFAULTS };
  }
}

async function fetchScene(id: string, since: number): Promise<ArrayBuffer | null> {
  const headers: Record<string, string> = {};
  const tok = token();
  if (tok) headers['X-FormCAD-Token'] = tok;
  const res = await fetch(`/api/docs/${enc(id)}/scene?since=${since}`, { headers });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(res.statusText || `The 3D data request failed (${res.status})`);
  try {
    return await res.arrayBuffer();
  } catch (e) {
    throw new Error(e instanceof RangeError ? 'The 3D data is too large to load.' : 'The 3D data could not be read.');
  }
}

const hint = (text: string): void => { document.dispatchEvent(new CustomEvent('formcad:hint', { detail: text })); };

class View3dController {
  vp: Viewport3D | null = null;
  on = false;
  failed = '';
  prefs = loadPrefs();
  private readonly stage: HTMLElement;
  private readonly host: HTMLElement;
  private readonly bar: HTMLElement;
  private readonly cluster: HTMLElement;
  private readonly modeSel: HTMLSelectElement;
  private readonly dialog: NamedViews3dDialog;
  private cache = new Map<number, BodyData>();
  private cacheDoc = '';
  private cacheRev = 0;
  private busy = false;
  private again = false;
  private timer = 0;
  private token = 0;
  private expectPoint = false;
  private firstFit = true;

  constructor(private readonly root: HTMLElement, stage: HTMLElement, status: HTMLElement) {
    this.stage = stage;
    this.host = el<HTMLElement>(
      '<div class="cv-view3d" aria-label="3D view" aria-hidden="true">' +
      '<div class="v3-bar" role="toolbar" aria-label="3D view tools">' +
      `<button class="v3-btn" type="button" data-cmd="v3-extents">${icon('fitView', 16)}</button>` +
      `<button class="v3-btn" type="button" data-cmd="v3-proj-toggle">${icon('perspective', 16)}</button>` +
      '<span class="v3-sep"></span>' +
      LEVEL_IDS.map(([id, label]) => `<button class="v3-seg" type="button" data-cmd="v3-level-${id}" aria-pressed="false">${t(label)}</button>`).join('') +
      '</div><div class="v3-note"></div></div>');
    stage.appendChild(this.host);
    this.bar = q(this.host, '.v3-bar');
    const hintAnchor = status.querySelector('.cv-st-hint');
    const html =
      '<div class="cv-st-3d" role="group" aria-label="3D view">' +
      `<button class="cv-st-tog v3-st-toggle" type="button" data-cmd="v3-toggle" aria-pressed="false">${icon('cube', 14)}</button>` +
      `<select class="v3-st-mode" aria-label="Display mode">${MODE_ORDER.map((m) => `<option value="${m}">${t(MODE_LABELS[m])}</option>`).join('')}</select>` +
      `<button class="cv-st-tog" type="button" data-cmd="v3-proj-toggle">${icon('perspective', 14)}</button>` +
      `<button class="cv-st-tog" type="button" data-cmd="v3-grid" aria-pressed="false">${icon('grid', 14)}</button>` +
      '</div>';
    if (hintAnchor) hintAnchor.insertAdjacentHTML('beforebegin', html); else status.insertAdjacentHTML('beforeend', html);
    this.cluster = q(status, '.cv-st-3d');
    this.modeSel = q<HTMLSelectElement>(this.cluster, '.v3-st-mode');
    this.modeSel.value = this.prefs.mode;
    this.modeSel.addEventListener('change', () => this.setMode(this.modeSel.value as DisplayMode));
    this.dialog = new NamedViews3dDialog({
      current: () => this.need().getCamera(),
      restore: (c) => void this.with3d((vp) => vp.setCamera(c, true)),
    });
    this.registerCommands();
    this.bindWorld();
    this.sync();
    onLanguage(() => this.words());
    this.words();
    const idle = (window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number }).requestIdleCallback;
    if (idle) idle(() => this.create(), { timeout: 3000 }); else window.setTimeout(() => this.create(), 800);
  }

  private need(): Viewport3D {
    const vp = this.create();
    if (!vp) throw new Error(this.failed || 'The 3D view is not available');
    return vp;
  }

  create(): Viewport3D | null {
    if (this.vp) return this.vp;
    if (this.failed) return null;
    try {
      const vp = new Viewport3D(this.host, {
        onMode: () => this.sync(),
        onProjection: () => this.sync(),
        onLevel: () => this.sync(),
        onPlane: () => this.sync(),
        onSelection: (s) => this.pushSelection(s),
        onHover: (text) => { if (this.on) hint(text); },
        onCursor: (p) => document.dispatchEvent(new CustomEvent('formcad:cursor', { detail: p ? { x: p[0], y: p[1], z: p[2] } : null })),
        onHint: (text) => hint(text),
        onPoint: (p, snap) => this.sendPoint(p, snap?.kind ?? null),
      });
      vp.mode = this.prefs.mode;
      vp.level = this.prefs.level;
      vp.angle = this.prefs.angle;
      vp.gridOn = this.prefs.grid;
      vp.setGrid(this.prefs.grid);
      vp.setCubeVisible(this.prefs.cube);
      if (this.prefs.projection === 'parallel') vp.rig.setProjection('parallel');
      this.vp = vp;
      this.applyVars();
      this.sync();
      if (import.meta.env.DEV) Object.assign(window, { formcadView3d: this });
      return vp;
    } catch (e) {
      this.failed = e instanceof Error ? e.message : 'WebGL is not available';
      this.sync();
      return null;
    }
  }

  private save(): void {
    store(PREF_KEY, JSON.stringify(this.prefs));
  }

  private applyVars(): void {
    const vp = this.vp;
    if (!vp) return;
    vp.rig.setZoomFactor(sysvars.num('ZOOMFACTOR', 60));
    const os = sysvars.num('OSMODE', 4133);
    vp.snapOn = (os & 16384) === 0 && (os & 16383) !== 0;
    vp.snapAllowed = (k) => (k === 'vertex' ? (os & 1) !== 0 : k === 'midpoint' ? (os & 2) !== 0 : k === 'center' ? (os & 4) !== 0 : true);
  }

  private bindWorld(): void {
    sysvars.onChange(() => this.applyVars());
    events.on('doc', (e) => { if (this.on && e.id === docStore.activeId) this.schedule(); });
    let last = docStore.activeId;
    docStore.onChange(() => {
      if (docStore.activeId === last) { this.sync(); return; }
      last = docStore.activeId;
      this.cache.clear();
      this.cacheDoc = '';
      this.cacheRev = 0;
      if (!last) { void this.leave(); this.sync(); return; }
      if (this.on) { this.firstFit = true; this.schedule(); }
      this.sync();
    });
    layoutState.onChange(() => { if (this.on && layoutState.inLayout) void this.leave(); });
    const retheme = (): void => { requestAnimationFrame(() => this.vp?.refreshTheme()); };
    document.addEventListener('nm:ui-settings-changed', retheme);
    document.addEventListener('formcad:prefs-changed', retheme);
    document.addEventListener('formcad:command-state', (e) => {
      const d = (e as CustomEvent<{ doc: string; state: CommandLineState }>).detail;
      if (d.doc === docStore.activeId) this.expectPoint = !!d.state.active && (d.state.expect === 'point' || d.state.expect === 'distance' || d.state.expect === 'angle');
    });
    document.addEventListener('formcad:set-selection', (e) => {
      const d = (e as CustomEvent<{ handles?: Array<string | number>; commit?: boolean }>).detail;
      if (this.on && this.vp && d.commit === false) this.vp.setBodySelection((d.handles ?? []).map(Number));
    });
  }

  private words(): void {
    const label = (cmd: string, text: string): void => {
      for (const b of Array.from(this.root.querySelectorAll<HTMLElement>(`[data-cmd="${cmd}"]`))) setTitle(b, t(text));
    };
    label('v3-toggle', 'Switch between the drawing and the 3D view');
    label('v3-extents', 'Zoom to the whole model');
    label('v3-proj-toggle', 'Perspective or parallel projection');
    label('v3-grid', 'Grid on the construction plane');
    for (const [id, text] of LEVEL_IDS) label(`v3-level-${id}`, `Pick filter: ${text}`);
    setTitle(this.modeSel, t('Display mode'));
  }

  sync(): void {
    const vp = this.vp;
    const hasDoc = !!docStore.current();
    const ok = hasDoc && !this.failed;
    for (const b of Array.from(this.root.querySelectorAll<HTMLButtonElement>('[data-cmd^="v3-"]'))) {
      const id = b.dataset.cmd ?? '';
      let pressed: boolean | null = null;
      if (id === 'v3-toggle') pressed = this.on;
      else if (id === 'v3-grid') pressed = vp ? vp.gridOn : this.prefs.grid;
      else if (id.startsWith('v3-level-')) pressed = (vp ? vp.level : this.prefs.level) === id.slice(9);
      if (pressed !== null) {
        setClass(b, 'is-on', pressed);
        if (b.getAttribute('aria-pressed') !== String(pressed)) b.setAttribute('aria-pressed', String(pressed));
      }
      setDisabled(b, !ok);
    }
    const proj = vp ? vp.projection : this.prefs.projection;
    for (const b of Array.from(this.root.querySelectorAll<HTMLElement>('[data-cmd="v3-proj-toggle"]'))) {
      const want = proj === 'parallel' ? 'parallel' : 'perspective';
      if (b.dataset.shown !== want) {
        b.dataset.shown = want;
        b.firstElementChild?.replaceWith(el(icon(want, b.closest('.v3-bar') ? 16 : 14)));
      }
    }
    const mode = vp ? vp.mode : this.prefs.mode;
    if (this.modeSel.value !== mode) this.modeSel.value = mode;
    setDisabled(this.modeSel, !ok);
    setClass(this.stage, 'is-3d', this.on);
    this.host.setAttribute('aria-hidden', String(!this.on));
    setClass(this.host, 'is-empty', this.on && !!vp && !vp.hasBodies);
    setClass(this.host, 'is-pending', !!vp && vp.pending !== '');
    const note = q(this.host, '.v3-note');
    const text = this.failed ? t('The 3D view needs WebGL, which this device does not offer.') : t('This drawing has no 3D bodies yet. Open a STEP file to see one here.');
    if (note.textContent !== text) note.textContent = text;
  }

  setMode(m: DisplayMode): void {
    this.prefs.mode = m;
    this.save();
    if (this.vp) this.vp.setMode(m); else this.sync();
  }

  async with3d(fn: (vp: Viewport3D) => void): Promise<void> {
    if (!this.on) await this.enter();
    const vp = this.vp;
    if (vp && this.on) fn(vp);
  }

  async enter(): Promise<void> {
    if (this.on || !docStore.activeId) return;
    const vp = this.create();
    if (!vp) { toast(t(this.failed || 'The 3D view is not available'), 'error'); return; }
    const mine = ++this.token;
    const stop = delayedIndicator(() => hint(t('Loading the 3D view...')), () => hint(''), 250, 250);
    try {
      await this.load(true);
    } catch (e) {
      stop();
      toast(e instanceof Error ? e.message : 'The 3D view could not load', 'error');
      return;
    }
    stop();
    if (mine !== this.token || !docStore.activeId) return;
    vp.setActive(true);
    vp.renderNow(true);
    await new Promise<void>((r) => requestAnimationFrame(() => r()));
    if (mine !== this.token) { vp.setActive(false); return; }
    this.on = true;
    this.sync();
    vp.renderNow(true);
    vp.canvas.focus({ preventScroll: true });
    void this.pullSelection();
    vp.warm();
  }

  async leave(): Promise<void> {
    if (!this.on) return;
    this.token++;
    this.on = false;
    this.sync();
    this.vp?.setActive(false);
    document.dispatchEvent(new CustomEvent('formcad:cursor', { detail: null }));
    hint('');
    document.dispatchEvent(new CustomEvent('formcad:view3d', { detail: { on: false } }));
  }

  toggle(): void {
    if (this.on) void this.leave(); else void this.enter();
  }

  schedule(): void {
    if (this.timer) return;
    this.timer = window.setTimeout(() => { this.timer = 0; void this.load(false).catch(() => undefined); }, 120);
  }

  private async load(first: boolean): Promise<void> {
    if (this.busy) { this.again = true; return; }
    const vp = this.vp;
    const id = docStore.activeId;
    if (!vp || !id) return;
    this.busy = true;
    try {
      do {
        this.again = false;
        const same = this.cacheDoc === id && this.cacheRev > 0;
        const buf = await fetchScene(id, same ? this.cacheRev : 0);
        if (docStore.activeId !== id) break;
        if (buf) {
          const parsed = parseScene(buf);
          if (!parsed.delta || !same) this.cache.clear();
          for (const r of parsed.removed) this.cache.delete(r);
          for (const h of parsed.hidden) this.cache.delete(h);
          for (const b of parsed.bodies) this.cache.set(b.id, b);
          this.cacheDoc = id;
          this.cacheRev = parsed.rev;
        } else {
          this.cache.clear();
          this.cacheDoc = id;
          this.cacheRev = 0;
        }
        const bodies = [...this.cache.values()];
        const model: SceneModel = { rev: this.cacheRev, bodies, snaps: bodies.flatMap((b) => b.snaps) };
        const keep = !this.firstFit && vp.hasBodies;
        vp.setScene(model, keep);
        this.firstFit = false;
        this.sync();
      } while (this.again);
    } finally {
      this.busy = false;
    }
    void first;
  }

  private async pullSelection(): Promise<void> {
    const id = docStore.activeId;
    if (!id || !this.vp) return;
    try {
      const s = await api.getSelection(id);
      if (this.on) this.vp.setBodySelection(s.handles.map(Number));
    } catch {
      return;
    }
  }

  private pushSelection(s: SelectionState): void {
    const id = docStore.activeId;
    if (!id) return;
    const owners = [...new Set([...s.faces.map((f) => f.body), ...s.edges.map((e) => e.body)])];
    void call('PUT', `/api/docs/${enc(id)}/selection`, { handles: s.bodies, mode: 'set', faces: s.faces, edges: s.edges, owners })
      .then(() => document.dispatchEvent(new CustomEvent('formcad:selection', { detail: { doc: id, handles: s.bodies } })))
      .catch((e: unknown) => toast(e instanceof Error ? e.message : 'The selection was not sent', 'error'));
  }

  private sendPoint(p: [number, number, number], snap: string | null): void {
    const id = docStore.activeId;
    if (!id || !this.expectPoint) return;
    void api.sendCanvasInput(id, { point: p as unknown as [number, number], ...(snap ? { snap: { mode: snap, handle: null, at: [p[0], p[1]] } } : {}) })
      .then((state) => document.dispatchEvent(new CustomEvent('formcad:command-state', { detail: { doc: id, state } })))
      .catch(() => undefined);
  }

  private add(id: string, label: string, run: () => void, opts: { checked?: () => boolean; keys?: string[]; enabled?: () => boolean } = {}): void {
    if (commands.get(id)) return;
    commands.add({ id, label, group: 'View', run, checked: opts.checked, keys: opts.keys, enabled: opts.enabled ?? (() => !!docStore.current() && !this.failed) });
  }

  private registerCommands(): void {
    const vp = (): Viewport3D | null => this.vp;
    this.add('v3-toggle', '3D View', () => this.toggle(), { checked: () => this.on, keys: ['Alt+Mod+3'] });
    for (const [id, label] of STD_VIEW_IDS) this.add(`v3-view-${id}`, label, () => void this.with3d((v) => v.showStandardView(id)));
    for (const m of MODE_ORDER) this.add(`v3-mode-${m}`, MODE_LABELS[m], () => this.setMode(m), { checked: () => (vp() ? vp()?.mode : this.prefs.mode) === m });
    this.add('v3-proj-persp', 'Perspective', () => this.setProjection('perspective'), { checked: () => (vp()?.projection ?? this.prefs.projection) === 'perspective' });
    this.add('v3-proj-ortho', 'Parallel', () => this.setProjection('parallel'), { checked: () => (vp()?.projection ?? this.prefs.projection) === 'parallel' });
    this.add('v3-proj-toggle', 'Toggle Projection', () => this.setProjection((vp()?.projection ?? this.prefs.projection) === 'parallel' ? 'perspective' : 'parallel'));
    this.add('v3-extents', 'Zoom Extents', () => void this.with3d((v) => v.zoomExtents(true)));
    this.add('v3-zoom-sel', 'Zoom to Selection', () => void this.with3d((v) => v.zoomToSelection()));
    this.add('v3-home', 'Home View', () => void this.with3d((v) => v.home()));
    this.add('v3-cube', 'View Cube', () => {
      this.prefs.cube = !this.prefs.cube;
      this.save();
      vp()?.setCubeVisible(this.prefs.cube);
    }, { checked: () => this.prefs.cube });
    for (const [id, label] of LEVEL_IDS) this.add(`v3-level-${id}`, label, () => this.setLevel(id as PickLevel), { checked: () => (vp()?.level ?? this.prefs.level) === id });
    for (const [id, label] of PLANE_IDS) this.add(`v3-plane-${id}`, `${label} Plane`, () => void this.with3d((v) => v.setWorldPlane(id)), { checked: () => vp()?.plane.name === label });
    this.add('v3-plane-3pt', 'Plane by Three Points', () => void this.with3d((v) => v.startPlaneByThreePoints()));
    this.add('v3-plane-face', 'Plane on Face', () => void this.with3d((v) => v.startPlaneOnFace()));
    this.add('v3-plane-view', 'Look at Plane', () => void this.with3d((v) => v.lookAtPlane()));
    this.add('v3-grid', 'Grid', () => {
      const v = vp();
      this.prefs.grid = !(v ? v.gridOn : this.prefs.grid);
      this.save();
      if (v) v.setGrid(this.prefs.grid); else this.sync();
    }, { checked: () => vp()?.gridOn ?? this.prefs.grid });
    this.add('v3-section', 'Section at Plane', () => void this.with3d((v) => { v.setSection(!v.sectionState.on); this.sync(); }), { checked: () => !!vp()?.sectionState.on });
    this.add('v3-section-flip', 'Flip Section Side', () => void this.with3d((v) => v.setSection(v.sectionState.on, !v.sectionState.flip)));
    this.add('v3-views', '3D Views...', () => void this.dialog.show());
    this.add('v3-angle-third', 'Third Angle', () => this.setAngle('third'), { checked: () => this.prefs.angle === 'third' });
    this.add('v3-angle-first', 'First Angle', () => this.setAngle('first'), { checked: () => this.prefs.angle === 'first' });
  }

  private setProjection(p: Projection): void {
    this.prefs.projection = p;
    this.save();
    if (this.vp) this.vp.setProjection(p); else this.sync();
  }

  private setLevel(l: PickLevel): void {
    this.prefs.level = l;
    this.save();
    if (this.vp) this.vp.setLevel(l); else this.sync();
  }

  private setAngle(a: AngleConvention): void {
    this.prefs.angle = a;
    this.save();
    if (this.vp) this.vp.angle = a;
  }
}

onShellMounted((ctx) => {
  new View3dController(ctx.hosts.root, ctx.hosts.stage, ctx.hosts.status);
});
