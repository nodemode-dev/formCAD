import { runsOf } from '../pick';
import type { CanvasApi, DisplayItem, Geom, Handle, Pt, Rect } from '../types';
import { centroid, ccwSweep, dist, ellipseAt, ellipseSweep, intersect, lerp, nearestOn, onSweep, perpFeet, polar, segMid, segsOf, tangentPoints, TAU, type Seg } from './geom';

export const OS = { end: 1, mid: 2, cen: 4, nod: 8, qua: 16, int: 32, ins: 64, per: 128, tan: 256, nea: 512, gcen: 1024, app: 2048, ext: 4096, par: 8192 } as const;
export type SnapMode = keyof typeof OS;

export interface SnapHit {
  mode: SnapMode;
  p: Pt;
  handle: Handle | null;
  d: number;
  w: number;
  prio: number;
  deferred: boolean;
}

export interface SnapEnv {
  canvas: CanvasApi;
  cursor: Pt;
  ap: number;
  mask: number;
  base: Pt | null;
  hatch: boolean;
  wpp: number;
}

const MAX_SEGS = 200;
const MAX_ITEMS = 2000;

interface Owned { seg: Seg; item: DisplayItem; idx: number }

function boxDist(b: Rect, p: Pt): number {
  const dx = Math.max(b[0] - p[0], 0, p[0] - b[2]);
  const dy = Math.max(b[1] - p[1], 0, p[1] - b[3]);
  return Math.hypot(dx, dy);
}

function polyMid(verts: number[][], i: number, n: number): Pt | null {
  const j = (i + 1) % n;
  const a: Pt = [verts[i][0], verts[i][1]];
  const b: Pt = [verts[j][0], verts[j][1]];
  const bulge = verts[i][2] || 0;
  if (Math.abs(bulge) < 1e-12) return lerp(a, b, 0.5);
  const segs: Seg[] = [];
  segsOf({ type: 'poly', verts: [verts[i], [b[0], b[1], 0]], closed: false }, 0, segs);
  return segs[0] ? segMid(segs[0]) : lerp(a, b, 0.5);
}

function runMid(run: number[]): Pt | null {
  const n = run.length / 2;
  if (n < 2) return null;
  let total = 0;
  for (let i = 1; i < n; i++) total += Math.hypot(run[i * 2] - run[i * 2 - 2], run[i * 2 + 1] - run[i * 2 - 1]);
  let acc = 0;
  for (let i = 1; i < n; i++) {
    const l = Math.hypot(run[i * 2] - run[i * 2 - 2], run[i * 2 + 1] - run[i * 2 - 1]);
    if (acc + l >= total / 2 && l > 0) {
      const t = (total / 2 - acc) / l;
      return [run[i * 2 - 2] + (run[i * 2] - run[i * 2 - 2]) * t, run[i * 2 - 1] + (run[i * 2 + 1] - run[i * 2 - 1]) * t];
    }
    acc += l;
  }
  return null;
}

type Push = (mode: SnapMode, p: Pt) => void;

function pointsOf(g: Geom, push: Push, tol: number): void {
  switch (g.type) {
    case 'line':
      push('end', g.p1);
      push('end', g.p2);
      push('mid', lerp(g.p1, g.p2, 0.5));
      break;
    case 'ray':
      push('end', g.p);
      break;
    case 'xline':
      break;
    case 'circle':
      push('cen', g.c);
      for (let k = 0; k < 4; k++) push('qua', polar(g.c, g.r, (k * Math.PI) / 2));
      break;
    case 'arc': {
      push('cen', g.c);
      push('end', polar(g.c, g.r, g.a0));
      push('end', polar(g.c, g.r, g.a1));
      push('mid', polar(g.c, g.r, g.a0 + ccwSweep(g.a0, g.a1) / 2));
      for (let k = 0; k < 4; k++) {
        const a = (k * Math.PI) / 2;
        if (onSweep(a, g.a0, g.a1)) push('qua', polar(g.c, g.r, a));
      }
      break;
    }
    case 'ellipse': {
      push('cen', g.c);
      const sw = ellipseSweep(g.a0, g.a1);
      if (sw < TAU - 1e-9) {
        push('end', ellipseAt(g.c, g.major, g.ratio, g.a0));
        push('end', ellipseAt(g.c, g.major, g.ratio, g.a0 + sw));
        push('mid', ellipseAt(g.c, g.major, g.ratio, g.a0 + sw / 2));
      }
      for (let k = 0; k < 4; k++) {
        const t = (k * Math.PI) / 2;
        if (sw >= TAU - 1e-9 || onSweep(t, g.a0, g.a0 + sw)) push('qua', ellipseAt(g.c, g.major, g.ratio, t));
      }
      break;
    }
    case 'poly': {
      const v = g.verts;
      const n = v.length;
      for (let i = 0; i < n; i++) push('end', [v[i][0], v[i][1]]);
      const m = g.closed ? n : n - 1;
      for (let i = 0; i < m; i++) {
        const p = polyMid(v, i, n);
        if (p) push('mid', p);
      }
      if (g.closed) {
        const runs: number[][] = [];
        runsOf(g, tol, runs);
        const c = runs[0] ? centroid(runs[0]) : null;
        if (c) push('gcen', c);
      }
      break;
    }
    case 'spline': {
      const pts = g.fit && g.fit.length ? g.fit : g.ctrl;
      const runs: number[][] = [];
      runsOf(g, tol, runs);
      if (!g.closed && pts.length) {
        push('end', [pts[0][0], pts[0][1]]);
        push('end', [pts[pts.length - 1][0], pts[pts.length - 1][1]]);
      }
      if (runs[0]) {
        const m = runMid(runs[0]);
        if (m) push('mid', m);
        if (g.closed) {
          const c = centroid(runs[0].slice(0, runs[0].length - 2));
          if (c) push('gcen', c);
        }
      }
      break;
    }
    case 'point':
      push('nod', g.p);
      break;
    case 'text':
      push('ins', g.insert);
      break;
    case 'compound':
      for (const part of g.parts) pointsOf(part, push, tol);
      break;
  }
}

export function findSnaps(env: SnapEnv): SnapHit[] {
  const { canvas, cursor, ap, mask } = env;
  if (mask === 0) return [];
  const tol = env.wpp * 0.5;
  const reach = mask & (OS.app) ? ap * 20 : ap;
  const rect: Rect = [cursor[0] - reach, cursor[1] - reach, cursor[0] + reach, cursor[1] + reach];
  let items = canvas.itemsIn(rect).filter((it) => it.geom && (env.hatch || it.kind !== 'hatch'));
  if (items.length > MAX_ITEMS) items = items.slice(0, MAX_ITEMS);
  items.sort((a, b) => boxDist(a.bounds, cursor) - boxDist(b.bounds, cursor));
  const hits: SnapHit[] = [];
  const seen = new Set<string>();
  const add = (mode: SnapMode, p: Pt, handle: Handle | null, d: number, prio = 0, deferred = false): void => {
    if (d > ap) return;
    const key = `${mode}|${p[0].toFixed(7)}|${p[1].toFixed(7)}`;
    if (seen.has(key)) return;
    seen.add(key);
    const bonus = mode === 'end' || mode === 'int' ? ap * 0.15 : 0;
    hits.push({ mode, p, handle, d, w: Math.max(0, d - bonus), prio, deferred });
  };
  const near = items.filter((it) => boxDist(it.bounds, cursor) <= ap || it.kind === 'xline' || it.kind === 'ray');
  for (const it of near) {
    const g = it.geom as Geom;
    pointsOf(g, (mode, p) => {
      if (mask & OS[mode]) add(mode, p, it.h, dist(cursor, p));
    }, tol);
    if (mask & OS.ins && it.grips) for (const gr of it.grips) if (gr.kind === 'insert') add('ins', gr.p, it.h, dist(cursor, gr.p));
  }
  const needSegs = mask & (OS.int | OS.app | OS.per | OS.tan | OS.nea);
  if (!needSegs) return hits;
  const owned: Owned[] = [];
  let count = 0;
  for (const it of items) {
    if (count >= MAX_SEGS) break;
    const segs: Seg[] = [];
    segsOf(it.geom, tol, segs);
    if (!segs.length) continue;
    const apparent = (mask & OS.app) !== 0;
    if (!apparent && boxDist(it.bounds, cursor) > ap && it.kind !== 'xline' && it.kind !== 'ray') continue;
    segs.forEach((seg, idx) => {
      if (count < MAX_SEGS) {
        owned.push({ seg, item: it, idx });
        count++;
      }
    });
  }
  const closeSegs = owned.filter((o) => dist(nearestOn(o.seg, cursor), cursor) <= ap);
  const base = env.base;
  for (const o of closeSegs) {
    const near1 = nearestOn(o.seg, cursor);
    const dn = dist(near1, cursor);
    if (mask & OS.per) {
      if (base) {
        const feet = perpFeet(o.seg, base);
        feet.sort((a, b) => dist(a, cursor) - dist(b, cursor));
        if (feet[0]) add('per', feet[0], o.item.h, dn);
      } else if (!o.seg.approx || o.seg.k === 'l') add('per', near1, o.item.h, dn, 1, true);
    }
    if (mask & OS.tan && o.seg.k === 'c') {
      if (base) {
        const ts = tangentPoints(o.seg, base);
        ts.sort((a, b) => dist(a, cursor) - dist(b, cursor));
        if (ts[0]) add('tan', ts[0], o.item.h, dn);
      } else add('tan', near1, o.item.h, dn, 1, true);
    }
    if (mask & OS.nea) add('nea', near1, o.item.h, dn, 2);
  }
  if (mask & (OS.int | OS.app)) {
    for (let i = 0; i < owned.length; i++) {
      for (let j = i + 1; j < owned.length; j++) {
        const a = owned[i];
        const b = owned[j];
        if (a.item === b.item && Math.abs(a.idx - b.idx) <= 1) continue;
        const real = intersect(a.seg, b.seg, false);
        for (const p of real) {
          const d = dist(p, cursor);
          if (d > ap) continue;
          if (mask & OS.int) add('int', p, a.item.h, d);
          else add('app', p, a.item.h, d);
        }
        if (mask & OS.app) {
          for (const p of intersect(a.seg, b.seg, true)) {
            const d = dist(p, cursor);
            if (d > ap) continue;
            if (real.some((r) => dist(r, p) < 1e-9)) continue;
            add('app', p, a.item.h, d);
          }
        }
      }
    }
  }
  return hits;
}

export function chooseSnap(hits: SnapHit[]): SnapHit | null {
  let best: SnapHit | null = null;
  for (const h of hits) {
    if (!best || h.prio < best.prio || (h.prio === best.prio && h.w < best.w)) best = h;
  }
  return best;
}

export function cycleList(hits: SnapHit[]): SnapHit[] {
  const first = chooseSnap(hits);
  if (!first) return [];
  const byMode = new Map<SnapMode, SnapHit>();
  for (const h of hits) {
    if (h === first || h.mode === first.mode) continue;
    const cur = byMode.get(h.mode);
    if (!cur || h.d < cur.d) byMode.set(h.mode, h);
  }
  const rest = [...byMode.values()].sort((a, b) => a.d - b.d);
  const out = [first, ...rest];
  const sameMode = hits.filter((h) => h !== first && h.mode === first.mode).sort((a, b) => a.d - b.d);
  if (sameMode[0] && !out.includes(sameMode[0])) out.splice(1, 0, sameMode[0]);
  return out;
}

export function modeMask(name: string | null | undefined, osmode: number): number {
  if (name === 'none') return 0;
  if (name && name in OS) return OS[name as SnapMode];
  if (osmode & 16384) return 0;
  return osmode & 16383;
}
