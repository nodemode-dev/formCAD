import type { DisplayItem, Geom } from '../../canvas/types';

const NS = 'http://www.w3.org/2000/svg';
const STROKES = 8;
const FILLS = 4;

const fx = (v: number): string => String(Math.round(v * 10000) / 10000);

function arcPath(cx: number, cy: number, r: number, a0: number, a1: number): string {
  let sweep = a1 - a0;
  while (sweep < 0) sweep += Math.PI * 2;
  if (sweep < 1e-9) sweep = Math.PI * 2;
  const x0 = cx + r * Math.cos(a0), y0 = cy + r * Math.sin(a0);
  const x1 = cx + r * Math.cos(a0 + sweep), y1 = cy + r * Math.sin(a0 + sweep);
  if (sweep >= Math.PI * 2 - 1e-9) {
    const xm = cx - r * Math.cos(a0), ym = cy - r * Math.sin(a0);
    return `M${fx(x0)} ${fx(-y0)}A${fx(r)} ${fx(r)} 0 1 0 ${fx(xm)} ${fx(-ym)}A${fx(r)} ${fx(r)} 0 1 0 ${fx(x0)} ${fx(-y0)}`;
  }
  return `M${fx(x0)} ${fx(-y0)}A${fx(r)} ${fx(r)} 0 ${sweep > Math.PI ? 1 : 0} 0 ${fx(x1)} ${fx(-y1)}`;
}

function polyPath(verts: number[][], closed: boolean): string {
  let d = '';
  const n = verts.length;
  const last = closed ? n : n - 1;
  for (let i = 0; i < last; i++) {
    const a = verts[i], b = verts[(i + 1) % n];
    if (i === 0) d += `M${fx(a[0])} ${fx(-a[1])}`;
    const bulge = a[2] ?? 0;
    if (Math.abs(bulge) < 1e-9) { d += `L${fx(b[0])} ${fx(-b[1])}`; continue; }
    const dist = Math.hypot(b[0] - a[0], b[1] - a[1]);
    const r = (dist * (1 + bulge * bulge)) / (4 * Math.abs(bulge));
    d += `A${fx(r)} ${fx(r)} 0 ${Math.abs(bulge) > 1 ? 1 : 0} ${bulge > 0 ? 0 : 1} ${fx(b[0])} ${fx(-b[1])}`;
  }
  return closed ? `${d}Z` : d;
}

function walk(g: Geom, out: (d: string) => void): void {
  switch (g.type) {
    case 'line': out(`M${fx(g.p1[0])} ${fx(-g.p1[1])}L${fx(g.p2[0])} ${fx(-g.p2[1])}`); break;
    case 'circle': out(arcPath(g.c[0], g.c[1], g.r, 0, Math.PI * 2)); break;
    case 'arc': out(arcPath(g.c[0], g.c[1], g.r, g.a0, g.a1)); break;
    case 'poly': out(polyPath(g.verts, g.closed)); break;
    case 'compound': for (const p of g.parts) walk(p, out); break;
    default: break;
  }
}

function colourOf(rgb: number[] | undefined, c7: boolean | undefined): string {
  if (c7 || !rgb) return 'currentColor';
  return `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
}

export class ItemSvg {
  readonly svg: SVGSVGElement;
  private readonly strokes: SVGPathElement[] = [];
  private readonly fills: SVGPathElement[] = [];

  constructor() {
    this.svg = document.createElementNS(NS, 'svg');
    this.svg.setAttribute('viewBox', '0 0 100 60');
    this.svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    this.svg.classList.add('u2-item-svg');
    for (let i = 0; i < FILLS; i++) {
      const p = document.createElementNS(NS, 'path');
      p.setAttribute('stroke', 'none');
      this.fills.push(p);
      this.svg.appendChild(p);
    }
    for (let i = 0; i < STROKES; i++) {
      const p = document.createElementNS(NS, 'path');
      p.setAttribute('fill', 'none');
      p.setAttribute('vector-effect', 'non-scaling-stroke');
      p.setAttribute('stroke-width', '1.2');
      p.setAttribute('stroke-linecap', 'round');
      p.setAttribute('stroke-linejoin', 'round');
      this.strokes.push(p);
      this.svg.appendChild(p);
    }
  }

  paint(items: DisplayItem[], pad = 0.12): void {
    const strokes = new Map<string, string>();
    const fills = new Map<string, string>();
    const add = (map: Map<string, string>, key: string, d: string): void => { map.set(key, (map.get(key) ?? '') + d); };
    let box: [number, number, number, number] | null = null;
    for (const it of items) {
      const base = colourOf(it.color, it.color7);
      if (it.geom) {
        const parts = it.geom.type === 'compound' ? it.geom.parts : [it.geom];
        for (const part of parts) {
          const pc = part as unknown as { color?: number[]; color7?: boolean };
          walk(part, (d) => add(strokes, pc.color ? colourOf(pc.color, pc.color7) : base, d));
        }
      }
      for (const p of it.prims ?? []) {
        const c = (p as { c?: number[]; c7?: boolean }).c;
        const key = c ? colourOf(c, (p as { c7?: boolean }).c7) : base;
        if (p.t === 'pl') {
          let d = '';
          for (let i = 0; i + 1 < p.pts.length; i += 2) d += `${i === 0 ? 'M' : 'L'}${fx(p.pts[i])} ${fx(-p.pts[i + 1])}`;
          add(strokes, key, p.closed ? `${d}Z` : d);
        } else if (p.t === 'tri') {
          let d = '';
          for (let i = 0; i + 5 < p.pts.length; i += 6) d += `M${fx(p.pts[i])} ${fx(-p.pts[i + 1])}L${fx(p.pts[i + 2])} ${fx(-p.pts[i + 3])}L${fx(p.pts[i + 4])} ${fx(-p.pts[i + 5])}Z`;
          add(fills, key, d);
        } else if (p.t === 'fill') {
          let d = '';
          for (const ring of p.rings) {
            for (let i = 0; i + 1 < ring.length; i += 2) d += `${i === 0 ? 'M' : 'L'}${fx(ring[i])} ${fx(-ring[i + 1])}`;
            d += 'Z';
          }
          add(fills, p.c ? colourOf(p.c, undefined) : base, d);
        }
      }
      const b = it.bounds;
      if (b) box = box ? [Math.min(box[0], b[0]), Math.min(box[1], b[1]), Math.max(box[2], b[2]), Math.max(box[3], b[3])] : [b[0], b[1], b[2], b[3]];
    }
    this.assign(this.strokes, strokes, 'stroke');
    this.assign(this.fills, fills, 'fill');
    if (box) {
      const w = Math.max(box[2] - box[0], 1e-6), h = Math.max(box[3] - box[1], 1e-6);
      const m = Math.max(w, h) * pad;
      this.svg.setAttribute('viewBox', `${fx(box[0] - m)} ${fx(-box[3] - m)} ${fx(w + 2 * m)} ${fx(h + 2 * m)}`);
    }
  }

  private assign(pool: SVGPathElement[], map: Map<string, string>, attr: 'stroke' | 'fill'): void {
    const entries = Array.from(map.entries());
    pool.forEach((p, i) => {
      const e = entries[i];
      const d = e ? e[1] : '';
      if (p.getAttribute('d') !== d) p.setAttribute('d', d);
      const c = e ? e[0] : 'none';
      if (p.getAttribute(attr) !== c) p.setAttribute(attr, c);
    });
  }
}
