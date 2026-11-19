import * as THREE from 'three';
import { Line2 } from 'three/examples/jsm/lines/Line2.js';
import { LineGeometry } from 'three/examples/jsm/lines/LineGeometry.js';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { tokenHexCss } from '../canvas/ink';
import { MEDIA } from '../canvas/media';
import type { InkColors } from './overlay';
import type { ViewLayer } from './layer';
import type { SeamReport } from './nurbs-api';
import type { Vec3 } from './types';

export type SeamState = 'pass' | 'partial' | 'fail';

export function seamState(r: SeamReport): SeamState {
  const t = r.tolerance;
  if (!t) return r.g2 ? 'pass' : r.g1 ? 'partial' : r.g0 ? 'partial' : 'fail';
  const pos = r.max_gap <= t.length;
  const tan = r.max_angle <= t.angle;
  const cur = r.max_curvature_gap <= t.curvature;
  if (pos && tan && cur) return 'pass';
  if (pos && tan) return 'partial';
  return 'fail';
}

export const seamLevel = (r: SeamReport): string => (r.g2 ? 'G2' : r.g1 ? 'G1' : r.g0 ? 'G0' : 'None');

const num = (v: number): string => (v === 0 ? '0' : Math.abs(v) < 1e-3 || Math.abs(v) >= 1e4 ? v.toExponential(1) : Number(v.toPrecision(3)).toString());

interface Seam {
  key: string;
  report: SeamReport;
  anchor: Vec3;
  line: Line2;
  state: SeamState;
  bodies: number[];
}

interface Colors { ok: string; warn: string; danger: string }

function readColors(host: HTMLElement): Colors {
  return {
    ok: tokenHexCss('--ok', MEDIA.analysisOk, host),
    warn: tokenHexCss('--warn', MEDIA.analysisWarn, host),
    danger: tokenHexCss('--danger', MEDIA.analysisDanger, host),
  };
}

export class AnalysisLayer implements ViewLayer {
  readonly group = new THREE.Group();
  private readonly seams = new Map<string, Seam>();
  private readonly mats: Record<SeamState, LineMaterial>;
  private readonly nakedMat: LineMaterial;
  private naked: Line2[] = [];
  private nakedCount = 0;
  private colors: Colors;

  constructor(private readonly host: HTMLElement, private readonly redraw: () => void) {
    this.colors = readColors(host);
    const mk = (hex: string, width: number): LineMaterial => new LineMaterial({ color: new THREE.Color(hex).getHex(), linewidth: width, worldUnits: false, depthTest: false, transparent: true });
    this.mats = { pass: mk(this.colors.ok, 4), partial: mk(this.colors.warn, 4), fail: mk(this.colors.danger, 4) };
    this.nakedMat = mk(this.colors.danger, 3.2);
    this.group.renderOrder = 6;
  }

  get seamCount(): number { return this.seams.size; }
  get nakedEdgeCount(): number { return this.nakedCount; }

  seamList(): Array<{ key: string; level: string; state: SeamState }> {
    return [...this.seams.values()].map((s) => ({ key: s.key, level: seamLevel(s.report), state: s.state }));
  }

  setSeam(r: SeamReport, scale: number, bodies: number[] = []): void {
    const hair = (r.hair ?? []).map((h) => h.p.map((c) => c / scale) as Vec3);
    if (hair.length < 2) return;
    const anchor = hair[hair.length >> 1];
    const key = `${anchor[0].toFixed(3)},${anchor[1].toFixed(3)},${anchor[2].toFixed(3)}`;
    const state = seamState(r);
    let s = this.seams.get(key);
    if (!s) {
      const line = new Line2(new LineGeometry(), this.mats[state]);
      line.frustumCulled = false;
      this.group.add(line);
      s = { key, report: r, anchor, line, state, bodies };
      this.seams.set(key, s);
    }
    s.bodies = bodies;
    s.report = r;
    s.anchor = anchor;
    s.state = state;
    s.line.material = this.mats[state];
    s.line.geometry.dispose();
    s.line.geometry = new LineGeometry();
    s.line.geometry.setPositions(hair.flat());
    this.redraw();
  }

  clearSeamsOf(changed: number[]): void {
    const hit = new Set(changed);
    let any = false;
    for (const [key, s] of this.seams) {
      if (s.bodies.length && !s.bodies.some((b) => hit.has(b))) continue;
      this.group.remove(s.line);
      s.line.geometry.dispose();
      this.seams.delete(key);
      any = true;
    }
    if (any) this.redraw();
  }

  clearSeams(): void {
    for (const s of this.seams.values()) { this.group.remove(s.line); s.line.geometry.dispose(); }
    this.seams.clear();
    this.redraw();
  }

  setNaked(polylines: Vec3[][], scale: number, count: number): void {
    this.dropNaked();
    for (const pl of polylines) {
      if (pl.length < 2) continue;
      const g = new LineGeometry();
      g.setPositions(pl.flatMap((p) => p.map((c) => c / scale)));
      const line = new Line2(g, this.nakedMat);
      line.frustumCulled = false;
      this.group.add(line);
      this.naked.push(line);
    }
    this.nakedCount = count;
    this.redraw();
  }

  private dropNaked(): void {
    for (const l of this.naked) { this.group.remove(l); l.geometry.dispose(); }
    this.naked = [];
    this.nakedCount = 0;
  }

  clearNaked(): void {
    this.dropNaked();
    this.redraw();
  }

  clear(): void {
    this.clearSeams();
    this.clearNaked();
  }

  resolution(w: number, h: number): void {
    for (const m of Object.values(this.mats)) m.resolution.set(w, h);
    this.nakedMat.resolution.set(w, h);
  }

  palette(): void {
    this.colors = readColors(this.host);
    this.mats.pass.color.set(this.colors.ok);
    this.mats.partial.color.set(this.colors.warn);
    this.mats.fail.color.set(this.colors.danger);
    this.nakedMat.color.set(this.colors.danger);
  }

  draw(g: CanvasRenderingContext2D, project: (p: Vec3) => { x: number; y: number } | null, ink: InkColors): void {
    if (!this.seams.size) return;
    g.save();
    for (const s of this.seams.values()) {
      const q = project(s.anchor);
      if (!q) continue;
      const color = this.colors[s.state === 'pass' ? 'ok' : s.state === 'partial' ? 'warn' : 'danger'];
      const r = s.report;
      const lines = [`gap ${num(r.max_gap)} mm`, `angle ${num(r.max_angle)} rad`, `curv ${num(r.max_curvature_gap)}`];
      g.font = '600 12px -apple-system, "Segoe UI", Inter, system-ui, sans-serif';
      const head = seamLevel(r);
      const hw = Math.ceil(g.measureText(head).width) + 14;
      g.font = '11px -apple-system, "Segoe UI", Inter, system-ui, sans-serif';
      const bw = Math.max(hw, ...lines.map((l) => Math.ceil(g.measureText(l).width) + 12));
      const bh = 22 + lines.length * 14 + 4;
      const x = Math.round(q.x + 12), y = Math.round(q.y - bh - 10);
      g.strokeStyle = color;
      g.lineWidth = 1.5;
      g.beginPath();
      g.moveTo(q.x, q.y);
      g.lineTo(x, y + bh);
      g.stroke();
      g.fillStyle = ink.tipBg;
      g.beginPath();
      g.roundRect(x + 0.5, y + 0.5, bw, bh, 5);
      g.fill();
      g.stroke();
      g.fillStyle = color;
      g.beginPath();
      g.roundRect(x + 0.5, y + 0.5, bw, 22, [5, 5, 0, 0]);
      g.fill();
      g.fillStyle = ink.tipBg;
      g.font = '600 12px -apple-system, "Segoe UI", Inter, system-ui, sans-serif';
      g.textBaseline = 'middle';
      g.fillText(head, x + 7, y + 12);
      g.fillStyle = ink.tipText;
      g.font = '11px -apple-system, "Segoe UI", Inter, system-ui, sans-serif';
      lines.forEach((l, i) => g.fillText(l, x + 6, y + 22 + 11 + i * 14));
    }
    g.restore();
  }

  dispose(): void {
    this.clear();
    for (const m of Object.values(this.mats)) m.dispose();
    this.nakedMat.dispose();
  }
}
