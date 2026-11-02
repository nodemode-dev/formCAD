import { drawBackground, type GridOptions } from './background';
import { BatchData } from './batch';
import { Emitter } from './build';
import { Camera } from './camera';
import { Chrome, drawCursor, type ChromePart } from './chrome';
import { handlesOf, hitMark, markState } from './cmarks';
import { css, isDark } from './color';
import { CpuPainter } from './cpu';
import { GlPainter } from './gl';
import { bindInput } from './input';
import { OverlayStore, drawOverlays, type OverlayEnv } from './overlay';
import { newDyn, type DynLayer, type PaintView, type Painter } from './painter';
import { distanceTo, distanceToInfinite, touchesRect } from './pick';
import { DisplayStore, type BuildOptions } from './store';
import { readTheme, type Theme } from './theme';
import type { CanvasApi, CanvasDeps, CanvasEvents, CursorMode, DisplayItem, DocEventInfo, Handle, Hit, MarkHit, OverlayItems, OverlayName, Pt, Rect, ViewState } from './types';

const VIEW_KEY = 'formCAD.canvasView';
const WORK_MS = 10;

interface Cfg {
  gridOn: boolean;
  unitX: number;
  unitY: number;
  major: number;
  iso: boolean;
  isoPlane: number;
  cursorSize: number;
  pickbox: number;
  gripSize: number;
  zoomFactor: number;
  opts: BuildOptions;
}

export class Renderer implements CanvasApi {
  readonly cam = new Camera();
  readonly store = new DisplayStore();
  readonly chrome = new Chrome();
  readonly overlays = new OverlayStore();
  private readonly bg: HTMLCanvasElement;
  private readonly main: HTMLCanvasElement;
  private readonly top: HTMLCanvasElement;
  private readonly probe: HTMLElement;
  private readonly bgCtx: CanvasRenderingContext2D;
  private readonly topCtx: CanvasRenderingContext2D;
  private painter: Painter;
  private theme: Theme;
  private cfg: Cfg;
  private dpr = 1;
  private cssW = 0;
  private cssH = 0;
  private raf = 0;
  private dirtyBg = true;
  private dirtyScene = true;
  private dirtyTop = true;
  private pointer: { px: number; py: number } | null = null;
  private cursorDirty = false;
  private effective: Pt | null = null;
  private override: CursorMode | null = null;
  private docId: string | null = null;
  private space = 'model';
  private needFit = false;
  private pulling = false;
  private pullAgain = false;
  private frames = 0;
  private readonly inf: DynLayer = newDyn();
  private readonly jig: DynLayer = newDyn();
  private jigItems: DisplayItem[] = [];
  private jigBand = NaN;
  private infKey = '';
  private readonly under: DynLayer[] = [];
  private underKey = '';
  private readonly listeners = new Map<string, Set<(e: never) => void>>();
  private readonly off: Array<() => void> = [];
  private hasSize = false;

  constructor(private readonly host: HTMLElement, private readonly deps: CanvasDeps) {
    this.bg = document.createElement('canvas');
    this.main = document.createElement('canvas');
    this.top = document.createElement('canvas');
    this.bg.className = 'cv-canvas-layer cv-canvas-bg';
    this.main.className = 'cv-canvas-layer cv-canvas-scene';
    this.top.className = 'cv-canvas-layer cv-canvas-top';
    this.probe = document.createElement('div');
    this.probe.className = 'cv-canvas-probe';
    this.probe.setAttribute('aria-hidden', 'true');
    for (const c of [this.bg, this.main, this.top]) c.setAttribute('aria-hidden', 'true');
    this.top.tabIndex = -1;
    host.append(this.bg, this.main, this.top, this.probe);

    const bgCtx = this.bg.getContext('2d');
    const topCtx = this.top.getContext('2d');
    if (!bgCtx || !topCtx) throw new Error('canvas2d unavailable');
    this.bgCtx = bgCtx;
    this.topCtx = topCtx;
    this.theme = readTheme(host, this.probe);
    this.cfg = this.readCfg();
    this.painter = this.makePainter();
    this.loadChromeState();
    this.store.setOptions(this.cfg.opts);
    this.store.onChange(() => { this.dirtyScene = true; this.dirtyBg = true; this.dirtyTop = true; this.schedule(); this.emit('display', this.store.rev); });

    const ro = new ResizeObserver((entries) => {
      const r = entries[entries.length - 1].contentRect;
      this.resize(r.width, r.height);
    });
    ro.observe(host);
    this.off.push(() => ro.disconnect());
    this.watchDpr();

    this.off.push(bindInput(this.top, {
      cam: this.cam,
      chrome: this.chrome,
      isMac: /Mac|iPhone|iPad/.test(navigator.platform),
      zoomFactor: () => this.cfg.zoomFactor,
      setPointer: (p) => this.setPointer(p),
      viewChanged: () => this.viewChanged(),
      zoomExtents: () => this.zoomExtents(),
      chromeAction: (part, button, px, py) => this.chromeAction(part, button, px, py),
      hoverPart: (part) => this.hoverPart(part),
      emit: (k, v) => this.emit(k, v),
    }));

    this.off.push(deps.onSysvar(() => this.syncSysvars()));
    const themeChanged = (): void => { requestAnimationFrame(() => this.refreshTheme()); };
    document.addEventListener('nm:ui-settings-changed', themeChanged);
    document.addEventListener('formcad:prefs-changed', themeChanged);
    this.off.push(() => {
      document.removeEventListener('nm:ui-settings-changed', themeChanged);
      document.removeEventListener('formcad:prefs-changed', themeChanged);
    });
    this.syncSysvars();
  }

  get view(): ViewState { return this.cam.state(); }

  get renderer(): 'webgl2' | 'canvas2d' { return this.painter.kind; }

  private makePainter(): Painter {
    let p: Painter;
    try {
      p = new GlPainter(this.main);
    } catch {
      p = new CpuPainter(this.main);
    }
    p.onLost((restored) => {
      if (!restored) return;
      this.painter = this.makePainter();
      for (const c of this.store.chunks.values()) { c.gpu = null; c.uploaded = -1; c.dirty = true; }
      this.inf.gpu = null;
      this.jig.gpu = null;
      this.painter.resize(this.cssW, this.cssH, this.dpr);
      this.markAll();
    });
    if (this.cssW > 0) p.resize(this.cssW, this.cssH, this.dpr);
    return p;
  }

  private readCfg(): Cfg {
    const d = this.deps;
    const gu = d.sysvarVec('GRIDUNIT') ?? [0, 0];
    const su = d.sysvarVec('SNAPUNIT') ?? [0.5, 0.5];
    const unitX = gu[0] > 0 ? gu[0] : su[0] > 0 ? su[0] : 1;
    const unitY = gu[1] > 0 ? gu[1] : su[1] > 0 ? su[1] : unitX;
    return {
      gridOn: d.sysvar('GRIDMODE', 1) !== 0,
      unitX,
      unitY,
      major: d.sysvar('GRIDMAJOR', 5),
      iso: d.sysvar('SNAPSTYL', 0) === 1,
      isoPlane: d.sysvar('SNAPISOPAIR', 0),
      cursorSize: d.sysvar('CURSORSIZE', 5),
      pickbox: d.sysvar('PICKBOX', 3),
      gripSize: d.sysvar('GRIPSIZE', 5),
      zoomFactor: d.sysvar('ZOOMFACTOR', 60),
      opts: {
        lwOn: d.sysvar('LWDISPLAY', 0) !== 0,
        lwScale: d.sysvar('LWSCALE', 1) || 1,
        fillOn: d.sysvar('FILLMODE', 1) !== 0,
        trOn: d.sysvar('TRANSPARENCYDISPLAY', 1) !== 0,
        dashOn: true,
        ltScale: 1,
      },
    };
  }

  private syncSysvars(): void {
    const next = this.readCfg();
    const prev = this.cfg;
    this.cfg = next;
    if (prev.gridOn !== next.gridOn || prev.unitX !== next.unitX || prev.unitY !== next.unitY || prev.major !== next.major || prev.iso !== next.iso) this.dirtyBg = true;
    this.dirtyTop = true;
    if (this.store.setOptions(next.opts)) this.jigBand = NaN;
    this.schedule();
  }

  private refreshTheme(): void {
    this.theme = readTheme(this.host, this.probe);
    this.markAll();
  }

  private markAll(): void {
    this.dirtyBg = true;
    this.dirtyScene = true;
    this.dirtyTop = true;
    this.schedule();
  }

  private watchDpr(): void {
    const mq = window.matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`);
    const fn = (): void => {
      this.resize(this.cssW, this.cssH, true);
      this.watchDpr();
    };
    mq.addEventListener('change', fn, { once: true });
  }

  private loadChromeState(): void {
    try {
      const v = JSON.parse(this.deps.stored(VIEW_KEY) ?? '{}') as { cube?: boolean; ucs?: boolean };
      if (typeof v.cube === 'boolean') this.chrome.cube = v.cube;
      if (typeof v.ucs === 'boolean') this.chrome.ucs = v.ucs;
    } catch {
      return;
    }
  }

  private saveChromeState(): void {
    this.deps.store(VIEW_KEY, JSON.stringify({ cube: this.chrome.cube, ucs: this.chrome.ucs }));
  }

  private resize(w: number, h: number, force = false): void {
    const dpr = window.devicePixelRatio || 1;
    if (!force && w === this.cssW && h === this.cssH && dpr === this.dpr) return;
    if (w < 1 || h < 1) return;
    this.cssW = w;
    this.cssH = h;
    this.dpr = dpr;
    this.cam.setSize(w, h);
    this.chrome.resize(w, h);
    for (const c of [this.bg, this.top]) {
      c.width = Math.max(1, Math.round(w * dpr));
      c.height = Math.max(1, Math.round(h * dpr));
    }
    this.painter.resize(w, h, dpr);
    const first = !this.hasSize;
    this.hasSize = true;
    if (first && this.needFit) this.fitNow();
    this.markAll();
    this.runFrame();
    this.emit('view', this.cam.state());
  }

  private schedule(): void {
    if (this.raf) return;
    this.raf = requestAnimationFrame(() => { this.raf = 0; this.runFrame(); });
  }

  private runFrame(): void {
    if (this.raf) {
      cancelAnimationFrame(this.raf);
      this.raf = 0;
    }
    if (!this.hasSize) return;
    this.frames++;
    const cam = this.cam;
    const band = cam.band();
    const vb = { cx: cam.cx, cy: cam.cy, height: cam.height, wpp: 1 / cam.scale };
    this.store.refreshStale(vb, band, cam.visible());
    let more = false;
    if (this.store.pending()) {
      more = this.store.work(WORK_MS, vb, band, cam.visible());
      this.dirtyScene = true;
    }
    if (this.dirtyBg) this.paintBg();
    if (this.dirtyScene) this.paintScene(band);
    if (this.dirtyTop) this.paintTop();
    if (this.cursorDirty) {
      this.cursorDirty = false;
      this.dispatchCursor();
    }
    if (more) this.schedule();
  }

  private paintBg(): void {
    this.dirtyBg = false;
    const g: GridOptions = { on: this.cfg.gridOn, unitX: this.cfg.unitX, unitY: this.cfg.unitY, major: this.cfg.major, isometric: this.cfg.iso, axes: true };
    drawBackground(this.bgCtx, this.cssW, this.cssH, this.dpr, this.cam, this.theme, g, this.store.sheet, this.store.printable);
  }

  private paintScene(band: number): void {
    this.dirtyScene = false;
    const cam = this.cam;
    const dyn: DynLayer[] = [];
    const vis = cam.visible();
    const infinite = this.store.visibleInfinite();
    if (infinite.length) {
      const key = `${cam.cx}|${cam.cy}|${cam.height}|${cam.width}|${this.store.rev}|${infinite.length}`;
      if (key !== this.infKey) {
        this.infKey = key;
        const data = new BatchData();
        const em = new Emitter(this.store.makeCtx(cam.cx, cam.cy, band));
        for (const it of infinite) em.infinite(it, vis, data);
        data.close();
        this.inf.data = data;
        this.inf.ox = cam.cx;
        this.inf.oy = cam.cy;
        this.inf.version++;
      }
      dyn.push(this.inf);
    }
    if (this.jigItems.length) {
      if (this.jigBand !== band) this.buildJig(band);
      dyn.push(this.jig);
    }
    const paper = !!this.store.sheet;
    const bg = this.theme.bg;
    const pv: PaintView = {
      cx: cam.cx,
      cy: cam.cy,
      scale: cam.scale,
      width: this.cssW,
      height: this.cssH,
      dpr: this.dpr,
      contrast: paper || !isDark(bg) ? 0 : 1,
      bg: [bg[0] / 255, bg[1] / 255, bg[2] / 255],
      visible: vis,
    };
    this.syncLayout(band);
    this.painter.frame(pv, this.store.chunks.values(), dyn, this.under);
    if (this.store.dead.length) {
      for (const g of this.store.dead) this.painter.release(g);
      this.store.dead.length = 0;
    }
  }

  private syncLayout(band: number): void {
    const lay = this.store.layout;
    const key = lay ? `${this.store.layoutVersion}|${band}` : '';
    if (key === this.underKey) return;
    this.underKey = key;
    for (const d of this.under) if (d.gpu) this.painter.release(d.gpu);
    this.under.length = 0;
    if (!lay) return;
    for (const vp of lay.viewports) {
      if (!vp.on || !vp.contentVisible || !vp.items.length) continue;
      const d = newDyn();
      d.ox = (vp.bounds[0] + vp.bounds[2]) / 2;
      d.oy = (vp.bounds[1] + vp.bounds[3]) / 2;
      const data = new BatchData();
      const em = new Emitter(this.store.makeCtx(d.ox, d.oy, band));
      for (const it of vp.items) em.emit(it, data);
      data.close();
      d.data = data;
      d.version = 1;
      const ring = vp.outline.length >= 3 ? vp.outline : [[vp.bounds[0], vp.bounds[1]], [vp.bounds[2], vp.bounds[1]], [vp.bounds[2], vp.bounds[3]], [vp.bounds[0], vp.bounds[3]]];
      d.clip = ring.flatMap((p) => [p[0], p[1]]);
      this.under.push(d);
    }
  }

  private paintActiveViewport(ctx: CanvasRenderingContext2D): void {
    const lay = this.store.layout;
    const vp = lay ? lay.viewports.find((v) => v.h === lay.active) : undefined;
    if (!vp) return;
    const ring = vp.outline.length >= 3 ? vp.outline : [[vp.bounds[0], vp.bounds[1]], [vp.bounds[2], vp.bounds[1]], [vp.bounds[2], vp.bounds[3]], [vp.bounds[0], vp.bounds[3]]];
    ctx.save();
    ctx.beginPath();
    ring.forEach((p, i) => {
      const [x, y] = this.cam.toScreen(p[0], p[1]);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.closePath();
    ctx.strokeStyle = css(this.theme.accent);
    ctx.lineWidth = 3;
    ctx.stroke();
    ctx.restore();
  }

  private buildJig(band: number): void {
    this.jigBand = band;
    const cam = this.cam;
    const data = new BatchData();
    const em = new Emitter(this.store.makeCtx(cam.cx, cam.cy, band));
    for (const it of this.jigItems) em.emit(it, data);
    data.close();
    this.jig.data = data;
    this.jig.ox = cam.cx;
    this.jig.oy = cam.cy;
    this.jig.version++;
  }

  private cursorMode(): CursorMode { return this.override ?? 'point'; }

  private paintTop(): void {
    this.dirtyTop = false;
    const ctx = this.topCtx;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, this.cssW, this.cssH);
    const env: OverlayEnv = {
      cam: this.cam,
      th: this.theme,
      store: this.store,
      marker: this.deps.markerSize(),
      gripSize: this.cfg.gripSize,
      pointer: this.pointer,
      width: this.cssW,
      height: this.cssH,
    };
    this.paintActiveViewport(ctx);
    drawOverlays(ctx, env, this.overlays);
    const system = this.deps.systemCursor();
    const part = this.chrome.hover;
    if (this.pointer && !system && !part && !this.chrome.menuOpen) {
      drawCursor(ctx, {
        sizePct: this.cfg.cursorSize,
        pickbox: this.cfg.pickbox,
        mode: this.cursorMode(),
        dark: this.store.sheet ? false : isDark(this.theme.bg),
        iso: this.cfg.iso ? (this.cfg.isoPlane === 1 ? [30, 150] : this.cfg.isoPlane === 2 ? [30, 90] : [90, 150]) : null,
        x: this.pointer.px,
        y: this.pointer.py,
        width: this.cssW,
        height: this.cssH,
      });
    }
    this.chrome.draw(ctx, this.theme, this.pointer);
  }

  private viewChanged(): void {
    this.dirtyBg = true;
    this.dirtyScene = true;
    this.dirtyTop = true;
    this.cursorDirty = true;
    this.emit('view', this.cam.state());
    this.schedule();
  }

  private setPointer(p: { px: number; py: number } | null): void {
    this.pointer = p;
    this.dirtyTop = true;
    this.cursorDirty = true;
    if (p) {
      const [x, y] = this.cam.toWorld(p.px, p.py);
      this.emit('cursor', { x, y });
    } else this.emit('cursor', null);
    this.schedule();
  }

  private dispatchCursor(): void {
    if (this.pointer) {
      const [x, y] = this.effective ?? this.cam.toWorld(this.pointer.px, this.pointer.py);
      document.dispatchEvent(new CustomEvent('formcad:cursor', { detail: { x, y, z: 0 } }));
    } else document.dispatchEvent(new CustomEvent('formcad:cursor', { detail: null }));
  }

  private hoverPart(part: ChromePart): void {
    if (this.chrome.hover === part) return;
    this.chrome.hover = part;
    this.host.classList.toggle('is-chrome', part !== null);
    this.dirtyTop = true;
    this.schedule();
  }

  private chromeAction(part: ChromePart, button: number, px: number, py: number): void {
    const c = this.chrome;
    if (c.menuOpen) {
      const id = part === 'menu' ? c.menuPick(px, py) : null;
      c.closeMenu();
      this.dirtyTop = true;
      this.schedule();
      if (id === 'home') this.zoomExtents();
      else if (id === 'hide-cube') this.setViewCubeVisible(false);
      else if (id === 'hide-ucs') this.setUcsIconVisible(false);
      return;
    }
    if (button === 2) {
      if (part === 'top' || part === 'home' || part === 'ring') c.openMenu('cube', px, py, [{ id: 'home', label: 'Home' }, { id: 'hide-cube', label: 'Hide ViewCube' }]);
      else if (part === 'wcs' || part === 'ucs') c.openMenu('ucs', px, py, [{ id: 'wcs', label: 'World (WCS)', checked: true }, { id: 'hide-ucs', label: 'Hide UCS Icon' }]);
    } else if (part === 'top' || part === 'home') this.zoomExtents();
    else if (part === 'ring') this.deps.notify('Rotating the view is not available in the plan view.');
    else if (part === 'wcs' || part === 'ucs') c.openMenu('ucs', px, py, [{ id: 'wcs', label: 'World (WCS)', checked: true }, { id: 'hide-ucs', label: 'Hide UCS Icon' }]);
    this.dirtyTop = true;
    this.schedule();
  }

  private fitNow(): void {
    if (!this.hasSize) {
      this.needFit = true;
      return;
    }
    this.needFit = false;
    const ext = this.store.sheet ?? this.store.extents();
    let box: Rect | null = ext && ext[2] > ext[0] || ext && ext[3] > ext[1] ? ext : null;
    if (!box) {
      const lo = this.deps.sysvarVec('LIMMIN') ?? [0, 0];
      const hi = this.deps.sysvarVec('LIMMAX') ?? [420, 297];
      box = [lo[0], lo[1], hi[0], hi[1]];
    }
    this.cam.fit(box);
    this.viewChanged();
  }

  setDocument(id: string | null): void {
    if (id === this.docId) return;
    this.docId = id;
    this.store.clear();
    this.jigItems = [];
    this.overlays.set('jig', null);
    this.needFit = true;
    this.markAll();
    if (id) void this.pull(true);
    else this.fitNow();
  }

  setSpace(space: string): void {
    if (space === this.space) return;
    this.space = space;
    this.needFit = true;
    if (this.docId) void this.pull(true);
  }

  refresh(): void {
    if (this.docId) void this.pull(false);
  }

  applyDocEvent(e: DocEventInfo): void {
    if (e.id !== this.docId) return;
    if (e.reason === 'view' && e.view) {
      this.applyView(e.view);
      return;
    }
    if (e.rev !== this.store.rev) void this.pull(false);
  }

  private applyView(v: NonNullable<DocEventInfo['view']>): void {
    if (v.mode === 'extents') {
      this.fitNow();
      return;
    }
    const c = v.center;
    if (Array.isArray(c) && c.length >= 2 && typeof v.height === 'number') {
      this.cam.set(c[0], c[1], v.height);
      this.viewChanged();
    }
  }

  private async pull(full: boolean): Promise<void> {
    if (!this.docId) return;
    if (this.pulling) {
      this.pullAgain = true;
      if (full) this.store.rev = -1;
      return;
    }
    this.pulling = true;
    const id = this.docId;
    try {
      do {
        this.pullAgain = false;
        const since = full || this.store.rev < 0 ? undefined : this.store.rev;
        full = false;
        const p = await this.deps.fetchDisplay(id, since, this.space === 'model' ? undefined : this.space);
        if (this.docId !== id) break;
        this.store.apply(p);
        if (this.needFit && this.hasSize) this.fitNow();
        this.dirtyScene = true;
        this.schedule();
      } while (this.pullAgain);
    } catch {
      return;
    } finally {
      this.pulling = false;
    }
  }

  worldFromScreen(px: number, py: number): Pt { return this.cam.toWorld(px, py); }

  screenFromWorld(x: number, y: number): Pt { return this.cam.toScreen(x, y); }

  markAt(px: number, py: number): MarkHit | null { return hitMark(this.cam, this.store, this.cssW, this.cssH, px, py); }

  markHandles(id: number): Handle[] { return handlesOf(this.store, id); }

  marked(): number { return this.store.bars.size; }

  setMarkHover(hit: MarkHit | null): void {
    const a = markState.hover;
    if (a === hit || (a && hit && a.id === hit.id && a.kind === hit.kind)) return;
    markState.hover = hit;
    this.dirtyTop = true;
    this.schedule();
  }

  pickAt(px: number, py: number, aperturePx?: number): Hit[] {
    const [x, y] = this.cam.toWorld(px, py);
    const ap = (aperturePx ?? Math.max(2, this.cfg.pickbox * 1.5)) / this.cam.scale;
    const tol = 0.25 / this.cam.scale;
    const { tree, list } = this.store.index();
    const hits: Hit[] = [];
    const take = (it: DisplayItem, d: number): void => {
      if (d <= ap) hits.push({ handle: it.h as Handle, dist: d, order: it.order });
    };
    if (list.length < 64) {
      for (const it of list) {
        const b = it.bounds;
        if (x < b[0] - ap || x > b[2] + ap || y < b[1] - ap || y > b[3] + ap) continue;
        take(it, distanceTo(it, x, y, tol));
      }
    } else {
      tree.query(x - ap, y - ap, x + ap, y + ap, (i) => {
        const it = list[i];
        take(it, distanceTo(it, x, y, tol));
      });
    }
    for (const it of this.store.visibleInfinite()) take(it, distanceToInfinite(it, x, y));
    hits.sort((a, b) => a.dist - b.dist || b.order - a.order);
    return hits;
  }

  boxQuery(rect: Rect, crossing: boolean): Handle[] {
    const r: Rect = [Math.min(rect[0], rect[2]), Math.min(rect[1], rect[3]), Math.max(rect[0], rect[2]), Math.max(rect[1], rect[3])];
    const tol = 0.25 / this.cam.scale;
    const { tree, list } = this.store.index();
    const found: DisplayItem[] = [];
    tree.query(r[0], r[1], r[2], r[3], (i) => {
      const it = list[i];
      const b = it.bounds;
      if (crossing) {
        if (touchesRect(it, r, tol)) found.push(it);
      } else if (b[0] >= r[0] && b[2] <= r[2] && b[1] >= r[1] && b[3] <= r[3]) found.push(it);
    });
    found.sort((a, b) => a.order - b.order);
    return found.map((it) => it.h as Handle);
  }

  itemsIn(rect: Rect): DisplayItem[] {
    const { tree, list } = this.store.index();
    const out: DisplayItem[] = [];
    tree.query(rect[0], rect[1], rect[2], rect[3], (i) => { out.push(list[i]); });
    for (const it of this.store.visibleInfinite()) out.push(it);
    return out;
  }

  item(h: Handle): DisplayItem | undefined { return this.store.items.get(h); }

  setEffectivePoint(p: Pt | null): void {
    this.effective = p;
    this.cursorDirty = true;
    this.schedule();
  }

  setOverlay(name: OverlayName, items: OverlayItems | null): void {
    if (name === 'jig') {
      this.jigItems = (items as DisplayItem[] | null) ?? [];
      this.overlays.set('jig', this.jigItems);
      this.jigBand = NaN;
      this.dirtyScene = true;
    } else {
      this.overlays.set(name, items as unknown[] | null);
      this.dirtyTop = true;
    }
    this.schedule();
  }

  setCursorMode(mode: CursorMode | null): void {
    if (this.override === mode) return;
    this.override = mode;
    this.dirtyTop = true;
    this.schedule();
  }

  setView(cx: number, cy: number, height: number): void {
    if (this.cam.set(cx, cy, height)) this.viewChanged();
  }

  zoomExtents(): void {
    this.fitNow();
  }

  zoomWindow(rect: Rect): void {
    this.cam.window([Math.min(rect[0], rect[2]), Math.min(rect[1], rect[3]), Math.max(rect[0], rect[2]), Math.max(rect[1], rect[3])]);
    this.viewChanged();
  }

  panBy(dx: number, dy: number): void {
    this.cam.panBy(dx, dy);
    this.viewChanged();
  }

  setViewCubeVisible(on: boolean): void {
    this.chrome.cube = on;
    this.saveChromeState();
    this.dirtyTop = true;
    this.schedule();
  }

  setUcsIconVisible(on: boolean): void {
    this.chrome.ucs = on;
    this.saveChromeState();
    this.dirtyTop = true;
    this.schedule();
  }

  stats(): { items: number; chunks: number; builds: number; frames: number } {
    return { items: this.store.items.size, chunks: this.store.chunks.size, builds: this.store.builds, frames: this.frames };
  }

  on<K extends keyof CanvasEvents>(event: K, fn: (e: CanvasEvents[K]) => void): () => void {
    let set = this.listeners.get(event);
    if (!set) { set = new Set(); this.listeners.set(event, set); }
    set.add(fn as (e: never) => void);
    return () => { set.delete(fn as (e: never) => void); };
  }

  emit<K extends keyof CanvasEvents>(event: K, value: CanvasEvents[K]): void {
    const set = this.listeners.get(event);
    if (!set) return;
    for (const fn of set) (fn as (e: CanvasEvents[K]) => void)(value);
  }
}
