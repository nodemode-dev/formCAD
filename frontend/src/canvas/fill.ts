import { bulgePoints } from './tess';

export type TriSink = (x0: number, y0: number, x1: number, y1: number, x2: number, y2: number) => void;

interface Edge { x0: number; y0: number; x1: number; y1: number; ymin: number; ymax: number }

const xAt = (e: Edge, y: number): number => (e.y1 === e.y0 ? e.x0 : e.x0 + ((e.x1 - e.x0) * (y - e.y0)) / (e.y1 - e.y0));

function slab(active: Edge[], ya: number, yb: number, sink: TriSink, depth: number): void {
  const ym = (ya + yb) / 2;
  const cut = active.filter((e) => e.ymin <= ya + 1e-12 && e.ymax >= yb - 1e-12);
  if (cut.length < 2) return;
  cut.sort((a, b) => xAt(a, ym) - xAt(b, ym));
  if (depth < 24) {
    for (let i = 0; i + 1 < cut.length; i++) {
      const a = cut[i];
      const b = cut[i + 1];
      const d0 = xAt(b, ya) - xAt(a, ya);
      const d1 = xAt(b, yb) - xAt(a, yb);
      if ((d0 < -1e-9 && d1 > 1e-9) || (d0 > 1e-9 && d1 < -1e-9)) {
        const t = d0 / (d0 - d1);
        const yc = ya + (yb - ya) * t;
        if (yc > ya && yc < yb) {
          slab(cut, ya, yc, sink, depth + 1);
          slab(cut, yc, yb, sink, depth + 1);
          return;
        }
      }
    }
  }
  for (let i = 0; i + 1 < cut.length; i += 2) {
    const l = cut[i];
    const r = cut[i + 1];
    const lx0 = xAt(l, ya);
    const lx1 = xAt(l, yb);
    const rx0 = xAt(r, ya);
    const rx1 = xAt(r, yb);
    sink(lx0, ya, rx0, ya, rx1, yb);
    sink(lx0, ya, rx1, yb, lx1, yb);
  }
}

export function fillRings(rings: number[][], sink: TriSink): void {
  const edges: Edge[] = [];
  const ys = new Set<number>();
  for (const ring of rings) {
    const n = ring.length / 2;
    if (n < 3) continue;
    for (let i = 0; i < n; i++) {
      const j = (i + 1) % n;
      const x0 = ring[i * 2];
      const y0 = ring[i * 2 + 1];
      const x1 = ring[j * 2];
      const y1 = ring[j * 2 + 1];
      if (y0 === y1) continue;
      edges.push({ x0, y0, x1, y1, ymin: Math.min(y0, y1), ymax: Math.max(y0, y1) });
      ys.add(y0);
      ys.add(y1);
    }
  }
  if (edges.length < 2 || edges.length > 60000) return;
  const levels = Array.from(ys).sort((a, b) => a - b);
  edges.sort((a, b) => a.ymin - b.ymin);
  let active: Edge[] = [];
  let next = 0;
  let budget = 4_000_000;
  for (let k = 0; k + 1 < levels.length; k++) {
    const ya = levels[k];
    const yb = levels[k + 1];
    while (next < edges.length && edges[next].ymin <= ya) active.push(edges[next++]);
    active = active.filter((e) => e.ymax > ya);
    budget -= active.length;
    if (budget < 0) return;
    slab(active, ya, yb, sink, 0);
  }
}

export function ringBounds(ring: number[]): [number, number, number, number] {
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (let i = 0; i + 1 < ring.length; i += 2) {
    if (ring[i] < x0) x0 = ring[i];
    if (ring[i] > x1) x1 = ring[i];
    if (ring[i + 1] < y0) y0 = ring[i + 1];
    if (ring[i + 1] > y1) y1 = ring[i + 1];
  }
  return [x0, y0, x1, y1];
}

export function bandTriangles(verts: number[][], closed: boolean, tol: number, sink: TriSink): boolean {
  const n = verts.length;
  if (n < 2) return false;
  let wide = false;
  for (const v of verts) if ((v[3] ?? 0) > 0 || (v[4] ?? 0) > 0) wide = true;
  if (!wide) return false;
  const last = closed ? n : n - 1;
  let prev: { x: number; y: number; nx: number; ny: number; w: number } | null = null;
  let first: { x: number; y: number; nx: number; ny: number; w: number } | null = null;
  const join = (a: { x: number; y: number; nx: number; ny: number; w: number }, b: { nx: number; ny: number }): void => {
    const hw = a.w / 2;
    sink(a.x + a.nx * hw, a.y + a.ny * hw, a.x + b.nx * hw, a.y + b.ny * hw, a.x, a.y);
    sink(a.x - a.nx * hw, a.y - a.ny * hw, a.x - b.nx * hw, a.y - b.ny * hw, a.x, a.y);
  };
  for (let i = 0; i < last; i++) {
    const a = verts[i];
    const b = verts[(i + 1) % n];
    const w0 = a[3] ?? 0;
    const w1 = a[4] ?? 0;
    const pts: number[] = [a[0], a[1]];
    bulgePoints(a[0], a[1], b[0], b[1], a[2] ?? 0, tol, pts);
    const m = pts.length / 2;
    const cum = [0];
    for (let k = 1; k < m; k++) cum.push(cum[k - 1] + Math.hypot(pts[k * 2] - pts[k * 2 - 2], pts[k * 2 + 1] - pts[k * 2 - 1]));
    const total = cum[m - 1] || 1;
    for (let k = 0; k + 1 < m; k++) {
      const x0 = pts[k * 2];
      const y0 = pts[k * 2 + 1];
      const x1 = pts[k * 2 + 2];
      const y1 = pts[k * 2 + 3];
      const len = Math.hypot(x1 - x0, y1 - y0);
      if (!(len > 0)) continue;
      const nx = -(y1 - y0) / len;
      const ny = (x1 - x0) / len;
      const wa = w0 + ((w1 - w0) * cum[k]) / total;
      const wb = w0 + ((w1 - w0) * cum[k + 1]) / total;
      const ha = wa / 2;
      const hb = wb / 2;
      sink(x0 + nx * ha, y0 + ny * ha, x0 - nx * ha, y0 - ny * ha, x1 + nx * hb, y1 + ny * hb);
      sink(x0 - nx * ha, y0 - ny * ha, x1 - nx * hb, y1 - ny * hb, x1 + nx * hb, y1 + ny * hb);
      const here = { x: x0, y: y0, nx, ny, w: wa };
      if (prev) join(prev, here);
      else first = here;
      prev = { x: x1, y: y1, nx, ny, w: wb };
    }
  }
  if (closed && prev && first) join(prev, first);
  return true;
}
