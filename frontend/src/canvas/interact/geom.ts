import { runsOf } from '../pick';
import type { Geom, Pt } from '../types';

export const TAU = Math.PI * 2;
export const EPS = 1e-9;

export const sub = (a: Pt, b: Pt): Pt => [a[0] - b[0], a[1] - b[1]];
export const add = (a: Pt, b: Pt): Pt => [a[0] + b[0], a[1] + b[1]];
export const mul = (a: Pt, k: number): Pt => [a[0] * k, a[1] * k];
export const dot = (a: Pt, b: Pt): number => a[0] * b[0] + a[1] * b[1];
export const cross = (a: Pt, b: Pt): number => a[0] * b[1] - a[1] * b[0];
export const len = (a: Pt): number => Math.hypot(a[0], a[1]);
export const dist = (a: Pt, b: Pt): number => Math.hypot(a[0] - b[0], a[1] - b[1]);
export const lerp = (a: Pt, b: Pt, t: number): Pt => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
export const polar = (c: Pt, r: number, a: number): Pt => [c[0] + r * Math.cos(a), c[1] + r * Math.sin(a)];
export const angleOf = (from: Pt, to: Pt): number => Math.atan2(to[1] - from[1], to[0] - from[0]);

export function normAng(a: number): number {
  const m = a % TAU;
  return m < 0 ? m + TAU : m;
}

export function ccwSweep(a0: number, a1: number): number {
  const s = normAng(a1 - a0);
  return s < EPS && Math.abs(a1 - a0) > EPS ? TAU : s;
}

export function onSweep(a: number, a0: number, a1: number, slack = 1e-9): boolean {
  const s = ccwSweep(a0, a1);
  if (s >= TAU - 1e-9) return true;
  const d = normAng(a - a0);
  return d <= s + slack || d >= TAU - slack;
}

export interface SegLine { k: 'l'; a: Pt; b: Pt; inf: 0 | 1 | 2; approx: boolean }
export interface SegArc { k: 'c'; c: Pt; r: number; a0: number; a1: number; full: boolean; approx: boolean }
export type Seg = SegLine | SegArc;

export function arcFromBulge(p0: Pt, p1: Pt, bulge: number): SegArc | null {
  const cx = p1[0] - p0[0];
  const cy = p1[1] - p0[1];
  const L = Math.hypot(cx, cy);
  if (L < EPS || Math.abs(bulge) < 1e-12) return null;
  const d = (L * (1 - bulge * bulge)) / (4 * bulge);
  const mid: Pt = [(p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2];
  const c: Pt = [mid[0] - (cy / L) * d, mid[1] + (cx / L) * d];
  const r = Math.abs((L * (1 + bulge * bulge)) / (4 * bulge));
  const s = angleOf(c, p0);
  const e = angleOf(c, p1);
  return bulge > 0 ? { k: 'c', c, r, a0: s, a1: e, full: false, approx: false } : { k: 'c', c, r, a0: e, a1: s, full: false, approx: false };
}

export function segsOf(g: Geom | null, tol: number, out: Seg[]): void {
  if (!g) return;
  switch (g.type) {
    case 'line':
      out.push({ k: 'l', a: g.p1, b: g.p2, inf: 0, approx: false });
      break;
    case 'xline':
      out.push({ k: 'l', a: g.p, b: [g.p[0] + g.dir[0], g.p[1] + g.dir[1]], inf: 2, approx: false });
      break;
    case 'ray':
      out.push({ k: 'l', a: g.p, b: [g.p[0] + g.dir[0], g.p[1] + g.dir[1]], inf: 1, approx: false });
      break;
    case 'circle':
      out.push({ k: 'c', c: g.c, r: g.r, a0: 0, a1: TAU, full: true, approx: false });
      break;
    case 'arc':
      out.push({ k: 'c', c: g.c, r: g.r, a0: g.a0, a1: g.a1, full: false, approx: false });
      break;
    case 'poly': {
      const v = g.verts;
      const n = v.length;
      const m = g.closed ? n : n - 1;
      for (let i = 0; i < m; i++) {
        const p0: Pt = [v[i][0], v[i][1]];
        const j = (i + 1) % n;
        const p1: Pt = [v[j][0], v[j][1]];
        const arc = arcFromBulge(p0, p1, v[i][2] || 0);
        if (arc) out.push(arc);
        else out.push({ k: 'l', a: p0, b: p1, inf: 0, approx: false });
      }
      break;
    }
    case 'compound':
      for (const part of g.parts) segsOf(part, tol, out);
      break;
    case 'point':
    case 'text':
      break;
    default: {
      const runs: number[][] = [];
      runsOf(g, tol, runs);
      for (const r of runs) {
        for (let i = 0; i + 3 < r.length; i += 2) out.push({ k: 'l', a: [r[i], r[i + 1]], b: [r[i + 2], r[i + 3]], inf: 0, approx: true });
      }
    }
  }
}

function bounds(s: SegLine, ext: boolean): [number, number] {
  if (ext || s.inf === 2) return [-Infinity, Infinity];
  if (s.inf === 1) return [0, Infinity];
  return [0, 1];
}

export function nearestOn(s: Seg, p: Pt): Pt {
  if (s.k === 'l') {
    const d = sub(s.b, s.a);
    const l2 = dot(d, d);
    if (l2 < EPS * EPS) return s.a;
    const [lo, hi] = bounds(s, false);
    const t = Math.min(hi, Math.max(lo, dot(sub(p, s.a), d) / l2));
    return [s.a[0] + d[0] * t, s.a[1] + d[1] * t];
  }
  const a = angleOf(s.c, p);
  if (s.full || onSweep(a, s.a0, s.a1)) {
    if (dist(p, s.c) < EPS) return polar(s.c, s.r, s.a0);
    return polar(s.c, s.r, a);
  }
  const e0 = polar(s.c, s.r, s.a0);
  const e1 = polar(s.c, s.r, s.a1);
  return dist(p, e0) <= dist(p, e1) ? e0 : e1;
}

export function segEnds(s: Seg): Pt[] {
  if (s.k === 'l') return s.inf === 0 ? [s.a, s.b] : s.inf === 1 ? [s.a] : [];
  return s.full ? [] : [polar(s.c, s.r, s.a0), polar(s.c, s.r, s.a1)];
}

export function segMid(s: Seg): Pt | null {
  if (s.k === 'l') return s.inf === 0 ? lerp(s.a, s.b, 0.5) : null;
  if (s.full) return null;
  return polar(s.c, s.r, s.a0 + ccwSweep(s.a0, s.a1) / 2);
}

export function intersect(a: Seg, b: Seg, ext: boolean): Pt[] {
  if (ext && (a.approx || b.approx)) ext = false;
  if (a.k === 'l' && b.k === 'l') return lineLine(a, b, ext);
  if (a.k === 'l' && b.k === 'c') return lineArc(a, b, ext);
  if (a.k === 'c' && b.k === 'l') return lineArc(b, a, ext);
  if (a.k === 'c' && b.k === 'c') return arcArc(a, b, ext);
  return [];
}

function lineLine(a: SegLine, b: SegLine, ext: boolean): Pt[] {
  const d1 = sub(a.b, a.a);
  const d2 = sub(b.b, b.a);
  const den = cross(d1, d2);
  if (Math.abs(den) < 1e-12 * (len(d1) * len(d2) + 1e-300)) return [];
  const w = sub(b.a, a.a);
  const t = cross(w, d2) / den;
  const u = cross(w, d1) / den;
  const [tl, th] = bounds(a, ext);
  const [ul, uh] = bounds(b, ext);
  const e = 1e-9;
  if (t < tl - e || t > th + e || u < ul - e || u > uh + e) return [];
  return [[a.a[0] + d1[0] * t, a.a[1] + d1[1] * t]];
}

function lineArc(l: SegLine, c: SegArc, ext: boolean): Pt[] {
  const d = sub(l.b, l.a);
  const f = sub(l.a, c.c);
  const A = dot(d, d);
  if (A < EPS * EPS) return [];
  const B = 2 * dot(f, d);
  const C = dot(f, f) - c.r * c.r;
  let disc = B * B - 4 * A * C;
  if (disc < 0) {
    if (disc > -1e-12 * (B * B + 1)) disc = 0;
    else return [];
  }
  const sq = Math.sqrt(disc);
  const [tl, th] = bounds(l, ext);
  const out: Pt[] = [];
  for (const t of sq === 0 ? [-B / (2 * A)] : [(-B - sq) / (2 * A), (-B + sq) / (2 * A)]) {
    if (t < tl - 1e-9 || t > th + 1e-9) continue;
    const p: Pt = [l.a[0] + d[0] * t, l.a[1] + d[1] * t];
    if (!ext && !c.full && !onSweep(angleOf(c.c, p), c.a0, c.a1, 1e-7)) continue;
    out.push(p);
  }
  return out;
}

function arcArc(a: SegArc, b: SegArc, ext: boolean): Pt[] {
  const d = dist(a.c, b.c);
  if (d < EPS || d > a.r + b.r + 1e-9 || d < Math.abs(a.r - b.r) - 1e-9) return [];
  const x = (d * d + a.r * a.r - b.r * b.r) / (2 * d);
  const h2 = a.r * a.r - x * x;
  const h = h2 > 0 ? Math.sqrt(h2) : 0;
  const ux = (b.c[0] - a.c[0]) / d;
  const uy = (b.c[1] - a.c[1]) / d;
  const mx = a.c[0] + ux * x;
  const my = a.c[1] + uy * x;
  const cand: Pt[] = h === 0 ? [[mx, my]] : [[mx - uy * h, my + ux * h], [mx + uy * h, my - ux * h]];
  if (ext) return cand;
  return cand.filter((p) => (a.full || onSweep(angleOf(a.c, p), a.a0, a.a1, 1e-7)) && (b.full || onSweep(angleOf(b.c, p), b.a0, b.a1, 1e-7)));
}

export function perpFeet(s: Seg, base: Pt): Pt[] {
  if (s.k === 'l') {
    const d = sub(s.b, s.a);
    const l2 = dot(d, d);
    if (l2 < EPS * EPS) return [];
    const t = dot(sub(base, s.a), d) / l2;
    const [lo, hi] = bounds(s, false);
    if (t < lo - 1e-9 || t > hi + 1e-9) return [];
    return [[s.a[0] + d[0] * t, s.a[1] + d[1] * t]];
  }
  if (dist(base, s.c) < EPS) return [];
  const a = angleOf(s.c, base);
  const out: Pt[] = [];
  for (const ang of [a, a + Math.PI]) if (s.full || onSweep(ang, s.a0, s.a1, 1e-7)) out.push(polar(s.c, s.r, ang));
  return out;
}

export function tangentPoints(s: Seg, base: Pt): Pt[] {
  if (s.k !== 'c' || s.approx) return [];
  const d = dist(base, s.c);
  if (d <= s.r + 1e-9) return [];
  const th = angleOf(s.c, base);
  const al = Math.acos(s.r / d);
  const out: Pt[] = [];
  for (const ang of [th + al, th - al]) if (s.full || onSweep(ang, s.a0, s.a1, 1e-7)) out.push(polar(s.c, s.r, ang));
  return out;
}

export function ellipseAt(c: Pt, major: Pt, ratio: number, t: number): Pt {
  const ct = Math.cos(t);
  const st = Math.sin(t);
  return [c[0] + major[0] * ct - major[1] * ratio * st, c[1] + major[1] * ct + major[0] * ratio * st];
}

export function ellipseSweep(a0: number, a1: number): number {
  return Math.abs(a1 - a0) >= TAU - 1e-9 ? TAU : ccwSweep(a0, a1);
}

export function centroid(pts: number[]): Pt | null {
  const n = pts.length / 2;
  if (n < 3) return null;
  let a = 0;
  let cx = 0;
  let cy = 0;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    const x0 = pts[i * 2];
    const y0 = pts[i * 2 + 1];
    const x1 = pts[j * 2];
    const y1 = pts[j * 2 + 1];
    const w = x0 * y1 - x1 * y0;
    a += w;
    cx += (x0 + x1) * w;
    cy += (y0 + y1) * w;
  }
  if (Math.abs(a) < EPS) return null;
  return [cx / (3 * a), cy / (3 * a)];
}

export function distToLine(p: Pt, o: Pt, d: Pt): number {
  return Math.abs(cross(sub(p, o), d));
}

export function project(p: Pt, o: Pt, d: Pt): { t: number; q: Pt } {
  const t = dot(sub(p, o), d);
  return { t, q: [o[0] + d[0] * t, o[1] + d[1] * t] };
}
