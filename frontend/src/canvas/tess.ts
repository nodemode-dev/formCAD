import type { Geom } from './types';

const TAU = Math.PI * 2;
const MAX_SEG = 4096;

export function segmentCount(radius: number, sweep: number, tol: number, minSeg = 1): number {
  const r = Math.abs(radius);
  if (!(r > 0) || !Number.isFinite(r)) return minSeg;
  const t = Math.min(r, Math.max(tol, r * 1e-6));
  const step = 2 * Math.acos(Math.max(-1, Math.min(1, 1 - t / r)));
  if (!(step > 1e-6)) return MAX_SEG;
  return Math.max(minSeg, Math.min(MAX_SEG, Math.ceil(Math.abs(sweep) / step)));
}

export function arcPoints(cx: number, cy: number, r: number, a0: number, sweep: number, tol: number, out: number[], skipFirst = false): void {
  const n = segmentCount(r, sweep, tol);
  for (let i = skipFirst ? 1 : 0; i <= n; i++) {
    const a = a0 + (sweep * i) / n;
    out.push(cx + r * Math.cos(a), cy + r * Math.sin(a));
  }
}

export function ccwSweep(a0: number, a1: number): number {
  let s = (a1 - a0) % TAU;
  if (s <= 0) s += TAU;
  return s;
}

export function ellipsePoints(c: number[], major: number[], ratio: number, t0: number, sweep: number, tol: number, out: number[]): void {
  const ux = major[0];
  const uy = major[1];
  const vx = -uy * ratio;
  const vy = ux * ratio;
  const n = segmentCount(Math.hypot(ux, uy), sweep, tol, 8);
  for (let i = 0; i <= n; i++) {
    const t = t0 + (sweep * i) / n;
    const co = Math.cos(t);
    const si = Math.sin(t);
    out.push(c[0] + ux * co + vx * si, c[1] + uy * co + vy * si);
  }
}

export function bulgePoints(x0: number, y0: number, x1: number, y1: number, bulge: number, tol: number, out: number[]): void {
  const dx = x1 - x0;
  const dy = y1 - y0;
  const chord = Math.hypot(dx, dy);
  if (!(Math.abs(bulge) > 1e-12) || !(chord > 0)) {
    out.push(x1, y1);
    return;
  }
  const theta = 4 * Math.atan(bulge);
  const r = chord / (2 * Math.sin(Math.abs(theta) / 2));
  const mx = (x0 + x1) / 2;
  const my = (y0 + y1) / 2;
  const d = r * Math.cos(Math.abs(theta) / 2) * Math.sign(bulge);
  const cx = mx - (dy / chord) * d;
  const cy = my + (dx / chord) * d;
  const a0 = Math.atan2(y0 - cy, x0 - cx);
  const n = segmentCount(r, theta, tol);
  for (let i = 1; i < n; i++) {
    const a = a0 + (theta * i) / n;
    out.push(cx + r * Math.cos(a), cy + r * Math.sin(a));
  }
  out.push(x1, y1);
}

type Spline = Extract<Geom, { type: 'spline' }>;

function findSpan(knots: number[], n: number, p: number, u: number): number {
  if (u >= knots[n]) return n - 1;
  if (u <= knots[p]) return p;
  let lo = p;
  let hi = n;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (u < knots[mid]) hi = mid; else lo = mid;
  }
  return lo;
}

function evalNurbs(s: Spline, hx: number[], hy: number[], hw: number[], u: number, tmp: Float64Array): [number, number] {
  const p = s.degree;
  const n = s.ctrl.length;
  const k = findSpan(s.knots, n, p, u);
  for (let j = 0; j <= p; j++) {
    const i = k - p + j;
    tmp[j * 3] = hx[i];
    tmp[j * 3 + 1] = hy[i];
    tmp[j * 3 + 2] = hw[i];
  }
  for (let r = 1; r <= p; r++) {
    for (let j = p; j >= r; j--) {
      const i = k - p + j;
      const d = s.knots[i + p - r + 1] - s.knots[i];
      const a = d === 0 ? 0 : (u - s.knots[i]) / d;
      for (let c = 0; c < 3; c++) tmp[j * 3 + c] = (1 - a) * tmp[(j - 1) * 3 + c] + a * tmp[j * 3 + c];
    }
  }
  const w = tmp[p * 3 + 2] || 1;
  return [tmp[p * 3] / w, tmp[p * 3 + 1] / w];
}

function distToChord(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax;
  const dy = by - ay;
  const l2 = dx * dx + dy * dy;
  if (l2 === 0) return Math.hypot(px - ax, py - ay);
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / l2));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

export function splinePoints(s: Spline, tol: number, out: number[]): void {
  const n = s.ctrl.length;
  const p = s.degree;
  const valid = n > p && p >= 1 && s.knots.length === n + p + 1 && s.knots[n] > s.knots[p];
  if (!valid) {
    const src = n >= 2 ? s.ctrl : s.fit ?? [];
    for (const q of src) out.push(q[0], q[1]);
    return;
  }
  const hw = s.weights && s.weights.length === n ? s.weights : new Array<number>(n).fill(1);
  const hx = s.ctrl.map((q, i) => q[0] * hw[i]);
  const hy = s.ctrl.map((q, i) => q[1] * hw[i]);
  const tmp = new Float64Array((p + 1) * 3);
  const budget = { left: 200000 };
  const refine = (u0: number, u1: number, p0: [number, number], p1: [number, number], depth: number): void => {
    const um = (u0 + u1) / 2;
    const pm = evalNurbs(s, hx, hy, hw, um, tmp);
    let flat = distToChord(pm[0], pm[1], p0[0], p0[1], p1[0], p1[1]) <= tol;
    if (flat) {
      const q1 = evalNurbs(s, hx, hy, hw, (u0 + um) / 2, tmp);
      const q3 = evalNurbs(s, hx, hy, hw, (um + u1) / 2, tmp);
      flat = distToChord(q1[0], q1[1], p0[0], p0[1], p1[0], p1[1]) <= tol && distToChord(q3[0], q3[1], p0[0], p0[1], p1[0], p1[1]) <= tol;
    }
    if (flat || depth >= 14 || budget.left <= 0) {
      out.push(p1[0], p1[1]);
      return;
    }
    budget.left -= 2;
    refine(u0, um, p0, pm, depth + 1);
    refine(um, u1, pm, p1, depth + 1);
  };
  let first = true;
  for (let i = p; i < n; i++) {
    const u0 = s.knots[i];
    const u1 = s.knots[i + 1];
    if (!(u1 > u0)) continue;
    const a = evalNurbs(s, hx, hy, hw, u0, tmp);
    const b = evalNurbs(s, hx, hy, hw, u1, tmp);
    if (first) { out.push(a[0], a[1]); first = false; }
    const parts = Math.max(1, p);
    let prev = a;
    for (let k = 1; k <= parts; k++) {
      const ua = u0 + ((u1 - u0) * (k - 1)) / parts;
      const ub = u0 + ((u1 - u0) * k) / parts;
      const pb = k === parts ? b : evalNurbs(s, hx, hy, hw, ub, tmp);
      refine(ua, ub, prev, pb, 0);
      prev = pb;
    }
  }
}

export function polyPoints(verts: number[][], closed: boolean, tol: number, out: number[]): void {
  const n = verts.length;
  if (n === 0) return;
  out.push(verts[0][0], verts[0][1]);
  const last = closed ? n : n - 1;
  for (let i = 0; i < last; i++) {
    const a = verts[i];
    const b = verts[(i + 1) % n];
    bulgePoints(a[0], a[1], b[0], b[1], a[2] ?? 0, tol, out);
  }
}
