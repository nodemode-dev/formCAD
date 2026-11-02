import { arcPoints, ccwSweep, ellipsePoints, polyPoints, splinePoints } from './tess';
import type { DisplayItem, Geom, Rect } from './types';

const TAU = Math.PI * 2;

export function runsOf(g: Geom | null, tol: number, out: number[][]): void {
  if (!g) return;
  switch (g.type) {
    case 'line':
      out.push([g.p1[0], g.p1[1], g.p2[0], g.p2[1]]);
      break;
    case 'circle': {
      const a: number[] = [];
      arcPoints(g.c[0], g.c[1], g.r, 0, TAU, tol, a);
      out.push(a);
      break;
    }
    case 'arc': {
      const a: number[] = [];
      arcPoints(g.c[0], g.c[1], g.r, g.a0, ccwSweep(g.a0, g.a1), tol, a);
      out.push(a);
      break;
    }
    case 'ellipse': {
      const a: number[] = [];
      ellipsePoints(g.c, g.major, g.ratio, g.a0, Math.abs(g.a1 - g.a0) >= TAU - 1e-9 ? TAU : ccwSweep(g.a0, g.a1), tol, a);
      out.push(a);
      break;
    }
    case 'poly': {
      const a: number[] = [];
      polyPoints(g.verts, g.closed, tol, a);
      out.push(a);
      break;
    }
    case 'spline': {
      const a: number[] = [];
      splinePoints(g, tol, a);
      if (g.closed && a.length >= 4) a.push(a[0], a[1]);
      out.push(a);
      break;
    }
    case 'point':
      out.push([g.p[0], g.p[1]]);
      break;
    case 'text': {
      const b = g.box;
      if (b && b.length >= 3) {
        const a: number[] = [];
        for (const q of b) a.push(q[0], q[1]);
        a.push(b[0][0], b[0][1]);
        out.push(a);
      }
      break;
    }
    case 'compound':
      for (const part of g.parts) runsOf(part, tol, out);
      break;
    default:
      break;
  }
}

export function itemRuns(item: DisplayItem, tol: number): number[][] {
  const out: number[][] = [];
  runsOf(item.geom, tol, out);
  if (item.prims) {
    for (const p of item.prims) {
      if (p.t === 'pl' && p.pts.length >= 4) {
        const a = p.closed ? p.pts.concat([p.pts[0], p.pts[1]]) : p.pts;
        out.push(a);
      }
    }
  }
  return out;
}

function distSeg(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax;
  const dy = by - ay;
  const l2 = dx * dx + dy * dy;
  const t = l2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / l2));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

function inTri(px: number, py: number, a: number[], i: number): boolean {
  const d1 = (px - a[i + 4]) * (a[i + 1] - a[i + 5]) - (a[i] - a[i + 4]) * (py - a[i + 5]);
  const d2 = (px - a[i + 2]) * (a[i + 5] - a[i + 3]) - (a[i + 4] - a[i + 2]) * (py - a[i + 3]);
  const d3 = (px - a[i]) * (a[i + 3] - a[i + 1]) - (a[i + 2] - a[i]) * (py - a[i + 1]);
  const neg = d1 < 0 || d2 < 0 || d3 < 0;
  const pos = d1 > 0 || d2 > 0 || d3 > 0;
  return !(neg && pos);
}

function inRing(px: number, py: number, ring: number[]): boolean {
  let inside = false;
  const n = ring.length / 2;
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const xi = ring[i * 2];
    const yi = ring[i * 2 + 1];
    const xj = ring[j * 2];
    const yj = ring[j * 2 + 1];
    if ((yi > py) !== (yj > py) && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export function distanceTo(item: DisplayItem, x: number, y: number, tol: number): number {
  let best = Infinity;
  for (const run of itemRuns(item, tol)) {
    if (run.length === 2) {
      best = Math.min(best, Math.hypot(x - run[0], y - run[1]));
      continue;
    }
    for (let i = 2; i < run.length; i += 2) {
      const d = distSeg(x, y, run[i - 2], run[i - 1], run[i], run[i + 1]);
      if (d < best) best = d;
    }
  }
  if (item.geom?.type === 'text' && item.geom.box?.length >= 3) {
    const ring: number[] = [];
    for (const q of item.geom.box) ring.push(q[0], q[1]);
    if (inRing(x, y, ring)) best = 0;
  }
  if (item.prims && best > 0) {
    for (const p of item.prims) {
      if (p.t === 'tri') {
        for (let i = 0; i + 5 < p.pts.length; i += 6) if (inTri(x, y, p.pts, i)) return 0;
      } else if (p.t === 'fill') {
        let inside = false;
        for (const r of p.rings) if (inRing(x, y, r)) inside = !inside;
        if (inside) return 0;
      }
    }
  }
  return best;
}

export function distanceToInfinite(item: DisplayItem, x: number, y: number): number {
  const g = item.geom;
  if (!g || (g.type !== 'xline' && g.type !== 'ray')) return Infinity;
  const vx = x - g.p[0];
  const vy = y - g.p[1];
  const t = vx * g.dir[0] + vy * g.dir[1];
  if (g.type === 'ray' && t < 0) return Math.hypot(vx, vy);
  return Math.abs(vx * g.dir[1] - vy * g.dir[0]);
}

function segHitsRect(ax: number, ay: number, bx: number, by: number, r: Rect): boolean {
  const code = (x: number, y: number): number => (x < r[0] ? 1 : x > r[2] ? 2 : 0) | (y < r[1] ? 4 : y > r[3] ? 8 : 0);
  let c0 = code(ax, ay);
  let c1 = code(bx, by);
  let x0 = ax;
  let y0 = ay;
  let x1 = bx;
  let y1 = by;
  for (let k = 0; k < 16; k++) {
    if ((c0 | c1) === 0) return true;
    if (c0 & c1) return false;
    const out = c0 || c1;
    let x = 0;
    let y = 0;
    if (out & 8) { x = x0 + ((x1 - x0) * (r[3] - y0)) / (y1 - y0); y = r[3]; }
    else if (out & 4) { x = x0 + ((x1 - x0) * (r[1] - y0)) / (y1 - y0); y = r[1]; }
    else if (out & 2) { y = y0 + ((y1 - y0) * (r[2] - x0)) / (x1 - x0); x = r[2]; }
    else { y = y0 + ((y1 - y0) * (r[0] - x0)) / (x1 - x0); x = r[0]; }
    if (out === c0) { x0 = x; y0 = y; c0 = code(x0, y0); } else { x1 = x; y1 = y; c1 = code(x1, y1); }
  }
  return false;
}

export function touchesRect(item: DisplayItem, r: Rect, tol: number): boolean {
  for (const run of itemRuns(item, tol)) {
    if (run.length === 2) {
      if (run[0] >= r[0] && run[0] <= r[2] && run[1] >= r[1] && run[1] <= r[3]) return true;
      continue;
    }
    for (let i = 2; i < run.length; i += 2) if (segHitsRect(run[i - 2], run[i - 1], run[i], run[i + 1], r)) return true;
  }
  if (item.prims) {
    for (const p of item.prims) {
      if (p.t === 'tri') {
        for (let i = 0; i + 5 < p.pts.length; i += 6) {
          if (inTri((r[0] + r[2]) / 2, (r[1] + r[3]) / 2, p.pts, i)) return true;
          for (let k = 0; k < 6; k += 2) if (p.pts[i + k] >= r[0] && p.pts[i + k] <= r[2] && p.pts[i + k + 1] >= r[1] && p.pts[i + k + 1] <= r[3]) return true;
        }
      }
    }
  }
  return false;
}
