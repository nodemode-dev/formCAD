import { events } from '../io/events';
import { docStore } from '../ui/doc-store';
import type { DockPanel } from '../ui/dock';
import { el, patchList, q, setClass, setHidden, setText, store, stored } from '../ui/dom';
import { t } from '../ui/i18n';
import { gate } from '../ui/panel-gate';
import { toast } from '../ui/toast';
import { req, text, docUrl } from '../u8/net';
import { numberCtl, section as baseSection, type Ctl } from '../u8/ui';

export { reportBox, num, fixed } from '../p11/kit';
export { fillSelect, mini } from '../p12/kit';
export type { ReportBox } from '../p11/kit';
export { button, buttons, checkCtl, numberCtl, selectCtl, readout } from '../u8/ui';
export type { Ctl } from '../u8/ui';
export { req, text, docUrl };

export type Json = Record<string, unknown>;
export const obj = (v: unknown): Json => (v && typeof v === 'object' && !Array.isArray(v) ? v as Json : {});
export const arr = (v: unknown): Json[] => (Array.isArray(v) ? v.filter((x) => x && typeof x === 'object') as Json[] : []);
export const str = (v: unknown): string => (typeof v === 'string' ? v : typeof v === 'number' ? String(v) : '');
export const nn = (v: unknown, d = 0): number => (typeof v === 'number' && Number.isFinite(v) ? v : d);
export const f3 = (v: unknown, digits = 3): string => {
  if (typeof v !== 'number' || !Number.isFinite(v)) return '-';
  if (v === 0) return '0';
  return Math.abs(v) >= 1e6 || Math.abs(v) < 1e-3 ? v.toExponential(2) : String(Number(v.toFixed(digits)));
};

const FOLD_KEY = 'formCAD.p15.folds';
const OPEN_FIRST = new Set(['Frame', 'Members', 'Cut list', 'Settings', 'Analysis', 'Generator', 'Characteristics', 'Estimate', 'Findings', 'Rules']);

function folds(): Record<string, boolean> {
  try { const v: unknown = JSON.parse(stored(FOLD_KEY) ?? '{}'); return v && typeof v === 'object' ? v as Record<string, boolean> : {}; } catch { return {}; }
}

export function section(title: string): { root: HTMLElement; body: HTMLElement; head: HTMLElement } {
  const s = baseSection(title);
  const open = (): boolean => folds()[title] ?? OPEN_FIRST.has(title);
  const paint = (): void => { setClass(s.root, 'is-folded', !open()); s.head.setAttribute('aria-expanded', String(open())); };
  s.head.setAttribute('role', 'button');
  s.head.tabIndex = 0;
  const flip = (): void => { store(FOLD_KEY, JSON.stringify({ ...folds(), [title]: !open() })); paint(); };
  s.head.addEventListener('click', flip);
  s.head.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); flip(); } });
  paint();
  return s;
}

export async function guard<T>(fn: () => Promise<T>): Promise<T | null> {
  try { return await fn(); } catch (e) { toast(text(e), 'error'); return null; }
}

export const docId = (): string => docStore.activeId ?? '';
export const docApi = <T = Json>(method: string, tail: string, body?: unknown): Promise<T> => req<T>(method, docUrl(docId(), tail), body);
export const globalApi = <T = Json>(method: string, tail: string, body?: unknown): Promise<T> => req<T>(method, `/api/${tail}`, body);
export const docKind = (): string => docStore.current()?.kind ?? '';

export interface Col { key: string; label: string; w?: string; right?: boolean }
export interface TRow { key: string; cells: string[]; tone?: string }
export interface Table { el: HTMLElement; set(rows: TRow[]): void; pick(fn: (key: string) => void): void; select(key: string): void; empty(msg: string): void }

export function table(cols: Col[], height: number): Table {
  const tpl = cols.map((c) => c.w ?? 'minmax(0, 1fr)').join(' ');
  const root = el('<div class="p15-tab"><div class="p15-th"></div><div class="u8-list p15-body" role="listbox"></div><p class="u8-note p15-empty"></p></div>');
  root.style.setProperty('--p15-cols', tpl);
  root.style.setProperty('--p15-h', `${height}px`);
  const head = q(root, '.p15-th');
  const body = q(root, '.p15-body');
  const empty = q(root, '.p15-empty');
  for (const c of cols) { const s = document.createElement('span'); s.textContent = t(c.label); if (c.right) s.className = 'is-r'; head.appendChild(s); }
  let handler: (k: string) => void = () => undefined;
  let sel = '';
  const paintSel = (): void => { for (const n of Array.from(body.children) as HTMLElement[]) setClass(n, 'is-selected', n.dataset.key === sel); };
  body.addEventListener('click', (e) => {
    const row = (e.target as HTMLElement).closest<HTMLElement>('.p15-row');
    if (row?.dataset.key !== undefined) { sel = row.dataset.key; paintSel(); handler(sel); }
  });
  return {
    el: root,
    set(rows) {
      patchList(body, rows, {
        key: (r) => r.key,
        create: () => {
          const n = el('<div class="u8-row p15-row" role="option"></div>');
          for (const c of cols) { const s = document.createElement('span'); s.className = c.right ? 'p15-c is-r' : 'p15-c'; n.appendChild(s); }
          return n;
        },
        update: (n, r) => {
          const kids = n.children;
          for (let i = 0; i < cols.length; i++) { const s = kids[i] as HTMLElement; const v = r.cells[i] ?? ''; if (s.textContent !== v) { s.textContent = v; s.title = v; } }
          if (n.dataset.tone !== (r.tone ?? '')) n.dataset.tone = r.tone ?? '';
          setClass(n, 'is-selected', n.dataset.key === sel);
        },
      });
    },
    pick(fn) { handler = fn; },
    select(key) { sel = key; paintSel(); },
    empty(msg) { setText(empty, msg); },
  };
}

export function textCtl(label: string, value = '', onChange?: () => void): Ctl<string> {
  const root = el('<label class="cv-field"><span></span><input class="cv-input" type="text" spellcheck="false" autocomplete="off"></label>');
  setText(q(root, 'span'), t(label));
  const input = q<HTMLInputElement>(root, 'input');
  input.value = value;
  input.addEventListener('change', () => onChange?.());
  input.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); input.blur(); } });
  return { el: root, input, get: () => input.value.trim(), set: (v) => { if (input.value !== v && document.activeElement !== input) input.value = v; } };
}

export interface VecCtl { el: HTMLElement; get(): [number, number, number] | null; set(v: number[]): void }

export function vecCtl(label: string, value: number[] = [0, 0, 0], onChange?: () => void): VecCtl {
  const root = el('<div class="p15-vec"><span class="p15-vec-l"></span><div class="p15-vec-f"></div></div>');
  setText(q(root, '.p15-vec-l'), t(label));
  const host = q(root, '.p15-vec-f');
  const cs: Ctl<number | null>[] = ['X', 'Y', 'Z'].map((a, i) => { const c = numberCtl(a, value[i] ?? 0, onChange); host.appendChild(c.el); return c; });
  return {
    el: root,
    get() { const v = cs.map((c) => c.get()); return v.every((x) => x !== null) ? v as [number, number, number] : null; },
    set(v) { cs.forEach((c, i) => c.set(v[i] ?? 0)); },
  };
}

export interface Panel { active: boolean; refresh(): Promise<void> }

export interface PanelSpec {
  id: string;
  label: string;
  icon: string;
  order: number;
  note: string;
  need?: () => boolean;
  kinds?: readonly string[];
  build(live: HTMLElement): { load(): Promise<void>; reset?(): void };
}

const panels: Panel[] = [];

export function dockPanel(spec: PanelSpec): DockPanel {
  return {
    id: spec.id, label: spec.label, icon: spec.icon, order: spec.order,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel', 'p15-panel');
      const note = el('<p class="u8-note"></p>');
      const live = el('<div class="u8-live p15-live"></div>');
      body.append(note, live);
      const view = spec.build(live);
      const p: Panel = { active: false, refresh: () => Promise.resolve() };
      let seq = 0;
      let busy = false;
      let again = false;
      const paint = (): void => {
        const ok = !!docStore.current() && (spec.need ? spec.need() : true);
        setText(note, ok ? '' : t(spec.note));
        setHidden(note, ok);
        setHidden(live, !ok);
      };
      const allow = gate([spec.id], spec.kinds ?? null, () => { void p.refresh(); });
      p.refresh = async (): Promise<void> => {
        paint();
        if (!p.active || !docStore.activeId || (spec.need && !spec.need())) return;
        if (!allow()) return;
        if (busy) { again = true; return; }
        busy = true;
        const mine = ++seq;
        try { await view.load(); } catch (e) { if (mine === seq) toast(text(e), 'error'); } finally { busy = false; }
        if (again) { again = false; void p.refresh(); }
      };
      panels.push(p);
      paint();
      return { show() { p.active = true; void p.refresh(); } };
    },
  };
}

let timer = 0;
export function refreshAll(delay = 200): void {
  window.clearTimeout(timer);
  timer = window.setTimeout(() => { for (const p of panels) void p.refresh(); }, delay);
}

events.on('doc', (e) => { if (e.id === docStore.activeId) refreshAll(); });
let seen = docStore.activeId;
docStore.onChange(() => { if (docStore.activeId !== seen) { seen = docStore.activeId; refreshAll(0); } });

export function msgLine(): { el: HTMLElement; set(s: string, bad?: boolean): void } {
  const n = el('<p class="u8-note p15-msg" role="status"></p>');
  return { el: n, set(s, bad = false) { setText(n, s); setClass(n, 'is-bad', bad); } };
}

export function rowOf(...nodes: HTMLElement[]): HTMLElement {
  const r = el('<div class="p15-row2"></div>');
  r.append(...nodes);
  return r;
}
