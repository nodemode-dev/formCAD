import type { BatchData, Mark } from './batch';
import type { DynLayer, PaintView, Painter } from './painter';
import type { PicDraw } from './pictures';
import type { Chunk } from './store';

interface Gpu {
  tri: WebGLBuffer;
  line: WebGLBuffer;
  quad: WebGLBuffer;
  marks: Mark[];
  alive: boolean;
}

const VS_FLAT = `#version 300 es
precision highp float;
layout(location=0) in vec2 a_pos;
layout(location=1) in vec4 a_col;
layout(location=2) in uint a_flag;
uniform vec2 u_off;
uniform vec2 u_k;
uniform float u_contrast;
uniform vec3 u_bg;
out vec4 v_col;
void main() {
  vec4 c = a_col;
  if (a_flag == 1u) c = vec4(vec3(u_contrast) * c.a, c.a);
  else if (a_flag == 2u) c = vec4(u_bg, 1.0);
  v_col = c;
  gl_Position = vec4((a_pos + u_off) * u_k, 0.0, 1.0);
}`;

const VS_QUAD = `#version 300 es
precision highp float;
layout(location=0) in vec4 a_seg;
layout(location=1) in float a_w;
layout(location=2) in vec4 a_col;
layout(location=3) in uint a_flag;
uniform vec2 u_off;
uniform float u_scale;
uniform vec2 u_half;
uniform float u_contrast;
uniform vec3 u_bg;
out vec4 v_col;
void main() {
  vec4 c = a_col;
  if (a_flag == 1u) c = vec4(vec3(u_contrast) * c.a, c.a);
  else if (a_flag == 2u) c = vec4(u_bg, 1.0);
  v_col = c;
  vec2 p0 = (a_seg.xy + u_off) * u_scale;
  vec2 p1 = (a_seg.zw + u_off) * u_scale;
  vec2 d = p1 - p0;
  float len = length(d);
  vec2 dir = len > 1e-6 ? d / len : vec2(1.0, 0.0);
  vec2 nrm = vec2(-dir.y, dir.x);
  float hw = max(a_w, 1.0) * 0.5;
  bool end = gl_VertexID >= 2;
  vec2 base = end ? p1 : p0;
  float side = (gl_VertexID & 1) == 0 ? -1.0 : 1.0;
  vec2 pos = base + dir * (end ? hw : -hw) + nrm * hw * side;
  gl_Position = vec4(pos / u_half, 0.0, 1.0);
}`;

const FS = `#version 300 es
precision mediump float;
in vec4 v_col;
out vec4 o;
void main() { o = v_col; }`;

const VS_IMG = `#version 300 es
precision highp float;
layout(location=0) in vec2 a_pos;
layout(location=1) in vec2 a_uv;
uniform vec2 u_k;
out vec2 v_uv;
void main() {
  v_uv = a_uv;
  gl_Position = vec4(a_pos * u_k, 0.0, 1.0);
}`;

const FS_IMG = `#version 300 es
precision mediump float;
in vec2 v_uv;
uniform sampler2D u_tex;
uniform float u_keep;
out vec4 o;
void main() { o = texture(u_tex, v_uv) * u_keep; }`;

function compile(gl: WebGL2RenderingContext, type: number, src: string): WebGLShader {
  const s = gl.createShader(type);
  if (!s) throw new Error('shader');
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) ?? 'shader');
  return s;
}

function program(gl: WebGL2RenderingContext, vs: string, fs: string): WebGLProgram {
  const p = gl.createProgram();
  if (!p) throw new Error('program');
  gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, vs));
  gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p) ?? 'link');
  return p;
}

export class GlPainter implements Painter {
  readonly kind = 'webgl2' as const;
  readonly retains = false;
  private readonly gl: WebGL2RenderingContext;
  private readonly flat: WebGLProgram;
  private readonly quad: WebGLProgram;
  private readonly fu: Record<string, WebGLUniformLocation | null> = {};
  private readonly qu: Record<string, WebGLUniformLocation | null> = {};
  private w = 1;
  private h = 1;
  private lost = false;
  private lostFn: (restored: boolean) => void = () => {};
  private readonly all = new Set<Gpu>();
  private readonly canvas: HTMLCanvasElement;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    const gl = canvas.getContext('webgl2', { alpha: true, premultipliedAlpha: true, antialias: false, depth: false, stencil: true, preserveDrawingBuffer: false, powerPreference: 'high-performance' });
    if (!gl) throw new Error('webgl2');
    this.gl = gl;
    this.flat = program(gl, VS_FLAT, FS);
    this.quad = program(gl, VS_QUAD, FS);
    for (const n of ['u_off', 'u_k', 'u_contrast', 'u_bg']) this.fu[n] = gl.getUniformLocation(this.flat, n);
    for (const n of ['u_off', 'u_scale', 'u_half', 'u_contrast', 'u_bg']) this.qu[n] = gl.getUniformLocation(this.quad, n);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.disable(gl.DEPTH_TEST);
    canvas.addEventListener('webglcontextlost', (e) => {
      e.preventDefault();
      this.lost = true;
      this.all.clear();
      this.lostFn(false);
    });
    canvas.addEventListener('webglcontextrestored', () => this.lostFn(true));
  }

  onLost(fn: (restored: boolean) => void): void { this.lostFn = fn; }

  resize(cssW: number, cssH: number, dpr: number): void {
    const w = Math.max(1, Math.round(cssW * dpr));
    const h = Math.max(1, Math.round(cssH * dpr));
    if (this.canvas.width !== w) this.canvas.width = w;
    if (this.canvas.height !== h) this.canvas.height = h;
    this.w = w;
    this.h = h;
  }

  private upload(owner: { data: BatchData | null; version: number; uploaded: number; gpu: unknown }): Gpu | null {
    const gl = this.gl;
    let g = owner.gpu as Gpu | null;
    if (owner.uploaded === owner.version && g && g.alive) return g;
    const d = owner.data;
    if (!d) return g && g.alive ? g : null;
    if (!g || !g.alive) {
      const tri = gl.createBuffer();
      const line = gl.createBuffer();
      const quad = gl.createBuffer();
      if (!tri || !line || !quad) return null;
      g = { tri, line, quad, marks: [], alive: true };
      this.all.add(g);
      owner.gpu = g;
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, g.tri);
    gl.bufferData(gl.ARRAY_BUFFER, d.tri.view(), gl.STATIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, g.line);
    gl.bufferData(gl.ARRAY_BUFFER, d.line.view(), gl.STATIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, g.quad);
    gl.bufferData(gl.ARRAY_BUFFER, d.quad.view(), gl.STATIC_DRAW);
    g.marks = d.marks;
    owner.uploaded = owner.version;
    owner.data = null;
    return g;
  }

  release(gpu: unknown): void {
    const g = gpu as Gpu | null;
    if (!g || !g.alive) return;
    g.alive = false;
    this.all.delete(g);
    if (this.lost) return;
    this.gl.deleteBuffer(g.tri);
    this.gl.deleteBuffer(g.line);
    this.gl.deleteBuffer(g.quad);
  }

  private flatPointers(buf: WebGLBuffer, first: number): void {
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 16, first * 16);
    gl.vertexAttribDivisor(0, 0);
    gl.enableVertexAttribArray(1);
    gl.vertexAttribPointer(1, 4, gl.UNSIGNED_BYTE, true, 16, first * 16 + 8);
    gl.vertexAttribDivisor(1, 0);
    gl.enableVertexAttribArray(2);
    gl.vertexAttribIPointer(2, 1, gl.UNSIGNED_INT, 16, first * 16 + 12);
    gl.vertexAttribDivisor(2, 0);
    gl.disableVertexAttribArray(3);
  }

  private quadPointers(buf: WebGLBuffer, first: number): void {
    const gl = this.gl;
    const b = first * 28;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 4, gl.FLOAT, false, 28, b);
    gl.vertexAttribDivisor(0, 1);
    gl.enableVertexAttribArray(1);
    gl.vertexAttribPointer(1, 1, gl.FLOAT, false, 28, b + 16);
    gl.vertexAttribDivisor(1, 1);
    gl.enableVertexAttribArray(2);
    gl.vertexAttribPointer(2, 4, gl.UNSIGNED_BYTE, true, 28, b + 20);
    gl.vertexAttribDivisor(2, 1);
    gl.enableVertexAttribArray(3);
    gl.vertexAttribIPointer(3, 1, gl.UNSIGNED_INT, 28, b + 24);
    gl.vertexAttribDivisor(3, 1);
  }

  private drawOne(g: Gpu, ox: number, oy: number, v: PaintView): void {
    const gl = this.gl;
    const offx = ox - v.cx;
    const offy = oy - v.cy;
    const m = g.marks;
    for (let i = 0; i + 1 < m.length; i++) {
      const a = m[i];
      const b = m[i + 1];
      if (b.t > a.t) {
        gl.useProgram(this.flat);
        gl.uniform2f(this.fu.u_off, offx, offy);
        gl.uniform2f(this.fu.u_k, (2 * v.scale) / v.width, (2 * v.scale) / v.height);
        gl.uniform1f(this.fu.u_contrast, v.contrast);
        gl.uniform3f(this.fu.u_bg, v.bg[0], v.bg[1], v.bg[2]);
        this.flatPointers(g.tri, a.t);
        gl.drawArrays(gl.TRIANGLES, 0, b.t - a.t);
      }
      if (b.l > a.l) {
        gl.useProgram(this.flat);
        gl.uniform2f(this.fu.u_off, offx, offy);
        gl.uniform2f(this.fu.u_k, (2 * v.scale) / v.width, (2 * v.scale) / v.height);
        gl.uniform1f(this.fu.u_contrast, v.contrast);
        gl.uniform3f(this.fu.u_bg, v.bg[0], v.bg[1], v.bg[2]);
        this.flatPointers(g.line, a.l);
        gl.drawArrays(gl.LINES, 0, b.l - a.l);
      }
      if (b.q > a.q) {
        gl.useProgram(this.quad);
        gl.uniform2f(this.qu.u_off, offx, offy);
        gl.uniform1f(this.qu.u_scale, v.scale);
        gl.uniform2f(this.qu.u_half, v.width / 2, v.height / 2);
        gl.uniform1f(this.qu.u_contrast, v.contrast);
        gl.uniform3f(this.qu.u_bg, v.bg[0], v.bg[1], v.bg[2]);
        this.quadPointers(g.quad, a.q);
        gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, b.q - a.q);
      }
    }
  }

  private clipBuf: WebGLBuffer | null = null;

  private stencilClip(poly: number[], v: PaintView): void {
    const gl = this.gl;
    const n = poly.length >> 1;
    if (n < 3) return;
    const tris = (n - 2) * 3;
    const buf = new ArrayBuffer(tris * 16);
    const f = new Float32Array(buf);
    const u = new Uint32Array(buf);
    for (let i = 0; i < n - 2; i++) {
      const ids = [0, i + 1, i + 2];
      for (let k = 0; k < 3; k++) {
        const o = (i * 3 + k) * 4;
        f[o] = poly[ids[k] * 2] - v.cx;
        f[o + 1] = poly[ids[k] * 2 + 1] - v.cy;
        u[o + 2] = 0xffffffff;
        u[o + 3] = 0;
      }
    }
    this.clipBuf ??= gl.createBuffer();
    if (!this.clipBuf) return;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.clipBuf);
    gl.bufferData(gl.ARRAY_BUFFER, buf, gl.DYNAMIC_DRAW);
    gl.enable(gl.STENCIL_TEST);
    gl.clear(gl.STENCIL_BUFFER_BIT);
    gl.colorMask(false, false, false, false);
    gl.stencilFunc(gl.ALWAYS, 0, 1);
    gl.stencilOp(gl.KEEP, gl.KEEP, gl.INVERT);
    gl.useProgram(this.flat);
    gl.uniform2f(this.fu.u_off, 0, 0);
    gl.uniform2f(this.fu.u_k, (2 * v.scale) / v.width, (2 * v.scale) / v.height);
    gl.uniform1f(this.fu.u_contrast, v.contrast);
    gl.uniform3f(this.fu.u_bg, v.bg[0], v.bg[1], v.bg[2]);
    this.flatPointers(this.clipBuf, 0);
    gl.drawArrays(gl.TRIANGLES, 0, tris);
    gl.colorMask(true, true, true, true);
    gl.stencilFunc(gl.EQUAL, 1, 1);
    gl.stencilOp(gl.KEEP, gl.KEEP, gl.KEEP);
  }

  private img: WebGLProgram | null = null;
  private readonly iu: Record<string, WebGLUniformLocation | null> = {};
  private imgBuf: WebGLBuffer | null = null;
  private readonly tex = new Map<ImageBitmap, WebGLTexture>();

  dropPicture(b: ImageBitmap): void {
    const t = this.tex.get(b);
    this.tex.delete(b);
    if (t && !this.lost) this.gl.deleteTexture(t);
  }

  private texture(b: ImageBitmap): WebGLTexture | null {
    const gl = this.gl;
    const have = this.tex.get(b);
    if (have && gl.isTexture(have)) return have;
    const t = gl.createTexture();
    if (!t) return null;
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, b);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    this.tex.set(b, t);
    return t;
  }

  private stencilRing(poly: number[], bit: number, v: PaintView): void {
    const gl = this.gl;
    const n = poly.length >> 1;
    if (n < 3) return;
    const tris = (n - 2) * 3;
    const buf = new ArrayBuffer(tris * 16);
    const f = new Float32Array(buf);
    const u = new Uint32Array(buf);
    for (let i = 0; i < n - 2; i++) {
      const ids = [0, i + 1, i + 2];
      for (let k = 0; k < 3; k++) {
        const o = (i * 3 + k) * 4;
        f[o] = poly[ids[k] * 2] - v.cx;
        f[o + 1] = poly[ids[k] * 2 + 1] - v.cy;
        u[o + 2] = 0xffffffff;
        u[o + 3] = 0;
      }
    }
    this.clipBuf ??= gl.createBuffer();
    if (!this.clipBuf) return;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.clipBuf);
    gl.bufferData(gl.ARRAY_BUFFER, buf, gl.DYNAMIC_DRAW);
    gl.stencilMask(bit);
    gl.stencilFunc(gl.ALWAYS, 0, bit);
    gl.stencilOp(gl.KEEP, gl.KEEP, gl.INVERT);
    gl.colorMask(false, false, false, false);
    gl.useProgram(this.flat);
    gl.uniform2f(this.fu.u_off, 0, 0);
    gl.uniform2f(this.fu.u_k, (2 * v.scale) / v.width, (2 * v.scale) / v.height);
    gl.uniform1f(this.fu.u_contrast, v.contrast);
    gl.uniform3f(this.fu.u_bg, v.bg[0], v.bg[1], v.bg[2]);
    this.flatPointers(this.clipBuf, 0);
    gl.drawArrays(gl.TRIANGLES, 0, tris);
    gl.colorMask(true, true, true, true);
  }

  private pictures(pics: PicDraw[], v: PaintView): void {
    if (!pics.length) return;
    const gl = this.gl;
    if (!this.img || !gl.isProgram(this.img)) {
      this.img = program(gl, VS_IMG, FS_IMG);
      for (const n of ['u_k', 'u_tex', 'u_keep']) this.iu[n] = gl.getUniformLocation(this.img, n);
    }
    this.imgBuf ??= gl.createBuffer();
    if (!this.imgBuf) return;
    for (const p of pics) {
      const t = this.texture(p.bitmap);
      if (!t) continue;
      let bits = 0;
      if (p.area || p.clip) {
        gl.enable(gl.STENCIL_TEST);
        gl.stencilMask(0xff);
        gl.clear(gl.STENCIL_BUFFER_BIT);
        if (p.area) { this.stencilRing(p.area, 1, v); bits |= 1; }
        if (p.clip) { this.stencilRing(p.clip, 2, v); bits |= 2; }
        gl.stencilMask(0);
        gl.stencilFunc(gl.EQUAL, bits, bits);
        gl.stencilOp(gl.KEEP, gl.KEEP, gl.KEEP);
      }
      const [ox, oy, rx, ry, tx, ty] = p.pts;
      const qx = rx + tx - ox;
      const qy = ry + ty - oy;
      const d = new Float32Array([
        ox - v.cx, oy - v.cy, 0, 1,
        rx - v.cx, ry - v.cy, 1, 1,
        tx - v.cx, ty - v.cy, 0, 0,
        qx - v.cx, qy - v.cy, 1, 0,
      ]);
      gl.useProgram(this.img);
      gl.uniform2f(this.iu.u_k, (2 * v.scale) / v.width, (2 * v.scale) / v.height);
      gl.uniform1f(this.iu.u_keep, 1 - p.fade);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, t);
      gl.uniform1i(this.iu.u_tex, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.imgBuf);
      gl.bufferData(gl.ARRAY_BUFFER, d, gl.DYNAMIC_DRAW);
      gl.enableVertexAttribArray(0);
      gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 16, 0);
      gl.vertexAttribDivisor(0, 0);
      gl.enableVertexAttribArray(1);
      gl.vertexAttribPointer(1, 2, gl.FLOAT, false, 16, 8);
      gl.vertexAttribDivisor(1, 0);
      gl.disableVertexAttribArray(2);
      gl.disableVertexAttribArray(3);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      if (bits) {
        gl.disable(gl.STENCIL_TEST);
        gl.stencilMask(0xff);
      }
    }
  }

  frame(v: PaintView, chunks: Iterable<Chunk>, dyn: DynLayer[], under: DynLayer[] = [], pics: PicDraw[] = []): void {
    if (this.lost || this.gl.isContextLost()) return;
    const gl = this.gl;
    gl.viewport(0, 0, this.w, this.h);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    this.pictures(pics, v);
    for (const d of under) {
      const g = this.upload(d);
      if (!g) continue;
      if (d.clip) this.stencilClip(d.clip, v);
      this.drawOne(g, d.ox, d.oy, v);
      if (d.clip) gl.disable(gl.STENCIL_TEST);
    }
    const r = v.visible;
    for (const c of chunks) {
      if (!c.built) continue;
      const b = c.bounds;
      if (b && (b[0] > r[2] || b[2] < r[0] || b[1] > r[3] || b[3] < r[1])) continue;
      const g = this.upload(c);
      if (g) this.drawOne(g, c.ox, c.oy, v);
    }
    for (const d of dyn) {
      const g = this.upload(d);
      if (g) this.drawOne(g, d.ox, d.oy, v);
    }
    gl.disableVertexAttribArray(3);
  }

  dispose(): void {
    for (const g of Array.from(this.all)) this.release(g);
    this.gl.getExtension('WEBGL_lose_context')?.loseContext();
  }
}
