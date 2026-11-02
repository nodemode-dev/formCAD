import type { Rect } from './types';

const FANOUT = 16;

interface Level { b: Float64Array; n: number }

export class RTree {
  private levels: Level[] = [];
  private ids: Int32Array = new Int32Array(0);
  size = 0;

  static build(bounds: Rect[]): RTree {
    const t = new RTree();
    const n = bounds.length;
    t.size = n;
    if (n === 0) return t;
    const order = Array.from({ length: n }, (_, i) => i);
    const cx = (i: number): number => bounds[i][0] + bounds[i][2];
    const cy = (i: number): number => bounds[i][1] + bounds[i][3];
    order.sort((a, b) => cx(a) - cx(b));
    const slices = Math.ceil(Math.sqrt(Math.ceil(n / FANOUT)));
    const per = Math.ceil(n / slices);
    for (let s = 0; s < n; s += per) {
      const part = order.slice(s, s + per).sort((a, b) => cy(a) - cy(b));
      for (let k = 0; k < part.length; k++) order[s + k] = part[k];
    }
    t.ids = Int32Array.from(order);
    const leaf = new Float64Array(n * 4);
    for (let i = 0; i < n; i++) {
      const r = bounds[order[i]];
      leaf[i * 4] = r[0];
      leaf[i * 4 + 1] = r[1];
      leaf[i * 4 + 2] = r[2];
      leaf[i * 4 + 3] = r[3];
    }
    t.levels.push({ b: leaf, n });
    let cur = t.levels[0];
    while (cur.n > FANOUT) {
      const m = Math.ceil(cur.n / FANOUT);
      const b = new Float64Array(m * 4);
      for (let i = 0; i < m; i++) {
        let x0 = Infinity;
        let y0 = Infinity;
        let x1 = -Infinity;
        let y1 = -Infinity;
        const end = Math.min(cur.n, (i + 1) * FANOUT);
        for (let j = i * FANOUT; j < end; j++) {
          if (cur.b[j * 4] < x0) x0 = cur.b[j * 4];
          if (cur.b[j * 4 + 1] < y0) y0 = cur.b[j * 4 + 1];
          if (cur.b[j * 4 + 2] > x1) x1 = cur.b[j * 4 + 2];
          if (cur.b[j * 4 + 3] > y1) y1 = cur.b[j * 4 + 3];
        }
        b[i * 4] = x0;
        b[i * 4 + 1] = y0;
        b[i * 4 + 2] = x1;
        b[i * 4 + 3] = y1;
      }
      cur = { b, n: m };
      t.levels.push(cur);
    }
    return t;
  }

  query(x0: number, y0: number, x1: number, y1: number, hit: (id: number) => void): void {
    if (this.size === 0) return;
    const top = this.levels.length - 1;
    const walk = (level: number, from: number, to: number): void => {
      const L = this.levels[level];
      for (let i = from; i < to; i++) {
        const o = i * 4;
        if (L.b[o] > x1 || L.b[o + 2] < x0 || L.b[o + 1] > y1 || L.b[o + 3] < y0) continue;
        if (level === 0) hit(this.ids[i]);
        else walk(level - 1, i * FANOUT, Math.min(this.levels[level - 1].n, (i + 1) * FANOUT));
      }
    };
    walk(top, 0, this.levels[top].n);
  }
}
