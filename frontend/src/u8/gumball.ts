import * as THREE from 'three';
import { docStore } from '../ui/doc-store';
import { el, q, setClass, setHidden, setText, setValue } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import type { ViewLayer } from '../view3d/layer';
import type { Palette } from '../view3d/kit';
import type { InkColors } from '../view3d/overlay';
import { view3d } from '../view3d/mount';
import type { Vec3 } from '../view3d/types';
import type { Viewport3D } from '../view3d/viewport';
import { add, dot, hex, lineParam, matrixOf, mul, planeHit, sub, worldPerPixel, type Ray } from './geo';
import { docUrl, req, text } from './net';
import { askSnaps, type Snap3dLayer } from './snap3d';

export interface GumballState {
  on: boolean;
  align: string;
  origin: Vec3 | null;
  axes: [Vec3, Vec3, Vec3];
  selection: number[];
  manual: boolean;
  seq: number;
}

interface ApplyReply { handles: number[]; skipped: number; matrix: number[]; kind: string; gumball: GumballState }
interface PreviewReply { matrix: number[]; kind: string; origin: Vec3; count: number }

type Part =
  | { kind: 'move'; axis: number }
  | { kind: 'plane'; axis: number }
  | { kind: 'rotate'; axis: number }
  | { kind: 'scale'; axis: number }
  | { kind: 'uniform' };

type Op = Record<string, unknown>;

const AXIS = ['x', 'y', 'z'] as const;
const PLANES = ['yz', 'zx', 'xy'] as const;
const ARM = 92;
const MIN_FACTOR = 0.01;

const same = (a: Part | null, b: Part | null): boolean => !!a && !!b && a.kind === b.kind && (a as { axis?: number }).axis === (b as { axis?: number }).axis;

function segDist(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax, dy = by - ay;
  const l2 = dx * dx + dy * dy;
  const k = l2 < 1e-9 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / l2));
  return Math.hypot(px - (ax + k * dx), py - (ay + k * dy));
}

function inPoly(px: number, py: number, pts: Array<{ x: number; y: number }>): boolean {
  let hit = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const a = pts[i], b = pts[j];
    if ((a.y > py) !== (b.y > py) && px < ((b.x - a.x) * (py - a.y)) / (b.y - a.y) + a.x) hit = !hit;
  }
  return hit;
}

export class GumballLayer implements ViewLayer {
  readonly group = new THREE.Group();
  state: GumballState | null = null;
  copy = false;
  private hot: Part | null = null;
  private drag: { part: Part; x0: number; y0: number; start: number; angle: number; unwrapped: number; value: number; moved: boolean; relocate: boolean; pointer: number; shift: [number, number] } | null = null;
  private box: { part: Part; value: number } | null = null;
  private busy = false;
  private pending: Op | null = null;
  private readonly bar: HTMLElement;
  private readonly boxEl: HTMLElement;
  private readonly input: HTMLInputElement;
  private readonly alignSel: HTMLSelectElement;
  private readonly onBtn: HTMLButtonElement;
  private readonly copyChk: HTMLInputElement;
  private readonly off: Array<() => void> = [];
  private geom: { o: Vec3; k: number } | null = null;

  constructor(private readonly vp: Viewport3D, private readonly snaps: Snap3dLayer | null) {
    this.bar = el(
      '<div class="u8-gb-bar" role="toolbar" aria-label="Gumball">' +
      '<button class="v3-seg u8-gb-on" type="button" aria-pressed="false"></button>' +
      '<select class="u8-gb-align" aria-label="Gumball alignment"><option value="world"></option><option value="cplane"></option><option value="object"></option><option value="view"></option></select>' +
      '<button class="v3-seg u8-gb-reset" type="button"></button>' +
      '<label class="u8-gb-copy"><input type="checkbox"><span></span></label></div>');
    this.onBtn = q<HTMLButtonElement>(this.bar, '.u8-gb-on');
    this.alignSel = q<HTMLSelectElement>(this.bar, '.u8-gb-align');
    this.copyChk = q<HTMLInputElement>(this.bar, 'input');
    const opts = Array.from(this.alignSel.options);
    setText(opts[0], t('World'));
    setText(opts[1], t('Construction plane'));
    setText(opts[2], t('Object'));
    setText(opts[3], t('View'));
    setText(this.onBtn, t('Gumball'));
    setText(q(this.bar, '.u8-gb-reset'), t('Reset'));
    setText(q(this.bar, '.u8-gb-copy span'), t('Copy'));
    this.boxEl = el('<div class="u8-gb-box" hidden><input type="text" inputmode="decimal" spellcheck="false" autocomplete="off"><span class="u8-gb-unit"></span></div>');
    this.input = q<HTMLInputElement>(this.boxEl, 'input');
    vp.host.append(this.bar, this.boxEl);
    this.bind();
  }

  private id(): string | null { return docStore.activeId; }

  private bind(): void {
    const host = this.vp.host;
    const on = (target: EventTarget, type: string, fn: (e: never) => void, capture = false): void => {
      target.addEventListener(type, fn as EventListener, { capture });
      this.off.push(() => target.removeEventListener(type, fn as EventListener, { capture }));
    };
    on(host, 'pointerdown', (e: PointerEvent) => this.onDown(e), true);
    on(host, 'pointermove', (e: PointerEvent) => this.onHover(e), true);
    on(this.onBtn, 'click', () => void this.setOn(!(this.state?.on ?? false)));
    on(this.alignSel, 'change', () => void this.align(this.alignSel.value));
    on(q(this.bar, '.u8-gb-reset'), 'click', () => void this.reset());
    on(this.copyChk, 'change', () => { this.copy = this.copyChk.checked; });
    on(this.input, 'keydown', (e: KeyboardEvent) => {
      e.stopPropagation();
      if (e.key === 'Enter') { e.preventDefault(); this.commitBox(); } else if (e.key === 'Escape') { e.preventDefault(); this.closeBox(); }
    });
    on(this.input, 'pointerdown', (e: PointerEvent) => e.stopPropagation());
  }

  async refresh(): Promise<void> {
    const id = this.id();
    if (!id) { this.state = null; this.paintBar(); this.vp.invalidate(); return; }
    try {
      this.state = await req<GumballState>('GET', docUrl(id, 'gumball'));
    } catch {
      this.state = null;
    }
    this.paintBar();
    this.vp.invalidate();
  }

  private paintBar(): void {
    const s = this.state;
    const on = !!s?.on;
    setClass(this.onBtn, 'is-on', on);
    if (this.onBtn.getAttribute('aria-pressed') !== String(on)) this.onBtn.setAttribute('aria-pressed', String(on));
    setValue(this.alignSel, s?.align ?? 'world');
    setClass(this.bar, 'is-live', on && !!s?.origin);
    if (!on || !s?.origin) this.closeBox();
  }

  async setOn(on: boolean): Promise<void> {
    const id = this.id();
    if (!id) return;
    try {
      this.state = await req<GumballState>('POST', docUrl(id, 'gumball/on'), { on });
      this.paintBar();
      this.vp.invalidate();
    } catch (e) {
      toast(text(e), 'error');
    }
  }

  async align(mode: string): Promise<void> {
    const id = this.id();
    if (!id) return;
    const body: Record<string, unknown> = { mode };
    try {
      if (mode === 'cplane') {
        const p = this.vp.plane;
        body.plane = { origin: p.origin, x: p.x, z: p.z, name: p.name };
      } else if (mode === 'view') {
        const cam = this.vp.rig.camera;
        const right = new THREE.Vector3(1, 0, 0).applyQuaternion(cam.quaternion);
        const back = new THREE.Vector3(0, 0, 1).applyQuaternion(cam.quaternion);
        body.plane = { origin: this.state?.origin ?? [0, 0, 0], x: right.toArray(), z: back.toArray(), name: 'View' };
      } else if (mode === 'object') {
        const sel = this.vp.sel;
        const face = sel.faces[0];
        const handle = face ? face.body : (sel.bodies[0] ?? this.state?.selection[0]);
        if (handle === undefined) { toast(t('Select an object to align the gumball with.'), 'info'); await this.refresh(); return; }
        body.object = handle;
        if (face) body.face = face.face;
      }
      this.state = await req<GumballState>('POST', docUrl(id, 'gumball/align'), body);
    } catch (e) {
      toast(text(e), 'error');
      await this.refresh();
      return;
    }
    this.paintBar();
    this.vp.invalidate();
  }

  async reset(): Promise<void> {
    const id = this.id();
    if (!id) return;
    try {
      this.state = await req<GumballState>('POST', docUrl(id, 'gumball/reset'));
      this.paintBar();
      this.vp.invalidate();
    } catch (e) {
      toast(text(e), 'error');
    }
  }

  private live(): GumballState | null {
    const s = this.state;
    return s && s.on && s.origin && s.selection.length ? s : null;
  }

  private layout(s: GumballState): { o: Vec3; k: number } {
    const o = s.origin as Vec3;
    const k = worldPerPixel(this.vp, o);
    this.geom = { o, k };
    return this.geom;
  }

  private shape(s: GumballState, part: Part): Array<Vec3> {
    const { o, k } = this.layout(s);
    const L = ARM * k;
    const ax = s.axes;
    const at = (a: number, u: number): Vec3 => add(o, mul(ax[a], u * L));
    switch (part.kind) {
      case 'move': return [o, at(part.axis, 1)];
      case 'scale': return [at(part.axis, 0.52)];
      case 'plane': {
        const a = (part.axis + 1) % 3, b = (part.axis + 2) % 3;
        const p = (u: number, v: number): Vec3 => add(add(o, mul(ax[a], u * L)), mul(ax[b], v * L));
        return [p(0.28, 0.28), p(0.5, 0.28), p(0.5, 0.5), p(0.28, 0.5)];
      }
      case 'rotate': {
        const a = (part.axis + 1) % 3, b = (part.axis + 2) % 3;
        const pts: Vec3[] = [];
        for (let i = 0; i <= 14; i++) {
          const th = (Math.PI / 2) * (0.18 + (0.64 * i) / 14);
          pts.push(add(add(o, mul(ax[a], Math.cos(th) * L * 0.74)), mul(ax[b], Math.sin(th) * L * 0.74)));
        }
        return pts;
      }
      default: return [o];
    }
  }

  private parts(): Part[] {
    const out: Part[] = [{ kind: 'uniform' }];
    for (let a = 0; a < 3; a++) out.push({ kind: 'scale', axis: a }, { kind: 'plane', axis: a }, { kind: 'move', axis: a }, { kind: 'rotate', axis: a });
    return out;
  }

  private hit(px: number, py: number): Part | null {
    const s = this.live();
    if (!s) return null;
    for (const part of this.parts()) {
      const pts = this.shape(s, part).map((p) => this.vp.project(p));
      if (pts.some((p) => !p)) continue;
      const sp = pts as Array<{ x: number; y: number }>;
      switch (part.kind) {
        case 'uniform': if (Math.hypot(px - sp[0].x, py - sp[0].y) <= 9) return part; break;
        case 'scale': if (Math.abs(px - sp[0].x) <= 7 && Math.abs(py - sp[0].y) <= 7) return part; break;
        case 'plane': if (inPoly(px, py, sp)) return part; break;
        case 'move': if (segDist(px, py, sp[0].x, sp[0].y, sp[1].x, sp[1].y) <= 6) return part; break;
        default: for (let i = 0; i + 1 < sp.length; i++) if (segDist(px, py, sp[i].x, sp[i].y, sp[i + 1].x, sp[i + 1].y) <= 6) return part;
      }
    }
    return null;
  }

  private rel(e: MouseEvent): { x: number; y: number } {
    const r = this.vp.canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  private onHover(e: PointerEvent): void {
    if (this.drag || (e.buttons & 7) !== 0 || !this.live()) { if (this.hot && !this.live()) { this.hot = null; } return; }
    const p = this.rel(e);
    const h = this.hit(p.x, p.y);
    if (!same(h, this.hot) || (h === null) !== (this.hot === null)) {
      this.hot = h;
      this.vp.canvas.style.cursor = h ? 'pointer' : '';
      this.vp.invalidate();
    }
  }

  private sample(part: Part, e: PointerEvent, from: { start: number; angle: number; shift: [number, number] }): { value: number; angle?: number } | null {
    const s = this.state;
    if (!s || !s.origin) return null;
    const p = this.rel(e);
    const ray: Ray = this.vp.rayAt(p.x, p.y);
    const o = s.origin;
    const ax = s.axes;
    if (part.kind === 'move' || part.kind === 'scale') {
      const tt = lineParam(ray, o, ax[part.axis]);
      if (tt === null) return null;
      if (part.kind === 'move') return { value: tt - from.start };
      const base = Math.abs(from.start) < 1e-9 ? 1e-9 : from.start;
      return { value: Math.max(MIN_FACTOR, tt / base) };
    }
    if (part.kind === 'plane') {
      const hitP = planeHit(ray, o, ax[part.axis]);
      if (!hitP) return null;
      const d = sub(hitP, o);
      const a = (part.axis + 1) % 3, b = (part.axis + 2) % 3;
      return { value: dot(d, ax[a]) - from.shift[0], angle: dot(d, ax[b]) - from.shift[1] };
    }
    if (part.kind === 'rotate') {
      const hitP = planeHit(ray, o, ax[part.axis]);
      if (!hitP) return null;
      const d = sub(hitP, o);
      const a = (part.axis + 1) % 3, b = (part.axis + 2) % 3;
      return { value: 0, angle: Math.atan2(dot(d, ax[b]), dot(d, ax[a])) };
    }
    const c = this.vp.project(o);
    if (!c) return null;
    const dist = Math.hypot(p.x - c.x, p.y - c.y);
    return { value: Math.max(MIN_FACTOR, dist / Math.max(from.start, 1)) };
  }

  private onDown(e: PointerEvent): void {
    if (e.button !== 0 || !this.live()) return;
    const p = this.rel(e);
    const part = this.hit(p.x, p.y);
    if (!part) { this.closeBox(); return; }
    e.stopPropagation();
    e.preventDefault();
    this.closeBox();
    const s = this.state as GumballState;
    const o = s.origin as Vec3;
    const ray = this.vp.rayAt(p.x, p.y);
    let start = 0, angle = 0;
    let shift: [number, number] = [0, 0];
    if (part.kind === 'move' || part.kind === 'scale') start = lineParam(ray, o, s.axes[part.axis]) ?? 0;
    else if (part.kind === 'uniform') { const c = this.vp.project(o); start = c ? Math.hypot(p.x - c.x, p.y - c.y) : 1; if (start < 14) start = 40; }
    else {
      const hp = planeHit(ray, o, s.axes[part.axis]);
      if (hp) {
        const d = sub(hp, o);
        const a = (part.axis + 1) % 3, b = (part.axis + 2) % 3;
        if (part.kind === 'plane') shift = [dot(d, s.axes[a]), dot(d, s.axes[b])];
        else angle = Math.atan2(dot(d, s.axes[b]), dot(d, s.axes[a]));
      }
    }
    const relocate = part.kind === 'uniform' && (e.ctrlKey || e.metaKey);
    this.drag = { part, x0: p.x, y0: p.y, start, angle, unwrapped: 0, value: part.kind === 'scale' || part.kind === 'uniform' ? 1 : 0, moved: false, relocate, pointer: e.pointerId, shift };
    this.hot = part;
    const move = (ev: PointerEvent): void => this.onDrag(ev);
    const up = (ev: PointerEvent): void => {
      window.removeEventListener('pointermove', move, true);
      window.removeEventListener('pointerup', up, true);
      window.removeEventListener('pointercancel', up, true);
      void this.onRelease(ev);
    };
    window.addEventListener('pointermove', move, true);
    window.addEventListener('pointerup', up, true);
    window.addEventListener('pointercancel', up, true);
    this.vp.invalidate();
  }

  private opFor(part: Part, value: number, extra = 0): Op {
    switch (part.kind) {
      case 'move': return { type: 'move', axis: AXIS[part.axis], distance: value };
      case 'plane': return { type: 'move', plane: PLANES[part.axis], u: value, v: extra };
      case 'rotate': return { type: 'rotate', axis: AXIS[part.axis], degrees: value };
      case 'scale': return { type: 'scale', axis: AXIS[part.axis], factor: value };
      default: return { type: 'scale', factor: value };
    }
  }

  private dragOp(): Op {
    const d = this.drag as NonNullable<GumballLayer['drag']>;
    return this.opFor(d.part, d.value, d.part.kind === 'plane' ? d.unwrapped : 0);
  }

  private onDrag(e: PointerEvent): void {
    const d = this.drag;
    if (!d) return;
    const p = this.rel(e);
    if (!d.moved && Math.hypot(p.x - d.x0, p.y - d.y0) < 4) return;
    d.moved = true;
    if (d.relocate) { this.relocateMove(p.x, p.y); return; }
    const got = this.sample(d.part, e, d);
    if (!got) return;
    if (d.part.kind === 'rotate' && got.angle !== undefined) {
      let delta = got.angle - d.angle;
      while (delta > Math.PI) delta -= 2 * Math.PI;
      while (delta < -Math.PI) delta += 2 * Math.PI;
      const prev = d.unwrapped;
      let step = delta - (prev % (2 * Math.PI));
      while (step > Math.PI) step -= 2 * Math.PI;
      while (step < -Math.PI) step += 2 * Math.PI;
      d.unwrapped = prev + step;
      d.value = (d.unwrapped * 180) / Math.PI;
      if (e.shiftKey) d.value = Math.round(d.value / 5) * 5;
    } else if (d.part.kind === 'plane') {
      d.value = got.value;
      d.unwrapped = got.angle ?? 0;
    } else {
      d.value = got.value;
      if (e.shiftKey && d.part.kind === 'move') d.value = Math.round(d.value / this.vp.gridStep) * this.vp.gridStep;
    }
    this.queuePreview(this.dragOp());
    this.vp.invalidate();
  }

  private queuePreview(op: Op): void {
    this.pending = op;
    if (this.busy) return;
    void this.pumpPreview();
  }

  private async pumpPreview(): Promise<void> {
    const id = this.id();
    if (!id) return;
    this.busy = true;
    try {
      while (this.pending) {
        const op = this.pending;
        this.pending = null;
        let reply: PreviewReply | null = null;
        try {
          reply = await req<PreviewReply>('POST', docUrl(id, 'gumball/apply'), { op, preview: true });
        } catch {
          reply = null;
        }
        if (!this.drag && !this.pending) break;
        if (reply) this.showPose(reply.matrix);
      }
    } finally {
      this.busy = false;
    }
  }

  private showPose(rows: number[]): void {
    const s = this.state;
    if (!s) return;
    const m = matrixOf(rows);
    const map = new Map<number, THREE.Matrix4 | null>();
    for (const h of s.selection) map.set(h, m);
    this.vp.setPoses(map);
  }

  private async relocateMove(x: number, y: number): Promise<void> {
    const s = this.state;
    if (!s || !s.origin || !this.drag) return;
    const ray = this.vp.rayAt(x, y);
    const cam = this.vp.rig.camera;
    const dir = new THREE.Vector3();
    cam.getWorldDirection(dir);
    let target = planeHit(ray, s.origin, [dir.x, dir.y, dir.z]);
    try {
      const list = await askSnaps(this.vp, x, y, ['vertex', 'end', 'mid', 'centre', 'quadrant', 'intersection'], undefined, 5);
      if (list.length) target = list[0].point;
    } catch {
      target = target ?? s.origin;
    }
    if (target) {
      s.origin = target;
      this.vp.invalidate();
    }
  }

  private async onRelease(e: PointerEvent): Promise<void> {
    const d = this.drag;
    this.drag = null;
    this.pending = null;
    if (!d) return;
    const id = this.id();
    if (!id) return;
    if (d.relocate) {
      if (d.moved && this.state?.origin) {
        const p = this.rel(e);
        const ray = this.vp.rayAt(p.x, p.y);
        try {
          const wpp = worldPerPixel(this.vp, this.state.origin);
          this.state = await req<GumballState>('POST', docUrl(id, 'gumball/relocate'), { point: this.state.origin, ray: { origin: ray.origin, dir: ray.direction }, aperture: 10 * wpp });
        } catch (er) { toast(text(er), 'error'); await this.refresh(); }
      }
      this.paintBar();
      this.vp.invalidate();
      return;
    }
    if (!d.moved) {
      this.vp.setPoses(null);
      this.openBox(d.part);
      return;
    }
    const copy = this.copy || e.altKey;
    await this.send(this.dragOp(), copy);
  }

  async send(op: Op, copy = false): Promise<boolean> {
    const id = this.id();
    if (!id) return false;
    try {
      await req<ApplyReply>('POST', docUrl(id, 'gumball/apply'), { op, copy });
      const c = view3d();
      if (c) await c.refresh();
      this.vp.setPoses(null);
      await this.refresh();
      return true;
    } catch (e) {
      this.vp.setPoses(null);
      toast(text(e), 'error');
      await this.refresh();
      return false;
    }
  }

  private openBox(part: Part): void {
    const s = this.live();
    if (!s) return;
    const pts = this.shape(s, part).map((p) => this.vp.project(p)).filter((p): p is { x: number; y: number } => !!p);
    if (!pts.length) return;
    const c = pts[Math.min(pts.length - 1, part.kind === 'move' ? 1 : pts.length >> 1)];
    const fresh = part.kind === 'scale' || part.kind === 'uniform' ? 1 : 0;
    this.box = { part, value: fresh };
    const unit = part.kind === 'rotate' ? '°' : part.kind === 'scale' || part.kind === 'uniform' ? '×' : t('units');
    setText(q(this.boxEl, '.u8-gb-unit'), unit);
    this.input.value = String(fresh);
    this.boxEl.style.left = `${Math.round(c.x + 10)}px`;
    this.boxEl.style.top = `${Math.round(c.y - 34)}px`;
    setHidden(this.boxEl, false);
    this.input.focus();
    this.input.select();
  }

  private closeBox(): void {
    if (!this.box && this.boxEl.hidden) return;
    this.box = null;
    setHidden(this.boxEl, true);
    this.vp.canvas.focus({ preventScroll: true });
  }

  private commitBox(): void {
    const b = this.box;
    if (!b) return;
    const raw = this.input.value.trim().replace(',', '.');
    const v = Number(raw);
    if (!raw || !Number.isFinite(v)) { toast(t('Type a number.'), 'info'); return; }
    this.closeBox();
    void this.send(this.opFor(b.part, v), this.copy);
  }

  draw(g: CanvasRenderingContext2D, _project: (p: Vec3) => { x: number; y: number } | null, ink: InkColors, pal: Palette): void {
    const s = this.live();
    if (!s) return;
    const cols = [hex(pal.axisX), hex(pal.axisY), hex(pal.axisZ)];
    const accent = hex(pal.accent);
    const hotNow = this.drag?.part ?? this.hot;
    g.save();
    g.lineCap = 'round';
    g.lineJoin = 'round';
    for (const part of this.parts()) {
      const pts = this.shape(s, part).map((p) => this.vp.project(p));
      if (pts.some((p) => !p)) continue;
      const sp = pts as Array<{ x: number; y: number }>;
      const on = same(part, hotNow) || (part.kind === 'uniform' && hotNow?.kind === 'uniform');
      const col = part.kind === 'uniform' ? ink.tipText : cols[(part as { axis: number }).axis];
      g.strokeStyle = on ? accent : col;
      g.fillStyle = on ? accent : col;
      g.lineWidth = on ? 3.2 : 2.2;
      g.globalAlpha = on ? 1 : 0.92;
      if (part.kind === 'move') {
        g.beginPath(); g.moveTo(sp[0].x, sp[0].y); g.lineTo(sp[1].x, sp[1].y); g.stroke();
        const ang = Math.atan2(sp[1].y - sp[0].y, sp[1].x - sp[0].x);
        g.beginPath();
        g.moveTo(sp[1].x + Math.cos(ang) * 11, sp[1].y + Math.sin(ang) * 11);
        g.lineTo(sp[1].x + Math.cos(ang + 2.6) * 8, sp[1].y + Math.sin(ang + 2.6) * 8);
        g.lineTo(sp[1].x + Math.cos(ang - 2.6) * 8, sp[1].y + Math.sin(ang - 2.6) * 8);
        g.closePath(); g.fill();
      } else if (part.kind === 'rotate') {
        g.beginPath(); sp.forEach((p, i) => (i ? g.lineTo(p.x, p.y) : g.moveTo(p.x, p.y))); g.stroke();
      } else if (part.kind === 'scale') {
        g.fillRect(sp[0].x - 4.5, sp[0].y - 4.5, 9, 9);
      } else if (part.kind === 'plane') {
        g.globalAlpha = on ? 0.75 : 0.3;
        g.beginPath(); sp.forEach((p, i) => (i ? g.lineTo(p.x, p.y) : g.moveTo(p.x, p.y))); g.closePath(); g.fill();
        g.globalAlpha = 1; g.lineWidth = 1.2; g.stroke();
      } else {
        g.globalAlpha = 1;
        g.fillStyle = ink.tipBg;
        g.beginPath(); g.arc(sp[0].x, sp[0].y, 7, 0, Math.PI * 2); g.fill(); g.stroke();
      }
    }
    const d = this.drag;
    if (d?.moved && !d.relocate) {
      const c = this.vp.project(s.origin as Vec3);
      if (c) {
        const label = d.part.kind === 'rotate' ? `${d.value.toFixed(1)}°` : d.part.kind === 'scale' || d.part.kind === 'uniform' ? `×${d.value.toFixed(3)}` : d.part.kind === 'plane' ? `${d.value.toFixed(3)}, ${d.unwrapped.toFixed(3)}` : d.value.toFixed(3);
        g.globalAlpha = 1;
        g.font = '600 12px -apple-system, "Segoe UI", Inter, system-ui, sans-serif';
        const w = Math.ceil(g.measureText(label).width) + 14;
        g.fillStyle = ink.tipBg;
        g.beginPath(); g.roundRect(Math.round(c.x + 16) + 0.5, Math.round(c.y + 18) + 0.5, w, 22, 5); g.fill();
        g.fillStyle = ink.tipText;
        g.textBaseline = 'middle';
        g.fillText(label, Math.round(c.x + 23), Math.round(c.y + 29));
      }
    }
    g.restore();
  }

  sceneChanged(): void {
    void this.refresh();
  }

  dispose(): void {
    for (const o of this.off) o();
    this.bar.remove();
    this.boxEl.remove();
  }
}
