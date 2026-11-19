import * as THREE from 'three';
import { parseCss } from '../canvas/color';
import { tokenHex } from '../canvas/ink';
import { el, q, setClass, setHidden, setTitle } from '../ui/dom';
import { icon } from '../ui/icons';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { add, dot, hex, lineParam, mul, planeHit, sub, worldPerPixel } from '../u8/geo';
import type { Palette } from '../view3d/kit';
import type { ViewLayer } from '../view3d/layer';
import type { InkColors } from '../view3d/overlay';
import type { Vec3 } from '../view3d/types';
import type { Viewport3D } from '../view3d/viewport';
import { form, type Mode, type Tool } from './form-store';

type Part =
  | { kind: 'move'; axis: number }
  | { kind: 'plane'; axis: number }
  | { kind: 'rotate'; axis: number }
  | { kind: 'scale'; axis: number }
  | { kind: 'uniform' };

const AXIS = ['x', 'y', 'z'] as const;
const ARM = 92;
const MIN_FACTOR = 0.01;
const PICK_PX = 10;

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

const cssColor = (host: HTMLElement, name: string, fallback: string): THREE.Color => new THREE.Color().setHex(tokenHex(name, parseCss(fallback), host));

export interface DragOp { command: 'subdmove' | 'subdrotate' | 'subdscale'; args: Record<string, unknown>; label: string }

const MODE_DEFS: Array<[Mode, string, string]> = [['vertex', 'formMove', 'Vertices'], ['edge', 'formEdge', 'Edges'], ['face', 'formSplit', 'Faces']];
const TOOL_DEFS: Array<[Tool, string, string]> = [['select', 'ftPick', 'Select'], ['move', 'formMove', 'Move'], ['rotate', 'formRotate', 'Rotate'], ['scale', 'formScale', 'Scale']];
const DISPLAY_DEFS: Array<[string, string, string]> = [['smooth', 'formSmooth', 'Smooth'], ['box', 'formBox', 'Cage'], ['both', 'formCage', 'Both']];

export class FormLayer implements ViewLayer {
  readonly group = new THREE.Group();
  private readonly points: THREE.Points;
  private readonly pointMat: THREE.PointsMaterial;
  private readonly selEdges: THREE.LineSegments;
  private readonly selEdgeMat: THREE.LineBasicMaterial;
  private readonly selFaces: THREE.Mesh;
  private readonly selFaceMat: THREE.MeshBasicMaterial;
  private readonly wire: THREE.LineSegments;
  private readonly wireMat: THREE.LineBasicMaterial;
  private readonly symLines: THREE.LineSegments;
  private readonly symMat: THREE.LineBasicMaterial;
  private readonly bar: HTMLElement;
  private readonly off: Array<() => void> = [];
  private base = new THREE.Color();
  private hotc = new THREE.Color();
  private softc = new THREE.Color();
  private hot: Part | null = null;
  private drag: { part: Part; x0: number; y0: number; start: number; angle: number; unwrapped: number; value: number; moved: boolean; shift: [number, number]; origin: Vec3 } | null = null;
  private pick: { x: number; y: number } | null = null;
  private seenCage: unknown = null;
  private seenSel = -1;
  editing = false;
  onCommit: ((op: DragOp) => void) | null = null;

  constructor(private readonly vp: Viewport3D) {
    this.pointMat = new THREE.PointsMaterial({ size: 7, sizeAttenuation: false, vertexColors: true, depthTest: false, transparent: true });
    this.points = new THREE.Points(new THREE.BufferGeometry(), this.pointMat);
    this.selEdgeMat = new THREE.LineBasicMaterial({ color: 0xffffff, depthTest: false, transparent: true });
    this.selEdges = new THREE.LineSegments(new THREE.BufferGeometry(), this.selEdgeMat);
    this.selFaceMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.3, side: THREE.DoubleSide, depthTest: false, depthWrite: false });
    this.selFaces = new THREE.Mesh(new THREE.BufferGeometry(), this.selFaceMat);
    this.wireMat = new THREE.LineBasicMaterial({ color: 0xffffff, depthTest: false, transparent: true });
    this.wire = new THREE.LineSegments(new THREE.BufferGeometry(), this.wireMat);
    this.symMat = new THREE.LineBasicMaterial({ color: 0xffffff, depthTest: false, transparent: true, opacity: 0.7 });
    this.symLines = new THREE.LineSegments(new THREE.BufferGeometry(), this.symMat);
    for (const [i, o] of [this.points, this.selFaces, this.selEdges, this.wire, this.symLines].entries()) { o.renderOrder = 10 + i; o.frustumCulled = false; this.group.add(o); }
    this.wire.visible = false;
    this.group.visible = false;
    this.bar = el('<div class="xw-formbar" role="toolbar" aria-label="Form tools" hidden></div>');
    this.buildBar();
    vp.host.appendChild(this.bar);
    this.palette({} as Palette);
    this.bind();
    form.onChange((what) => this.sync(what));
  }

  private buildBar(): void {
    const on = el<HTMLButtonElement>(`<button class="v3-seg xw-fb-on" type="button" aria-pressed="false">${icon('formCage', 16)}<span></span></button>`);
    setTitle(on, t('Edit the form cage'));
    on.addEventListener('click', () => this.setEditing(!this.editing));
    this.bar.appendChild(on);
    const seg = (defs: Array<[string, string, string]>, kind: string, run: (k: string) => void): void => {
      this.bar.appendChild(el('<span class="v3-sep"></span>'));
      for (const [key, ic, label] of defs) {
        const b = el<HTMLButtonElement>(`<button class="v3-seg xw-fb" type="button" data-kind="${kind}" data-key="${key}" aria-pressed="false">${icon(ic, 16)}</button>`);
        setTitle(b, t(label));
        b.setAttribute('aria-label', t(label));
        b.addEventListener('click', () => run(key));
        this.bar.appendChild(b);
      }
    };
    seg(MODE_DEFS, 'mode', (k) => form.setMode(k as Mode));
    seg(TOOL_DEFS, 'tool', (k) => form.setTool(k as Tool));
    seg(DISPLAY_DEFS, 'display', (k) => { void form.run('subddisplay', { mode: k }, false); });
    this.bar.appendChild(el('<span class="v3-sep"></span>'));
    const soft = el<HTMLButtonElement>(`<button class="v3-seg xw-fb" type="button" data-kind="soft" aria-pressed="false">${icon('gcOptimize', 16)}</button>`);
    setTitle(soft, t('Soft selection'));
    soft.addEventListener('click', () => form.setSoft({ on: !form.soft.on }));
    this.bar.appendChild(soft);
    setHidden(this.bar, false);
    this.bar.classList.add('is-idle');
    this.paintBar();
  }

  private paintBar(): void {
    const live = form.on;
    setClass(this.bar, 'is-idle', !live);
    for (const b of Array.from(this.bar.querySelectorAll<HTMLButtonElement>('.xw-fb'))) {
      const kind = b.dataset.kind;
      const key = b.dataset.key;
      const on = kind === 'mode' ? form.mode === key : kind === 'tool' ? form.tool === key : kind === 'display' ? form.cage?.display === key : form.soft.on;
      setClass(b, 'is-on', !!on);
      const v = String(!!on);
      if (b.getAttribute('aria-pressed') !== v) b.setAttribute('aria-pressed', v);
      b.disabled = !this.editing || !live;
    }
    const onBtn = q<HTMLButtonElement>(this.bar, '.xw-fb-on');
    setClass(onBtn, 'is-on', this.editing);
    onBtn.setAttribute('aria-pressed', String(this.editing));
    onBtn.disabled = !live;
    const label = q(onBtn, 'span');
    const text = t('Edit form');
    if (label.textContent !== text) label.textContent = text;
  }

  setEditing(on: boolean): void {
    if (this.editing === on) return;
    this.editing = on;
    this.sync('cage');
  }

  palette(_pal: Palette): void {
    const host = this.vp.host;
    this.base = cssColor(host, '--text-secondary', '#a4a4a4');
    this.hotc = cssColor(host, '--accent-color', '#f97316');
    this.softc = cssColor(host, '--warn', '#f59e0b');
    this.selEdgeMat.color.copy(this.hotc);
    this.selFaceMat.color.copy(this.hotc);
    this.wireMat.color.copy(this.hotc);
    this.symMat.color.copy(cssColor(host, '--ok', '#34d399'));
    this.seenCage = null;
    this.sync('cage');
  }

  bounds(): { min: Vec3; max: Vec3 } | null { return null; }

  private sync(what: 'cage' | 'sel' | 'tool' | 'soft'): void {
    const cage = form.cage;
    const show = this.editing && !!cage;
    if (this.group.visible !== show) this.group.visible = show;
    this.paintBar();
    if (!show || !cage) { this.vp.invalidate(); return; }
    if (what === 'cage' || this.seenCage !== cage) { this.seenCage = cage; this.buildPoints(); this.buildSym(); this.seenSel = -1; }
    this.buildSelection();
    this.vp.invalidate();
  }

  private buildPoints(): void {
    const c = form.cage;
    if (!c) return;
    const pos = new Float32Array(c.v.length * 3);
    c.v.forEach((p, i) => { pos[i * 3] = p[0] + c.offset[0]; pos[i * 3 + 1] = p[1] + c.offset[1]; pos[i * 3 + 2] = p[2] + c.offset[2]; });
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(c.v.length * 3), 3));
    this.points.geometry.dispose();
    this.points.geometry = geo;
    this.paintColors();
  }

  private paintColors(): void {
    const c = form.cage;
    const attr = this.points.geometry.getAttribute('color') as THREE.BufferAttribute | undefined;
    if (!c || !attr) return;
    const verts = new Set(form.vertices());
    const w = form.weights;
    const tmp = new THREE.Color();
    for (let i = 0; i < c.v.length; i++) {
      if (verts.has(i)) tmp.copy(this.hotc);
      else if (w && w[i] > 0.001) tmp.copy(this.base).lerp(this.softc, Math.min(1, w[i]));
      else tmp.copy(this.base);
      attr.setXYZ(i, tmp.r, tmp.g, tmp.b);
    }
    attr.needsUpdate = true;
  }

  private buildSelection(): void {
    const c = form.cage;
    if (!c) return;
    this.paintColors();
    const e: number[] = [];
    const f: number[] = [];
    if (form.mode === 'edge') for (const i of form.sel) { const p = c.edges[i]; if (p) e.push(...form.world(p[0]), ...form.world(p[1])); }
    if (form.mode === 'face') {
      for (const i of form.sel) {
        const face = c.f[i];
        if (!face) continue;
        for (let k = 1; k + 1 < face.length; k++) f.push(...form.world(face[0]), ...form.world(face[k]), ...form.world(face[k + 1]));
        for (let k = 0; k < face.length; k++) e.push(...form.world(face[k]), ...form.world(face[(k + 1) % face.length]));
      }
    }
    const eg = new THREE.BufferGeometry();
    eg.setAttribute('position', new THREE.Float32BufferAttribute(e, 3));
    this.selEdges.geometry.dispose();
    this.selEdges.geometry = eg;
    const fg = new THREE.BufferGeometry();
    fg.setAttribute('position', new THREE.Float32BufferAttribute(f, 3));
    this.selFaces.geometry.dispose();
    this.selFaces.geometry = fg;
  }

  private buildSym(): void {
    const c = form.cage;
    const out: number[] = [];
    if (c) {
      const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
      for (const p of c.v) for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], p[k] + c.offset[k]); hi[k] = Math.max(hi[k], p[k] + c.offset[k]); }
      const pad = 0.15;
      const ext = lo.map((l, k) => [l - (hi[k] - l) * pad, hi[k] + (hi[k] - l) * pad]);
      for (const m of c.sym.mirror) {
        const a = AXIS.indexOf(m.axis as 'x' | 'y' | 'z');
        if (a < 0) continue;
        const u = (a + 1) % 3, v = (a + 2) % 3;
        const at = m.at + c.offset[a];
        const corner = (du: number, dv: number): number[] => { const p = [0, 0, 0]; p[a] = at; p[u] = ext[u][du]; p[v] = ext[v][dv]; return p; };
        const ring = [corner(0, 0), corner(1, 0), corner(1, 1), corner(0, 1)];
        for (let k = 0; k < 4; k++) out.push(...ring[k], ...ring[(k + 1) % 4]);
      }
      const r = c.sym.radial;
      if (r && r.count > 1) {
        const a = AXIS.indexOf(r.axis as 'x' | 'y' | 'z');
        if (a >= 0) {
          const u = (a + 1) % 3, v = (a + 2) % 3;
          const radius = Math.max(ext[u][1] - ext[u][0], ext[v][1] - ext[v][0]) / 2;
          const ctr = [0, 0, 0];
          ctr[u] = (r.center[0] ?? 0) + c.offset[u];
          ctr[v] = (r.center[1] ?? 0) + c.offset[v];
          ctr[a] = ext[a][0];
          for (let k = 0; k < r.count; k++) {
            const th = (2 * Math.PI * k) / r.count;
            const p = [...ctr];
            p[u] += Math.cos(th) * radius; p[v] += Math.sin(th) * radius;
            out.push(...ctr, ...p);
          }
        }
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(out, 3));
    this.symLines.geometry.dispose();
    this.symLines.geometry = geo;
  }

  private bind(): void {
    const host = this.vp.host;
    const on = (target: EventTarget, type: string, fn: (e: never) => void, capture = false): void => {
      target.addEventListener(type, fn as EventListener, { capture });
      this.off.push(() => target.removeEventListener(type, fn as EventListener, { capture }));
    };
    on(host, 'pointerdown', (e: PointerEvent) => this.onDown(e), true);
    on(host, 'pointermove', (e: PointerEvent) => this.onHover(e), true);
    on(host, 'pointerup', (e: PointerEvent) => this.onUp(e), true);
    on(this.bar, 'pointerdown', (e: PointerEvent) => e.stopPropagation());
  }

  private live(): boolean { return this.editing && !!form.cage && form.tool !== 'select' && form.sel.size > 0; }

  private rel(e: MouseEvent): { x: number; y: number } {
    const r = this.vp.canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  private origin(): Vec3 | null { return this.drag?.origin ?? form.centroid(); }

  private parts(): Part[] {
    const tool = form.tool;
    const out: Part[] = [];
    if (tool === 'scale') out.push({ kind: 'uniform' });
    for (let a = 0; a < 3; a++) {
      if (tool === 'scale') out.push({ kind: 'scale', axis: a });
      if (tool === 'move') out.push({ kind: 'plane', axis: a }, { kind: 'move', axis: a });
      if (tool === 'rotate') out.push({ kind: 'rotate', axis: a });
    }
    return out;
  }

  private shape(o: Vec3, part: Part): Vec3[] {
    const k = worldPerPixel(this.vp, o);
    const L = ARM * k;
    const at = (a: number, u: number): Vec3 => { const v: Vec3 = [0, 0, 0]; v[a] = u * L; return add(o, v); };
    switch (part.kind) {
      case 'move': return [o, at(part.axis, 1)];
      case 'scale': return [at(part.axis, 0.52)];
      case 'plane': {
        const a = (part.axis + 1) % 3, b = (part.axis + 2) % 3;
        const p = (u: number, v: number): Vec3 => { const r: Vec3 = [0, 0, 0]; r[a] = u * L; r[b] = v * L; return add(o, r); };
        return [p(0.28, 0.28), p(0.5, 0.28), p(0.5, 0.5), p(0.28, 0.5)];
      }
      case 'rotate': {
        const a = (part.axis + 1) % 3, b = (part.axis + 2) % 3;
        const pts: Vec3[] = [];
        for (let i = 0; i <= 28; i++) {
          const th = (Math.PI * 2 * i) / 28;
          const r: Vec3 = [0, 0, 0];
          r[a] = Math.cos(th) * L * 0.74; r[b] = Math.sin(th) * L * 0.74;
          pts.push(add(o, r));
        }
        return pts;
      }
      default: return [o];
    }
  }

  private hit(px: number, py: number): Part | null {
    const o = this.origin();
    if (!o) return null;
    for (const part of this.parts()) {
      const pts = this.shape(o, part).map((p) => this.vp.project(p));
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

  private onHover(e: PointerEvent): void {
    if (this.drag || (e.buttons & 7) !== 0 || !this.live()) return;
    const p = this.rel(e);
    const h = this.hit(p.x, p.y);
    if (!same(h, this.hot) || (h === null) !== (this.hot === null)) {
      this.hot = h;
      this.vp.canvas.style.cursor = h ? 'pointer' : '';
      this.vp.invalidate();
    }
  }

  private sample(d: NonNullable<FormLayer['drag']>, e: PointerEvent): { value: number; angle?: number } | null {
    const p = this.rel(e);
    const ray = this.vp.rayAt(p.x, p.y);
    const o = d.origin;
    const part = d.part;
    const axisVec = (a: number): Vec3 => { const v: Vec3 = [0, 0, 0]; v[a] = 1; return v; };
    if (part.kind === 'move' || part.kind === 'scale') {
      const tt = lineParam(ray, o, axisVec(part.axis));
      if (tt === null) return null;
      if (part.kind === 'move') return { value: tt - d.start };
      const base = Math.abs(d.start) < 1e-9 ? 1e-9 : d.start;
      return { value: Math.max(MIN_FACTOR, tt / base) };
    }
    if (part.kind === 'plane') {
      const hp = planeHit(ray, o, axisVec(part.axis));
      if (!hp) return null;
      const dd = sub(hp, o);
      const a = (part.axis + 1) % 3, b = (part.axis + 2) % 3;
      return { value: dd[a] - d.shift[0], angle: dd[b] - d.shift[1] };
    }
    if (part.kind === 'rotate') {
      const hp = planeHit(ray, o, axisVec(part.axis));
      if (!hp) return null;
      const dd = sub(hp, o);
      const a = (part.axis + 1) % 3, b = (part.axis + 2) % 3;
      return { value: 0, angle: Math.atan2(dd[b], dd[a]) };
    }
    const c = this.vp.project(o);
    if (!c) return null;
    return { value: Math.max(MIN_FACTOR, Math.hypot(p.x - c.x, p.y - c.y) / Math.max(d.start, 1)) };
  }

  private onDown(e: PointerEvent): void {
    if (e.button !== 0 || !this.editing || !form.cage) return;
    const p = this.rel(e);
    if (this.live()) {
      const part = this.hit(p.x, p.y);
      if (part) {
        e.stopPropagation();
        e.preventDefault();
        const o = form.centroid() as Vec3;
        const ray = this.vp.rayAt(p.x, p.y);
        let start = 0, angle = 0;
        let shift: [number, number] = [0, 0];
        const axisVec = (a: number): Vec3 => { const v: Vec3 = [0, 0, 0]; v[a] = 1; return v; };
        if (part.kind === 'move' || part.kind === 'scale') start = lineParam(ray, o, axisVec(part.axis)) ?? 0;
        else if (part.kind === 'uniform') { const c = this.vp.project(o); start = c ? Math.hypot(p.x - c.x, p.y - c.y) : 1; if (start < 14) start = 40; }
        else {
          const hp = planeHit(ray, o, axisVec(part.axis));
          if (hp) {
            const dd = sub(hp, o);
            const a = (part.axis + 1) % 3, b = (part.axis + 2) % 3;
            if (part.kind === 'plane') shift = [dd[a], dd[b]];
            else angle = Math.atan2(dd[b], dd[a]);
          }
        }
        this.drag = { part, x0: p.x, y0: p.y, start, angle, unwrapped: 0, value: part.kind === 'scale' || part.kind === 'uniform' ? 1 : 0, moved: false, shift, origin: o };
        this.hot = part;
        const move = (ev: PointerEvent): void => this.onDrag(ev);
        const up = (ev: PointerEvent): void => {
          window.removeEventListener('pointermove', move, true);
          window.removeEventListener('pointerup', up, true);
          window.removeEventListener('pointercancel', up, true);
          this.onRelease(ev);
        };
        window.addEventListener('pointermove', move, true);
        window.addEventListener('pointerup', up, true);
        window.addEventListener('pointercancel', up, true);
        this.vp.invalidate();
        return;
      }
    }
    if (form.mode === 'vertex') this.pick = { x: p.x, y: p.y };
  }

  private onUp(e: PointerEvent): void {
    const down = this.pick;
    this.pick = null;
    if (!down || this.drag || !this.editing || !form.cage || form.mode !== 'vertex') return;
    const p = this.rel(e);
    if (Math.hypot(p.x - down.x, p.y - down.y) > 4) return;
    let best = -1, bd = PICK_PX;
    const n = form.cage.v.length;
    for (let i = 0; i < n; i++) {
      const s = this.vp.project(form.world(i));
      if (!s) continue;
      const d = Math.hypot(s.x - p.x, s.y - p.y);
      if (d < bd) { bd = d; best = i; }
    }
    if (best >= 0) form.set([best], e.shiftKey || e.ctrlKey || e.metaKey);
    else if (!e.shiftKey) form.clear();
  }

  private current(): { delta: Vec3; axis?: Vec3; degrees: number; factor: Vec3; uniform: number } | null {
    const d = this.drag;
    if (!d) return null;
    const unit = (a: number): Vec3 => { const v: Vec3 = [0, 0, 0]; v[a] = 1; return v; };
    const part = d.part;
    let delta: Vec3 = [0, 0, 0];
    let factor: Vec3 = [1, 1, 1];
    let degrees = 0;
    let axis: Vec3 | undefined;
    if (part.kind === 'move') delta = mul(unit(part.axis), d.value);
    else if (part.kind === 'plane') { const a = (part.axis + 1) % 3, b = (part.axis + 2) % 3; delta = add(mul(unit(a), d.value), mul(unit(b), d.unwrapped)); }
    else if (part.kind === 'rotate') { degrees = d.value; axis = unit(part.axis); }
    else if (part.kind === 'scale') { factor = [1, 1, 1]; factor[part.axis] = d.value; }
    else factor = [d.value, d.value, d.value];
    return { delta, axis, degrees, factor, uniform: part.kind === 'uniform' ? d.value : 1 };
  }

  private onDrag(e: PointerEvent): void {
    const d = this.drag;
    if (!d) return;
    const p = this.rel(e);
    if (!d.moved && Math.hypot(p.x - d.x0, p.y - d.y0) < 4) return;
    d.moved = true;
    const got = this.sample(d, e);
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
    this.preview();
    this.vp.invalidate();
  }

  previewPositions(op: { delta: Vec3; axis?: Vec3; degrees: number; factor: Vec3 }, o: Vec3): Float32Array | null {
    const c = form.cage;
    if (!c) return null;
    const sel = new Set(form.vertices());
    const w = form.weights;
    const th = (op.degrees * Math.PI) / 180;
    const cos = Math.cos(th), sin = Math.sin(th);
    const pos = new Float32Array(c.v.length * 3);
    for (let i = 0; i < c.v.length; i++) {
      const world = form.world(i);
      let k = sel.has(i) ? 1 : w ? w[i] ?? 0 : 0;
      if (form.images.has(i) && !sel.has(i)) k = 0;
      let out: Vec3 = world;
      if (k > 0) {
        let moved: Vec3;
        const rel = sub(world, o);
        if (op.axis) {
          const ax = op.axis;
          const kx = ax[1] * rel[2] - ax[2] * rel[1], ky = ax[2] * rel[0] - ax[0] * rel[2], kz = ax[0] * rel[1] - ax[1] * rel[0];
          const dd = dot(ax, rel);
          moved = add(o, [rel[0] * cos + kx * sin + ax[0] * dd * (1 - cos), rel[1] * cos + ky * sin + ax[1] * dd * (1 - cos), rel[2] * cos + kz * sin + ax[2] * dd * (1 - cos)]);
        } else moved = add(add(o, [rel[0] * op.factor[0], rel[1] * op.factor[1], rel[2] * op.factor[2]]), op.delta);
        out = [world[0] + (moved[0] - world[0]) * k, world[1] + (moved[1] - world[1]) * k, world[2] + (moved[2] - world[2]) * k];
      }
      pos[i * 3] = out[0]; pos[i * 3 + 1] = out[1]; pos[i * 3 + 2] = out[2];
    }
    return pos;
  }

  private preview(): void {
    const cur = this.current();
    const d = this.drag;
    const c = form.cage;
    if (!cur || !d || !c) return;
    const pos = this.previewPositions(cur, d.origin);
    if (!pos) return;
    const lines = new Float32Array(c.edges.length * 6);
    c.edges.forEach((ed, k) => {
      for (let j = 0; j < 3; j++) { lines[k * 6 + j] = pos[ed[0] * 3 + j]; lines[k * 6 + 3 + j] = pos[ed[1] * 3 + j]; }
    });
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(lines, 3));
    this.wire.geometry.dispose();
    this.wire.geometry = geo;
    this.wire.visible = true;
    const pa = this.points.geometry.getAttribute('position') as THREE.BufferAttribute;
    pa.array.set(pos);
    pa.needsUpdate = true;
  }

  private onRelease(_e: PointerEvent): void {
    const d = this.drag;
    const cur = this.current();
    this.drag = null;
    this.wire.visible = false;
    if (!d) return;
    if (!d.moved) { this.vp.invalidate(); return; }
    const c = form.cage;
    if (!cur || !c) return;
    const local = sub(d.origin, c.offset as Vec3);
    const common = { symmetry: form.soft.symmetry, ...form.softArgs() };
    let op: DragOp;
    if (d.part.kind === 'rotate') op = { command: 'subdrotate', args: { axis: cur.axis, angle: cur.degrees, pivot: local, ...common }, label: `${cur.degrees.toFixed(1)} deg` };
    else if (d.part.kind === 'scale' || d.part.kind === 'uniform') op = { command: 'subdscale', args: { factor: d.part.kind === 'uniform' ? cur.uniform : cur.factor, pivot: local, ...common }, label: `x${d.value.toFixed(3)}` };
    else op = { command: 'subdmove', args: { delta: cur.delta, ...common }, label: cur.delta.map((x) => x.toFixed(3)).join(', ') };
    if (this.onCommit) this.onCommit(op);
    else toast(t('Nothing is listening for the form edit.'), 'error');
  }

  cancelPreview(): void {
    this.wire.visible = false;
    this.buildPoints();
    this.vp.invalidate();
  }

  draw(g: CanvasRenderingContext2D, _project: (p: Vec3) => { x: number; y: number } | null, ink: InkColors, pal: Palette): void {
    if (!this.live()) return;
    const o = this.origin();
    if (!o) return;
    const cols = [hex(pal.axisX), hex(pal.axisY), hex(pal.axisZ)];
    const accent = hex(pal.accent);
    const hotNow = this.drag?.part ?? this.hot;
    g.save();
    g.lineCap = 'round';
    g.lineJoin = 'round';
    for (const part of this.parts()) {
      const pts = this.shape(o, part).map((p) => this.vp.project(p));
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
    if (d?.moved) {
      const c = this.vp.project(o);
      const cur = this.current();
      if (c && cur) {
        const label = d.part.kind === 'rotate' ? `${d.value.toFixed(1)} deg` : d.part.kind === 'scale' || d.part.kind === 'uniform' ? `x${d.value.toFixed(3)}` : cur.delta.map((x) => x.toFixed(3)).join(', ');
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

  sceneChanged(): void { form.queue(); }

  dispose(): void {
    for (const o of this.off) o();
    this.bar.remove();
    for (const o of [this.points, this.selEdges, this.selFaces, this.wire, this.symLines]) o.geometry.dispose();
  }
}
