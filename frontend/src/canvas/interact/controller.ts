import { api, ApiError, type CanvasInput, type CommandLineState, type SnapPayload } from '../../io/api';
import { SNAP_NAMES } from '../overlay';
import type { CanvasApi, DisplayItem, DragInfo, GripMark, PointerInfo, Pt, SnapMark, TrackMark } from '../types';
import { IDLE_STATE, pointLike, type Ctx, type Pointer } from './ctx';
import { DynamicInput, EMPTY_DYN, type InputField, type DynView } from './dyn';
import { angleOf, dist, polar } from './geom';
import { Gripper, type GripRef } from './gripper';
import { ContextMenu } from './menu';
import { MenuBuilder, type MenuHost } from './menus';
import { Selector } from './select';
import { readSettings, type Settings, type SysApi } from './settings';
import { Tracker, type Path, type Resolved } from './track';
import { fmtLinear, round1 } from './units';

export interface InteractDeps {
  docId(): string | null;
  onDoc(fn: () => void): () => void;
  sys: SysApi;
  onSys(fn: () => void): () => void;
  timeRightClick(): boolean;
  toast(text: string): void;
  runUi(id: string): void;
  commandNames(): Promise<string[]>;
  cmdInput(): HTMLInputElement | null;
  typing(t: EventTarget | null): boolean;
  dialogOpen(): boolean;
  recall(): string[];
}

const NUM = /^[-+]?(\d+(\.\d*)?|\.\d+)?$/;
const DEG = Math.PI / 180;

function lineItem(p1: Pt, p2: Pt): DisplayItem {
  return {
    h: null, kind: 'line', layer: '0', color: [255, 255, 255], color7: true, lw: 0, lt: null, tr: 0, order: 0,
    geom: { type: 'line', p1, p2 },
    bounds: [Math.min(p1[0], p2[0]), Math.min(p1[1], p2[1]), Math.max(p1[0], p2[0]), Math.max(p1[1], p2[1])],
  };
}

function plain(v: number): string {
  return String(Number(v.toFixed(8)));
}

interface Typed { parts: string[]; ok: boolean; sep: boolean }

export class Interaction implements Ctx {
  private st: CommandLineState = IDLE_STATE;
  private readonly states = new Map<string, CommandLineState>();
  private settings: Settings;
  private ptrNow: Pointer | null = null;
  private shiftDown = false;
  private ctrlDown = false;
  private queued = false;
  private res: Resolved | null = null;
  private effPoint: Pt | null = null;
  private readonly tracker = new Tracker();
  private readonly dyn: DynamicInput;
  private readonly menu: ContextMenu;
  private readonly sel: Selector;
  private readonly grips: Gripper;
  private readonly builder: MenuBuilder;
  private names = new Set<string>();
  private namesLoaded = false;
  private cycle = 0;
  private cycleAt: Pt | null = null;
  private lastAngle: number | null = null;
  private lastSent: Pt | null = null;
  private lastCmd = '';
  private recentCmds: string[] = [];
  private rightDown: { t: number } | null = null;
  private menuWasOpen = false;
  private dragMode: 'grip' | 'window' | null = null;
  private lock2 = false;
  private optIdx = -1;
  private optOpen = false;
  private previewSeq = 0;
  private previewBusy = false;
  private previewWant: { key: string; p: Pt; snap: SnapPayload | undefined } | null = null;
  private previewKey = '';
  private jigFromPreview = false;
  private snapKey = '';
  private trackKey = '';
  private gripKey = '';
  private hlKey = '';
  private boxKey = '';
  private timer = 0;
  private viewStack: Array<[number, number, number]> = [];
  private readonly off: Array<() => void> = [];
  private cursorModeKey = '';

  constructor(readonly canvas: CanvasApi, readonly host: HTMLElement, private readonly deps: InteractDeps) {
    this.settings = readSettings(deps.sys);
    this.off.push(this.listenDoc('pointerdown', (e) => { this.menuWasOpen = this.menu.isOpen; void e; }, true));
    this.menu = new ContextMenu();
    this.dyn = new DynamicInput(host);
    this.sel = new Selector(this, this.menu);
    this.grips = new Gripper(this, () => this.sel.selected, (items) => this.setJig(items));
    this.builder = new MenuBuilder(this.menuHost());

    this.dyn.onRow = (i) => this.pickOption(i);
    this.dyn.onRowHover = (i) => { this.optIdx = i; this.schedule(); };

    this.off.push(canvas.on('cursor', (c) => this.onCursor(c)));
    this.off.push(canvas.on('click', (e) => this.onClick(e)));
    this.off.push(canvas.on('drag', (e) => this.onDrag(e)));
    this.off.push(canvas.on('dblclick', () => { if (this.sel.cancelWindow()) this.schedule(); }));
    this.off.push(canvas.on('view', () => this.schedule()));
    this.off.push(canvas.on('display', () => { this.previewKey = ''; this.schedule(); }));
    this.off.push(deps.onSys(() => { this.settings = readSettings(deps.sys); this.schedule(); }));
    this.off.push(deps.onDoc(() => this.switchDoc()));

    host.addEventListener('pointerdown', (e) => { if (e.button === 2) this.rightDown = { t: performance.now() }; }, true);
    const onState = (e: Event): void => {
      const d = (e as CustomEvent<{ doc: string; state: CommandLineState }>).detail;
      this.accept(d.doc, d.state);
    };
    for (const n of ['formcad:command-state', 'formcad:cmdline-applied']) {
      document.addEventListener(n, onState);
      this.off.push(() => document.removeEventListener(n, onState));
    }
    const onText = (): void => { this.lock2 = this.typedStr() === '' ? false : this.lock2; this.schedule(); };
    document.addEventListener('formcad:cmdline-text', onText);
    this.off.push(() => document.removeEventListener('formcad:cmdline-text', onText));
    window.addEventListener('keydown', this.onKeyDown, true);
    window.addEventListener('keyup', this.onKeyUp, true);
    window.addEventListener('blur', this.onBlur);
    this.off.push(() => {
      window.removeEventListener('keydown', this.onKeyDown, true);
      window.removeEventListener('keyup', this.onKeyUp, true);
      window.removeEventListener('blur', this.onBlur);
    });
    this.switchDoc();
  }

  private listenDoc(name: string, fn: (e: Event) => void, capture: boolean): () => void {
    document.addEventListener(name, fn, capture);
    return () => document.removeEventListener(name, fn, capture);
  }

  doc(): string | null { return this.deps.docId(); }
  set(): Settings { return this.settings; }
  state(): CommandLineState { return this.st; }
  ptr(): Pointer | null { return this.ptrNow; }
  shift(): boolean { return this.shiftDown; }
  ctrl(): boolean { return this.ctrlDown; }
  toast(text: string): void { this.deps.toast(text); }
  effective(): Pt | null { return this.effPoint; }

  hint(text: string): void {
    document.dispatchEvent(new CustomEvent('formcad:hint', { detail: text }));
  }

  publish(doc: string, state: CommandLineState): void {
    document.dispatchEvent(new CustomEvent('formcad:command-state', { detail: { doc, state } }));
  }

  schedule(): void {
    if (this.queued) return;
    this.queued = true;
    requestAnimationFrame(() => { this.queued = false; this.frame(); });
  }

  private typedStr(): string {
    return this.deps.cmdInput()?.value ?? '';
  }

  private setTyped(v: string): void {
    const el = this.deps.cmdInput();
    if (!el) return;
    el.value = v;
    document.dispatchEvent(new CustomEvent('formcad:cmdline-text'));
  }

  private menuHost(): MenuHost {
    return {
      canvas: this.canvas,
      state: () => this.st,
      has: (c) => this.names.has(c),
      send: (t) => { void this.sendText(t); },
      cancel: () => { void this.cancelCommand(); },
      ui: (id) => this.deps.runUi(id),
      properties: () => document.dispatchEvent(new CustomEvent('formcad:ui', { detail: { action: 'palette:properties' } })),
      selection: () => [...this.sel.selected],
      clearSelection: () => this.sel.clearSelection(),
      lastCommand: () => this.lastCmd,
      recentCommands: () => this.recentCmds,
      recentInput: () => this.deps.recall().slice(-8).reverse(),
      zoomPrevious: () => {
        const v = this.viewStack.pop();
        if (v) this.canvas.setView(v[0], v[1], v[2]);
      },
      zoomBy: (k) => {
        const v = this.canvas.view;
        this.viewStack.push([v.cx, v.cy, v.height]);
        this.canvas.setView(v.cx, v.cy, v.height / k);
      },
      gripOption: (g, option) => this.gripOption(g, option),
      gripMode: (g) => this.grips.begin(g, false, false),
    };
  }

  private async loadNames(): Promise<void> {
    if (this.namesLoaded) return;
    this.namesLoaded = true;
    try {
      this.names = new Set((await this.deps.commandNames()).map((n) => n.toLowerCase()));
    } catch {
      this.namesLoaded = false;
    }
  }

  private switchDoc(): void {
    const id = this.deps.docId();
    this.st = (id ? this.states.get(id) : undefined) ?? IDLE_STATE;
    this.sel.reset();
    this.grips.cancel();
    this.tracker.clear();
    this.previewKey = '';
    this.setJig(null);
    this.setCursorMode();
    void this.loadNames();
    if (id) {
      void api.getSelection(id).then((r) => { if (this.deps.docId() === id) this.sel.sync(r.handles); }).catch(() => undefined);
    }
    this.schedule();
  }

  private accept(doc: string, st: CommandLineState): void {
    this.states.set(doc, st);
    if (doc !== this.deps.docId()) return;
    const was = this.st;
    this.st = st;
    if (st.active && st.command) this.lastCmd = st.command.toLowerCase();
    if (was.active && !st.active) {
      if (this.lastCmd) this.recentCmds = [this.lastCmd, ...this.recentCmds.filter((c) => c !== this.lastCmd)].slice(0, 8);
      this.tracker.clear();
      this.lastAngle = null;
      this.lastSent = null;
      this.previewKey = '';
      this.setJig(null);
      this.lock2 = false;
    }
    if (!st.active || st.expect !== 'selection') {
      if (this.sel.pending.size) this.sel.pending = new Set();
    }
    if (!st.active && Array.isArray(st.selection)) this.sel.sync(st.selection);
    if (st.options.length === 0) { this.optOpen = false; this.optIdx = -1; }
    this.sel.prune();
    this.grips.invalidate();
    this.setCursorMode();
    this.schedule();
  }

  private setCursorMode(): void {
    const s = this.st;
    const pick = s.active ? s.expect === 'selection' || s.expect === 'entity' : this.settings.pickfirst;
    const key = pick ? 'pick' : 'point';
    if (key === this.cursorModeKey) return;
    this.cursorModeKey = key;
    this.canvas.setCursorMode(pick ? 'pick' : 'point');
  }

  private onCursor(c: { x: number; y: number } | null): void {
    if (!c) {
      this.ptrNow = null;
      this.canvas.setEffectivePoint(null);
      this.schedule();
      return;
    }
    const [px, py] = this.canvas.screenFromWorld(c.x, c.y);
    this.ptrNow = { px, py, x: c.x, y: c.y };
    this.sel.moved(px, py);
    if (this.cycleAt && dist(this.cycleAt, [c.x, c.y]) > this.settings.aperture / this.canvas.view.scale) {
      this.cycle = 0;
      this.cycleAt = null;
    }
    this.schedule();
  }

  private promptMode(): boolean {
    return this.st.active && (this.st.expect === 'selection' || this.st.expect === 'entity');
  }

  private pickActive(): boolean {
    const s = this.st;
    if (s.active) return s.expect === 'selection' || s.expect === 'entity';
    return this.settings.pickfirst;
  }

  private base(): Pt | null {
    if (this.grips.session) return this.grips.session.base ?? this.grips.anchor() ?? this.grips.session.grips[0].p;
    const b = this.st.base;
    return b ? [b[0], b[1]] : null;
  }

  private snapPayload(r: Resolved): SnapPayload | undefined {
    if (r.snap) return { mode: r.snap.mode, handle: r.snap.handle, at: [r.snap.p[0], r.snap.p[1]], aperture: this.settings.aperture / this.canvas.view.scale };
    const s = r.slide;
    if (s && (s.kind === 'ext' || s.kind === 'par')) return { mode: s.kind, handle: s.handle, at: [r.p[0], r.p[1]] };
    if (r.cross && r.tip) return { mode: r.tip.startsWith('Apparent') ? 'app' : 'int', handle: null, at: [r.cross[0], r.cross[1]] };
    return undefined;
  }

  private parseTyped(text: string, polarFmt: boolean): Typed {
    if (!text || /^[@#*]/.test(text)) return { parts: [], ok: false, sep: false };
    const sep = polarFmt ? '<' : ',';
    const parts = text.split(sep);
    if (parts.length > 2) return { parts: [], ok: false, sep: false };
    const ok = parts.every((p) => NUM.test(p));
    return { parts, ok, sep: parts.length > 1 };
  }

  private polarFormat(): boolean {
    return this.st.base !== null && this.st.base !== undefined && !this.settings.dynpiformat;
  }

  private relative(): boolean {
    return !!this.st.base && !this.settings.dynpicoords;
  }

  private compute(raw: Pt, shift: boolean): Resolved {
    const base = this.base();
    const r = this.tracker.resolve({
      canvas: this.canvas,
      set: this.settings,
      raw,
      scale: this.canvas.view.scale,
      base,
      lastAngle: this.lastAngle,
      shift,
      windowCorner: false,
      override: this.st.snapOverride ?? null,
      cycle: this.cycle,
      now: performance.now(),
    });
    return this.applyLocks(r, base);
  }

  private applyLocks(r: Resolved, base: Pt | null): Resolved {
    const s = this.settings;
    const gripOn = this.grips.session !== null;
    if (!s.dynmode || !(gripOn || (this.st.active && this.st.expect === 'point')) || r.snap) return r;
    const t = this.parseTyped(this.typedStr(), gripOn || this.polarFormat());
    if (!t.ok || !t.parts.length) return r;
    const v0 = t.parts[0] !== '' ? Number(t.parts[0]) : null;
    const v1 = t.parts[1] !== undefined && t.parts[1] !== '' ? Number(t.parts[1]) : null;
    if (gripOn || this.polarFormat()) {
      if (!base) return r;
      const d = v0 !== null && t.sep ? v0 : null;
      const a = v1;
      if (d === null && a === null) return r;
      const dd = d ?? dist(base, r.p);
      const aa = a !== null ? a * DEG : angleOf(base, r.p);
      return { ...r, p: polar(base, dd, aa), dir: [Math.cos(aa), Math.sin(aa)] };
    }
    const rel = this.relative() && base !== null;
    let x = r.p[0];
    let y = r.p[1];
    if (v0 !== null && t.sep) x = rel && base ? base[0] + v0 : v0;
    if (v1 !== null) y = rel && base ? base[1] + v1 : v1;
    return { ...r, p: [x, y] };
  }

  private frame(): void {
    const id = this.deps.docId();
    const cv = this.canvas;
    if (!id) {
      this.res = null;
      cv.setOverlay('snap-marker', null);
      cv.setOverlay('tracking', null);
      cv.setOverlay('grips', null);
      cv.setOverlay('highlight', null);
      cv.setOverlay('selection-box', null);
      this.dyn.patch(EMPTY_DYN);
      return;
    }
    this.sel.prune();
    this.setCursorMode();
    const p = this.ptrNow;
    const st = this.st;
    const gripOn = this.grips.session !== null;
    const point = pointLike(st) || gripOn;
    let res: Resolved | null = null;
    if (p && point) res = this.compute([p.x, p.y], this.shiftDown);
    else if (p && st.active && st.expect === 'selection') this.tracker.clear();
    this.res = res;
    this.effPoint = p ? (res ? res.p : [p.x, p.y]) : null;
    cv.setEffectivePoint(this.effPoint);
    if (this.timer) { window.clearTimeout(this.timer); this.timer = 0; }
    if (res && res.timer > 0) this.timer = window.setTimeout(() => { this.timer = 0; this.schedule(); }, Math.max(16, res.timer));

    const hoverGrip = !st.active && !gripOn && p ? this.grips.hit(p.px, p.py) : null;
    this.grips.hover = hoverGrip;
    const pickable = this.pickActive() && !gripOn && !hoverGrip && !this.menu.isOpen;
    this.sel.updateHover(p ? p.px : null, p ? p.py : null, pickable && p !== null);
    if (this.sel.corner && p) this.sel.rubber = { x0: this.sel.corner.x, y0: this.sel.corner.y, x1: p.x, y1: p.y };

    this.paintMarks(res);
    this.paintSelection();
    this.driveJig(res);
    this.dyn.patch(this.dynView(res));
  }

  private paintMarks(res: Resolved | null): void {
    const cv = this.canvas;
    const marks: SnapMark[] = res?.snap ? [{ p: res.snap.p, mode: res.snap.mode, label: SNAP_NAMES[res.snap.mode] }] : [];
    const sk = marks.length ? `${marks[0].mode}|${marks[0].p[0]}|${marks[0].p[1]}` : '';
    if (sk !== this.snapKey) {
      this.snapKey = sk;
      cv.setOverlay('snap-marker', marks.length ? marks : null);
    }
    const tr: TrackMark[] = [];
    if (res || this.tracker.acquired.length) {
      for (const a of this.tracker.acquired) tr.push({ type: 'acquired', p: a.p, parallel: !!a.parallel });
      if (res) {
        const far = cv.view.height * 4;
        for (const pa of res.engaged) this.pathMarks(pa, far, res.p, tr);
        if (res.cross) tr.push({ type: 'cross', p: res.cross });
        if (res.tip) tr.push({ type: 'tip', text: res.tip });
      }
    }
    const tk = tr.map((t) => `${t.type}|${t.text ?? ''}|${t.p ? t.p[0].toFixed(5) : ''}|${t.p ? t.p[1].toFixed(5) : ''}|${t.q ? t.q[0].toFixed(3) : ''}`).join(';');
    if (tk !== this.trackKey) {
      this.trackKey = tk;
      cv.setOverlay('tracking', tr.length ? tr : null);
    }
  }

  private pathMarks(pa: Path, far: number, at: Pt, out: TrackMark[]): void {
    if (pa.t === 'ray') {
      const a: Pt = pa.bi ? [pa.o[0] - pa.d[0] * far, pa.o[1] - pa.d[1] * far] : pa.o;
      out.push({ type: 'path', p: a, q: [pa.o[0] + pa.d[0] * far, pa.o[1] + pa.d[1] * far] });
      return;
    }
    const th = angleOf(pa.c, at);
    let prev: Pt = polar(pa.c, pa.r, th - 0.6);
    for (let i = 1; i <= 24; i++) {
      const q = polar(pa.c, pa.r, th - 0.6 + (1.2 * i) / 24);
      out.push({ type: 'path', p: prev, q });
      prev = q;
    }
  }

  private paintSelection(): void {
    const cv = this.canvas;
    const marks = this.sel.marks(this.promptMode());
    const hk = marks.map((m) => `${m.kind}:${m.handles.join(',')}`).join(';');
    if (hk !== this.hlKey) {
      this.hlKey = hk;
      cv.setOverlay('highlight', marks.length ? marks : null);
    }
    const boxes = this.sel.box();
    const bk = boxes.map((b) => `${b.x0}|${b.y0}|${b.x1}|${b.y1}`).join(';');
    if (bk !== this.boxKey) {
      this.boxKey = bk;
      cv.setOverlay('selection-box', boxes.length ? boxes : null);
    }
    const gm: GripMark[] = this.grips.marks();
    const gk = gm.map((g) => `${g.p[0]}|${g.p[1]}|${g.state}`).join(';');
    if (gk !== this.gripKey) {
      this.gripKey = gk;
      cv.setOverlay('grips', gm.length ? gm : null);
    }
  }

  private setJig(items: DisplayItem[] | null): void {
    this.jigFromPreview = !!items;
    this.canvas.setOverlay('jig', items && items.length ? items : null);
  }

  private driveJig(res: Resolved | null): void {
    const id = this.deps.docId();
    const st = this.st;
    const gs = this.grips.session;
    if (gs && res) {
      this.grips.preview(res.p);
      return;
    }
    if (!id || !st.active || !pointLike(st) || !res) {
      if (this.previewKey !== '' || (this.jigFromPreview && !gs)) {
        this.previewKey = '';
        this.previewWant = null;
        this.previewSeq++;
        this.setJig(null);
      }
      return;
    }
    const base = st.base;
    if (st.preview) {
      const snap = this.snapPayload(res);
      const key = `${res.p[0].toFixed(9)}|${res.p[1].toFixed(9)}|${st.rev}|${st.prompt}|${snap?.mode ?? ''}`;
      if (key === this.previewKey) return;
      this.previewKey = key;
      this.requestPreview(id, key, res.p, snap);
      return;
    }
    const key = base ? `rb|${base[0]}|${base[1]}|${res.p[0].toFixed(9)}|${res.p[1].toFixed(9)}` : 'none';
    if (key === this.previewKey) return;
    this.previewKey = key;
    this.previewSeq++;
    this.setJig(base ? [lineItem([base[0], base[1]], res.p)] : null);
  }

  private requestPreview(id: string, key: string, p: Pt, snap: SnapPayload | undefined): void {
    if (this.previewBusy) {
      this.previewWant = { key, p, snap };
      return;
    }
    void this.runPreview(id, key, p, snap);
  }

  private async runPreview(id: string, key: string, p: Pt, snap: SnapPayload | undefined): Promise<void> {
    this.previewBusy = true;
    const seq = ++this.previewSeq;
    try {
      const r = await api.preview(id, [p[0], p[1]], snap);
      if (seq === this.previewSeq && this.previewKey === key && this.deps.docId() === id) this.setJig(r.items ?? []);
    } catch {
      if (seq === this.previewSeq) this.setJig(null);
    } finally {
      this.previewBusy = false;
      const next = this.previewWant;
      this.previewWant = null;
      if (next && this.st.active && this.deps.docId() === id) this.requestPreview(id, next.key, next.p, next.snap);
    }
  }

  private liveBoxes(res: Resolved | null): InputField[] {
    const s = this.settings;
    const st = this.st;
    const base = st.base ?? null;
    const gs = this.grips.session;
    const text = this.typedStr();
    const p = res?.p ?? this.effPoint;
    if (!p) return [];
    const lin = (v: number): string => fmtLinear(v, s.lunits, s.luprec);
    if (gs) {
      const a = this.grips.anchor() ?? gs.grips[0].p;
      const t = this.parseTyped(text, true);
      const len = dist(a, p);
      const ang = ((angleOf(a, p) / DEG) % 360 + 360) % 360;
      const out: InputField[] = [];
      const bits = [1, 2, 4, 8, 16].filter((b) => (s.dyndigrip & b) !== 0);
      const shown = bits.slice(0, s.dyndivis === 0 ? 1 : s.dyndivis === 1 ? 2 : 3);
      const old = dist(a, gs.grips[0].p);
      const oldAng = angleOf(a, gs.grips[0].p);
      shown.forEach((b) => {
        const first = b === 1;
        const second = b === 4;
        const typedIdx = first ? 0 : second ? 1 : -1;
        const tv = typedIdx >= 0 && t.ok ? t.parts[typedIdx] : undefined;
        const live = tv === undefined || tv === '';
        let label = '';
        let val = '';
        if (b === 1) val = lin(len);
        else if (b === 2) { label = 'Δ'; val = lin(len - old); }
        else if (b === 4) { label = '<'; val = round1(ang); }
        else if (b === 8) { label = 'Δ<'; val = round1((((angleOf(a, p) - oldAng) / DEG + 540) % 360) - 180); }
        else { label = 'R'; val = lin(len); }
        out.push({ label, text: live ? val : tv ?? val, live, active: typedIdx >= 0 && t.ok && t.parts.length - 1 === typedIdx, locked: typedIdx >= 0 && !live && t.parts.length - 1 > typedIdx });
      });
      return out;
    }
    if (st.expect === 'distance' && base) {
      const typed = NUM.test(text) && text !== '';
      return [{ label: '', text: typed ? text : lin(dist(base, p)), live: !typed, active: true, locked: false }];
    }
    if (st.expect === 'angle' && base) {
      const typed = NUM.test(text) && text !== '';
      return [{ label: '<', text: typed ? text : round1((((angleOf(base, p) / DEG) % 360) + 360) % 360), live: !typed, active: true, locked: false }];
    }
    if (st.expect !== 'point') return [];
    const polarFmt = this.polarFormat();
    const t = this.parseTyped(text, polarFmt);
    const active = t.ok ? t.parts.length - 1 : 0;
    const typedAt = (i: number): string | undefined => (t.ok && t.parts[i] !== undefined && t.parts[i] !== '' ? t.parts[i] : undefined);
    let live0: string;
    let live1: string;
    if (base && polarFmt) {
      live0 = lin(dist(base, p));
      live1 = round1((((angleOf(base, p) / DEG) % 360) + 360) % 360);
    } else if (base && this.relative()) {
      live0 = lin(p[0] - base[0]);
      live1 = lin(p[1] - base[1]);
    } else {
      live0 = lin(p[0]);
      live1 = lin(p[1]);
    }
    const labels = base && polarFmt ? ['', '<'] : ['X', 'Y'];
    const lives = [live0, live1];
    return [0, 1].map((i): InputField => {
      const tv = typedAt(i);
      return {
        label: labels[i],
        text: tv ?? lives[i],
        live: tv === undefined,
        active: i === active,
        locked: (t.ok && t.sep && i === 0 && tv !== undefined) || (this.lock2 && i === 1 && tv !== undefined),
      };
    });
  }

  private dynView(res: Resolved | null): DynView {
    const s = this.settings;
    const p = this.ptrNow;
    const st = this.st;
    const hidden = { ...EMPTY_DYN };
    if (!p || !s.dynmode) return hidden;
    const typed = this.typedStr();
    const gs = this.grips.session;
    const badge = this.pickActive() && s.cycling > 0 && this.sel.overlap > 1;
    const view: DynView = { ...EMPTY_DYN, visible: true, x: p.px, y: p.py, badge, badgeX: p.px, badgeY: p.py };
    if (this.optOpen && st.options.length) {
      view.list = { rows: st.options.map((o) => o.label), idx: Math.max(0, this.optIdx) };
    }
    if (gs) {
      view.boxes = this.liveBoxes(res);
      view.msg = s.dynprompt ? 'Specify point' : '';
      return view;
    }
    if (!st.active) {
      if (typed === '') return { ...hidden, badge, badgeX: p.px, badgeY: p.py, visible: badge };
      view.msg = typed;
      return view;
    }
    const prompt = st.prompt.replace(/\s*\[[^\]]*\]/, '').trim();
    if (st.expect === 'point' || (pointLike(st) && st.base)) {
      view.boxes = this.liveBoxes(res);
      const t = this.parseTyped(typed, this.polarFormat());
      if (typed && !t.ok && !/^[@#*]/.test(typed.slice(0, 1))) {
        view.boxes = [];
        view.msg = `${prompt} ${typed}`;
      } else if (/^[@#*]/.test(typed)) {
        view.boxes = [];
        view.msg = `${prompt} ${typed}`;
      } else view.msg = s.dynprompt ? prompt : '';
      view.at = view.boxes.length > 0 && !!st.base && !s.dynpicoords && st.expect === 'point';
    } else {
      const base = st.base;
      let msg = s.dynprompt ? prompt : '';
      if (typed) msg = `${msg}: ${typed}`;
      else if (base && p && res) msg = `${msg} ${fmtLinear(dist(base, res.p), s.lunits, 2)} < ${round1((((angleOf(base, res.p) / DEG) % 360) + 360) % 360)}`;
      view.msg = msg.trim();
    }
    view.arrow = s.dynprompt && st.options.length > 0;
    return view;
  }

  private async post(body: CanvasInput): Promise<void> {
    const id = this.deps.docId();
    if (!id) return;
    try {
      this.publish(id, await api.sendCanvasInput(id, body));
    } catch (e) {
      this.deps.toast(e instanceof ApiError || e instanceof Error ? e.message : 'The engine did not answer');
    }
  }

  async sendText(text: string): Promise<void> {
    const id = this.deps.docId();
    if (!id) return;
    try {
      this.publish(id, await api.sendInput(id, text));
    } catch (e) {
      this.deps.toast(e instanceof ApiError || e instanceof Error ? e.message : 'The engine did not answer');
    }
    this.sel.endCycle();
  }

  private async cancelCommand(): Promise<void> {
    const id = this.deps.docId();
    if (!id) return;
    try {
      this.publish(id, await api.cancelCommand(id));
    } catch (e) {
      this.deps.toast(e instanceof ApiError || e instanceof Error ? e.message : 'The engine did not answer');
    }
  }

  private sendPoint(r: Resolved): void {
    const p = r.p;
    const base = this.st.base;
    if (this.lastSent && base && dist(base, this.lastSent) < 1e-9) this.lastAngle = angleOf(base, p);
    this.lastSent = p;
    this.cycle = 0;
    this.cycleAt = null;
    this.lock2 = false;
    this.setTyped('');
    const snap = this.snapPayload(r);
    void this.post(snap ? { point: [p[0], p[1]], snap } : { point: [p[0], p[1]] });
  }

  private onClick(e: PointerInfo): void {
    if (e.button === 2) {
      this.onRightClick(e);
      return;
    }
    if (e.button !== 0) return;
    if (this.menuWasOpen) {
      this.menuWasOpen = false;
      return;
    }
    if (this.menu.isOpen) return;
    const st = this.st;
    const gs = this.grips.session;
    if (gs) {
      const r = this.compute([e.x, e.y], e.shift);
      if (e.ctrl) this.grips.addCopy(r.p);
      else void this.grips.commit(r.p, gs.copies.length > 0);
      return;
    }
    if (st.active) {
      if (pointLike(st)) this.sendPoint(this.compute([e.x, e.y], e.shift));
      else if (st.expect === 'selection') this.sel.click(e, true);
      else if (st.expect === 'entity') void this.sel.pickEntity(e.px, e.py);
      return;
    }
    const g = this.grips.hit(e.px, e.py);
    if (g) {
      if (e.shift) this.grips.toggleHot(g);
      else this.grips.begin(g, false, e.ctrl);
      return;
    }
    if (this.settings.pickfirst) this.sel.click(e, false);
  }

  private onDrag(e: DragInfo): void {
    if (e.button !== 0) return;
    const st = this.st;
    if (e.phase === 'start') {
      this.dragMode = null;
      if (this.menu.isOpen || this.grips.session) return;
      if (!st.active) {
        const g = this.grips.hit(e.px0, e.py0);
        if (g) {
          this.grips.begin(g, true, e.ctrl);
          this.dragMode = 'grip';
          return;
        }
      }
      if (this.settings.pickdrag === 0) return;
      if ((!st.active && this.settings.pickfirst) || (st.active && st.expect === 'selection')) this.dragMode = 'window';
      else return;
    }
    if (this.dragMode === 'grip') {
      if (e.phase === 'end') {
        const r = this.compute([e.x, e.y], e.shift);
        void this.grips.commit(r.p, e.ctrl);
        this.dragMode = null;
      }
      return;
    }
    if (this.dragMode === 'window') {
      this.sel.drag(e.phase, e.x0, e.y0, e.x, e.y, e.shift, st.active);
      if (e.phase === 'end') this.dragMode = null;
    }
  }

  private onRightClick(e: PointerInfo): void {
    const st = this.st;
    const held = this.rightDown ? performance.now() - this.rightDown.t : 0;
    this.rightDown = null;
    const rect = this.host.getBoundingClientRect();
    const cx = rect.left + e.px;
    const cy = rect.top + e.py;
    this.menu.onClose = () => this.schedule();
    if (this.grips.session) {
      this.grips.cancel();
      return;
    }
    if (e.shift || e.ctrl) {
      this.menu.open(cx, cy, this.builder.snapItems());
      return;
    }
    if (!st.active) {
      const g = this.grips.hit(e.px, e.py);
      if (g) {
        this.menu.open(cx, cy, this.builder.grip(g));
        return;
      }
      const kinds = [...this.sel.selected].map((h) => this.canvas.item(h)?.kind ?? '');
      this.menu.open(cx, cy, this.builder.idle(kinds));
      return;
    }
    if (this.deps.timeRightClick() && held < 250) {
      this.lock2 = false;
      void this.sendText(this.typedStr());
      this.setTyped('');
      return;
    }
    this.menu.open(cx, cy, this.builder.running());
  }

  private gripOption(g: GripRef, option: string): void {
    if (option === 'remove_vertex' || option === 'convert_line') {
      this.grips.begin(g, false, false, option);
      void this.grips.commit(g.p, false);
      return;
    }
    this.grips.begin(g, false, false, option);
  }

  private pickOption(i: number): void {
    const o = this.st.options[i];
    this.optOpen = false;
    this.optIdx = -1;
    if (o) void this.sendText(o.key);
    this.schedule();
  }

  private canHandle(e: KeyboardEvent): boolean {
    if (this.deps.dialogOpen()) return false;
    const t = e.target;
    if (this.deps.typing(t) && t !== this.deps.cmdInput()) return false;
    return true;
  }

  private onBlur = (): void => {
    this.shiftDown = false;
    this.ctrlDown = false;
    this.schedule();
  };

  private onKeyUp = (e: KeyboardEvent): void => {
    if (e.key === 'Shift') { this.shiftDown = false; this.schedule(); }
    if (e.key === 'Control' || e.key === 'Meta') this.ctrlDown = false;
  };

  private stop(e: KeyboardEvent): void {
    e.preventDefault();
    e.stopImmediatePropagation();
  }

  private onKeyDown = (e: KeyboardEvent): void => {
    if (e.key === 'Shift' && !this.shiftDown) { this.shiftDown = true; this.schedule(); }
    if (e.key === 'Control' || e.key === 'Meta') this.ctrlDown = true;
    if (e.isComposing || !this.canHandle(e) || !this.deps.docId()) return;
    const mods = e.ctrlKey || e.metaKey || e.altKey;
    const st = this.st;
    const typed = this.typedStr();
    if (e.key === 'Escape') {
      this.onEscape(e);
      return;
    }
    if (this.optOpen && st.options.length) {
      const n = st.options.length;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        this.optIdx = (this.optIdx + (e.key === 'ArrowDown' ? 1 : -1) + n) % n;
        this.stop(e);
        this.schedule();
        return;
      }
      if (e.key === 'Enter') {
        this.stop(e);
        this.pickOption(Math.max(0, this.optIdx));
        return;
      }
    }
    if (e.key === 'ArrowDown' && !mods && typed === '' && this.settings.dynmode && this.settings.dynprompt && st.active && st.options.length && this.ptrNow) {
      this.optOpen = true;
      this.optIdx = 0;
      this.stop(e);
      this.schedule();
      return;
    }
    if (e.key === ' ' && e.shiftKey && !mods && typed === '' && this.ptrNow && this.pickActive()) {
      this.stop(e);
      this.sel.step(this.ptrNow.px, this.ptrNow.py);
      return;
    }
    if (mods) return;
    if (e.key === 'Tab') {
      this.onTab(e, typed);
      return;
    }
    if (e.key === 'Enter' || e.key === ' ') this.onEnter(e, typed);
  };

  private onEscape(e: KeyboardEvent): void {
    if (this.menu.isOpen) {
      this.menu.close();
      this.stop(e);
      return;
    }
    if (this.optOpen) {
      this.optOpen = false;
      this.stop(e);
      this.schedule();
      return;
    }
    const hadGrip = this.grips.session !== null || this.grips.hot.length > 0;
    this.grips.cancel();
    const hadWindow = this.sel.cancelWindow();
    this.sel.endCycle();
    this.lock2 = false;
    this.tracker.clear();
    this.cycle = 0;
    if (!this.st.active && !hadGrip && !hadWindow && this.typedStr() === '') this.sel.clearSelection();
    this.schedule();
  }

  private onTab(e: KeyboardEvent, typed: string): void {
    const gs = this.grips.session !== null;
    if (gs || (this.st.active && this.st.expect === 'point')) {
      if (typed === '' && this.res && this.res.cycleCount > 1) {
        this.cycle++;
        this.cycleAt = this.ptrNow ? [this.ptrNow.x, this.ptrNow.y] : null;
        this.stop(e);
        this.schedule();
        return;
      }
      if (this.settings.dynmode && typed !== '') {
        const polarFmt = gs || this.polarFormat();
        const sep = polarFmt ? '<' : ',';
        const t = this.parseTyped(typed, polarFmt);
        if (t.ok && !t.sep && typed !== '') {
          this.setTyped(typed + sep);
          this.stop(e);
          return;
        }
        if (t.ok && t.sep && t.parts[1] !== '' && t.parts[0] !== '') {
          this.lock2 = true;
          this.stop(e);
          this.schedule();
          return;
        }
      }
    } else if (this.st.active && typed === '' && this.res === null && this.st.expect === 'point') this.cycle = 0;
  }

  private onEnter(e: KeyboardEvent, typed: string): void {
    const gs = this.grips.session;
    if (gs) {
      if (typed === '') {
        this.stop(e);
        if (gs.copies.length && e.key === 'Enter') void this.grips.finishCopies();
        else this.grips.cycle();
        return;
      }
      const t = this.parseTyped(typed, true);
      const r = this.res;
      if (t.ok && r) {
        this.stop(e);
        this.setTyped('');
        this.lock2 = false;
        void this.grips.commit(r.p, this.ctrlDown);
      }
      return;
    }
    const st = this.st;
    if (!st.active || st.expect !== 'point' || typed === '' || !this.ptrNow) return;
    const r = this.res;
    if (!r) return;
    const acc = st.accepts ?? [];
    const plainNum = NUM.test(typed) && typed !== '';
    const origin = r.slide && r.slide.t === 'ray' ? r.slide.origin : st.base ? [st.base[0], st.base[1]] as Pt : null;
    if (plainNum && !acc.includes('number') && !acc.includes('distance') && !acc.includes('angle') && origin && r.dir) {
      const d = Number(typed);
      this.stop(e);
      this.sendPoint({ ...r, snap: null, slide: null, cross: null, tip: '', p: [origin[0] + r.dir[0] * d, origin[1] + r.dir[1] * d] });
      return;
    }
    if (!this.settings.dynmode || /^[@#*]/.test(typed)) return;
    const polarFmt = this.polarFormat();
    const t = this.parseTyped(typed, polarFmt);
    if (!t.ok || !t.sep) return;
    const base = st.base ? ([st.base[0], st.base[1]] as Pt) : null;
    const rel = this.relative() && base !== null;
    const p = r.p;
    let a: string;
    let b: string;
    if (base && polarFmt) {
      a = t.parts[0] !== '' ? t.parts[0] : plain(dist(base, p));
      b = t.parts[1] !== '' ? t.parts[1] : plain((((angleOf(base, p) / DEG) % 360) + 360) % 360);
      this.setTyped(`${rel ? '@' : ''}${a}<<${b}`);
    } else {
      a = t.parts[0] !== '' ? t.parts[0] : plain(rel && base ? p[0] - base[0] : p[0]);
      b = t.parts[1] !== '' ? t.parts[1] : plain(rel && base ? p[1] - base[1] : p[1]);
      this.setTyped(`${rel ? '@' : ''}${a},${b}`);
    }
    this.lock2 = false;
  }

  dispose(): void {
    for (const f of this.off) f();
  }
}
