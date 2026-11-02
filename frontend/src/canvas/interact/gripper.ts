import { api, ApiError, type GripRequest } from '../../io/api';
import type { DisplayItem, GripMark, Handle, Pt } from '../types';
import type { Ctx } from './ctx';

export type GripAction = 'stretch' | 'move' | 'rotate' | 'scale' | 'mirror';
export const MODES: GripAction[] = ['stretch', 'move', 'rotate', 'scale', 'mirror'];
const MODE_TEXT: Record<GripAction, string> = {
  stretch: '** STRETCH ** Specify stretch point or [Base point/Copy/Undo/eXit]:',
  move: '** MOVE ** Specify move point or [Base point/Copy/Undo/eXit]:',
  rotate: '** ROTATE ** Specify rotation angle or [Base point/Copy/Undo/Reference/eXit]:',
  scale: '** SCALE ** Specify scale factor or [Base point/Copy/Undo/Reference/eXit]:',
  mirror: '** MIRROR ** Specify second point or [Base point/Copy/Undo/eXit]:',
};
const OPTION_TEXT: Record<string, string> = {
  add_vertex: '** ADD VERTEX ** Specify new vertex:',
  convert_arc: '** CONVERT TO ARC ** Specify point on arc:',
  lengthen: '** LENGTHEN ** Specify new end point:',
  radius: '** RADIUS ** Specify point on new circle:',
};

export interface GripRef { h: Handle; id: string | number; p: Pt; kind: string; geom: string; item: DisplayItem }

export interface GripSession {
  grips: GripRef[];
  mode: GripAction;
  option: string | null;
  copies: Pt[];
  drag: boolean;
  base: Pt | null;
}

const MAX_OBJECTS = 200;

export class Gripper {
  hot: GripRef[] = [];
  session: GripSession | null = null;
  hover: GripRef | null = null;
  private seq = 0;
  private busy = false;
  private wanted: Pt | null = null;
  private lastKey = '';
  private cache: GripRef[] = [];
  private cacheItems: DisplayItem[] = [];

  constructor(private readonly cx: Ctx, private readonly selected: () => Set<Handle>, private readonly setJig: (items: DisplayItem[] | null) => void) {}

  active(): boolean {
    return this.session !== null;
  }

  list(): GripRef[] {
    const s = this.cx.set();
    const sel = this.selected();
    if (!s.grips || this.cx.state().active || sel.size === 0 || sel.size > MAX_OBJECTS || (s.gripobjlimit > 0 && sel.size > s.gripobjlimit)) return [];
    const items: DisplayItem[] = [];
    for (const h of sel) {
      const it = this.cx.canvas.item(h);
      if (it) items.push(it);
    }
    if (items.length === this.cacheItems.length && items.every((it, i) => it === this.cacheItems[i])) return this.cache;
    const out: GripRef[] = [];
    for (const it of items) {
      if (!it.grips) continue;
      for (const g of it.grips) out.push({ h: it.h as Handle, id: g.id, p: g.p, kind: g.kind ?? '', geom: it.geom?.type ?? '', item: it });
    }
    this.cacheItems = items;
    this.cache = out;
    return out;
  }

  invalidate(): void {
    this.cacheItems = [];
  }

  hit(px: number, py: number): GripRef | null {
    const half = Math.max(2, this.cx.set().gripsize) + 3;
    let best: GripRef | null = null;
    let bd = Infinity;
    for (const g of this.list()) {
      const [sx, sy] = this.cx.canvas.screenFromWorld(g.p[0], g.p[1]);
      const d = Math.max(Math.abs(sx - px), Math.abs(sy - py));
      if (d <= half && d < bd) { best = g; bd = d; }
    }
    return best;
  }

  marks(): GripMark[] {
    const out: GripMark[] = [];
    const hotKeys = new Set(this.hot.map((g) => `${String(g.h)}|${String(g.id)}`));
    const sess = this.session ? new Set(this.session.grips.map((g) => `${String(g.h)}|${String(g.id)}`)) : null;
    for (const g of this.list()) {
      const key = `${String(g.h)}|${String(g.id)}`;
      const hot = hotKeys.has(key) || (sess?.has(key) ?? false);
      const warm = !hot && this.hover !== null && this.hover.h === g.h && this.hover.id === g.id;
      out.push({ p: g.p, state: hot ? 'hot' : warm ? 'warm' : 'cold', kind: g.kind === 'segmid' ? 'mid' : g.kind });
    }
    return out;
  }

  toggleHot(g: GripRef): void {
    const i = this.hot.findIndex((q) => q.h === g.h && q.id === g.id);
    if (i >= 0) this.hot.splice(i, 1);
    else this.hot.push(g);
    this.cx.schedule();
  }

  begin(g: GripRef, drag: boolean, copy: boolean, option: string | null = null): void {
    const grips = this.hot.length && this.hot.some((q) => q.h === g.h && q.id === g.id) ? [...this.hot] : [g];
    this.session = { grips, mode: 'stretch', option, copies: [], drag, base: null };
    this.lastKey = '';
    if (copy) this.session.copies = [];
    this.announce();
    this.cx.schedule();
  }

  announce(): void {
    const s = this.session;
    if (!s) {
      this.cx.hint('');
      return;
    }
    this.cx.hint(s.option ? OPTION_TEXT[s.option] ?? '' : MODE_TEXT[s.mode]);
  }

  cycle(): void {
    const s = this.session;
    if (!s || s.option) return;
    s.mode = MODES[(MODES.indexOf(s.mode) + 1) % MODES.length];
    this.lastKey = '';
    this.announce();
    this.cx.schedule();
  }

  cancel(): void {
    this.seq++;
    this.session = null;
    this.hot = [];
    this.setJig(null);
    this.announce();
    this.cx.schedule();
  }

  anchor(): Pt | null {
    const s = this.session;
    if (!s) return null;
    const g = s.grips[0];
    if (s.base) return s.base;
    const geom = g.item.geom;
    const id = String(g.id);
    if (geom?.type === 'line') return id === 'start' ? geom.p2 : id === 'end' ? geom.p1 : g.p;
    if (geom?.type === 'poly' && id.startsWith('v')) {
      const i = Number(id.slice(1));
      const v = geom.verts;
      const prev = i > 0 ? v[i - 1] : geom.closed ? v[v.length - 1] : v[1];
      return prev ? [prev[0], prev[1]] : g.p;
    }
    if (geom?.type === 'circle') return geom.c;
    if (geom?.type === 'arc') return geom.c;
    if (geom?.type === 'ellipse') return geom.c;
    return g.p;
  }

  private request(to: Pt, preview: boolean, g: GripRef, copy: boolean, more?: Pt[]): GripRequest {
    const s = this.session as GripSession;
    const first = s.grips[0];
    const d: Pt = [to[0] - first.p[0], to[1] - first.p[1]];
    const target: Pt = g === first ? to : [g.p[0] + d[0], g.p[1] + d[1]];
    const body: GripRequest = { handle: g.h, grip: g.id, mode: s.mode, to: target, preview };
    if (s.option) body.option = s.option;
    if (s.base) body.base = s.base;
    if (copy) body.copy = true;
    if (more && more.length) body.more = more;
    return body;
  }

  preview(to: Pt): void {
    const s = this.session;
    const id = this.cx.doc();
    if (!s || !id) return;
    const key = `${to[0].toFixed(9)}|${to[1].toFixed(9)}|${s.mode}|${s.copies.length}|${s.option ?? ''}`;
    if (key === this.lastKey) return;
    this.lastKey = key;
    if (this.busy) {
      this.wanted = to;
      return;
    }
    void this.runPreview(id, to);
  }

  private async runPreview(id: string, to: Pt): Promise<void> {
    const s = this.session;
    if (!s) return;
    this.busy = true;
    const seq = ++this.seq;
    try {
      const copy = s.copies.length > 0;
      const pts = copy ? [...s.copies, to] : [to];
      const res = await Promise.all(s.grips.map((g) => api.grip(id, this.request(pts[0], true, g, copy, pts.slice(1)))));
      if (seq === this.seq && this.session) this.setJig(res.flatMap((r) => r.items ?? []));
    } catch {
      if (seq === this.seq) this.setJig(null);
    } finally {
      this.busy = false;
      const next = this.wanted;
      this.wanted = null;
      if (next && this.session) {
        this.lastKey = '';
        this.preview(next);
      }
    }
  }

  async commit(to: Pt, copy: boolean): Promise<void> {
    const s = this.session;
    const id = this.cx.doc();
    if (!s || !id) return;
    const pts = copy || s.copies.length ? [...s.copies, to] : [to];
    const isCopy = pts.length > 1 || copy || s.copies.length > 0;
    try {
      for (const g of s.grips) await api.grip(id, this.request(pts[0], false, g, isCopy, pts.slice(1)));
    } catch (e) {
      this.cx.toast(e instanceof ApiError || e instanceof Error ? e.message : 'The grip edit failed');
    }
    this.end();
  }

  addCopy(to: Pt): void {
    const s = this.session;
    if (!s) return;
    s.copies.push(to);
    this.lastKey = '';
    this.cx.schedule();
  }

  async finishCopies(): Promise<void> {
    const s = this.session;
    const id = this.cx.doc();
    if (!s || !id || !s.copies.length) {
      this.cancel();
      return;
    }
    const pts = s.copies;
    try {
      for (const g of s.grips) await api.grip(id, this.request(pts[0], false, g, true, pts.slice(1)));
    } catch (e) {
      this.cx.toast(e instanceof ApiError || e instanceof Error ? e.message : 'The grip edit failed');
    }
    this.end();
  }

  end(): void {
    this.seq++;
    this.session = null;
    this.hot = [];
    this.setJig(null);
    this.invalidate();
    this.announce();
    this.cx.schedule();
  }
}
