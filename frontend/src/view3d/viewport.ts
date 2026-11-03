import * as THREE from 'three';
import { t } from '../ui/i18n';
import { BodyView } from './body-view';
import { ViewCube } from './cube';
import { ConstructionGrid } from './grid';
import { Highlight, highlightColor } from './highlight';
import type { ViewLayer } from './layer';
import { EDGES_VISIBLE, FACE_VISIBLE, FACES_OCCLUDE, ModeKit, readPalette, type Palette } from './kit';
import { Overlay, resolveInk } from './overlay';
import { Picker, type EdgeHit, type FaceHit } from './pick';
import { RefGeometry, type RefItem } from './refgeo';
import { rayHit, STARTING_PLANE } from './planes';
import { Rig } from './rig';
import type { AngleConvention, CameraSpec, ConstructionPlane, DisplayMode, PickLevel, PlaneSpec, Projection, SceneModel, SelectionState, SnapHit, SnapKind, Vec3, ViewListener } from './types';
import { MODE_LABELS, MODE_ORDER } from './types';
import { directionFor, HOME_DIRECTION, standardView } from './views';

interface Target { snap: SnapHit | null; edge: EdgeHit | null; face: FaceHit | null }
type PlaneJob = null | { kind: 'three'; pts: Vec3[] } | { kind: 'face' };

const EMPTY: SelectionState = { bodies: [], faces: [], edges: [] };
const sameSel = (a: SelectionState, b: SelectionState): boolean => JSON.stringify(a) === JSON.stringify(b);

export class Viewport3D {
  readonly canvas = document.createElement('canvas');
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly rig: Rig;
  readonly kit: ModeKit;
  readonly overlay = new Overlay();
  mode: DisplayMode = 'shadedEdges';
  level: PickLevel = 'any';
  angle: AngleConvention = 'third';
  snapOn = true;
  snapAllowed: (k: SnapKind) => boolean = () => true;
  gridOn = true;
  gridSnap = false;
  plane: ConstructionPlane = STARTING_PLANE;
  sel: SelectionState = { bodies: [], faces: [], edges: [] };
  model: SceneModel = { rev: 0, bodies: [], snaps: [] };
  frames = 0;
  lastCpuMs = 0;
  onPick: ((s: SelectionState) => void) | null = null;
  private readonly group = new THREE.Group();
  private readonly previewGroup = new THREE.Group();
  private previewViews: BodyView[] = [];
  private bodiesHidden = false;
  private readonly refGeo = new RefGeometry();
  private refItems: RefItem[] = [];
  private readonly layers: ViewLayer[] = [];
  private readonly views = new Map<number, BodyView>();
  private readonly hemi = new THREE.HemisphereLight(0xffffff, 0x70767f, 1.25);
  private readonly key = new THREE.DirectionalLight(0xffffff, 2.1);
  private readonly grid: ConstructionGrid;
  private readonly cube: ViewCube;
  private readonly picker: Picker;
  private readonly hoverHL: Highlight;
  private readonly selHL: Highlight;
  private readonly probe: HTMLElement;
  private pal: Palette;
  private w = 1;
  private h = 1;
  private dpr = 1;
  private raf = 0;
  private pickRaf = 0;
  private isActive = false;
  private interacting = false;
  private cubeOnly = false;
  private pointer: { x: number; y: number } | null = null;
  private down: { x: number; y: number; t: number; button: number; cube: boolean } | null = null;
  private hover: Target = { snap: null, edge: null, face: null };
  private hoverSel: SelectionState = EMPTY;
  private cycle = 0;
  private job: PlaneJob = null;
  private section = { on: false, flip: false, offset: 0 };
  private tip = '';
  private readonly ro: ResizeObserver;
  private readonly off: Array<() => void> = [];

  constructor(readonly host: HTMLElement, private readonly ls: ViewListener) {
    this.canvas.className = 'v3-canvas';
    this.canvas.tabIndex = -1;
    this.canvas.setAttribute('aria-label', 'Model view');
    this.probe = document.createElement('div');
    this.probe.className = 'v3-probe';
    this.probe.setAttribute('aria-hidden', 'true');
    host.append(this.canvas, this.overlay.canvas, this.probe);
    this.pal = readPalette(host);
    this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true, alpha: false, powerPreference: 'high-performance' });
    this.renderer.setClearColor(this.pal.bg, 1);
    this.renderer.localClippingEnabled = true;
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.renderer.setPixelRatio(this.dpr);
    this.kit = new ModeKit(this.pal);
    this.rig = new Rig(this.canvas);
    this.scene.add(this.group, this.previewGroup, this.refGeo.group, this.hemi, this.key, this.key.target);
    this.grid = new ConstructionGrid(this.plane, this.pal);
    this.scene.add(this.grid.mesh);
    this.grid.ask = (a) => (this.ls.askGrid ? this.ls.askGrid(a) : Promise.reject(new Error('No engine')));
    this.grid.onLines = () => this.invalidate();
    this.cube = new ViewCube(this.pal);
    const look = (id: number): BodyView | undefined => this.views.get(id);
    this.hoverHL = new Highlight(look, highlightColor(this.pal, 'hover'), this.kit.resolution);
    this.selHL = new Highlight(look, highlightColor(this.pal, 'select'), this.kit.resolution);
    this.scene.add(this.hoverHL.group, this.selHL.group);
    this.picker = new Picker(this.rig, () => (this.bodiesHidden ? [] : [...this.views.values()]), () => (this.snapOn && !this.bodiesHidden ? this.model.snaps : []));
    this.overlay.ink = resolveInk(this.probe);
    this.rig.onChange = () => { this.invalidate(); if (!this.interacting) this.schedulePick(); };
    this.rig.onInteract = (on) => { this.interacting = on; if (on) this.clearHover(); };
    this.rig.onSettled = () => this.schedulePick();
    this.bind();
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(host);
    this.resize();
  }

  get camera(): THREE.PerspectiveCamera | THREE.OrthographicCamera { return this.rig.camera; }
  get active(): boolean { return this.isActive; }
  get projection(): Projection { return this.rig.projection; }
  get hasBodies(): boolean { return this.views.size > 0; }
  get gridStep(): number { return this.grid.step; }
  get pending(): string { return this.job ? (this.job.kind === 'three' ? `three:${this.job.pts.length}` : 'face') : ''; }

  private bind(): void {
    const c = this.canvas;
    const on = <K extends keyof HTMLElementEventMap>(type: K, fn: (e: HTMLElementEventMap[K]) => void, opts?: AddEventListenerOptions): void => {
      c.addEventListener(type, fn as EventListener, opts);
      this.off.push(() => c.removeEventListener(type, fn as EventListener, opts));
    };
    on('pointermove', (e) => this.onMove(e));
    on('pointerleave', () => this.onLeave());
    on('pointerdown', (e) => this.onDown(e), { capture: true });
    on('pointerup', (e) => this.onUp(e));
    on('contextmenu', (e) => e.preventDefault());
    on('keydown', (e) => this.onKey(e));
    on('view3d:extents' as keyof HTMLElementEventMap, () => this.zoomExtents(true));
  }

  private rel(e: MouseEvent): { x: number; y: number } {
    const r = this.canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  private onMove(e: PointerEvent): void {
    const p = this.rel(e);
    this.pointer = p;
    if (this.interacting || (e.buttons & 7) !== 0) return;
    if (this.cube.hover(p.x, p.y, this.w)) this.invalidate();
    this.schedulePick();
  }

  private onLeave(): void {
    this.pointer = null;
    if (this.cube.leave()) this.invalidate();
    this.clearHover();
    this.ls.onCursor?.(null);
  }

  private onDown(e: PointerEvent): void {
    const p = this.rel(e);
    this.canvas.focus({ preventScroll: true });
    this.down = { x: p.x, y: p.y, t: performance.now(), button: e.button, cube: this.cube.contains(p.x, p.y, this.w) };
  }

  private onUp(e: PointerEvent): void {
    const d = this.down;
    this.down = null;
    if (!d || d.button !== 0) return;
    const p = this.rel(e);
    if (Math.hypot(p.x - d.x, p.y - d.y) > 4 || performance.now() - d.t > 700) return;
    if (d.cube) {
      const dir = this.cube.pick(p.x, p.y, this.w);
      if (dir) this.lookFrom(directionFor(dir));
      return;
    }
    this.click(p.x, p.y, e.shiftKey || e.ctrlKey || e.metaKey);
  }

  private onKey(e: KeyboardEvent): void {
    if (e.key === 'Escape') {
      if (this.job) { this.cancelPlaneJob(); e.preventDefault(); return; }
      if (this.sel.bodies.length || this.sel.faces.length || this.sel.edges.length) { this.setSelection(EMPTY, true); e.preventDefault(); }
    } else if (e.key === 'Tab' && this.snapOn) {
      this.cycle++;
      this.schedulePick();
      e.preventDefault();
    } else if (!e.ctrlKey && !e.metaKey && !e.altKey) {
      const ids = ['front', 'back', 'left', 'right', 'top', 'bottom', 'iso'];
      const n = /^(?:Digit|Numpad)([1-7])$/.exec(e.code);
      if (n) { this.showStandardView(ids[Number(n[1]) - 1]); e.preventDefault(); }
      else if (e.key === 'Home') { this.zoomExtents(true); e.preventDefault(); }
    }
  }

  warm(): void {
    const current = this.mode;
    const rest = MODE_ORDER.filter((m) => m !== current);
    const step = (): void => {
      const m = rest.shift();
      if (!m || !this.isActive) return;
      const keep = this.mode;
      this.mode = m;
      this.applyAll();
      this.renderer.compile(this.scene, this.rig.camera);
      this.mode = keep;
      this.applyAll();
      this.invalidate();
      const idle = (window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number }).requestIdleCallback;
      if (idle) idle(step, { timeout: 4000 }); else window.setTimeout(step, 200);
    };
    step();
  }

  private pickTarget(px: number, py: number): Target {
    this.picker.sync(this.w, this.h);
    const lvl = this.level;
    const occl = FACES_OCCLUDE[this.mode];
    const facesShown = FACE_VISIBLE[this.mode];
    const edgesShown = EDGES_VISIBLE[this.mode];
    const needFace = facesShown && (lvl !== 'edge' || occl || this.snapOn);
    const face = needFace ? this.picker.face(px, py) : null;
    let edge: EdgeHit | null = null;
    if (edgesShown && lvl !== 'face') {
      edge = this.picker.edge(px, py, 7);
      if (edge && occl && face && edge.depth > face.depth + Math.max(face.depth * 2e-3, 1e-6)) edge = null;
    }
    let snap: SnapHit | null = null;
    if (this.snapOn) {
      const list = this.picker.snapCandidates(px, py, 10, this.snapAllowed).filter((s) => this.picker.visibleAt(s, occl));
      if (list.length) snap = list[this.cycle % list.length];
    }
    return { snap, edge, face };
  }

  private selectionFor(tg: Target): SelectionState {
    const lvl = this.level;
    if (lvl === 'edge') return tg.edge ? { bodies: [], faces: [], edges: [{ body: tg.edge.body.data.id, edge: tg.edge.edge }] } : EMPTY;
    if (lvl === 'face') return tg.face ? { bodies: [], faces: [{ body: tg.face.body.data.id, face: tg.face.face }], edges: [] } : EMPTY;
    if (lvl === 'body') {
      const b = tg.edge?.body ?? tg.face?.body;
      return b ? { bodies: [b.data.id], faces: [], edges: [] } : EMPTY;
    }
    if (tg.edge) return { bodies: [], faces: [], edges: [{ body: tg.edge.body.data.id, edge: tg.edge.edge }] };
    if (tg.face) return { bodies: [], faces: [{ body: tg.face.body.data.id, face: tg.face.face }], edges: [] };
    return EMPTY;
  }

  private describe(tg: Target): string {
    if (tg.snap) return t(tg.snap.label);
    if (tg.edge) return `${t('Edge')} ${tg.edge.edge} · ${tg.edge.body.data.name}`;
    if (tg.face) return `${t('Face')} ${tg.face.face} · ${tg.face.body.data.name}`;
    return '';
  }

  private schedulePick(): void {
    if (this.pickRaf || !this.isActive) return;
    this.pickRaf = requestAnimationFrame(() => { this.pickRaf = 0; this.pickNow(); });
  }

  private pickNow(): void {
    const p = this.pointer;
    if (!p || this.interacting) return;
    if (this.cube.contains(p.x, p.y, this.w)) {
      this.setHover({ snap: null, edge: null, face: null }, this.cube.describe(p.x, p.y, this.w));
      return;
    }
    const tg = this.pickTarget(p.x, p.y);
    this.setHover(tg, this.describe(tg));
    const pt = this.cursorPoint(tg, p);
    this.ls.onCursor?.(pt);
  }

  private cursorPoint(tg: Target, p: { x: number; y: number }): Vec3 | null {
    if (tg.snap) return tg.snap.p;
    if (tg.edge) return tg.edge.point;
    if (tg.face) return tg.face.point;
    const ray = this.rig.ndcToRay((p.x / this.w) * 2 - 1, -((p.y / this.h) * 2 - 1));
    return rayHit(this.plane, [ray.origin.x, ray.origin.y, ray.origin.z], [ray.direction.x, ray.direction.y, ray.direction.z]);
  }

  private setHover(tg: Target, text: string): void {
    this.hover = tg;
    this.tip = text;
    const s = this.pointer && this.job ? EMPTY : this.selectionFor(tg);
    if (!sameSel(s, this.hoverSel)) {
      this.hoverSel = s;
      this.syncHighlights();
    }
    this.ls.onHover?.(text);
    this.invalidate();
  }

  private clearHover(): void {
    this.hover = { snap: null, edge: null, face: null };
    this.tip = '';
    if (this.hoverSel !== EMPTY) { this.hoverSel = EMPTY; this.syncHighlights(); }
    this.invalidate();
  }

  private click(px: number, py: number, additive: boolean): void {
    const tg = this.pickTarget(px, py);
    if (this.job) { this.jobClick(tg, px, py); return; }
    const hit = this.selectionFor(tg);
    if (this.snapOn && tg.snap) {
      const pt = tg.snap.p;
      this.ls.onPoint?.(pt, tg.snap);
    } else {
      const pt = this.cursorPoint(tg, { x: px, y: py });
      if (pt) this.ls.onPoint?.(pt, null);
    }
    if (!additive) { this.setSelection(hit, true); return; }
    const next: SelectionState = { bodies: [...this.sel.bodies], faces: [...this.sel.faces], edges: [...this.sel.edges] };
    for (const b of hit.bodies) toggle(next.bodies, b, (x, y) => x === y);
    for (const f of hit.faces) toggle(next.faces, f, (x, y) => x.body === y.body && x.face === y.face);
    for (const e of hit.edges) toggle(next.edges, e, (x, y) => x.body === y.body && x.edge === y.edge);
    this.setSelection(next, true);
  }

  private jobClick(tg: Target, px: number, py: number): void {
    const job = this.job;
    if (!job) return;
    if (job.kind === 'face') {
      if (!tg.face) { this.ls.onHint?.(t('Click a face to put the plane on it.')); return; }
      this.job = null;
      this.requestPlane({ face: { point: tg.face.point, normal: tg.face.normal } });
      this.ls.onHint?.('');
      return;
    }
    const pt = tg.snap?.p ?? tg.edge?.point ?? tg.face?.point ?? this.cursorPoint(tg, { x: px, y: py });
    if (!pt) return;
    job.pts.push(pt);
    if (job.pts.length < 3) {
      this.ls.onHint?.(t(job.pts.length === 1 ? 'Plane by three points: click the point on the X direction.' : 'Plane by three points: click a point on the plane, off the line.'));
      this.invalidate();
      return;
    }
    const pts = [job.pts[0], job.pts[1], job.pts[2]];
    this.job = null;
    this.ls.onHint?.('');
    this.requestPlane({ points: pts }, t('The three points are on one line. Try again.'));
    this.invalidate();
  }

  private requestPlane(spec: PlaneSpec, failHint?: string): void {
    if (!this.ls.askPlane) return;
    this.ls.askPlane(spec).then((p) => this.setPlane(p)).catch((e: unknown) => {
      this.ls.onHint?.(failHint ?? (e instanceof Error ? e.message : t('The plane could not be made.')));
    });
  }

  setSelection(s: SelectionState, notify: boolean): void {
    if (sameSel(s, this.sel)) return;
    this.sel = { bodies: [...s.bodies], faces: [...s.faces], edges: [...s.edges] };
    this.syncHighlights();
    this.invalidate();
    if (notify) {
      if (this.onPick) this.onPick(this.sel);
      else this.ls.onSelection?.(this.sel);
    }
  }

  setPreview(model: SceneModel | null): void {
    const next = (model?.bodies ?? []).map((b) => new BodyView(b));
    for (const v of next) { v.apply(this.kit, this.mode); this.previewGroup.add(v.group); }
    for (const v of this.previewViews) { this.previewGroup.remove(v.group); v.dispose(); }
    this.previewViews = next;
    this.group.visible = next.length === 0 && !this.bodiesHidden;
    this.invalidate();
  }

  setBodiesHidden(hidden: boolean): void {
    if (hidden === this.bodiesHidden) return;
    this.bodiesHidden = hidden;
    this.group.visible = this.previewViews.length === 0 && !hidden;
    this.invalidate();
  }

  get previewing(): boolean { return this.previewViews.length > 0; }

  setReference(items: RefItem[]): void {
    this.refItems = items;
    this.refGeo.set(items, Math.max(this.rig.radius * 0.7, 1), this.pal);
    this.invalidate();
  }

  get referenceCount(): number { return this.refItems.length; }

  addLayer(layer: ViewLayer): void {
    this.layers.push(layer);
    this.scene.add(layer.group);
    layer.resolution?.(this.w, this.h);
    this.invalidate();
  }

  project(p: Vec3): { x: number; y: number } | null {
    this.picker.sync(this.w, this.h);
    return this.picker.project(p);
  }

  rayAt(px: number, py: number): { origin: Vec3; direction: Vec3 } {
    const ray = this.rig.ndcToRay((px / this.w) * 2 - 1, -((py / this.h) * 2 - 1));
    return { origin: [ray.origin.x, ray.origin.y, ray.origin.z], direction: [ray.direction.x, ray.direction.y, ray.direction.z] };
  }

  get size(): { w: number; h: number } { return { w: this.w, h: this.h }; }

  get bodyViews(): ReadonlyMap<number, BodyView> { return this.views; }

  private paintMat: THREE.Material | null = null;

  private clipPaint(planes: THREE.Plane[]): void {
    if (!this.paintMat) return;
    this.paintMat.clippingPlanes = planes.length ? planes : null;
    this.paintMat.needsUpdate = true;
  }

  setPaint(map: Map<number, Float32Array | null>, mat: THREE.Material | null): void {
    this.paintMat = mat;
    this.clipPaint(this.kit.clip);
    for (const [id, vals] of map) this.views.get(id)?.setPaint(vals, mat);
    this.applyAll();
    this.invalidate();
  }

  setPoses(map: Map<number, THREE.Matrix4 | null> | null): void {
    for (const [id, v] of this.views) v.setPose(map?.get(id) ?? null);
    this.invalidate();
  }

  fitLayers(): void {
    this.updateBounds();
    this.zoomExtents(false);
  }

  setBodySelection(ids: number[]): void {
    const keep = ids.filter((i) => this.views.has(i));
    this.setSelection({ bodies: keep, faces: [], edges: [] }, false);
  }

  private syncHighlights(): void {
    const faces = FACE_VISIBLE[this.mode], lines = EDGES_VISIBLE[this.mode];
    this.selHL.show(this.sel, faces, lines);
    this.hoverHL.show(this.hoverSel, faces, lines);
  }

  startPlaneByThreePoints(): void {
    this.job = { kind: 'three', pts: [] };
    this.ls.onHint?.(t('Plane by three points: click the origin.'));
    this.invalidate();
  }

  startPlaneOnFace(): void {
    if (this.sel.faces.length === 1) {
      const f = this.sel.faces[0];
      const v = this.views.get(f.body);
      if (v) {
        const info = this.faceFrame(v, f.face);
        if (info) { this.requestPlane({ face: { point: info.point, normal: info.normal } }); return; }
      }
    }
    this.job = { kind: 'face' };
    this.ls.onHint?.(t('Click a face to put the plane on it.'));
  }

  private faceFrame(v: BodyView, face: number): { point: Vec3; normal: Vec3 } | null {
    const tris = v.trianglesOf(face);
    if (!tris.length) return null;
    const n = v.data.normals;
    const a = v.data.indices[tris[0] * 3] * 3;
    return { point: v.faceCentroid(face), normal: [n[a], n[a + 1], n[a + 2]] };
  }

  cancelPlaneJob(): void {
    if (!this.job) return;
    this.job = null;
    this.ls.onHint?.('');
    this.invalidate();
  }

  setPlane(p: ConstructionPlane): void {
    this.plane = p;
    this.grid.setPlane(p);
    this.applySection();
    this.ls.onPlane?.(p, this.gridOn);
    this.invalidate();
  }

  setWorldPlane(id: string): void {
    this.requestPlane({ world: id });
  }

  setGrid(on: boolean): void {
    this.gridOn = on;
    this.grid.mesh.visible = on;
    this.ls.onPlane?.(this.plane, on);
    this.invalidate();
  }

  lookAtPlane(animate = true): void {
    const z = this.plane.z;
    this.lookFrom(directionFor([z[0], z[1], z[2]]), animate);
  }

  setSection(on: boolean, flip = this.section.flip, offset = this.section.offset): void {
    this.section = { on, flip, offset };
    this.applySection();
  }

  get sectionState(): { on: boolean; flip: boolean; offset: number } { return { ...this.section }; }

  private applySection(): void {
    const planes: THREE.Plane[] = [];
    if (this.section.on) {
      const n = new THREE.Vector3(...this.plane.z).multiplyScalar(this.section.flip ? -1 : 1);
      const o = new THREE.Vector3(...this.plane.origin).addScaledVector(new THREE.Vector3(...this.plane.z), this.section.offset);
      planes.push(new THREE.Plane().setFromNormalAndCoplanarPoint(n, o));
    }
    this.kit.applyClip(planes);
    this.clipPaint(planes);
    this.selHL.setClip(planes);
    this.hoverHL.setClip(planes);
    this.applyAll();
    this.invalidate();
  }

  setScene(model: SceneModel, keepView: boolean): void {
    for (const v of this.views.values()) { this.group.remove(v.group); v.dispose(); }
    this.views.clear();
    this.model = model;
    for (const b of model.bodies) {
      const v = new BodyView(b);
      this.views.set(b.id, v);
      this.group.add(v.group);
    }
    const keep = (s: SelectionState): SelectionState => ({
      bodies: s.bodies.filter((i) => this.views.has(i)),
      faces: s.faces.filter((f) => this.views.get(f.body)?.faceIds.includes(f.face)),
      edges: s.edges.filter((e) => this.views.get(e.body)?.edgeIds.includes(e.edge)),
    });
    this.sel = keep(this.sel);
    this.hoverSel = EMPTY;
    this.hover = { snap: null, edge: null, face: null };
    this.updateBounds();
    this.applyAll();
    this.selHL.refresh();
    this.hoverHL.refresh();
    this.syncHighlights();
    if (!keepView) this.zoomExtents(false);
    for (const l of this.layers) l.sceneChanged?.();
    this.invalidate();
  }

  private bounds(): { min: Vec3; max: Vec3 } {
    const min: Vec3 = [Infinity, Infinity, Infinity], max: Vec3 = [-Infinity, -Infinity, -Infinity];
    if (!this.bodiesHidden) for (const v of this.views.values()) for (let k = 0; k < 3; k++) { min[k] = Math.min(min[k], v.min[k]); max[k] = Math.max(max[k], v.max[k]); }
    for (const l of this.layers) {
      const b = l.bounds?.();
      if (b) for (let k = 0; k < 3; k++) { min[k] = Math.min(min[k], b.min[k]); max[k] = Math.max(max[k], b.max[k]); }
    }
    if (!Number.isFinite(min[0])) return { min: [-100, -100, -50], max: [100, 100, 50] };
    return { min, max };
  }

  private updateBounds(): void {
    const { min, max } = this.bounds();
    const c: Vec3 = [(min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2];
    const r = Math.hypot(max[0] - min[0], max[1] - min[1], max[2] - min[2]) / 2;
    this.rig.setBounds(c, r);
  }

  private applyAll(): void {
    for (const v of this.views.values()) v.apply(this.kit, this.mode);
    for (const v of this.previewViews) v.apply(this.kit, this.mode);
  }

  setMode(m: DisplayMode): void {
    if (m === this.mode) return;
    this.mode = m;
    this.applyAll();
    this.selHL.refresh();
    this.hoverHL.refresh();
    this.syncHighlights();
    this.ls.onMode?.(m);
    this.renderNow();
    this.invalidate();
  }

  setProjection(p: Projection): void {
    if (p === this.rig.projection) return;
    this.rig.setProjection(p);
    this.ls.onProjection?.(p);
    this.renderNow();
  }

  setLevel(l: PickLevel): void {
    this.level = l;
    this.clearHover();
    this.ls.onLevel?.(l);
  }

  setCubeVisible(on: boolean): void {
    this.cube.visible = on;
    this.invalidate();
  }

  setCubeOnly(on: boolean): void {
    if (this.cubeOnly === on) return;
    this.cubeOnly = on;
    this.invalidate();
  }

  cubeRect(): { x: number; y: number; size: number } {
    return this.cube.rect(this.w);
  }

  zoomExtents(animate: boolean): void {
    const { min, max } = this.bounds();
    this.rig.fitBox(min, max, animate);
  }

  zoomToSelection(): void {
    const min: Vec3 = [Infinity, Infinity, Infinity], max: Vec3 = [-Infinity, -Infinity, -Infinity];
    const add = (p: Vec3): void => { for (let k = 0; k < 3; k++) { min[k] = Math.min(min[k], p[k]); max[k] = Math.max(max[k], p[k]); } };
    for (const id of this.sel.bodies) { const v = this.views.get(id); if (v) { add(v.min); add(v.max); } }
    for (const f of this.sel.faces) {
      const v = this.views.get(f.body);
      if (!v) continue;
      for (const tri of v.trianglesOf(f.face)) for (let k = 0; k < 3; k++) { const i = v.data.indices[tri * 3 + k] * 3; add([v.data.positions[i], v.data.positions[i + 1], v.data.positions[i + 2]]); }
    }
    for (const e of this.sel.edges) {
      const v = this.views.get(e.body);
      const r = v?.segmentsOf(e.edge);
      if (!v || !r) continue;
      const pos = v.data.edges.positions;
      for (let s = r[0]; s < r[0] + r[1]; s++) { add([pos[s * 6], pos[s * 6 + 1], pos[s * 6 + 2]]); add([pos[s * 6 + 3], pos[s * 6 + 4], pos[s * 6 + 5]]); }
    }
    if (!Number.isFinite(min[0])) { this.zoomExtents(true); return; }
    this.rig.fitBox(min, max, true);
  }

  lookFrom(dir: Vec3, animate = true): void {
    this.rig.lookFrom(dir, animate);
  }

  showStandardView(id: string): void {
    const v = standardView(id, this.angle);
    this.rig.lookFrom(v.dir, true);
    if (id.startsWith('iso') && this.rig.projection !== 'parallel') this.setProjection('parallel');
  }

  home(): void {
    this.rig.lookFrom(HOME_DIRECTION, true);
    this.zoomExtents(true);
  }

  getCamera(): CameraSpec { return this.rig.getSpec(); }
  setCamera(spec: CameraSpec, animate = true): void { this.rig.setSpec(spec, animate); }

  refreshTheme(): void {
    this.pal = readPalette(this.host);
    this.renderer.setClearColor(this.pal.bg, 1);
    this.kit.setPalette(this.pal);
    this.grid.setPalette(this.pal);
    this.cube.setPalette(this.pal);
    this.selHL.setColor(highlightColor(this.pal, 'select'));
    this.hoverHL.setColor(highlightColor(this.pal, 'hover'));
    this.overlay.ink = resolveInk(this.probe);
    for (const l of this.layers) l.palette?.(this.pal);
    this.applyAll();
    this.invalidate();
  }

  setActive(on: boolean): void {
    this.isActive = on;
    this.rig.setEnabled(on);
    if (on) { this.resize(); this.invalidate(); }
    else if (this.raf) { cancelAnimationFrame(this.raf); this.raf = 0; }
  }

  private resize(): void {
    const w = Math.round(this.host.clientWidth), h = Math.round(this.host.clientHeight);
    if (w < 2 || h < 2) return;
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (w === this.w && h === this.h && this.renderer.getPixelRatio() === this.dpr) return;
    this.w = w; this.h = h;
    this.renderer.setPixelRatio(this.dpr);
    this.renderer.setSize(w, h, false);
    this.rig.size(w, h);
    this.kit.setResolution(w, h);
    this.selHL.setResolution(w, h);
    this.hoverHL.setResolution(w, h);
    this.overlay.size(w, h, this.dpr);
    for (const l of this.layers) l.resolution?.(w, h);
    this.renderNow(true);
  }

  invalidate(): void {
    if (this.raf || !this.isActive) return;
    this.raf = requestAnimationFrame(() => { this.raf = 0; this.renderNow(); });
  }

  renderNow(force = false): void {
    if (!this.isActive && !force) return;
    const t0 = performance.now();
    const cam = this.rig.camera;
    cam.updateMatrixWorld();
    if (this.gridOn) this.grid.fit(this.rig.target, this.rig.visibleHeightAtTarget(), this.rig.radius);
    const d = cam.position.distanceTo(this.rig.target);
    const up = new THREE.Vector3(0, 0, 1).applyQuaternion(cam.quaternion);
    const right = new THREE.Vector3(1, 0, 0).applyQuaternion(cam.quaternion);
    this.key.position.copy(cam.position).addScaledVector(up, d * 0.5).addScaledVector(right, -d * 0.35);
    this.key.target.position.copy(this.rig.target);
    this.renderer.setViewport(0, 0, this.w, this.h);
    if (this.cubeOnly) this.renderer.clear();
    else this.renderer.render(this.scene, cam);
    this.cube.render(this.renderer, this.rig.direction(), this.w, this.h);
    this.drawOverlay();
    this.frames++;
    this.lastCpuMs = performance.now() - t0;
  }

  private drawOverlay(): void {
    const g = this.overlay.begin();
    this.overlay.triad(g, this.rig.camera.quaternion, this.pal);
    if (this.refGeo.count) {
      this.picker.sync(this.w, this.h);
      this.refGeo.drawLabels(g, (p) => this.picker.project(p), this.overlay.ink.text);
    }
    if (this.layers.length) {
      this.picker.sync(this.w, this.h);
      for (const l of this.layers) l.draw?.(g, (p) => this.picker.project(p), this.overlay.ink, this.pal);
    }
    const snapColor = `#${this.pal.snap.getHexString()}`;
    if (this.job?.kind === 'three') {
      this.picker.sync(this.w, this.h);
      const pts: Array<[number, number]> = [];
      for (const p of this.job.pts) { const q = this.picker.project(p); if (q) pts.push([q.x, q.y]); }
      this.overlay.points(g, pts, snapColor);
    }
    const p = this.pointer;
    if (!p || this.interacting) return;
    const s = this.hover.snap;
    if (s) this.overlay.marker(g, s.kind, s.sx, s.sy, snapColor);
    if (this.tip) this.overlay.tip(g, this.tip, s ? s.sx : p.x, s ? s.sy : p.y);
  }

  frameTimes(frames: number, step = 0.012): Promise<number[]> {
    return new Promise((resolve) => {
      const out: number[] = [];
      const turn = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), step);
      let last = performance.now();
      let n = 0;
      const tick = (now: number): void => {
        if (n > 0) out.push(now - last);
        last = now;
        if (n++ >= frames) { resolve(out); return; }
        const cam = this.rig.camera;
        const offset = cam.position.clone().sub(this.rig.target).applyQuaternion(turn);
        cam.position.copy(this.rig.target).add(offset);
        cam.lookAt(this.rig.target);
        this.rig.update();
        this.renderNow(true);
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
  }

  dispose(): void {
    this.ro.disconnect();
    for (const o of this.off) o();
    if (this.raf) cancelAnimationFrame(this.raf);
    if (this.pickRaf) cancelAnimationFrame(this.pickRaf);
    for (const v of this.views.values()) v.dispose();
    for (const v of this.previewViews) v.dispose();
    this.refGeo.dispose();
    for (const l of this.layers) l.dispose();
    this.rig.dispose();
    this.kit.dispose();
    this.grid.dispose();
    this.cube.dispose();
    this.selHL.dispose();
    this.hoverHL.dispose();
    this.renderer.dispose();
  }

  modeLabel(): string { return t(MODE_LABELS[this.mode]); }
}

function toggle<T>(list: T[], item: T, same: (a: T, b: T) => boolean): void {
  const i = list.findIndex((x) => same(x, item));
  if (i >= 0) list.splice(i, 1); else list.push(item);
}
