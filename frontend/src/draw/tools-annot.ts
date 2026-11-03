import type { Pt } from '../canvas/types';
import { call } from '../io/api';
import { docStore } from '../ui/doc-store';
import { el } from '../ui/dom';
import { t } from '../ui/i18n';
import { selection } from '../ui/panels/selection-bus';
import { toast } from '../ui/toast';
import { dv, messageOf, type ViewInfo } from './api';
import { drawStore } from './store';
import { lengthOf, toPaper, type Tool, type ToolHost } from './tool-host';
import { selectCtl, textCtl } from './ui';

export interface Feature { view: ViewInfo; edge: string; t: string; at: Pt; kind: 'line' | 'circle' | 'arc' }
interface EdgeRec { id: string; kind: 'line' | 'circle' | 'arc'; pts: Array<{ t: string; at: Pt }>; r?: number; c?: Pt }

const ORDER = ['sharp_v', 'outline_v', 'smooth_v', 'sewn_v'];
const edgeCache = new Map<number, { sig: string; edges: EdgeRec[] }>();

interface Rec { t: string; a?: Pt; b?: Pt; c?: Pt; r?: number; a0?: number; a1?: number; pid?: number }

async function edgesOf(v: ViewInfo): Promise<EdgeRec[]> {
  const hit = edgeCache.get(v.handle);
  if (hit && hit.sig === v.state.sig) return hit.edges;
  const id = docStore.activeId;
  if (!id) return [];
  const r = await call<{ cache?: { classes?: Record<string, Rec[]> } }>('GET', `/api/docs/${encodeURIComponent(id)}/drawviews/${v.handle}?cache=true`);
  const classes = r.cache?.classes ?? {};
  const used = new Set<string>();
  const out: EdgeRec[] = [];
  const k = v.scale / (v.unitMm || 1);
  for (const cls of ['sharp_v', 'outline_v', 'smooth_v', 'sewn_v', 'sharp_h', 'smooth_h', 'sewn_h', 'outline_h']) {
    (classes[cls] ?? []).forEach((rec, i) => {
      let ident = rec.pid ? `p${rec.pid}` : `${cls}.${i}`;
      if (used.has(ident)) ident = `${ident}.${i}`;
      used.add(ident);
      if (!ORDER.includes(cls)) return;
      if (rec.t === 'line' && rec.a && rec.b) {
        const a = toPaper(v, rec.a);
        const b = toPaper(v, rec.b);
        out.push({ id: ident, kind: 'line', pts: [{ t: 'start', at: a }, { t: 'end', at: b }, { t: 'mid', at: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] }] });
      } else if (rec.t === 'circle' && rec.c && rec.r !== undefined) {
        out.push({ id: ident, kind: 'circle', pts: [{ t: 'center', at: toPaper(v, rec.c) }], r: rec.r * k, c: toPaper(v, rec.c) });
      } else if (rec.t === 'arc' && rec.c && rec.r !== undefined && rec.a0 !== undefined && rec.a1 !== undefined) {
        const c = toPaper(v, rec.c);
        const rr = rec.r * k;
        const at = (a: number): Pt => [c[0] + rr * Math.cos(a), c[1] + rr * Math.sin(a)];
        const sweep = (((rec.a1 - rec.a0) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
        out.push({ id: ident, kind: 'arc', pts: [{ t: 'start', at: at(rec.a0) }, { t: 'end', at: at(rec.a1) }, { t: 'mid', at: at(rec.a0 + sweep / 2) }, { t: 'center', at: c }], r: rr, c });
      }
    });
  }
  edgeCache.set(v.handle, { sig: v.state.sig, edges: out });
  return out;
}

export async function featureAt(h: ToolHost, p: Pt, tolPx = 10, circles = false): Promise<Feature | null> {
  const w = Math.abs(h.env.canvas.worldFromScreen(tolPx, 0)[0] - h.env.canvas.worldFromScreen(0, 0)[0]);
  let best: Feature | null = null;
  let dist = w;
  for (const v of drawStore.views) {
    const [x0, y0, x1, y1] = v.bounds;
    if (p[0] < x0 - w || p[0] > x1 + w || p[1] < y0 - w || p[1] > y1 + w) continue;
    for (const e of await edgesOf(v)) {
      if (circles) {
        if (e.kind === 'line' || !e.c || e.r === undefined) continue;
        const d = Math.abs(lengthOf(p, e.c) - e.r);
        if (d < dist) { dist = d; best = { view: v, edge: e.id, t: 'center', at: e.c, kind: e.kind }; }
        continue;
      }
      for (const f of e.pts) {
        const d = lengthOf(p, f.at);
        if (d < dist) { dist = d; best = { view: v, edge: e.id, t: f.t, at: f.at, kind: e.kind }; }
      }
    }
  }
  return best;
}

export async function circleEdges(v: ViewInfo): Promise<EdgeRec[]> {
  return (await edgesOf(v)).filter((e) => e.kind !== 'line');
}

const link = (f: Feature): { e: string; t: string } => ({ e: f.edge, t: f.t });

function hover(h: ToolHost, circles = false): (p: Pt) => Promise<void> {
  let busy = false;
  return async (p) => {
    if (busy) return;
    busy = true;
    const f = await featureAt(h, p, 10, circles);
    busy = false;
    h.env.overlay.setGhost(f ? { hot: [[f.at[0] - 1, f.at[1]], [f.at[0] + 1, f.at[1]]], cross: f.at } : {});
  };
}

async function runCommand(name: string, args: Record<string, unknown>): Promise<Record<string, unknown> | null> {
  const id = docStore.activeId;
  if (!id) return null;
  try {
    const res = (await dv.run(id, name, args)) as { result?: Record<string, unknown>; error?: string };
    void docStore.refresh();
    if (res?.error) { toast(res.error, 'error'); return null; }
    return res?.result ?? {};
  } catch (e) {
    toast(messageOf(e), 'error');
    return null;
  }
}

export const runAnnot = runCommand;

export function dimensionTool(h: ToolHost): Tool {
  const kind = selectCtl('Dimension', [['linear', 'Linear'], ['aligned', 'Aligned'], ['radius', 'Radius'], ['diameter', 'Diameter']]);
  const orient = selectCtl('Direction', [['', 'Automatic'], ['horizontal', 'Horizontal'], ['vertical', 'Vertical']]);
  const opts = el('<span class="dw-inline"></span>');
  opts.append(kind.el, orient.el);
  let a: Feature | null = null;
  let b: Feature | null = null;
  const round = (): boolean => kind.get() === 'radius' || kind.get() === 'diameter';
  const near = hover(h);
  const nearCircle = hover(h, true);
  kind.input.addEventListener('change', () => { a = null; b = null; h.paintHint(); h.env.overlay.clearGhost(); });
  const create = async (loc: Pt): Promise<void> => {
    if (!a) return;
    const base: Record<string, unknown> = { view: a.view.handle, kind: kind.get(), location: loc };
    if (round()) base.edge = a.edge;
    else { base.a = link(a); base.b = b ? link(b) : undefined; if (orient.get()) base.orientation = orient.get(); }
    const res = await runCommand('viewdim', base);
    a = null;
    b = null;
    h.env.overlay.clearGhost();
    h.paintHint();
    if (res) toast(t('Dimension added.'));
  };
  return {
    id: 'dim',
    title: 'Dimension view geometry',
    opts,
    hint: () => {
      if (round()) return !a ? 'Click a circle or arc of a view.' : 'Click where the dimension text goes.';
      return !a ? 'Click the first point on a view edge.' : !b ? 'Click the second point.' : 'Click where the dimension line goes.';
    },
    enter: () => { a = null; b = null; },
    leave: () => { a = null; b = null; },
    move: (p) => {
      if (a && (round() || b)) { h.env.overlay.setGhost({ line: [a.at, p], cross: p }); return; }
      if (a && !b) { h.env.overlay.setGhost({ line: [a.at, p] }); void near(p); return; }
      return round() ? nearCircle(p) : near(p);
    },
    click: async (p) => {
      if (!a) {
        const f = await featureAt(h, p, 10, round());
        if (!f) { toast(t('Click on a view edge.')); return; }
        a = f;
        h.paintHint();
        return;
      }
      if (round()) { await create(p); return; }
      if (!b) {
        const f = await featureAt(h, p);
        if (!f || f.view.handle !== a.view.handle) { toast(t('Pick a point on the same view.')); return; }
        b = f;
        h.paintHint();
        return;
      }
      await create(p);
    },
    back: () => { if (b) b = null; else a = null; h.paintHint(); },
  };
}

export interface LeaderPick { at: Pt; tip: { tip?: Pt; tip_link?: { h: number; e: string; t: string } } }

export function placeTool(h: ToolHost, spec: {
  id: string;
  title: string;
  hint: string;
  tipHint?: string;
  opts?: HTMLElement;
  done(at: Pt, tip: LeaderPick['tip']): void | Promise<void>;
}): Tool {
  let at: Pt | null = null;
  const near = hover(h);
  return {
    id: spec.id,
    title: spec.title,
    opts: spec.opts,
    finishLabel: spec.tipHint ? 'No leader' : undefined,
    finish: spec.tipHint ? async () => { if (at) { const p = at; at = null; h.disarm(); await spec.done(p, {}); } } : undefined,
    hint: () => (!at ? spec.hint : spec.tipHint ?? ''),
    enter: () => { at = null; },
    leave: () => { at = null; },
    move: (p) => {
      if (at) { h.env.overlay.setGhost({ line: [at, p] }); void near(p); return; }
      h.env.overlay.setGhost({ cross: p });
    },
    click: async (p) => {
      if (!at) {
        if (!spec.tipHint) { h.disarm(); await spec.done(p, {}); return; }
        at = p;
        h.paintHint();
        return;
      }
      const f = await featureAt(h, p);
      const from = at;
      at = null;
      h.disarm();
      if (f) await spec.done(from, { tip_link: { h: f.view.handle, ...link(f) } });
      else await spec.done(from, { tip: p });
    },
  };
}

export function finishTool(h: ToolHost): Tool {
  const value = textCtl('Value');
  value.set('Ra 3.2');
  const opts = el('<span class="dw-inline"></span>');
  opts.append(value.el);
  return placeTool(h, {
    id: 'finish',
    title: 'Surface finish mark',
    hint: 'Click where the mark goes; click an edge to attach it.',
    opts,
    done: async (at) => {
      const res = await runCommand('finishmark', { point: at, value: value.get() || 'Ra 3.2' });
      if (res?.created) selection.select([Number(res.created)]);
    },
  });
}
