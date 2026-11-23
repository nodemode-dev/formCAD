import * as THREE from 'three';
import { docStore } from '../ui/doc-store';
import { el, q, setHidden, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import type { ViewLayer } from '../view3d/layer';
import type { Palette } from '../view3d/kit';
import type { Vec3 } from '../view3d/types';
import type { Viewport3D } from '../view3d/viewport';
import { buffer, docUrl, req } from './net';

export interface Ramp {
  kind: 'gradient' | 'bands' | 'zones';
  stops: Array<[number, string]>;
  min: number | null;
  max: number | null;
  center: number | null;
  symmetric: boolean;
  limits?: [number, number];
}

export interface AnalysisMeta {
  mode: string;
  label: string;
  unit: string;
  measure: string;
  ramp_name: string;
  ramp: Ramp;
  range: [number, number];
  undefined: string;
  stats: Record<string, number | null>;
  params: Record<string, unknown>;
  bodies: Array<{ handle: number; name: string }>;
}

export interface AnalysisState {
  seq: number;
  spec: Record<string, unknown> | null;
  combs: Record<string, unknown> | null;
  modes: string[];
  ramps: Record<string, Ramp>;
}

interface CombReply {
  curves: Array<{ planar: boolean; segments: Array<{ points: number[][]; tips: number[][]; curvature: number[]; inflections: number[] }> }>;
  max_curvature: number;
  height: number;
}

export interface ParsedValues { meta: AnalysisMeta; bodies: Map<number, Float32Array>; version: Map<number, number> }

const MAGIC = 0x56414346;
const SENTINEL = -3.0e38;
const RAMP_W = 512;

export function parseValues(buf: ArrayBuffer): ParsedValues {
  if (buf.byteLength < 64) throw new Error('The analysis data is truncated.');
  const dv = new DataView(buf);
  const u = (i: number): number => dv.getUint32(i * 4, true);
  if (u(0) !== MAGIC) throw new Error('The analysis data has the wrong header.');
  const count = u(5), tableAt = u(7), metaAt = u(8), metaLen = u(9);
  if (metaAt + metaLen > buf.byteLength || tableAt + count * 32 > buf.byteLength) throw new Error('The analysis data tables are outside the buffer.');
  const meta = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, metaAt, metaLen))) as AnalysisMeta;
  const bodies = new Map<number, Float32Array>();
  const version = new Map<number, number>();
  for (let i = 0; i < count; i++) {
    const o = tableAt + i * 32;
    const handle = dv.getUint32(o, true), ver = dv.getUint32(o + 4, true), n = dv.getUint32(o + 8, true), at = dv.getUint32(o + 12, true);
    if (at % 4 !== 0 || at + n * 4 > buf.byteLength) throw new Error('The analysis data has a section outside the buffer.');
    const src = new Float32Array(buf, at, n);
    const out = new Float32Array(n);
    for (let k = 0; k < n; k++) out[k] = Number.isFinite(src[k]) ? src[k] : SENTINEL;
    bodies.set(handle, out);
    version.set(handle, ver);
  }
  return { meta, bodies, version };
}

function rampTexture(ramp: Ramp, bands: boolean): THREE.DataTexture {
  const stops = ramp.stops.map(([p, c]) => ({ p, c: new THREE.Color(c) }));
  const data = new Uint8Array(RAMP_W * 4);
  const tmp = new THREE.Color();
  for (let i = 0; i < RAMP_W; i++) {
    const x = (i + 0.5) / RAMP_W;
    let col = stops[stops.length - 1].c;
    if (bands) {
      const idx = Math.min(stops.length - 1, Math.floor(x * stops.length));
      col = stops[idx].c;
    } else if (x <= stops[0].p) {
      col = stops[0].c;
    } else {
      for (let k = 0; k + 1 < stops.length; k++) {
        const a = stops[k], b = stops[k + 1];
        if (x >= a.p && x <= b.p) {
          const span = b.p - a.p;
          col = span < 1e-9 ? b.c : tmp.copy(a.c).lerp(b.c, (x - a.p) / span);
          break;
        }
      }
    }
    const lin = col.clone().convertLinearToSRGB();
    data[i * 4] = Math.round(lin.r * 255);
    data[i * 4 + 1] = Math.round(lin.g * 255);
    data[i * 4 + 2] = Math.round(lin.b * 255);
    data[i * 4 + 3] = 255;
  }
  const tex = new THREE.DataTexture(data, RAMP_W, 1, THREE.RGBAFormat);
  tex.colorSpace = THREE.NoColorSpace;
  tex.magFilter = tex.minFilter = THREE.LinearFilter;
  tex.needsUpdate = true;
  return tex;
}

const VERT = `
#include <clipping_planes_pars_vertex>
attribute vec2 aval;
varying vec2 vVal;
varying vec3 vN;
void main() {
  vVal = aval;
  vN = normalize(normalMatrix * normal);
  vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mvPosition;
#include <clipping_planes_vertex>
}`;

const FRAG = `
#include <clipping_planes_pars_fragment>
uniform sampler2D uRamp;
uniform float uLo;
uniform float uHi;
uniform float uBands;
uniform float uStripes;
uniform float uPeriodic;
uniform float uBand;
uniform vec3 uUndef;
varying vec2 vVal;
varying vec3 vN;
void main() {
#include <clipping_planes_fragment>
  vec3 base;
  float val = uPeriodic > 0.5 ? degrees(atan(vVal.y, vVal.x)) / uBand : vVal.x;
  if (vVal.x < -1.0e38) {
    base = uUndef;
  } else if (uStripes > 0.5) {
    float cell = floor(val);
    float idx = mod(cell, uBands);
    float x = (idx + 0.5) / uBands;
    base = texture2D(uRamp, vec2(x, 0.5)).rgb;
  } else {
    float x = clamp((val - uLo) / max(uHi - uLo, 1.0e-30), 0.0, 1.0);
    base = texture2D(uRamp, vec2(x, 0.5)).rgb;
  }
  float shade = 0.72 + 0.28 * abs(normalize(vN).z);
  gl_FragColor = vec4(base * shade, 1.0);
}`;

export class AnalysisColors implements ViewLayer {
  readonly group = new THREE.Group();
  meta: AnalysisMeta | null = null;
  private data: ParsedValues | null = null;
  private tex: THREE.DataTexture | null = null;
  private readonly mat: THREE.ShaderMaterial;
  private readonly lines = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0xffffff, depthTest: false, transparent: true }));
  private readonly tipLines = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0xffffff, depthTest: false, transparent: true }));
  private readonly legend: HTMLElement;
  private timer = 0;
  private gen = 0;
  combInfo: { max: number; teeth: number; inflections: number } | null = null;
  onChange: (() => void) | null = null;
  stateSeq = 0;
  applied = 0;

  constructor(private readonly vp: Viewport3D) {
    this.mat = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: FRAG,
      uniforms: { uRamp: { value: null }, uLo: { value: 0 }, uHi: { value: 1 }, uBands: { value: 2 }, uStripes: { value: 0 }, uPeriodic: { value: 0 }, uBand: { value: 6 }, uUndef: { value: new THREE.Color('#8a8a8a') } },
      clipping: true,
      side: THREE.DoubleSide,
      polygonOffset: true,
      polygonOffsetFactor: 1,
      polygonOffsetUnits: 1,
    });
    this.lines.frustumCulled = false;
    this.tipLines.frustumCulled = false;
    this.lines.renderOrder = this.tipLines.renderOrder = 7;
    this.lines.visible = this.tipLines.visible = false;
    this.group.add(this.lines, this.tipLines);
    this.legend = el(
      '<div class="u8-legend" hidden><div class="u8-legend-title"></div><div class="u8-legend-body"><div class="u8-legend-bar"></div><div class="u8-legend-ticks"><span data-t="hi"></span><span data-t="mid"></span><span data-t="lo"></span></div></div><div class="u8-legend-foot"></div></div>');
    vp.host.append(this.legend);
  }

  get active(): boolean { return this.data !== null; }
  get hasCombs(): boolean { return this.lines.visible; }

  private async state(): Promise<AnalysisState | null> {
    const id = docStore.activeId;
    if (!id) return null;
    return req<AnalysisState>('GET', docUrl(id, 'analysis'));
  }

  schedule(delay = 250): void {
    if (this.timer) return;
    this.timer = window.setTimeout(() => { this.timer = 0; void this.refresh(); }, delay);
  }

  async refresh(): Promise<AnalysisState | null> {
    const my = ++this.gen;
    const id = docStore.activeId;
    let st: AnalysisState | null = null;
    try { st = await this.state(); } catch { st = null; }
    if (my !== this.gen) return st;
    if (!id || !st) { this.clearSurface(); this.clearCombs(); return st; }
    this.stateSeq = st.seq;
    if (st.spec) {
      try {
        const buf = await buffer(docUrl(id, 'analysis/values'));
        if (my !== this.gen) return st;
        if (buf) this.apply(parseValues(buf)); else this.clearSurface();
      } catch {
        if (my === this.gen) this.clearSurface();
      }
    } else {
      this.clearSurface();
    }
    if (st.combs) {
      try {
        const res = await req<CombReply>('GET', docUrl(id, 'analysis/combs'));
        if (my === this.gen) this.setCombs(res);
      } catch {
        if (my === this.gen) this.clearCombs();
      }
    } else {
      this.clearCombs();
    }
    this.onChange?.();
    return st;
  }

  private apply(p: ParsedValues): void {
    this.data = p;
    this.meta = p.meta;
    const r = p.meta.ramp;
    const stripes = p.meta.mode === 'zebra' || p.meta.mode === 'isophote';
    const bands = r.kind === 'bands' || stripes;
    this.tex?.dispose();
    this.tex = rampTexture(r, bands);
    const u = this.mat.uniforms;
    u.uRamp.value = this.tex;
    u.uLo.value = p.meta.range[0];
    u.uHi.value = p.meta.range[1];
    u.uBands.value = Math.max(2, r.stops.length);
    u.uStripes.value = stripes ? 1 : 0;
    const band = Number(p.meta.params.band);
    u.uPeriodic.value = p.meta.mode === 'zebra' && band > 0 ? 1 : 0;
    u.uBand.value = band > 0 ? band : 6;
    (u.uUndef.value as THREE.Color).set(p.meta.undefined || '#8a8a8a');
    this.applied++;
    this.paint();
    this.paintLegend();
  }

  stripesFor(id: number, normals: Float32Array, reversed: boolean): { values: Float32Array; size: number; mat: THREE.ShaderMaterial } | null {
    const m = this.meta;
    if (!m || !this.data?.bodies.has(id) || (m.mode !== 'zebra' && m.mode !== 'isophote')) return null;
    const vec = (raw: unknown, fallback: Vec3): Vec3 => {
      const a = Array.isArray(raw) && raw.length === 3 ? raw.map(Number) : fallback;
      const l = Math.hypot(a[0], a[1], a[2]) || 1;
      return [a[0] / l, a[1] / l, a[2] / l];
    };
    const n = normals.length / 3;
    const band = this.mat.uniforms.uBand.value as number;
    if (m.mode === 'isophote') {
      const d = vec(m.params.light, [0, -1, 1]);
      const sign = reversed ? -1 : 1;
      const out = new Float32Array(n);
      for (let k = 0; k < n; k++) {
        const c = sign * (normals[k * 3] * d[0] + normals[k * 3 + 1] * d[1] + normals[k * 3 + 2] * d[2]);
        out[k] = (Math.acos(Math.max(-1, Math.min(1, c))) * 180) / Math.PI / band;
      }
      return { values: out, size: 1, mat: this.mat };
    }
    const v = vec(m.params.view, [0, -1, 0]);
    const a = vec(m.params.axis, [0, 0, 1]);
    const ref: Vec3 = Math.abs(a[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0];
    const ra = ref[0] * a[0] + ref[1] * a[1] + ref[2] * a[2];
    const e1 = vec([ref[0] - ra * a[0], ref[1] - ra * a[1], ref[2] - ra * a[2]], [1, 0, 0]);
    const e2: Vec3 = [a[1] * e1[2] - a[2] * e1[1], a[2] * e1[0] - a[0] * e1[2], a[0] * e1[1] - a[1] * e1[0]];
    const out = new Float32Array(n * 2);
    for (let k = 0; k < n; k++) {
      const nx = normals[k * 3], ny = normals[k * 3 + 1], nz = normals[k * 3 + 2];
      const s = 2 * (nx * v[0] + ny * v[1] + nz * v[2]);
      const rx = s * nx - v[0], ry = s * ny - v[1], rz = s * nz - v[2];
      const along = rx * a[0] + ry * a[1] + rz * a[2];
      const dx = rx - along * a[0], dy = ry - along * a[1], dz = rz - along * a[2];
      const x = dx * e1[0] + dy * e1[1] + dz * e1[2], y = dx * e2[0] + dy * e2[1] + dz * e2[2];
      const l = Math.hypot(x, y);
      if (l < 1e-9) { out[k * 2] = SENTINEL; continue; }
      out[k * 2] = x / l;
      out[k * 2 + 1] = y / l;
    }
    return { values: out, size: 2, mat: this.mat };
  }

  paint(): void {
    const d = this.data;
    const map = new Map<number, Float32Array | null>();
    const periodic = this.mat.uniforms.uPeriodic.value > 0.5;
    const band = this.mat.uniforms.uBand.value as number;
    for (const [id, v] of this.vp.bodyViews) {
      const vals = d?.bodies.get(id);
      if (!vals || vals.length !== v.vertexCount) { map.set(id, null); continue; }
      if (!periodic) { map.set(id, vals); continue; }
      const out = new Float32Array(vals.length * 2);
      for (let k = 0; k < vals.length; k++) {
        const x = vals[k];
        if (x < -1.0e38) { out[k * 2] = x; continue; }
        const phi = (x * band * Math.PI) / 180;
        out[k * 2] = Math.cos(phi);
        out[k * 2 + 1] = Math.sin(phi);
      }
      map.set(id, out);
    }
    this.vp.setPaint(map, this.mat);
  }

  sceneChanged(): void {
    if (this.data) { this.paint(); this.schedule(300); }
    if (this.hasCombs) this.schedule(300);
  }

  clearSurface(): void {
    if (!this.data && !this.meta) return;
    this.data = null;
    this.meta = null;
    this.applied++;
    this.paint();
    setHidden(this.legend, true);
    this.onChange?.();
  }

  private setCombs(res: CombReply): void {
    const teeth: number[] = [];
    const tips: number[] = [];
    let n = 0, infl = 0;
    for (const c of res.curves) {
      for (const s of c.segments) {
        infl += s.inflections.length;
        for (let i = 0; i < s.points.length; i++) {
          teeth.push(...s.points[i], ...s.tips[i]);
          n++;
          if (i + 1 < s.tips.length) tips.push(...s.tips[i], ...s.tips[i + 1]);
        }
      }
    }
    this.lines.geometry.dispose();
    this.tipLines.geometry.dispose();
    this.lines.geometry = new THREE.BufferGeometry();
    this.tipLines.geometry = new THREE.BufferGeometry();
    this.lines.geometry.setAttribute('position', new THREE.Float32BufferAttribute(teeth, 3));
    this.tipLines.geometry.setAttribute('position', new THREE.Float32BufferAttribute(tips, 3));
    this.lines.visible = this.tipLines.visible = n > 0;
    this.combInfo = { max: res.max_curvature, teeth: n, inflections: infl };
    this.vp.invalidate();
  }

  clearCombs(): void {
    if (!this.lines.visible && !this.combInfo) return;
    this.lines.visible = this.tipLines.visible = false;
    this.combInfo = null;
    this.vp.invalidate();
    this.onChange?.();
  }

  private nakedLines: THREE.LineSegments | null = null;

  setNaked(loops: number[][][]): number {
    this.clearNaked();
    const pos: number[] = [];
    for (const pl of loops) for (let i = 0; i + 1 < pl.length; i++) pos.push(...pl[i], ...pl[i + 1]);
    if (!pos.length) return 0;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    this.nakedLines = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0xef4444, depthTest: false, transparent: true }));
    this.nakedLines.renderOrder = 8;
    this.nakedLines.frustumCulled = false;
    this.group.add(this.nakedLines);
    this.vp.invalidate();
    return pos.length / 6;
  }

  clearNaked(): void {
    if (!this.nakedLines) return;
    this.group.remove(this.nakedLines);
    this.nakedLines.geometry.dispose();
    this.nakedLines = null;
    this.vp.invalidate();
  }

  clearAll(): void {
    this.clearNaked();
    this.gen++;
    this.clearSurface();
    this.clearCombs();
  }

  private paintLegend(): void {
    const m = this.meta;
    if (!m) { setHidden(this.legend, true); return; }
    const [lo, hi] = m.range;
    const stripes = m.mode === 'zebra' || m.mode === 'isophote';
    const num = (v: number): string => (Math.abs(v) >= 1e4 || (Math.abs(v) < 1e-3 && v !== 0) ? v.toExponential(2) : String(Number(v.toPrecision(4))));
    setText(q(this.legend, '.u8-legend-title'), t(m.label) + (m.measure ? ` · ${t(m.measure)}` : ''));
    const bar = q(this.legend, '.u8-legend-bar');
    const stops = m.ramp.stops;
    const css = stripes || m.ramp.kind === 'bands'
      ? stops.map((s, i) => `${s[1]} ${(i / stops.length) * 100}% ${((i + 1) / stops.length) * 100}%`).join(', ')
      : stops.map((s) => `${s[1]} ${(s[0] * 100).toFixed(2)}%`).join(', ');
    const g = `linear-gradient(to top, ${css})`;
    if (bar.style.background !== g) bar.style.background = g;
    const unit = m.unit && m.unit !== 'stripe' ? ` ${m.unit}` : '';
    setText(q(this.legend, '[data-t="hi"]'), stripes ? '' : num(hi));
    setText(q(this.legend, '[data-t="mid"]'), stripes ? '' : num((lo + hi) / 2));
    setText(q(this.legend, '[data-t="lo"]'), stripes ? '' : num(lo));
    const st = m.stats;
    const foot = stripes ? t('Stripes follow the light reflected off each surface.') : `${t('min')} ${st.min == null ? '-' : num(st.min)} · ${t('max')} ${st.max == null ? '-' : num(st.max)}${unit}`;
    setText(q(this.legend, '.u8-legend-foot'), foot);
    setHidden(this.legend, false);
  }

  palette(pal: Palette): void {
    (this.lines.material as THREE.LineBasicMaterial).color.copy(pal.accent);
    (this.tipLines.material as THREE.LineBasicMaterial).color.copy(pal.snap);
    this.vp.invalidate();
  }

  bounds(): { min: Vec3; max: Vec3 } | null { return null; }

  dispose(): void {
    this.mat.dispose();
    this.tex?.dispose();
    this.lines.geometry.dispose();
    this.tipLines.geometry.dispose();
    this.legend.remove();
  }
}
