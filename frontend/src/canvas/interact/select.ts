import { api, ApiError } from '../../io/api';
import type { BoxMark, Handle, HighlightMark, PointerInfo } from '../types';
import type { Ctx } from './ctx';
import type { ContextMenu } from './menu';

export interface WindowState { x0: number; y0: number; x1: number; y1: number }

export class Selector {
  selected = new Set<Handle>();
  pending = new Set<Handle>();
  hover: Handle | null = null;
  corner: { x: number; y: number } | null = null;
  rubber: WindowState | null = null;
  overlap = 0;
  private cycleHits: Handle[] = [];
  private cycleIdx = -1;
  private cycleAt: { px: number; py: number } | null = null;
  private lastHoverKey = '';

  constructor(private readonly cx: Ctx, private readonly menu: ContextMenu) {}

  private apertureOf(): number {
    return Math.max(2, this.cx.set().pickbox * 1.5);
  }

  hitsAt(px: number, py: number): Handle[] {
    const hits = this.cx.canvas.pickAt(px, py, this.apertureOf()).filter((h) => h.handle !== null && h.handle !== undefined);
    hits.sort((a, b) => b.order - a.order || a.dist - b.dist);
    const seen = new Set<Handle>();
    const out: Handle[] = [];
    for (const h of hits) if (!seen.has(h.handle)) { seen.add(h.handle); out.push(h.handle); }
    return out;
  }

  topAt(px: number, py: number): Handle | null {
    if (this.cycleIdx >= 0 && this.cycleHits.length) return this.cycleHits[this.cycleIdx];
    return this.hitsAt(px, py)[0] ?? null;
  }

  sync(handles: Handle[]): void {
    const next = new Set<Handle>(handles);
    if (next.size === this.selected.size && [...next].every((h) => this.selected.has(h))) return;
    this.selected = next;
    this.cx.schedule();
  }

  prune(): void {
    let changed = false;
    for (const h of [...this.selected]) if (!this.cx.canvas.item(h)) { this.selected.delete(h); changed = true; }
    for (const h of [...this.pending]) if (!this.cx.canvas.item(h)) { this.pending.delete(h); changed = true; }
    if (changed) this.cx.schedule();
  }

  reset(): void {
    this.selected = new Set();
    this.pending = new Set();
    this.hover = null;
    this.corner = null;
    this.rubber = null;
    this.endCycle();
    this.cx.schedule();
  }

  endCycle(): void {
    this.cycleHits = [];
    this.cycleIdx = -1;
    this.cycleAt = null;
  }

  async commit(): Promise<void> {
    const id = this.cx.doc();
    if (!id) return;
    try {
      await api.putSelection(id, [...this.selected], 'set');
    } catch (e) {
      this.cx.toast(e instanceof ApiError || e instanceof Error ? e.message : 'The engine did not answer');
    }
  }

  clearSelection(): void {
    if (!this.selected.size) return;
    this.selected = new Set();
    this.cx.schedule();
    void this.commit();
  }

  applyIdle(found: Handle[], shift: boolean): void {
    const s = this.cx.set();
    const next = new Set(this.selected);
    if (s.pickadd) {
      for (const h of found) { if (shift) next.delete(h); else next.add(h); }
    } else if (shift) {
      for (const h of found) next.add(h);
    } else {
      next.clear();
      for (const h of found) next.add(h);
    }
    this.selected = next;
    this.cx.schedule();
    void this.commit();
  }

  async applyPrompt(found: Handle[], shift: boolean, box?: [number, number, number, number]): Promise<void> {
    const id = this.cx.doc();
    if (!id || !found.length) return;
    for (const h of found) { if (shift) this.pending.delete(h); else this.pending.add(h); }
    this.cx.schedule();
    try {
      const st = await api.sendCanvasInput(id, { selection: { handles: found, mode: shift ? 'remove' : 'add', box } });
      this.cx.publish(id, st);
    } catch (e) {
      this.cx.toast(e instanceof ApiError || e instanceof Error ? e.message : 'The engine did not answer');
    }
  }

  async pickEntity(px: number, py: number): Promise<void> {
    const id = this.cx.doc();
    const h = this.topAt(px, py);
    if (!id || h === null) return;
    const [x, y] = this.cx.canvas.worldFromScreen(px, py);
    try {
      this.cx.publish(id, await api.sendCanvasInput(id, { pick: { point: [x, y], handle: h } }));
    } catch (e) {
      this.cx.toast(e instanceof ApiError || e instanceof Error ? e.message : 'The engine did not answer');
    }
    this.endCycle();
  }

  deliver(found: Handle[], shift: boolean, prompt: boolean, box?: [number, number, number, number]): void {
    if (prompt) void this.applyPrompt(found, shift, box);
    else this.applyIdle(found, shift);
  }

  click(info: PointerInfo, prompt: boolean): void {
    const shift = info.shift;
    if (this.corner) {
      const c = this.corner;
      this.corner = null;
      this.rubber = null;
      this.finishWindow(c.x, c.y, info.x, info.y, shift, prompt);
      return;
    }
    const hits = this.hitsAt(info.px, info.py);
    const level = this.cx.set().cycling;
    if (this.cycleIdx >= 0 && this.cycleHits.length) {
      const h = this.cycleHits[this.cycleIdx];
      this.endCycle();
      this.deliver([h], shift, prompt);
      return;
    }
    if (hits.length > 1 && level >= 2) {
      this.openList(hits, info, prompt);
      return;
    }
    if (hits.length) {
      this.deliver([hits[0]], shift, prompt);
      return;
    }
    this.corner = { x: info.x, y: info.y };
    this.rubber = { x0: info.x, y0: info.y, x1: info.x, y1: info.y };
    this.cx.schedule();
  }

  private openList(hits: Handle[], info: PointerInfo, prompt: boolean): void {
    const rect = this.cx.host.getBoundingClientRect();
    const entries = hits.slice(0, 40).map((h) => {
      const it = this.cx.canvas.item(h);
      return {
        label: `${it?.kind ?? 'object'}  ${it?.layer ?? ''}`,
        hover: () => { this.hover = h; this.cx.schedule(); },
        run: () => { this.hover = null; this.deliver([h], info.shift, prompt); },
      };
    });
    this.menu.onClose = () => { this.hover = null; this.cx.schedule(); };
    this.menu.open(rect.left + info.px + 6, rect.top + info.py + 6, entries);
  }

  step(px: number, py: number): void {
    const hits = this.hitsAt(px, py);
    if (hits.length < 2) return;
    const near = this.cycleAt && Math.hypot(px - this.cycleAt.px, py - this.cycleAt.py) <= this.apertureOf();
    if (!near || !this.cycleHits.length) {
      this.cycleHits = hits;
      this.cycleIdx = 0;
      this.cycleAt = { px, py };
    }
    this.cycleIdx = (this.cycleIdx + 1) % this.cycleHits.length;
    this.hover = this.cycleHits[this.cycleIdx];
    this.cx.schedule();
  }

  moved(px: number, py: number): void {
    if (this.cycleAt && Math.hypot(px - this.cycleAt.px, py - this.cycleAt.py) > this.apertureOf()) this.endCycle();
  }

  drag(phase: 'start' | 'move' | 'end', x0: number, y0: number, x: number, y: number, shift: boolean, prompt: boolean): void {
    if (phase === 'end') {
      this.rubber = null;
      this.corner = null;
      this.finishWindow(x0, y0, x, y, shift, prompt);
      return;
    }
    this.corner = null;
    this.rubber = { x0, y0, x1: x, y1: y };
    this.cx.schedule();
  }

  finishWindow(x0: number, y0: number, x1: number, y1: number, shift: boolean, prompt: boolean): void {
    const px = Math.abs(x1 - x0) * this.cx.canvas.view.scale;
    const py = Math.abs(y1 - y0) * this.cx.canvas.view.scale;
    this.cx.schedule();
    if (px < 2 && py < 2) return;
    const found = this.cx.canvas.boxQuery([x0, y0, x1, y1], x1 < x0).filter((h) => h !== null && h !== undefined);
    if (!found.length) {
      if (!prompt && !this.cx.set().pickadd && !shift) this.clearSelection();
      return;
    }
    this.deliver(found, shift, prompt, [x0, y0, x1, y1]);
  }

  cancelWindow(): boolean {
    const had = !!this.corner || !!this.rubber;
    this.corner = null;
    this.rubber = null;
    if (had) this.cx.schedule();
    return had;
  }

  marks(promptMode: boolean): HighlightMark[] {
    const out: HighlightMark[] = [];
    const sel = [...this.selected, ...this.pending].filter((h) => this.cx.canvas.item(h));
    if (sel.length) out.push({ handles: sel, kind: 'selected' });
    const s = this.cx.set();
    const allowed = promptMode ? (s.selpreview & 2) !== 0 : (s.selpreview & 1) !== 0;
    if (allowed && this.hover !== null && this.cx.canvas.item(this.hover)) out.push({ handles: [this.hover], kind: 'hover' });
    return out;
  }

  updateHover(px: number | null, py: number | null, active: boolean): void {
    if (!active || px === null || py === null || this.menu.isOpen) {
      if (this.hover !== null && !this.menu.isOpen) { this.hover = null; }
      this.overlap = 0;
      return;
    }
    const key = `${Math.round(px)}|${Math.round(py)}|${this.cycleIdx}`;
    if (key === this.lastHoverKey) return;
    this.lastHoverKey = key;
    const hits = this.hitsAt(px, py);
    this.overlap = hits.length;
    this.hover = this.cycleIdx >= 0 && this.cycleHits.length ? this.cycleHits[this.cycleIdx] : hits[0] ?? null;
  }

  box(): BoxMark[] {
    const r = this.rubber;
    return r ? [{ x0: r.x0, y0: r.y0, x1: r.x1, y1: r.y1, crossing: r.x1 < r.x0 }] : [];
  }
}
