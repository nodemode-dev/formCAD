import * as THREE from 'three';
import type { Palette } from '../view3d/kit';
import type { ViewLayer, Projector } from '../view3d/layer';
import type { InkColors } from '../view3d/overlay';
import type { Vec3 } from '../view3d/types';
import type { Viewport3D } from '../view3d/viewport';

export interface PmiFrame { char: string; tol: number; zone: string; modifier: string; datums: string[] }
export interface PmiDraw {
  id: string; type: string; state: string; label: string; anchor: Vec3; text_at: Vec3;
  lines: number[][][]; arrows: number[][]; frame: PmiFrame | null; letter: string | null;
}

const CHAR_WORD: Record<string, string> = {
  straightness: 'Straightness', flatness: 'Flatness', circularity: 'Circularity', cylindricity: 'Cylindricity', profile_line: 'Profile of a line',
  profile_surface: 'Profile of a surface', parallelism: 'Parallelism', perpendicularity: 'Perpendicularity', angularity: 'Angularity', position: 'Position',
  concentricity: 'Concentricity', symmetry: 'Symmetry', runout: 'Runout', total_runout: 'Total runout',
};

export const charWord = (c: string): string => CHAR_WORD[c] ?? c;

const cssColor = (host: HTMLElement, name: string, fallback: string): THREE.Color => {
  const raw = getComputedStyle(host).getPropertyValue(name).trim();
  const c = new THREE.Color();
  try { c.set(raw || fallback); } catch { c.set(fallback); }
  return c;
};

const GROUPS = ['ok', 'lost', 'unsupported'] as const;
type Group = (typeof GROUPS)[number];

export function frameText(f: PmiFrame): string[] {
  const zone = f.zone === 'diameter' ? '⌀' : f.zone === 'sphere' ? 'S⌀' : '';
  const cells = [charWord(f.char), `${zone}${f.tol}${f.modifier ? ` ${f.modifier}` : ''}`, ...f.datums];
  return cells;
}

export class PmiLayer implements ViewLayer {
  readonly group = new THREE.Group();
  private readonly mats = new Map<Group, THREE.LineBasicMaterial>();
  private readonly objs = new Map<Group, THREE.LineSegments>();
  private items: PmiDraw[] = [];
  private sig = '';
  private picked = '';
  private ink = { ok: '#f97316', lost: '#ef4444', unsupported: '#f59e0b' };

  constructor(private readonly vp: Viewport3D) {
    for (const g of GROUPS) {
      const mat = new THREE.LineBasicMaterial({ color: 0xffffff, depthTest: false, transparent: true });
      const obj = new THREE.LineSegments(new THREE.BufferGeometry(), mat);
      obj.renderOrder = 9;
      obj.frustumCulled = false;
      this.mats.set(g, mat);
      this.objs.set(g, obj);
      this.group.add(obj);
    }
    this.group.visible = false;
    this.palette({} as Palette);
  }

  get shown(): boolean { return this.group.visible; }

  palette(_pal: Palette): void {
    const host = this.vp.host;
    const ok = cssColor(host, '--accent-color', '#f97316');
    const lost = cssColor(host, '--danger', '#ef4444');
    const unsupported = cssColor(host, '--warn', '#f59e0b');
    this.mats.get('ok')?.color.copy(ok);
    this.mats.get('lost')?.color.copy(lost);
    this.mats.get('unsupported')?.color.copy(unsupported);
    this.ink = { ok: `#${ok.getHexString()}`, lost: `#${lost.getHexString()}`, unsupported: `#${unsupported.getHexString()}` };
    this.vp.invalidate();
  }

  bounds(): { min: Vec3; max: Vec3 } | null {
    return null;
  }

  highlight(id: string): void {
    if (this.picked === id) return;
    this.picked = id;
    this.vp.invalidate();
  }

  set(items: PmiDraw[], show: boolean): void {
    const next = show ? JSON.stringify(items.map((i) => [i.id, i.state, i.label, i.lines, i.arrows, i.text_at])) : '';
    if (next !== this.sig) {
      this.sig = next;
      this.items = show ? items : [];
      this.build();
    }
    if (this.group.visible !== (show && this.items.length > 0)) this.group.visible = show && this.items.length > 0;
    this.vp.invalidate();
  }

  private size(): number {
    let lo = Infinity, hi = -Infinity;
    for (const i of this.items) for (const pl of i.lines) for (const p of pl) { lo = Math.min(lo, p[0], p[1], p[2]); hi = Math.max(hi, p[0], p[1], p[2]); }
    const span = hi > lo ? hi - lo : 10;
    return Math.max(span * 0.015, 0.2);
  }

  private build(): void {
    const arrow = this.size();
    const buf: Record<Group, number[]> = { ok: [], lost: [], unsupported: [] };
    for (const it of this.items) {
      const out = buf[(GROUPS as readonly string[]).includes(it.state) ? (it.state as Group) : 'ok'];
      for (const pl of it.lines) for (let i = 0; i + 1 < pl.length; i++) out.push(...pl[i].slice(0, 3), ...pl[i + 1].slice(0, 3));
      for (const a of it.arrows) {
        const tip = new THREE.Vector3(a[0], a[1], a[2]);
        const dir = new THREE.Vector3(a[3], a[4], a[5]).normalize();
        const side = Math.abs(dir.z) < 0.9 ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(1, 0, 0);
        const perp = new THREE.Vector3().crossVectors(dir, side).normalize().multiplyScalar(arrow * 0.3);
        const back = tip.clone().addScaledVector(dir, -arrow);
        const l = back.clone().add(perp), r = back.clone().sub(perp);
        out.push(tip.x, tip.y, tip.z, l.x, l.y, l.z, tip.x, tip.y, tip.z, r.x, r.y, r.z, l.x, l.y, l.z, r.x, r.y, r.z);
      }
    }
    for (const g of GROUPS) {
      const obj = this.objs.get(g);
      if (!obj) continue;
      obj.geometry.dispose();
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(buf[g], 3));
      obj.geometry = geo;
    }
  }

  draw(g: CanvasRenderingContext2D, project: Projector, ink: InkColors): void {
    if (!this.group.visible) return;
    g.save();
    g.font = '11px -apple-system, "Segoe UI", Inter, system-ui, sans-serif';
    g.textBaseline = 'middle';
    for (const it of this.items) {
      const p = project(it.text_at);
      if (!p) continue;
      const colour = this.ink[(GROUPS as readonly string[]).includes(it.state) ? (it.state as Group) : 'ok'];
      const sel = it.id === this.picked;
      if (it.frame) this.drawFrame(g, p.x, p.y, it.frame, ink, colour, sel);
      else if (it.letter) this.drawDatum(g, p.x, p.y, it.letter, ink, colour, sel);
      else this.drawLabel(g, p.x, p.y, it.label, ink, colour, sel);
    }
    g.restore();
  }

  private box(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, ink: InkColors, colour: string, sel: boolean): void {
    g.fillStyle = ink.tipBg;
    g.strokeStyle = colour;
    g.lineWidth = sel ? 2 : 1;
    g.beginPath();
    g.roundRect(x + 0.5, y + 0.5, w, h, 3);
    g.fill();
    g.stroke();
  }

  private drawLabel(g: CanvasRenderingContext2D, x: number, y: number, text: string, ink: InkColors, colour: string, sel: boolean): void {
    const w = Math.ceil(g.measureText(text).width) + 10;
    this.box(g, x - w / 2, y - 10, w, 20, ink, colour, sel);
    g.fillStyle = ink.tipText;
    g.textAlign = 'center';
    g.fillText(text, x, y + 0.5);
  }

  private drawFrame(g: CanvasRenderingContext2D, x: number, y: number, f: PmiFrame, ink: InkColors, colour: string, sel: boolean): void {
    const cells = frameText(f);
    const ws = cells.map((c) => Math.ceil(g.measureText(c).width) + 12);
    const total = ws.reduce((a, b) => a + b, 0);
    let cx = x - total / 2;
    this.box(g, cx, y - 10, total, 20, ink, colour, sel);
    g.fillStyle = ink.tipText;
    g.textAlign = 'center';
    cells.forEach((c, i) => {
      g.fillText(c, cx + ws[i] / 2, y + 0.5);
      cx += ws[i];
      if (i < cells.length - 1) { g.strokeStyle = colour; g.lineWidth = 1; g.beginPath(); g.moveTo(cx + 0.5, y - 10); g.lineTo(cx + 0.5, y + 10); g.stroke(); }
    });
  }

  private drawDatum(g: CanvasRenderingContext2D, x: number, y: number, letter: string, ink: InkColors, colour: string, sel: boolean): void {
    this.box(g, x - 11, y - 11, 22, 22, ink, colour, sel);
    g.fillStyle = ink.tipText;
    g.textAlign = 'center';
    g.font = '600 12px -apple-system, "Segoe UI", Inter, system-ui, sans-serif';
    g.fillText(letter, x, y + 0.5);
  }

  dispose(): void {
    for (const o of this.objs.values()) o.geometry.dispose();
    for (const m of this.mats.values()) m.dispose();
  }
}
