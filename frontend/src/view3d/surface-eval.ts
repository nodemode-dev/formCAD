import type { SurfaceNet } from './nurbs-api';

interface Table { span: Int32Array; n: Float64Array; d: Float64Array; width: number }

function findSpan(knots: number[], degree: number, count: number, u: number): number {
  const top = count - 1;
  if (u >= knots[top + 1]) return top;
  if (u <= knots[degree]) return degree;
  let lo = degree, hi = top + 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (u < knots[mid]) hi = mid; else lo = mid;
  }
  return lo;
}

function basis(knots: number[], span: number, u: number, degree: number, out: Float64Array): void {
  const left = new Float64Array(degree + 1), right = new Float64Array(degree + 1);
  out[0] = 1;
  for (let j = 1; j <= degree; j++) {
    left[j] = u - knots[span + 1 - j];
    right[j] = knots[span + j] - u;
    let saved = 0;
    for (let r = 0; r < j; r++) {
      const den = right[r + 1] + left[j - r];
      const tmp = den > 0 ? out[r] / den : 0;
      out[r] = saved + right[r + 1] * tmp;
      saved = left[j - r] * tmp;
    }
    out[j] = saved;
  }
}

function table(knots: number[], degree: number, count: number, params: number[]): Table {
  const width = degree + 1;
  const span = new Int32Array(params.length);
  const n = new Float64Array(params.length * width), d = new Float64Array(params.length * width);
  const full = new Float64Array(width), low = new Float64Array(width);
  params.forEach((u, a) => {
    const s = findSpan(knots, degree, count, u);
    span[a] = s;
    basis(knots, s, u, degree, full);
    low.fill(0);
    basis(knots, s, u, degree - 1, low);
    for (let k = 0; k < width; k++) {
      const i = s - degree + k;
      const da = knots[i + degree] - knots[i], db = knots[i + degree + 1] - knots[i + 1];
      const first = k >= 1 && da > 0 ? low[k - 1] / da : 0;
      const second = k < degree && db > 0 ? low[k] / db : 0;
      n[a * width + k] = full[k];
      d[a * width + k] = degree * (first - second);
    }
  });
  return { span, n, d, width };
}

export class SurfaceEval {
  readonly positions: Float32Array;
  readonly normals: Float32Array;
  readonly indices: Uint32Array;
  readonly border: Float32Array;
  readonly nodes: number;
  private readonly tu: Table;
  private readonly tv: Table;
  private readonly gu: number;
  private readonly gv: number;
  private readonly nv: number;
  private readonly weights: Float64Array | null;
  private readonly sign: number;
  private readonly borderNodes: Uint32Array;

  constructor(net: SurfaceNet) {
    const [pu, pv] = net.degree;
    const [nu, nv] = net.count;
    this.nv = nv;
    this.gu = net.grid.u.length;
    this.gv = net.grid.v.length;
    this.nodes = this.gu * this.gv;
    this.tu = table(net.uknots, pu, nu, net.grid.u);
    this.tv = table(net.vknots, pv, nv, net.grid.v);
    this.weights = net.weights.length === nu * nv ? Float64Array.from(net.weights) : null;
    this.sign = net.reversed ? -1 : 1;
    this.positions = new Float32Array(this.nodes * 3);
    this.normals = new Float32Array(this.nodes * 3);
    const mask = net.grid.mask.length === this.nodes ? net.grid.mask : null;
    const gv = this.gv;
    const kept = (a: number, b: number): boolean => a >= 0 && b >= 0 && a < this.gu - 1 && b < gv - 1
      && (!mask || (mask[a * gv + b] === 1 && mask[(a + 1) * gv + b] === 1 && mask[a * gv + b + 1] === 1 && mask[(a + 1) * gv + b + 1] === 1));
    const idx: number[] = [];
    const edge: number[] = [];
    for (let a = 0; a < this.gu - 1; a++) {
      for (let b = 0; b < gv - 1; b++) {
        if (!kept(a, b)) continue;
        const p00 = a * gv + b, p10 = (a + 1) * gv + b, p01 = p00 + 1, p11 = p10 + 1;
        idx.push(p00, p10, p11, p00, p11, p01);
        if (!kept(a, b - 1)) edge.push(p00, p10);
        if (!kept(a, b + 1)) edge.push(p01, p11);
        if (!kept(a - 1, b)) edge.push(p00, p01);
        if (!kept(a + 1, b)) edge.push(p10, p11);
      }
    }
    this.indices = Uint32Array.from(idx);
    this.borderNodes = Uint32Array.from(edge);
    this.border = new Float32Array(edge.length * 3);
  }

  update(poles: Float64Array): void {
    const { tu, tv, gu, gv, nv, weights, sign } = this;
    const pos = this.positions, nor = this.normals;
    const wu = tu.width, wv = tv.width;
    for (let a = 0; a < gu; a++) {
      const iu = tu.span[a] - wu + 1;
      for (let b = 0; b < gv; b++) {
        const iv = tv.span[b] - wv + 1;
        let ax = 0, ay = 0, az = 0, aw = 0, ux = 0, uy = 0, uz = 0, uw = 0, vx = 0, vy = 0, vz = 0, vw = 0;
        for (let k = 0; k < wu; k++) {
          const nk = tu.n[a * wu + k], dk = tu.d[a * wu + k];
          const row = (iu + k) * nv + iv;
          for (let l = 0; l < wv; l++) {
            const at = row + l;
            const w = weights ? weights[at] : 1;
            const nl = tv.n[b * wv + l] * w, dl = tv.d[b * wv + l] * w;
            const x = poles[at * 3], y = poles[at * 3 + 1], z = poles[at * 3 + 2];
            const s = nk * nl, su = dk * nl, sv = nk * dl;
            ax += s * x; ay += s * y; az += s * z; aw += s;
            ux += su * x; uy += su * y; uz += su * z; uw += su;
            vx += sv * x; vy += sv * y; vz += sv * z; vw += sv;
          }
        }
        const inv = aw !== 0 ? 1 / aw : 1;
        const px = ax * inv, py = ay * inv, pz = az * inv;
        const sux = (ux - uw * px) * inv, suy = (uy - uw * py) * inv, suz = (uz - uw * pz) * inv;
        const svx = (vx - vw * px) * inv, svy = (vy - vw * py) * inv, svz = (vz - vw * pz) * inv;
        let nx = suy * svz - suz * svy, ny = suz * svx - sux * svz, nz = sux * svy - suy * svx;
        const len = Math.hypot(nx, ny, nz);
        if (len > 1e-14) { nx *= sign / len; ny *= sign / len; nz *= sign / len; } else { nx = 0; ny = 0; nz = 1; }
        const o = (a * gv + b) * 3;
        pos[o] = px; pos[o + 1] = py; pos[o + 2] = pz;
        nor[o] = nx; nor[o + 1] = ny; nor[o + 2] = nz;
      }
    }
    const e = this.borderNodes, out = this.border;
    for (let k = 0; k < e.length; k++) {
      const o = e[k] * 3;
      out[k * 3] = pos[o]; out[k * 3 + 1] = pos[o + 1]; out[k * 3 + 2] = pos[o + 2];
    }
  }
}
