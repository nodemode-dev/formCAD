import { ec, type Json } from './store';
import { boxOf, ink, inPoly, round4, segDist, snap, View2d, type Box, type Pointer, type Pt } from './view2d';

export type PcbTool = 'select' | 'track' | 'via' | 'zone' | 'keepout' | 'delete';
export interface PSel { kind: 'part' | 'track' | 'via' | 'zone' | 'keepout' | 'hole' | 'drc'; id: string }
export interface Vis { fcu: boolean; bcu: boolean; silk: boolean; zones: boolean; rat: boolean; drc: boolean; court: boolean; keep: boolean }

const rad = (d: number): number => (d * Math.PI) / 180;

export function partPoint(part: Json, x: number, y: number): Pt {
  const mx = part.side === 'bottom' ? -x : x;
  const a = rad(Number(part.rot ?? 0));
  const c = Math.cos(a), s = Math.sin(a);
  return [part.x + mx * c - y * s, part.y + mx * s + y * c];
}

export class PcbEditor {
  readonly view: View2d;
  tool: PcbTool = 'select';
  active = 'F.Cu';
  net = '';
  width = 0;
  viaDia = 0;
  grid = 0.25;
  sel: PSel | null = null;
  vis: Vis = { fcu: true, bcu: true, silk: true, zones: true, rat: true, drc: true, court: false, keep: true };
  onState: () => void = () => undefined;
  private cur: Pt = [0, 0];
  private pts: Pt[] = [];
  private startNet = '';
  private busy = false;
  private drag: { ref: string; start: Pt; delta: Pt; moved: boolean } | null = null;

  constructor(readonly host: HTMLElement) {
    this.view = new View2d(host);
    this.view.paint = (v, g) => this.paint(v, g);
    this.view.down = (p) => void this.down(p);
    this.view.move = (p) => this.move(p);
    this.view.up = () => this.up();
    this.view.dbl = () => void this.finish();
    this.view.key = (e) => this.key(e);
  }

  setTool(t: PcbTool): void { this.tool = t; this.pts = []; this.view.request(); this.onState(); }
  select(s: PSel | null): void { this.sel = s; this.view.request(); this.onState(); }
  setActive(l: string): void { this.active = l; this.view.request(); this.onState(); }

  outline(): Pt[] { return (ec.pcb?.board?.outline ?? []) as Pt[]; }

  fit(): void {
    const o = this.outline();
    if (o.length) this.view.fit(boxOf(o), 0.1);
  }

  dataChanged(): void {
    const s = this.sel;
    if (s && s.kind !== 'drc') {
      const p = ec.pcb;
      const list = !p ? [] : (s.kind === 'part' ? p.parts : s.kind === 'track' ? p.tracks : s.kind === 'via' ? p.vias : s.kind === 'zone' ? p.zones : s.kind === 'keepout' ? p.keepouts : p.holes) as Json[];
      if (!list.some((r) => (s.kind === 'part' ? r.refdes : r.id) === s.id)) this.sel = null;
    }
    if (!this.net) this.net = '';
    this.view.request();
    this.onState();
  }

  defaultWidth(net: string): number {
    if (this.width > 0) return this.width;
    const rules = ec.pcb?.rules;
    const cls = rules?.classes?.[net];
    return Number(cls?.width ?? rules?.values?.track_width ?? 0.2);
  }

  private padsOf(part: Json): Array<{ pad: Json; x: number; y: number; rot: number; layers: string[] }> {
    const bottom = part.side === 'bottom';
    return (part.pads as Json[]).map((pad) => {
      const [x, y] = partPoint(part, pad.x, pad.y);
      const layers = (pad.layers as string[]).map((l) => (bottom ? (l === 'F.Cu' ? 'B.Cu' : l === 'B.Cu' ? 'F.Cu' : l) : l));
      return { pad, x, y, rot: Number(part.rot ?? 0) + (bottom ? -Number(pad.rot ?? 0) : Number(pad.rot ?? 0)), layers };
    });
  }

  private snapNet(wx: number, wy: number): { p: Pt; net: string } | null {
    const p = ec.pcb;
    if (!p) return null;
    const tol = Math.max(0.5, 8 / this.view.scale);
    let best: { d: number; p: Pt; net: string } | null = null;
    const consider = (d: number, q: Pt, net: string): void => { if (d <= tol && (!best || d < best.d)) best = { d, p: q, net }; };
    for (const part of p.parts as Json[]) for (const pd of this.padsOf(part)) if (pd.layers.includes(this.active) || pd.pad.drill > 0) consider(Math.hypot(pd.x - wx, pd.y - wy), [pd.x, pd.y], String(pd.pad.net ?? ''));
    for (const v of p.vias as Json[]) consider(Math.hypot(v.x - wx, v.y - wy), [v.x, v.y], String(v.net ?? ''));
    for (const t of p.tracks as Json[]) {
      if (t.layer !== this.active) continue;
      consider(Math.hypot(t.a[0] - wx, t.a[1] - wy), [t.a[0], t.a[1]], String(t.net));
      consider(Math.hypot(t.b[0] - wx, t.b[1] - wy), [t.b[0], t.b[1]], String(t.net));
    }
    return best ? { p: (best as { p: Pt }).p, net: (best as { net: string }).net } : null;
  }

  private gridPt(wx: number, wy: number): Pt { return [round4(snap(wx, this.grid)), round4(snap(wy, this.grid))]; }

  private octi(from: Pt, to: Pt): Pt {
    const dx = to[0] - from[0], dy = to[1] - from[1];
    const ang = Math.round(Math.atan2(dy, dx) / (Math.PI / 4)) * (Math.PI / 4);
    const len = Math.hypot(dx, dy);
    const c = Math.cos(ang), s = Math.sin(ang);
    const proj = dx * c + dy * s;
    void len;
    return [round4(from[0] + proj * c), round4(from[1] + proj * s)];
  }

  hit(wx: number, wy: number): PSel | null {
    const p = ec.pcb;
    if (!p) return null;
    const tol = 5 / this.view.scale;
    for (const part of p.parts as Json[]) {
      for (const pd of this.padsOf(part)) {
        if (Math.hypot(pd.x - wx, pd.y - wy) <= Math.max(pd.pad.w, pd.pad.h) / 2) return { kind: 'part', id: part.refdes };
      }
    }
    for (const v of p.vias as Json[]) if (Math.hypot(v.x - wx, v.y - wy) <= v.dia / 2 + tol * 0.5) return { kind: 'via', id: v.id };
    for (const t of p.tracks as Json[]) {
      if ((t.layer === 'F.Cu' && !this.vis.fcu) || (t.layer === 'B.Cu' && !this.vis.bcu)) continue;
      if (segDist(wx, wy, t.a[0], t.a[1], t.b[0], t.b[1]) <= t.width / 2 + tol * 0.5) return { kind: 'track', id: t.id };
    }
    for (const part of p.parts as Json[]) {
      const cy = (part.courtyard as Pt[] | undefined) ?? [];
      if (cy.length > 2 && inPoly(wx, wy, cy.map((q) => partPoint(part, q[0], q[1])))) return { kind: 'part', id: part.refdes };
    }
    for (const h of p.holes as Json[]) if (Math.hypot(h.x - wx, h.y - wy) <= h.drill / 2) return { kind: 'hole', id: h.id };
    for (const k of p.keepouts as Json[]) if (inPoly(wx, wy, k.polygon)) return { kind: 'keepout', id: k.id };
    for (const z of p.zones as Json[]) if (z.layer === this.active && inPoly(wx, wy, z.polygon)) return { kind: 'zone', id: z.id };
    return null;
  }

  private async down(p: Pointer): Promise<void> {
    if (p.button !== 0 || this.busy || !ec.pcb) return;
    if (this.tool === 'select') {
      const h = this.hit(p.wx, p.wy);
      this.select(h);
      if (h?.kind === 'part') {
        const part = (ec.pcb.parts as Json[]).find((q) => q.refdes === h.id);
        if (part && !part.locked) this.drag = { ref: h.id, start: [p.wx, p.wy], delta: [0, 0], moved: false };
      }
      return;
    }
    if (this.tool === 'delete') {
      const h = this.hit(p.wx, p.wy);
      if (h) await this.remove(h);
      return;
    }
    if (this.tool === 'track') {
      const sn = this.snapNet(p.wx, p.wy);
      let pt: Pt = sn ? sn.p : this.gridPt(p.wx, p.wy);
      const last = this.pts[this.pts.length - 1];
      if (last && !sn) pt = this.octi(last, pt);
      if (last && last[0] === pt[0] && last[1] === pt[1]) { await this.finish(); return; }
      if (!this.pts.length) this.startNet = sn?.net || this.net;
      this.pts.push(pt);
      this.view.request();
      if (sn && this.pts.length > 1) await this.finish();
      return;
    }
    if (this.tool === 'via') {
      const sn = this.snapNet(p.wx, p.wy);
      const pt = sn ? sn.p : this.gridPt(p.wx, p.wy);
      const body: Json = { net: sn?.net || this.net, x: pt[0], y: pt[1] };
      if (this.viaDia > 0) body.dia = this.viaDia;
      await this.call('POST', 'pcb/vias', body);
      return;
    }
    if (this.tool === 'zone' || this.tool === 'keepout') {
      this.pts.push(this.gridPt(p.wx, p.wy));
      this.view.request();
    }
  }

  async finish(): Promise<void> {
    const pts = this.pts;
    this.pts = [];
    this.view.request();
    if (this.tool === 'track' && pts.length >= 2) {
      const net = this.startNet || this.net;
      await this.call('POST', 'pcb/tracks', { net, layer: this.active, width: this.defaultWidth(net), points: pts });
    } else if (this.tool === 'zone' && pts.length >= 3) {
      await this.call('POST', 'pcb/zones', { net: this.net, layer: this.active, polygon: pts });
    } else if (this.tool === 'keepout' && pts.length >= 3) {
      await this.call('POST', 'pcb/keepouts', { polygon: pts, layers: [this.active], tracks: true, vias: true, pours: true, footprints: false });
    }
  }

  private move(p: Pointer): void {
    const sn = this.tool === 'select' || this.tool === 'delete' ? null : this.snapNet(p.wx, p.wy);
    let c: Pt = sn ? sn.p : this.gridPt(p.wx, p.wy);
    const last = this.pts[this.pts.length - 1];
    if (this.tool === 'track' && last && !sn) c = this.octi(last, c);
    this.cur = c;
    if (this.drag) {
      const d: Pt = [round4(snap(p.wx - this.drag.start[0], 0.05)), round4(snap(p.wy - this.drag.start[1], 0.05))];
      this.drag.delta = d;
      this.drag.moved = true;
    }
    if (this.drag || this.pts.length || this.tool !== 'select') this.view.request();
  }

  private up(): void {
    const d = this.drag;
    this.drag = null;
    if (d?.moved && (d.delta[0] || d.delta[1])) {
      const part = (ec.pcb?.parts as Json[]).find((q) => q.refdes === d.ref);
      if (part) void this.call('PATCH', `pcb/parts/${encodeURIComponent(d.ref)}`, { x: round4(part.x + d.delta[0]), y: round4(part.y + d.delta[1]) });
    } else this.view.request();
  }

  async call(method: string, tail: string, body?: unknown): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    try { await ec.call(method, tail, body); } finally { this.busy = false; this.view.request(); }
  }

  async remove(s: PSel): Promise<void> {
    const map: Record<string, string> = { part: 'parts', track: 'tracks', via: 'vias', zone: 'zones', keepout: 'keepouts', hole: 'holes' };
    if (s.kind === 'drc') return;
    await this.call('DELETE', `pcb/${map[s.kind]}/${encodeURIComponent(s.id)}`);
    this.select(null);
  }

  async editPart(patch: Json): Promise<void> {
    if (this.sel?.kind !== 'part') return;
    await this.call('PATCH', `pcb/parts/${encodeURIComponent(this.sel.id)}`, patch);
  }

  private key(e: KeyboardEvent): void {
    const k = e.key.toLowerCase();
    if (e.ctrlKey || e.metaKey) {
      if (k === 'z') { e.preventDefault(); void (e.shiftKey ? ec.redo() : ec.undo()); }
      else if (k === 'y') { e.preventDefault(); void ec.redo(); }
      return;
    }
    const part = this.sel?.kind === 'part' ? (ec.pcb?.parts as Json[]).find((q) => q.refdes === this.sel?.id) : null;
    if (k === 'escape') { this.pts = []; this.setTool('select'); }
    else if (k === 'enter') void this.finish();
    else if ((k === 'delete' || k === 'backspace') && this.sel) { e.preventDefault(); void this.remove(this.sel); }
    else if (k === 'r' && part) void this.editPart({ rot: (Number(part.rot) + 90) % 360 });
    else if (k === 'f' && part) void this.editPart({ side: part.side === 'bottom' ? 'top' : 'bottom' });
    else if (k === 'v' && this.tool === 'track') { /* handled by panel */ }
    else if (k === 'x') this.setTool('track');
    else if (k === 'u') this.setTool('via');
    else if (k === 'z') this.setTool('zone');
    else if (k === 's') this.setTool('select');
    else if (k === 'd') this.setTool('delete');
    else if (k === 'k') this.setTool('keepout');
    else if (k === '1') this.setActive('F.Cu');
    else if (k === '2') this.setActive('B.Cu');
  }

  private layerColor(l: string, c: ReturnType<typeof ink>): string { return l === 'B.Cu' ? c.bcu : c.fcu; }

  private paint(v: View2d, g: CanvasRenderingContext2D): void {
    const c = ink();
    g.fillStyle = c.bg;
    g.fillRect(0, 0, v.w, v.h);
    const p = ec.pcb;
    if (!p) return;
    if (v.scale >= 14) {
      g.fillStyle = c.grid;
      const gs = this.grid;
      for (let x = Math.floor(v.wx(0) / gs) * gs; x <= v.wx(v.w); x += gs) for (let y = Math.floor(v.wy(v.h) / gs) * gs; y <= v.wy(0); y += gs) g.fillRect(Math.round(v.sx(x)), Math.round(v.sy(y)), 1, 1);
    }
    const out = this.outline();
    if (out.length) {
      g.beginPath();
      out.forEach((q, i) => { if (i === 0) g.moveTo(v.sx(q[0]), v.sy(q[1])); else g.lineTo(v.sx(q[0]), v.sy(q[1])); });
      g.closePath();
      g.fillStyle = c.paper; g.fill();
      g.strokeStyle = c.edge; g.lineWidth = 1.5; g.stroke();
    }
    for (const cut of (p.board?.cutouts ?? []) as Pt[][]) { g.beginPath(); cut.forEach((q, i) => { if (i === 0) g.moveTo(v.sx(q[0]), v.sy(q[1])); else g.lineTo(v.sx(q[0]), v.sy(q[1])); }); g.closePath(); g.fillStyle = c.bg; g.fill(); g.strokeStyle = c.edge; g.stroke(); }
    const order = this.active === 'B.Cu' ? ['F.Cu', 'B.Cu'] : ['B.Cu', 'F.Cu'];
    for (const layer of order) {
      const on = layer === 'F.Cu' ? this.vis.fcu : this.vis.bcu;
      if (!on) continue;
      const col = this.layerColor(layer, c);
      if (this.vis.zones) this.zones(g, v, layer, col);
      this.tracks(g, v, layer, col, c);
      this.pads(g, v, layer, col, c);
    }
    this.vias(g, v, c);
    for (const h of (p.holes ?? []) as Json[]) { g.fillStyle = c.bg; g.strokeStyle = c.hole; g.lineWidth = 1.5; g.beginPath(); g.arc(v.sx(h.x), v.sy(h.y), (h.drill / 2) * v.scale, 0, 7); g.fill(); g.stroke(); }
    if (this.vis.keep) for (const k of (p.keepouts ?? []) as Json[]) { this.polyPath(g, v, k.polygon); g.fillStyle = c.keepout; g.globalAlpha = 0.25; g.fill(); g.globalAlpha = 1; g.strokeStyle = c.keepout; g.setLineDash([5, 4]); g.lineWidth = this.sel?.id === k.id ? 2.5 : 1.2; g.stroke(); g.setLineDash([]); }
    if (this.vis.silk) this.silk(g, v, c);
    if (this.vis.rat) {
      g.strokeStyle = c.rat; g.lineWidth = 1; g.setLineDash([3, 3]);
      g.beginPath();
      for (const r of ec.rat) { g.moveTo(v.sx(r.a[0]), v.sy(r.a[1])); g.lineTo(v.sx(r.b[0]), v.sy(r.b[1])); }
      g.stroke(); g.setLineDash([]);
    }
    this.selection(g, v, c);
    if (this.vis.drc && ec.drc) {
      for (const m of (ec.drc.violations ?? []) as Json[]) {
        const at = m.at as Pt | undefined;
        if (!at) continue;
        const col = m.severity === 'error' ? c.danger : c.warn;
        g.strokeStyle = col; g.lineWidth = 2; g.beginPath(); g.arc(v.sx(at[0]), v.sy(at[1]), Math.max(8, 0.9 * v.scale), 0, 7); g.stroke();
        g.fillStyle = col; g.globalAlpha = 0.2; g.fill(); g.globalAlpha = 1;
      }
    }
    if (this.pts.length) {
      const pts = [...this.pts, this.cur];
      g.strokeStyle = this.tool === 'track' ? this.layerColor(this.active, c) : c.accent;
      g.lineWidth = this.tool === 'track' ? Math.max(2, this.defaultWidth(this.startNet || this.net) * v.scale) : 1.5;
      g.globalAlpha = 0.8; g.beginPath();
      pts.forEach((q, i) => { if (i === 0) g.moveTo(v.sx(q[0]), v.sy(q[1])); else g.lineTo(v.sx(q[0]), v.sy(q[1])); });
      if (this.tool !== 'track') g.closePath();
      g.stroke(); g.globalAlpha = 1;
    }
    if (this.tool !== 'select' && this.tool !== 'delete') {
      g.strokeStyle = c.accent; g.lineWidth = 1;
      const x = v.sx(this.cur[0]), y = v.sy(this.cur[1]);
      g.beginPath(); g.moveTo(x - 8, y); g.lineTo(x + 8, y); g.moveTo(x, y - 8); g.lineTo(x, y + 8); g.stroke();
    }
  }

  private polyPath(g: CanvasRenderingContext2D, v: View2d, pts: Pt[]): void {
    g.beginPath();
    pts.forEach((q, i) => { if (i === 0) g.moveTo(v.sx(q[0]), v.sy(q[1])); else g.lineTo(v.sx(q[0]), v.sy(q[1])); });
    g.closePath();
  }

  private zones(g: CanvasRenderingContext2D, v: View2d, layer: string, col: string): void {
    g.fillStyle = col; g.globalAlpha = 0.34;
    for (const f of ec.fills) {
      if (f.layer !== layer) continue;
      for (const poly of f.polygons as Json[]) {
        g.beginPath();
        const ring = (pts: Pt[]): void => { pts.forEach((q, i) => { if (i === 0) g.moveTo(v.sx(q[0]), v.sy(q[1])); else g.lineTo(v.sx(q[0]), v.sy(q[1])); }); g.closePath(); };
        ring(poly.outline as Pt[]);
        for (const h of (poly.holes ?? []) as Pt[][]) ring(h);
        g.fill('evenodd');
      }
    }
    g.globalAlpha = 1;
    for (const z of (ec.pcb?.zones ?? []) as Json[]) {
      if (z.layer !== layer) continue;
      this.polyPath(g, v, z.polygon);
      g.strokeStyle = col; g.lineWidth = this.sel?.id === z.id ? 2.5 : 1; g.setLineDash([2, 4]); g.stroke(); g.setLineDash([]);
    }
  }

  private tracks(g: CanvasRenderingContext2D, v: View2d, layer: string, col: string, c: ReturnType<typeof ink>): void {
    g.strokeStyle = col; g.lineCap = 'round';
    for (const t of (ec.pcb?.tracks ?? []) as Json[]) {
      if (t.layer !== layer) continue;
      g.lineWidth = Math.max(1, t.width * v.scale);
      g.beginPath(); g.moveTo(v.sx(t.a[0]), v.sy(t.a[1])); g.lineTo(v.sx(t.b[0]), v.sy(t.b[1])); g.stroke();
    }
    void c;
  }

  private padShape(g: CanvasRenderingContext2D, v: View2d, pd: { pad: Json; x: number; y: number; rot: number }, dx: number, dy: number): void {
    const { pad } = pd;
    const sx = v.sx(pd.x + dx), sy = v.sy(pd.y + dy);
    g.save();
    g.translate(sx, sy);
    g.rotate(-rad(pd.rot));
    const w = pad.w * v.scale, h = pad.h * v.scale;
    g.beginPath();
    if (pad.shape === 'circle') g.arc(0, 0, Math.max(w, h) / 2, 0, 7);
    else if (pad.shape === 'oval') {
      const r = Math.min(w, h) / 2;
      if (w >= h) { g.moveTo(-w / 2 + r, -h / 2); g.lineTo(w / 2 - r, -h / 2); g.arc(w / 2 - r, 0, r, -Math.PI / 2, Math.PI / 2); g.lineTo(-w / 2 + r, h / 2); g.arc(-w / 2 + r, 0, r, Math.PI / 2, -Math.PI / 2); }
      else { g.moveTo(-w / 2, -h / 2 + r); g.arc(0, -h / 2 + r, r, Math.PI, 0); g.lineTo(w / 2, h / 2 - r); g.arc(0, h / 2 - r, r, 0, Math.PI); }
      g.closePath();
    } else if (pad.shape === 'poly' && pad.poly) {
      (pad.poly as Pt[]).forEach((q, i) => { if (i === 0) g.moveTo(q[0] * v.scale, -q[1] * v.scale); else g.lineTo(q[0] * v.scale, -q[1] * v.scale); });
      g.closePath();
    } else if (pad.shape === 'roundrect') {
      const r = Math.min(w, h) * Number(pad.roundrect_ratio ?? 0.25);
      g.roundRect(-w / 2, -h / 2, w, h, r);
    } else g.rect(-w / 2, -h / 2, w, h);
    g.fill();
    if (pad.drill > 0) {
      g.beginPath();
      if (pad.slot) { const sw = pad.slot[0] * v.scale, sh = pad.slot[1] * v.scale; g.roundRect(-sw / 2, -sh / 2, sw, sh, Math.min(sw, sh) / 2); }
      else g.arc(0, 0, (pad.drill / 2) * v.scale, 0, 7);
      g.save(); g.fillStyle = ink().bg; g.fill(); g.restore();
    }
    g.restore();
  }

  private pads(g: CanvasRenderingContext2D, v: View2d, layer: string, col: string, c: ReturnType<typeof ink>): void {
    g.fillStyle = col;
    for (const part of (ec.pcb?.parts ?? []) as Json[]) {
      const dx = this.drag && this.drag.ref === part.refdes ? this.drag.delta[0] : 0;
      const dy = this.drag && this.drag.ref === part.refdes ? this.drag.delta[1] : 0;
      for (const pd of this.padsOf(part)) {
        if (!pd.layers.includes(layer)) continue;
        this.padShape(g, v, pd, dx, dy);
      }
    }
    void c;
  }

  private vias(g: CanvasRenderingContext2D, v: View2d, c: ReturnType<typeof ink>): void {
    for (const via of (ec.pcb?.vias ?? []) as Json[]) {
      g.beginPath(); g.arc(v.sx(via.x), v.sy(via.y), (via.dia / 2) * v.scale, 0, 7);
      g.fillStyle = c.fcu; g.globalAlpha = 0.9; g.fill(); g.globalAlpha = 1;
      g.beginPath(); g.arc(v.sx(via.x), v.sy(via.y), Math.max(1, (via.drill / 2) * v.scale), 0, 7);
      g.fillStyle = c.bg; g.fill();
    }
  }

  private silk(g: CanvasRenderingContext2D, v: View2d, c: ReturnType<typeof ink>): void {
    for (const part of (ec.pcb?.parts ?? []) as Json[]) {
      const bottom = part.side === 'bottom';
      const dx = this.drag && this.drag.ref === part.refdes ? this.drag.delta[0] : 0;
      const dy = this.drag && this.drag.ref === part.refdes ? this.drag.delta[1] : 0;
      g.strokeStyle = bottom ? c.bsilk : c.fsilk; g.lineCap = 'round';
      for (const s of (part.silk ?? []) as Json[]) {
        g.lineWidth = Math.max(1, (s.w ?? 0.12) * v.scale);
        if (s.t === 'line' || s.t === 'poly') {
          g.beginPath();
          (s.pts as Pt[]).forEach((q, i) => { const w = partPoint(part, q[0], q[1]); if (i === 0) g.moveTo(v.sx(w[0] + dx), v.sy(w[1] + dy)); else g.lineTo(v.sx(w[0] + dx), v.sy(w[1] + dy)); });
          g.stroke();
        } else if (s.t === 'circle') {
          const w = partPoint(part, s.c[0], s.c[1]);
          g.beginPath(); g.arc(v.sx(w[0] + dx), v.sy(w[1] + dy), s.r * v.scale, 0, 7); g.stroke();
        }
      }
      if (this.vis.court && part.courtyard?.length) {
        g.strokeStyle = c.court; g.lineWidth = 1; g.setLineDash([2, 3]);
        this.polyPath(g, v, (part.courtyard as Pt[]).map((q) => { const w = partPoint(part, q[0], q[1]); return [w[0] + dx, w[1] + dy] as Pt; }));
        g.stroke(); g.setLineDash([]);
      }
      if (v.scale >= 9) {
        g.fillStyle = c.text; g.globalAlpha = 0.85; g.font = `${Math.max(8, 0.9 * v.scale)}px sans-serif`; g.textAlign = 'center'; g.textBaseline = 'middle';
        g.fillText(String(part.refdes), v.sx(part.x + dx), v.sy(part.y + dy)); g.textAlign = 'left'; g.globalAlpha = 1;
      }
    }
  }

  private selection(g: CanvasRenderingContext2D, v: View2d, c: ReturnType<typeof ink>): void {
    const s = this.sel;
    const p = ec.pcb;
    if (!s || !p) return;
    g.strokeStyle = c.accent; g.lineWidth = 2;
    if (s.kind === 'part') {
      const part = (p.parts as Json[]).find((q) => q.refdes === s.id);
      if (!part) return;
      const dx = this.drag?.ref === s.id ? this.drag.delta[0] : 0, dy = this.drag?.ref === s.id ? this.drag.delta[1] : 0;
      const cy = (part.courtyard as Pt[] | undefined) ?? [];
      if (cy.length > 2) { this.polyPath(g, v, cy.map((q) => { const w = partPoint(part, q[0], q[1]); return [w[0] + dx, w[1] + dy] as Pt; })); g.stroke(); }
    } else if (s.kind === 'track') {
      const t = (p.tracks as Json[]).find((q) => q.id === s.id);
      if (t) { g.lineWidth = Math.max(3, t.width * v.scale + 4); g.globalAlpha = 0.5; g.beginPath(); g.moveTo(v.sx(t.a[0]), v.sy(t.a[1])); g.lineTo(v.sx(t.b[0]), v.sy(t.b[1])); g.stroke(); g.globalAlpha = 1; }
    } else if (s.kind === 'via') {
      const t = (p.vias as Json[]).find((q) => q.id === s.id);
      if (t) { g.beginPath(); g.arc(v.sx(t.x), v.sy(t.y), (t.dia / 2) * v.scale + 3, 0, 7); g.stroke(); }
    }
  }

  focus(x: number, y: number): void { this.view.centerOn(x, y); if (this.view.scale < 14) this.view.zoomBy(14 / this.view.scale); }
  boxOfBoard(): Box | null { const o = this.outline(); return o.length ? boxOf(o) : null; }
}
