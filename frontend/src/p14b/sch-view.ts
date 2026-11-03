import { toast } from '../ui/toast';
import { askText } from './prompt';
import { ec, type Json } from './store';
import { ink, round4, segDist, snap, View2d, type Box, type Pointer, type Pt } from './view2d';

export type SchTool = 'select' | 'place' | 'wire' | 'bus' | 'label' | 'glabel' | 'junction' | 'noconn' | 'power' | 'delete' | 'entry';
export interface Sel { kind: 'part' | 'wire' | 'bus' | 'label' | 'junction' | 'noconn' | 'text' | 'sheet' | 'entry'; id: string }

const GRID = 1.27;
const PAPER: Record<string, [number, number]> = { A5: [210, 148], A4: [297, 210], A3: [420, 297], A2: [594, 420], A1: [841, 594], A0: [1189, 841] };

export class SchEditor {
  readonly view: View2d;
  tool: SchTool = 'select';
  symbol = 'R';
  power = '+5V';
  labelText = 'NET1';
  sel: Sel | null = null;
  markers = true;
  onState: () => void = () => undefined;
  private cur: Pt = [0, 0];
  private pts: Pt[] = [];
  private drag: { part: string; start: Pt; delta: Pt; moved: boolean } | null = null;
  private busy = false;
  private boxes = new Map<string, Box>();
  private sceneRef: Json | null = null;

  constructor(readonly host: HTMLElement) {
    this.view = new View2d(host);
    this.view.paint = (v, g) => this.paint(v, g);
    this.view.down = (p) => void this.down(p);
    this.view.move = (p) => this.move(p);
    this.view.up = (p) => this.up(p);
    this.view.dbl = () => void this.finishPoly();
    this.view.key = (e) => this.key(e);
  }

  setTool(t: SchTool): void {
    this.tool = t;
    this.pts = [];
    this.view.request();
    this.onState();
  }

  select(s: Sel | null): void { this.sel = s; this.view.request(); this.onState(); }

  paperBox(): Box {
    const p = PAPER[String(ec.scene?.sheet?.paper ?? 'A4')] ?? PAPER.A4;
    return { x0: 0, y0: 0, x1: p[0], y1: p[1] };
  }

  fit(): void {
    const sc = ec.scene;
    const pts: Pt[] = [];
    if (sc) {
      for (const c of (sc.components ?? []) as Json[]) for (const p of (c.pins ?? []) as Json[]) pts.push(p.pos as Pt);
      for (const w of (sc.wires ?? []) as Json[]) pts.push(...(w.points as Pt[]));
      for (const l of (sc.labels ?? []) as Json[]) pts.push(l.pos as Pt);
      for (const s of (sc.sheet_symbols ?? []) as Json[]) { pts.push(s.pos as Pt, [s.pos[0] + s.size[0], s.pos[1] - s.size[1]]); }
    }
    if (!pts.length) { this.view.fit(this.paperBox()); return; }
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const [x, y] of pts) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
    this.view.fit({ x0: x0 - 8, y0: y0 - 8, x1: x1 + 8, y1: y1 + 8 }, 0.08);
  }

  dataChanged(): void {
    if (this.sceneRef !== ec.scene) { this.sceneRef = ec.scene; this.boxes.clear(); }
    if (this.sel) {
      const sc = ec.scene;
      const live = !sc ? false : this.sel.kind === 'part' ? (sc.components as Json[]).some((c) => c.part === this.sel?.id)
        : this.sel.kind === 'wire' ? (sc.wires as Json[]).some((c) => c.id === this.sel?.id)
        : this.sel.kind === 'label' ? (sc.labels as Json[]).some((c) => c.id === this.sel?.id) : true;
      if (!live) this.sel = null;
    }
    this.view.request();
    this.onState();
  }

  partBox(c: Json): Box {
    const key = String(c.part) + ':' + String(c.placement?.unit ?? 1);
    const hit = this.boxes.get(key);
    if (hit) return hit;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const add = (x: number, y: number): void => { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); };
    for (const gr of (c.graphics ?? []) as Json[]) {
      if (gr.pts) for (const p of gr.pts as Pt[]) add(p[0], p[1]);
      else if (gr.c) { add(gr.c[0] - gr.r, gr.c[1] - gr.r); add(gr.c[0] + gr.r, gr.c[1] + gr.r); }
      else if (gr.x0 !== undefined) { add(gr.x0, gr.y0); add(gr.x1, gr.y1); }
    }
    for (const p of (c.pins ?? []) as Json[]) add(p.pos[0], p.pos[1]);
    if (!Number.isFinite(x0)) { const q = c.placement?.pos ?? [0, 0]; x0 = q[0] - 1; x1 = q[0] + 1; y0 = q[1] - 1; y1 = q[1] + 1; }
    const b = { x0, y0, x1, y1 };
    this.boxes.set(key, b);
    return b;
  }

  private snapPoint(wx: number, wy: number): { p: Pt; pin: { ref: string; num: string } | null } {
    const tol = 9 / this.view.scale;
    let best: { d: number; p: Pt; ref: string; num: string } | null = null;
    for (const c of (ec.scene?.components ?? []) as Json[]) {
      for (const pin of (c.pins ?? []) as Json[]) {
        const d = Math.hypot(pin.pos[0] - wx, pin.pos[1] - wy);
        if (d <= tol && (!best || d < best.d)) best = { d, p: [pin.pos[0], pin.pos[1]], ref: String(c.refdes), num: String(pin.number) };
      }
    }
    if (best) return { p: best.p, pin: { ref: best.ref, num: best.num } };
    return { p: [round4(snap(wx, GRID)), round4(snap(wy, GRID))], pin: null };
  }

  private hit(wx: number, wy: number): Sel | null {
    const sc = ec.scene;
    if (!sc) return null;
    const tol = 6 / this.view.scale;
    for (const l of (sc.labels ?? []) as Json[]) if (Math.hypot(l.pos[0] - wx, l.pos[1] - wy) < tol * 1.6) return { kind: 'label', id: l.id };
    for (const j of (sc.junctions ?? []) as Json[]) if (Math.hypot(j.pos[0] - wx, j.pos[1] - wy) < tol) return { kind: 'junction', id: j.id };
    for (const n of (sc.no_connects ?? []) as Json[]) if (Math.hypot(n.pos[0] - wx, n.pos[1] - wy) < tol) return { kind: 'noconn', id: n.id };
    for (const c of (sc.components ?? []) as Json[]) {
      const b = this.partBox(c);
      if (wx >= b.x0 - tol && wx <= b.x1 + tol && wy >= b.y0 - tol && wy <= b.y1 + tol) return { kind: 'part', id: String(c.part) };
    }
    for (const w of (sc.wires ?? []) as Json[]) {
      const ps = w.points as Pt[];
      for (let i = 0; i + 1 < ps.length; i++) if (segDist(wx, wy, ps[i][0], ps[i][1], ps[i + 1][0], ps[i + 1][1]) < tol) return { kind: 'wire', id: w.id };
    }
    for (const w of (sc.buses ?? []) as Json[]) {
      const ps = w.points as Pt[];
      for (let i = 0; i + 1 < ps.length; i++) if (segDist(wx, wy, ps[i][0], ps[i][1], ps[i + 1][0], ps[i + 1][1]) < tol) return { kind: 'bus', id: w.id };
    }
    for (const s of (sc.sheet_symbols ?? []) as Json[]) {
      if (wx >= s.pos[0] && wx <= s.pos[0] + s.size[0] && wy <= s.pos[1] && wy >= s.pos[1] - s.size[1]) return { kind: 'sheet', id: s.id };
    }
    return null;
  }

  private async down(p: Pointer): Promise<void> {
    if (p.button !== 0 || this.busy) return;
    const s = this.snapPoint(p.wx, p.wy);
    switch (this.tool) {
      case 'select': {
        const h = this.hit(p.wx, p.wy);
        this.select(h);
        if (h?.kind === 'part') this.drag = { part: h.id, start: [p.wx, p.wy], delta: [0, 0], moved: false };
        break;
      }
      case 'place': await this.run([{ op: 'add_part', symbol: this.symbol, pos: s.p }]); break;
      case 'wire': case 'bus': this.polyClick(s); break;
      case 'junction': await this.run([{ op: 'add_junction', pos: s.p }]); break;
      case 'noconn': await this.run([{ op: 'add_no_connect', pos: s.p }]); break;
      case 'entry': await this.run([{ op: 'add_bus_entry', pos: s.p }]); break;
      case 'label': case 'glabel': {
        const text = await askText(this.host, p.x, p.y, this.tool === 'glabel' ? 'Global label' : 'Net label', this.labelText);
        if (!text) break;
        this.labelText = text;
        const op: Json = { op: 'add_label', kind: this.tool === 'glabel' ? 'global' : 'local', text };
        if (s.pin) op.pin = `${s.pin.ref}.${s.pin.num}`; else op.pos = s.p;
        await this.run([op]);
        break;
      }
      case 'power': {
        if (s.pin) await this.run([{ op: 'power_at', pin: `${s.pin.ref}.${s.pin.num}`, net: this.power }]);
        else await this.run([{ op: 'add_part', symbol: `PWR:${this.power}`, pos: s.p }]);
        break;
      }
      case 'delete': {
        const h = this.hit(p.wx, p.wy);
        if (h) await this.remove(h);
        break;
      }
    }
  }

  private polyClick(s: { p: Pt; pin: { ref: string; num: string } | null }): void {
    const last = this.pts[this.pts.length - 1];
    if (last && last[0] === s.p[0] && last[1] === s.p[1]) { void this.finishPoly(); return; }
    if (last && last[0] !== s.p[0] && last[1] !== s.p[1]) this.pts.push([s.p[0], last[1]]);
    this.pts.push(s.p);
    this.view.request();
    if (s.pin && this.pts.length > 1) void this.finishPoly();
  }

  async finishPoly(): Promise<void> {
    const pts = this.pts;
    this.pts = [];
    this.view.request();
    if (pts.length < 2 || (this.tool !== 'wire' && this.tool !== 'bus')) return;
    const ops: Json[] = [{ op: this.tool === 'wire' ? 'add_wire' : 'add_bus', points: pts }];
    if (this.tool === 'wire') {
      for (const end of [pts[0], pts[pts.length - 1]]) {
        if (this.onWireInterior(end)) ops.push({ op: 'add_junction', pos: end });
      }
    }
    await this.run(ops);
  }

  private onWireInterior(p: Pt): boolean {
    for (const w of (ec.scene?.wires ?? []) as Json[]) {
      const ps = w.points as Pt[];
      for (let i = 0; i + 1 < ps.length; i++) {
        if (segDist(p[0], p[1], ps[i][0], ps[i][1], ps[i + 1][0], ps[i + 1][1]) < 0.01) {
          const atEnd = (Math.hypot(p[0] - ps[i][0], p[1] - ps[i][1]) < 0.01 && i === 0) || (Math.hypot(p[0] - ps[i + 1][0], p[1] - ps[i + 1][1]) < 0.01 && i + 2 === ps.length);
          if (!atEnd) return !((ec.scene?.junctions ?? []) as Json[]).some((j) => Math.hypot(j.pos[0] - p[0], j.pos[1] - p[1]) < 0.01);
        }
      }
    }
    return false;
  }

  private move(p: Pointer): void {
    this.cur = this.snapPoint(p.wx, p.wy).p;
    if (this.drag) {
      const d: Pt = [snap(p.wx - this.drag.start[0], GRID), snap(p.wy - this.drag.start[1], GRID)];
      if (d[0] !== this.drag.delta[0] || d[1] !== this.drag.delta[1]) { this.drag.delta = d; this.drag.moved = true; }
    }
    if (this.drag || this.pts.length || this.tool !== 'select') this.view.request();
  }

  private up(_p: Pointer): void {
    const d = this.drag;
    this.drag = null;
    if (d?.moved && (d.delta[0] || d.delta[1])) void this.run([{ op: 'move_part', part: d.part, delta: d.delta }]);
    else this.view.request();
  }

  async remove(s: Sel): Promise<void> {
    if (s.kind === 'part') await this.run([{ op: 'delete_part', part: s.id }]);
    else if (s.kind === 'sheet') await this.run([{ op: 'delete_item', item: s.id }]);
    else await this.run([{ op: 'delete_item', item: s.id }]);
    this.select(null);
  }

  private key(e: KeyboardEvent): void {
    const k = e.key.toLowerCase();
    if (e.ctrlKey || e.metaKey) {
      if (k === 'z') { e.preventDefault(); void (e.shiftKey ? ec.redo() : ec.undo()); }
      else if (k === 'y') { e.preventDefault(); void ec.redo(); }
      return;
    }
    if (k === 'escape') { this.pts = []; this.setTool('select'); }
    else if (k === 'enter') void this.finishPoly();
    else if ((k === 'delete' || k === 'backspace') && this.sel) { e.preventDefault(); void this.remove(this.sel); }
    else if (k === 'r' && this.sel?.kind === 'part') void this.rotate(90);
    else if (k === 'm' && this.sel?.kind === 'part') void this.mirror();
    else if (k === 'w') this.setTool('wire');
    else if (k === 'b') this.setTool('bus');
    else if (k === 'l') this.setTool('label');
    else if (k === 'g') this.setTool('glabel');
    else if (k === 'j') this.setTool('junction');
    else if (k === 'n') this.setTool('noconn');
    else if (k === 'p') this.setTool('place');
    else if (k === 'v') this.setTool('select');
    else if (k === 'x') this.setTool('delete');
  }

  private comp(id: string): Json | undefined { return ((ec.scene?.components ?? []) as Json[]).find((c) => c.part === id); }

  async rotate(deg: number): Promise<void> {
    if (this.sel?.kind !== 'part') return;
    const c = this.comp(this.sel.id);
    if (!c) return;
    await this.run([{ op: 'move_part', part: this.sel.id, rotation: (Number(c.placement?.rotation ?? 0) + deg + 360) % 360 }]);
  }

  async mirror(): Promise<void> {
    if (this.sel?.kind !== 'part') return;
    const c = this.comp(this.sel.id);
    if (!c) return;
    await this.run([{ op: 'move_part', part: this.sel.id, mirror: !c.placement?.mirror }]);
  }

  private async run(ops: Json[]): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    try { await ec.ops(ops); } catch (e) { toast(String(e), 'error'); } finally { this.busy = false; this.view.request(); }
  }

  private paint(v: View2d, g: CanvasRenderingContext2D): void {
    const c = ink();
    const sc = ec.scene;
    g.fillStyle = c.bg;
    g.fillRect(0, 0, v.w, v.h);
    const pb = this.paperBox();
    g.fillStyle = c.paper;
    g.fillRect(v.sx(pb.x0), v.sy(pb.y1), (pb.x1 - pb.x0) * v.scale, (pb.y1 - pb.y0) * v.scale);
    if (v.scale >= 5) {
      g.fillStyle = c.grid;
      const x0 = Math.floor(v.wx(0) / GRID) * GRID, x1 = v.wx(v.w), y1 = v.wy(0), y0 = v.wy(v.h);
      for (let x = x0; x <= x1; x += GRID) for (let y = Math.floor(y0 / GRID) * GRID; y <= y1; y += GRID) g.fillRect(Math.round(v.sx(x)), Math.round(v.sy(y)), 1, 1);
    }
    if (!sc) return;
    const sel = this.sel;
    g.lineCap = 'round'; g.lineJoin = 'round';
    for (const w of (sc.buses ?? []) as Json[]) this.poly(g, v, w.points as Pt[], sel?.id === w.id ? c.accent : c.bus, 3);
    for (const w of (sc.wires ?? []) as Json[]) this.poly(g, v, w.points as Pt[], sel?.id === w.id ? c.accent : c.wire, 1.4);
    for (const e of (sc.bus_entries ?? []) as Json[]) this.poly(g, v, [e.pos, [e.pos[0] + e.dir[0], e.pos[1] + e.dir[1]]], c.bus, 2);
    for (const j of (sc.junctions ?? []) as Json[]) { g.fillStyle = c.wire; g.beginPath(); g.arc(v.sx(j.pos[0]), v.sy(j.pos[1]), Math.max(2.5, 0.45 * v.scale), 0, 7); g.fill(); }
    for (const n of (sc.no_connects ?? []) as Json[]) {
      const x = v.sx(n.pos[0]), y = v.sy(n.pos[1]), r = Math.max(3, 0.6 * v.scale);
      g.strokeStyle = c.danger; g.lineWidth = 1.4; g.beginPath(); g.moveTo(x - r, y - r); g.lineTo(x + r, y + r); g.moveTo(x - r, y + r); g.lineTo(x + r, y - r); g.stroke();
    }
    for (const s of (sc.sheet_symbols ?? []) as Json[]) {
      const x = v.sx(s.pos[0]), y = v.sy(s.pos[1]), w = s.size[0] * v.scale, h = s.size[1] * v.scale;
      g.strokeStyle = sel?.id === s.id ? c.accent : c.sym; g.lineWidth = 1.6; g.strokeRect(x, y, w, h);
      g.fillStyle = c.text; g.font = `${Math.max(9, 1.4 * v.scale)}px sans-serif`; g.textBaseline = 'bottom'; g.fillText(String(s.name), x + 3, y - 2);
      for (const p of (s.pins ?? []) as Json[]) {
        const pp = (p.pos ?? p.at) as Pt | undefined;
        if (!pp) continue;
        g.fillStyle = c.pin; g.font = `${Math.max(8, 1.1 * v.scale)}px sans-serif`; g.textBaseline = 'middle';
        g.fillText(String(p.name ?? ''), v.sx(pp[0]) + 4, v.sy(pp[1]));
      }
    }
    for (const comp of (sc.components ?? []) as Json[]) this.component(g, v, comp, c, sel?.kind === 'part' && sel.id === comp.part);
    for (const l of (sc.labels ?? []) as Json[]) this.labelShape(g, v, l, c, sel?.id === l.id);
    for (const t of (sc.texts ?? []) as Json[]) { g.fillStyle = c.text; g.font = `${Math.max(8, t.h * v.scale)}px sans-serif`; g.textBaseline = 'alphabetic'; g.fillText(String(t.text), v.sx(t.pos[0]), v.sy(t.pos[1])); }
    if (this.markers) {
      for (const m of (ec.erc?.violations ?? []) as Json[]) {
        if (m.sheet && m.sheet !== ec.sheetId) continue;
        const p = m.pos as Pt | undefined;
        if (!p) continue;
        const col = m.severity === 'error' ? c.danger : c.warn;
        const x = v.sx(p[0]), y = v.sy(p[1]);
        g.strokeStyle = col; g.lineWidth = 2; g.beginPath(); g.arc(x, y, Math.max(7, 1.6 * v.scale), 0, 7); g.stroke();
        g.fillStyle = col; g.globalAlpha = 0.18; g.fill(); g.globalAlpha = 1;
      }
    }
    if (this.pts.length) {
      const pts: Pt[] = [...this.pts];
      const last = pts[pts.length - 1];
      if (last[0] !== this.cur[0] && last[1] !== this.cur[1]) pts.push([this.cur[0], last[1]]);
      pts.push(this.cur);
      this.poly(g, v, pts, c.accent, this.tool === 'bus' ? 3 : 1.4);
    }
    if (this.tool !== 'select') {
      g.strokeStyle = c.accent; g.lineWidth = 1;
      const x = v.sx(this.cur[0]), y = v.sy(this.cur[1]);
      g.beginPath(); g.moveTo(x - 7, y); g.lineTo(x + 7, y); g.moveTo(x, y - 7); g.lineTo(x, y + 7); g.stroke();
    }
  }

  private poly(g: CanvasRenderingContext2D, v: View2d, pts: Pt[], color: string, width: number): void {
    g.strokeStyle = color; g.lineWidth = width; g.beginPath();
    pts.forEach((p, i) => { if (i === 0) g.moveTo(v.sx(p[0]), v.sy(p[1])); else g.lineTo(v.sx(p[0]), v.sy(p[1])); });
    g.stroke();
  }

  private component(g: CanvasRenderingContext2D, v: View2d, comp: Json, c: ReturnType<typeof ink>, selected: boolean): void {
    const d = this.drag && this.drag.part === comp.part ? this.drag.delta : [0, 0];
    const X = (x: number): number => v.sx(x + d[0]);
    const Y = (y: number): number => v.sy(y + d[1]);
    const col = selected ? c.accent : c.sym;
    g.strokeStyle = col; g.lineWidth = selected ? 2 : 1.5;
    for (const gr of (comp.graphics ?? []) as Json[]) {
      if (gr.t === 'line' || gr.t === 'poly') {
        g.beginPath();
        (gr.pts as Pt[]).forEach((p, i) => { if (i === 0) g.moveTo(X(p[0]), Y(p[1])); else g.lineTo(X(p[0]), Y(p[1])); });
        g.stroke();
      } else if (gr.t === 'circle') {
        g.beginPath(); g.arc(X(gr.c[0]), Y(gr.c[1]), gr.r * v.scale, 0, 7); g.stroke();
      } else if (gr.t === 'rect') {
        g.strokeRect(X(Math.min(gr.x0, gr.x1)), Y(Math.max(gr.y0, gr.y1)), Math.abs(gr.x1 - gr.x0) * v.scale, Math.abs(gr.y1 - gr.y0) * v.scale);
      } else if (gr.t === 'text') {
        const s = String(gr.text).replace('%V', String(comp.value)).replace('%R', String(comp.refdes));
        g.fillStyle = c.text; g.font = `${Math.max(7, gr.h * v.scale)}px sans-serif`; g.textBaseline = 'middle'; g.textAlign = 'center'; g.fillText(s, X(gr.pos[0]), Y(gr.pos[1])); g.textAlign = 'left';
      }
    }
    for (const p of (comp.pins ?? []) as Json[]) {
      const len = Number(p.length ?? 0);
      const dir: Record<string, Pt> = { U: [0, -1], D: [0, 1], L: [-1, 0], R: [1, 0] };
      const o = dir[String(p.orient)] ?? [0, 0];
      const x = X(p.pos[0]), y = Y(p.pos[1]);
      if (len > 0) { g.strokeStyle = col; g.lineWidth = 1.2; g.beginPath(); g.moveTo(x, y); g.lineTo(x - o[0] * len * v.scale, y - o[1] * len * v.scale); g.stroke(); }
      g.fillStyle = c.pin; g.beginPath(); g.arc(x, y, 1.8, 0, 7); g.fill();
      if (v.scale >= 7 && !p.hidden && len > 0) {
        g.font = `${Math.max(7, 0.9 * v.scale)}px sans-serif`; g.fillStyle = c.pin; g.textBaseline = 'bottom'; g.textAlign = 'center';
        g.fillText(String(p.number), x - o[0] * len * v.scale * 0.5 + (o[0] === 0 ? 7 : 0), y - o[1] * len * v.scale * 0.5 - (o[0] === 0 ? 0 : 1));
        g.textAlign = 'left';
      }
    }
    if (!comp.power) {
      const b = this.partBox(comp);
      g.fillStyle = c.label; g.font = `${Math.max(8, 1.3 * v.scale)}px sans-serif`; g.textBaseline = 'alphabetic';
      g.fillText(String(comp.refdes), X(b.x0), Y(b.y1) - 3);
      g.fillStyle = c.muted; g.textBaseline = 'top';
      g.fillText(String(comp.value), X(b.x0), Y(b.y0) + 3);
    }
  }

  private labelShape(g: CanvasRenderingContext2D, v: View2d, l: Json, c: ReturnType<typeof ink>, selected: boolean): void {
    const x = v.sx(l.pos[0]), y = v.sy(l.pos[1]);
    const col = selected ? c.accent : l.kind === 'global' ? c.ok : c.label;
    g.font = `${Math.max(8, 1.3 * v.scale)}px sans-serif`;
    const w = g.measureText(String(l.text)).width;
    g.fillStyle = col; g.textBaseline = 'bottom'; g.fillText(String(l.text), x + 2, y - 1);
    g.strokeStyle = col; g.lineWidth = 1;
    g.beginPath(); g.moveTo(x, y); g.lineTo(x + w + 4, y); g.stroke();
    if (l.kind === 'global') { g.strokeRect(x - 1, y - 1.3 * v.scale - 2, w + 6, 1.3 * v.scale + 3); }
  }
}
