export class Sink {
  buf: ArrayBuffer;
  f: Float32Array;
  u: Uint32Array;
  n = 0;
  readonly stride: number;

  constructor(stride: number, initial = 1024) {
    this.stride = stride;
    this.buf = new ArrayBuffer(initial * 4);
    this.f = new Float32Array(this.buf);
    this.u = new Uint32Array(this.buf);
  }

  get count(): number { return this.n / this.stride; }

  ensure(words: number): void {
    const need = this.n + words;
    if (need <= this.f.length) return;
    let cap = this.f.length;
    while (cap < need) cap *= 2;
    const next = new ArrayBuffer(cap * 4);
    new Uint8Array(next).set(new Uint8Array(this.buf, 0, this.n * 4));
    this.buf = next;
    this.f = new Float32Array(next);
    this.u = new Uint32Array(next);
  }

  vertex(x: number, y: number, col: number, flag: number): void {
    this.ensure(4);
    const i = this.n;
    this.f[i] = x;
    this.f[i + 1] = y;
    this.u[i + 2] = col;
    this.u[i + 3] = flag;
    this.n = i + 4;
  }

  quad(x0: number, y0: number, x1: number, y1: number, w: number, col: number, flag: number): void {
    this.ensure(7);
    const i = this.n;
    this.f[i] = x0;
    this.f[i + 1] = y0;
    this.f[i + 2] = x1;
    this.f[i + 3] = y1;
    this.f[i + 4] = w;
    this.u[i + 5] = col;
    this.u[i + 6] = flag;
    this.n = i + 7;
  }

  view(): Uint8Array { return new Uint8Array(this.buf, 0, this.n * 4); }
}

export interface Mark { t: number; l: number; q: number }

export class BatchData {
  readonly tri = new Sink(4);
  readonly line = new Sink(4);
  readonly quad = new Sink(7);
  readonly marks: Mark[] = [{ t: 0, l: 0, q: 0 }];

  split(): void {
    const last = this.marks[this.marks.length - 1];
    const m = { t: this.tri.count, l: this.line.count, q: this.quad.count };
    if (m.t !== last.t || m.l !== last.l || m.q !== last.q) this.marks.push(m);
  }

  close(): void {
    this.marks.push({ t: this.tri.count, l: this.line.count, q: this.quad.count });
  }

  get empty(): boolean { return this.tri.n === 0 && this.line.n === 0 && this.quad.n === 0; }
}
