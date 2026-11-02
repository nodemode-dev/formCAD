import { SNAP_NAMES } from '../overlay';
import type { CanvasApi, Handle, Pt, Rect } from '../types';
import { angleOf, cross, dist, dot, EPS, intersect, len, nearestOn, normAng, onSweep, polar, segsOf, TAU, type Seg, type SegLine } from './geom';
import type { Settings } from './settings';
import { chooseSnap, cycleList, findSnaps, modeMask, OS, type SnapHit, type SnapMode } from './snaps';
import { fmtLinear } from './units';

export type PathKind = 'polar' | 'otrack' | 'ext' | 'par';
export interface RayPath { t: 'ray'; o: Pt; d: Pt; bi: boolean; name: string; kind: PathKind; handle: Handle | null; origin: Pt }
export interface CircPath { t: 'circ'; c: Pt; r: number; a0: number; a1: number; full: boolean; name: string; kind: 'ext'; handle: Handle | null; origin: Pt }
export type Path = RayPath | CircPath;

export interface Acq {
  p: Pt;
  mode: SnapMode;
  handle: Handle | null;
  line?: Pt;
  arc?: { c: Pt; r: number; a0: number; a1: number; full: boolean };
  parallel?: Pt;
}

export interface ResolveIn {
  canvas: CanvasApi;
  set: Settings;
  raw: Pt;
  scale: number;
  base: Pt | null;
  lastAngle: number | null;
  shift: boolean;
  windowCorner: boolean;
  override: string | null;
  cycle: number;
  now: number;
}

export interface Resolved {
  p: Pt;
  snap: SnapHit | null;
  hits: SnapHit[];
  cycleCount: number;
  slide: Path | null;
  engaged: Path[];
  cross: Pt | null;
  tip: string;
  dir: Pt | null;
  timer: number;
  ortho: boolean;
}

const DWELL_MS = 400;
const PATH_PX = 6;
const MAX_ACQ = 7;
const MAX_PATHS = 64;
const DEG = Math.PI / 180;

function isoAxes(plane: number): [number, number] {
  return plane === 1 ? [30, 150] : plane === 2 ? [30, 90] : [90, 150];
}

export function gridSnap(p: Pt, s: Settings): Pt {
  const ux = s.snapunit[0] > 0 ? s.snapunit[0] : 0.5;
  const uy = s.snapunit[1] > 0 ? s.snapunit[1] : ux;
  const ang = s.snapang * DEG;
  const c = Math.cos(ang);
  const sn = Math.sin(ang);
  const dx = p[0] - s.snapbase[0];
  const dy = p[1] - s.snapbase[1];
  const lx = dx * c + dy * sn;
  const ly = -dx * sn + dy * c;
  let qx: number;
  let qy: number;
  if (s.iso) {
    const d = uy;
    const k = Math.cos(30 * DEG);
    let best = Infinity;
    qx = 0;
    qy = 0;
    const i0 = Math.floor(lx / (d * k));
    for (let i = i0 - 1; i <= i0 + 2; i++) {
      const x = i * d * k;
      const y0 = i * d * 0.5;
      const j = Math.round((ly - y0) / d);
      const y = y0 + j * d;
      const e = Math.hypot(x - lx, y - ly);
      if (e < best) { best = e; qx = x; qy = y; }
    }
  } else {
    qx = Math.round(lx / ux) * ux;
    qy = Math.round(ly / uy) * uy;
  }
  return [s.snapbase[0] + qx * c - qy * sn, s.snapbase[1] + qx * sn + qy * c];
}

export function polarAngles(s: Settings, lastAngle: number | null): number[] {
  const sign = s.angdir ? -1 : 1;
  const ref = s.polarmode & 1 && lastAngle !== null ? lastAngle : s.angbase * DEG;
  const out: number[] = [];
  const n = Math.min(360, Math.max(1, Math.floor(360 / s.polarang + 1e-9)));
  for (let k = 0; k < n; k++) out.push(normAng(ref + sign * k * s.polarang * DEG));
  if (s.polarmode & 4) for (const a of s.polaradd) out.push(normAng(ref + sign * a * DEG));
  return out;
}

function rayDist(path: RayPath, p: Pt): { d: number; t: number } {
  const w: Pt = [p[0] - path.o[0], p[1] - path.o[1]];
  const t = dot(w, path.d);
  return { d: Math.abs(cross(w, path.d)), t };
}

function pathNear(path: Path, p: Pt, tol: number): { d: number; q: Pt } | null {
  if (path.t === 'ray') {
    const { d, t } = rayDist(path, p);
    if (d > tol) return null;
    if (!path.bi && t < -tol) return null;
    return { d, q: [path.o[0] + path.d[0] * t, path.o[1] + path.d[1] * t] };
  }
  const dc = dist(p, path.c);
  const d = Math.abs(dc - path.r);
  if (d > tol) return null;
  const a = angleOf(path.c, p);
  if (!path.full && !onSweep(a, path.a0, path.a1)) return null;
  return { d, q: polar(path.c, path.r, a) };
}

function pathSeg(path: Path): Seg {
  if (path.t === 'ray') return { k: 'l', a: path.o, b: [path.o[0] + path.d[0], path.o[1] + path.d[1]], inf: path.bi ? 2 : 1, approx: false };
  return { k: 'c', c: path.c, r: path.r, a0: 0, a1: TAU, full: true, approx: false };
}

export class Tracker {
  acquired: Acq[] = [];
  private dwellKey = '';
  private dwellSince = 0;
  private dwellDone = false;

  clear(): void {
    this.acquired = [];
    this.dwellKey = '';
    this.dwellDone = false;
  }

  private toggle(a: Acq): void {
    const i = this.acquired.findIndex((q) => dist(q.p, a.p) < 1e-7 && q.mode === a.mode);
    if (i >= 0) this.acquired.splice(i, 1);
    else {
      this.acquired.push(a);
      if (this.acquired.length > MAX_ACQ) this.acquired.shift();
    }
  }

  private extFor(hit: SnapHit, canvas: CanvasApi): Acq {
    const acq: Acq = { p: hit.p, mode: hit.mode, handle: hit.handle };
    const it = hit.handle !== null ? canvas.item(hit.handle) : undefined;
    const g = it?.geom;
    if (!g) return acq;
    if (hit.mode === 'end' || hit.mode === 'mid') {
      const segs: Seg[] = [];
      segsOf(g, 0, segs);
      for (const s of segs) {
        if (s.k === 'l' && s.inf === 0) {
          const atA = dist(s.a, hit.p) < 1e-7;
          const atB = dist(s.b, hit.p) < 1e-7;
          if (atA || atB) {
            const far = atA ? s.b : s.a;
            const dx = hit.p[0] - far[0];
            const dy = hit.p[1] - far[1];
            const l = Math.hypot(dx, dy);
            if (l > EPS) acq.line = [dx / l, dy / l];
            break;
          }
        } else if (s.k === 'c' && !s.full) {
          const e0 = polar(s.c, s.r, s.a0);
          const e1 = polar(s.c, s.r, s.a1);
          if (dist(e0, hit.p) < 1e-7 || dist(e1, hit.p) < 1e-7) {
            acq.arc = { c: s.c, r: s.r, a0: 0, a1: TAU, full: true };
            break;
          }
        }
      }
    }
    return acq;
  }

  private paths(inp: ResolveIn, orthoOn: boolean, mask: number): Path[] {
    const s = inp.set;
    const out: Path[] = [];
    const polarOn = (s.autosnap & 8) !== 0 && !orthoOn;
    const angles = polarOn || (s.autosnap & 16 && s.polarmode & 2) ? polarAngles(s, inp.lastAngle) : [];
    if (polarOn && inp.base) {
      for (const a of angles) out.push({ t: 'ray', o: inp.base, d: [Math.cos(a), Math.sin(a)], bi: false, name: 'Polar', kind: 'polar', handle: null, origin: inp.base });
    }
    if (s.autosnap & 16) {
      for (const q of this.acquired) {
        if (q.parallel) {
          if (inp.base) out.push({ t: 'ray', o: inp.base, d: q.parallel, bi: true, name: 'Parallel', kind: 'par', handle: q.handle, origin: inp.base });
          continue;
        }
        const name = SNAP_NAMES[q.mode] ?? 'Tracking';
        const ang = s.polarmode & 2 ? polarAngles(s, null) : [0, Math.PI / 2, Math.PI, Math.PI * 1.5];
        for (const a of ang) out.push({ t: 'ray', o: q.p, d: [Math.cos(a), Math.sin(a)], bi: false, name, kind: 'otrack', handle: q.handle, origin: q.p });
        if (mask & OS.ext) {
          if (q.line) out.push({ t: 'ray', o: q.p, d: q.line, bi: false, name: 'Extension', kind: 'ext', handle: q.handle, origin: q.p });
          if (q.arc) out.push({ t: 'circ', c: q.arc.c, r: q.arc.r, a0: q.arc.a0, a1: q.arc.a1, full: true, name: 'Extension', kind: 'ext', handle: q.handle, origin: q.p });
        }
      }
    }
    return out;
  }

  private dwell(inp: ResolveIn, key: string, make: () => Acq): number {
    const s = inp.set;
    if ((s.autosnap & 16) === 0) return 0;
    const shiftMode = (s.polarmode & 8) !== 0;
    if (key !== this.dwellKey) {
      this.dwellKey = key;
      this.dwellSince = inp.now;
      this.dwellDone = false;
    }
    if (this.dwellDone || key === '') return 0;
    if (shiftMode) {
      if (inp.shift) {
        this.dwellDone = true;
        this.toggle(make());
      }
      return 0;
    }
    const left = DWELL_MS - (inp.now - this.dwellSince);
    if (left <= 0) {
      this.dwellDone = true;
      this.toggle(make());
      return 0;
    }
    return left;
  }

  resolve(inp: ResolveIn): Resolved {
    const s = inp.set;
    const wpp = 1 / inp.scale;
    const ap = s.aperture * wpp;
    const tol = PATH_PX * wpp;
    const orthoOn = s.ortho !== inp.shift;
    const out: Resolved = { p: inp.raw, snap: null, hits: [], cycleCount: 0, slide: null, engaged: [], cross: null, tip: '', dir: null, timer: 0, ortho: false };
    const mask = modeMask(inp.override, s.osmode);
    const hits = findSnaps({ canvas: inp.canvas, cursor: inp.raw, ap, mask, base: inp.base, hatch: s.osnaphatch, wpp });
    out.hits = hits;
    const list = cycleList(hits);
    out.cycleCount = list.length;
    const snap = list.length > 1 && inp.cycle > 0 ? list[inp.cycle % list.length] : chooseSnap(hits);
    if (snap) {
      out.snap = snap;
      out.p = snap.p;
      if (snap.deferred) out.p = snap.p;
      out.timer = snap.mode === 'per' || snap.mode === 'tan' || snap.mode === 'nea' ? 0 : this.dwell(inp, `${snap.mode}|${snap.p[0].toFixed(6)}|${snap.p[1].toFixed(6)}`, () => this.extFor(snap, inp.canvas));
      if (inp.base) out.dir = unit(out.p[0] - inp.base[0], out.p[1] - inp.base[1]);
      return out;
    }
    if (mask & OS.par && inp.base) {
      const par = this.parLine(inp, ap);
      if (par) out.timer = this.dwell(inp, `par|${String(par.handle)}`, () => ({ p: par.p, mode: 'par', handle: par.handle, parallel: par.dir }));
      else this.dwell(inp, '', () => ({ p: inp.raw, mode: 'par', handle: null }));
    } else this.dwell(inp, '', () => ({ p: inp.raw, mode: 'par', handle: null }));

    let p: Pt = inp.raw;
    const gridOn = s.snapmode && s.snaptype === 0;
    if (gridOn) p = gridSnap(p, s);

    const paths = this.paths(inp, orthoOn, mask).slice(0, 4096);
    const near: Array<{ path: Path; d: number; q: Pt }> = [];
    for (const path of paths) {
      const hit = pathNear(path, p, tol);
      if (hit) near.push({ path, d: hit.d, q: hit.q });
    }
    near.sort((a, b) => a.d - b.d);
    const cand = near.slice(0, MAX_PATHS);
    let slid = false;
    if (cand.length) {
      let best: { q: Pt; a: Path; b: Path | null; dd: number } | null = null;
      for (let i = 0; i < cand.length; i++) {
        for (let j = i + 1; j < cand.length; j++) {
          if (cand[i].path.kind === cand[j].path.kind && cand[i].path.origin === cand[j].path.origin) continue;
          for (const x of intersect(pathSeg(cand[i].path), pathSeg(cand[j].path), false)) {
            const dd = dist(x, p);
            if (dd <= tol && (!best || dd < best.dd)) best = { q: x, a: cand[i].path, b: cand[j].path, dd };
          }
        }
      }
      let objHit: { q: Pt; path: Path; app: boolean; dd: number } | null = null;
      if (!best) {
        const r: Rect = [p[0] - tol, p[1] - tol, p[0] + tol, p[1] + tol];
        const items = inp.canvas.itemsIn(r).slice(0, 300);
        const segs: Seg[] = [];
        for (const it of items) if (it.geom) segsOf(it.geom, wpp * 0.5, segs);
        for (const c of cand) {
          const ps = pathSeg(c.path);
          for (const sg of segs.slice(0, MAX_PATHS * 4)) {
            for (const x of intersect(ps, sg, false)) {
              const dd = dist(x, p);
              if (dd <= tol && (!objHit || dd < objHit.dd)) objHit = { q: x, path: c.path, app: false, dd };
            }
            if (mask & OS.app) {
              for (const x of intersect(ps, sg, true)) {
                const dd = dist(x, p);
                if (dd <= tol && (!objHit || dd < objHit.dd)) objHit = { q: x, path: c.path, app: true, dd };
              }
            }
          }
        }
      }
      if (best) {
        p = best.q;
        out.cross = best.q;
        out.engaged = best.b ? [best.a, best.b] : [best.a];
        slid = true;
      } else if (objHit) {
        p = objHit.q;
        out.cross = objHit.q;
        out.engaged = [objHit.path];
        out.slide = objHit.path;
        out.tip = objHit.app ? 'Apparent Intersection' : 'Intersection';
        slid = true;
      } else {
        const c = cand[0];
        p = c.q;
        out.slide = c.path;
        out.engaged = [c.path];
        slid = true;
        if (c.path.kind === 'polar' && s.snapmode && s.snaptype === 1 && c.path.t === 'ray') {
          const step = s.polardist > 0 ? s.polardist : s.snapunit[0] > 0 ? s.snapunit[0] : 1;
          const t = Math.max(step, Math.round(dot([p[0] - c.path.o[0], p[1] - c.path.o[1]], c.path.d) / step) * step);
          p = [c.path.o[0] + c.path.d[0] * t, c.path.o[1] + c.path.d[1] * t];
        }
      }
    }
    if (!slid && orthoOn && inp.base && !inp.windowCorner) {
      p = this.orthoPoint(p, inp.base, s);
      out.ortho = true;
    }
    out.p = p;
    if (out.slide && out.slide.t === 'ray') {
      const o = out.slide.o;
      const t = dot([p[0] - o[0], p[1] - o[1]], out.slide.d);
      out.dir = out.slide.bi && t < 0 ? [-out.slide.d[0], -out.slide.d[1]] : out.slide.d;
    } else if (inp.base) out.dir = unit(p[0] - inp.base[0], p[1] - inp.base[1]);
    if (out.engaged.length) {
      const parts = out.engaged.map((pa) => {
        const d = dist(pa.origin, p);
        const a = Math.round(normAng(angleOf(pa.origin, p)) / DEG) % 360;
        return `${pa.name}: ${fmtLinear(d, s.lunits, 2)} < ${a}`;
      });
      out.tip = [...parts, out.tip].filter(Boolean).join(', ');
    }
    return out;
  }

  private orthoPoint(p: Pt, base: Pt, s: Settings): Pt {
    const axes: Pt[] = s.iso ? isoAxes(s.isoplane).map((a): Pt => [Math.cos(a * DEG), Math.sin(a * DEG)]) : [[1, 0], [0, 1]];
    const w: Pt = [p[0] - base[0], p[1] - base[1]];
    let best = axes[0];
    let bt = dot(w, axes[0]);
    for (const ax of axes) {
      const t = dot(w, ax);
      if (Math.abs(t) > Math.abs(bt)) { best = ax; bt = t; }
    }
    if (s.iso && s.snapmode) {
      const step = s.snapunit[1] > 0 ? s.snapunit[1] : s.snapunit[0];
      bt = Math.round(bt / step) * step;
    }
    return [base[0] + best[0] * bt, base[1] + best[1] * bt];
  }

  private parLine(inp: ResolveIn, ap: number): { p: Pt; dir: Pt; handle: Handle | null } | null {
    const r: Rect = [inp.raw[0] - ap, inp.raw[1] - ap, inp.raw[0] + ap, inp.raw[1] + ap];
    let best: { p: Pt; dir: Pt; handle: Handle | null; d: number } | null = null;
    for (const it of inp.canvas.itemsIn(r)) {
      if (it.geom?.type !== 'line') continue;
      const seg: SegLine = { k: 'l', a: it.geom.p1, b: it.geom.p2, inf: 0, approx: false };
      const q = nearestOn(seg, inp.raw);
      const d = dist(q, inp.raw);
      const l = len([seg.b[0] - seg.a[0], seg.b[1] - seg.a[1]]);
      if (d <= ap && l > EPS && (!best || d < best.d)) best = { p: q, dir: [(seg.b[0] - seg.a[0]) / l, (seg.b[1] - seg.a[1]) / l], handle: it.h, d };
    }
    return best;
  }
}

function unit(dx: number, dy: number): Pt | null {
  const l = Math.hypot(dx, dy);
  return l < EPS ? null : [dx / l, dy / l];
}
