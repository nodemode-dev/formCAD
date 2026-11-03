import { el, patchList, q, setClass, setHidden, setText, store, stored } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { text } from '../u8/net';
import { section as baseSection, checkCtl, numberCtl, selectCtl, type Ctl } from '../u8/ui';

export { req, text, docUrl } from '../u8/net';
export { reportBox, progressBar, num, fixed } from '../p11/kit';
export { fillSelect, mini } from '../p12/kit';
export type { ReportBox, Bar } from '../p11/kit';
export type { Json } from '../p13/sim-store';

const FOLD_KEY = 'formCAD.p14a.folds';
const OPEN_FIRST = new Set(['Studies', 'Study setup', 'Run', 'Outcomes', 'Overview', 'Nodes', 'Runs', 'Devices', 'Specs']);

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

export interface FieldDef { key: string; label: string; kind?: 'num' | 'text' | 'select' | 'check'; value?: string | number | boolean; options?: ReadonlyArray<readonly [string, string]> }
export interface FormGrid { el: HTMLElement; get(): Record<string, unknown>; set(key: string, value: unknown): void; show(key: string, on: boolean): void; ctl: Record<string, Ctl<unknown>>; options(key: string, rows: ReadonlyArray<readonly [string, string]>): void }

export function textCtl(label: string, value = ''): Ctl<string> {
  const root = el('<label class="cv-field"><span></span><input class="cv-input" type="text" spellcheck="false" autocomplete="off"></label>');
  setText(q(root, 'span'), t(label));
  const input = q<HTMLInputElement>(root, 'input');
  input.value = value;
  input.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); input.blur(); } });
  return { el: root, input, get: () => input.value.trim(), set: (v) => { if (input.value !== v && document.activeElement !== input) input.value = v; } };
}

export function formGrid(defs: FieldDef[], onChange?: () => void): FormGrid {
  const root = el('<div class="p14-form"></div>');
  const ctl: Record<string, Ctl<unknown>> = {};
  const kinds: Record<string, string> = {};
  for (const d of defs) {
    const kind = d.kind ?? 'num';
    kinds[d.key] = kind;
    let c: Ctl<unknown>;
    if (kind === 'select') c = selectCtl(d.label, d.options ?? [], onChange) as Ctl<unknown>;
    else if (kind === 'check') c = checkCtl(d.label, d.value === true, onChange) as Ctl<unknown>;
    else if (kind === 'text') c = textCtl(d.label, String(d.value ?? '')) as Ctl<unknown>;
    else c = numberCtl(d.label, typeof d.value === 'number' ? d.value : 0, onChange) as Ctl<unknown>;
    if (kind === 'text') c.input.addEventListener('change', () => onChange?.());
    if (kind === 'select' && d.value !== undefined) c.set(String(d.value));
    ctl[d.key] = c;
    root.appendChild(c.el);
  }
  return {
    el: root, ctl,
    get() {
      const out: Record<string, unknown> = {};
      for (const [k, c] of Object.entries(ctl)) {
        const v = c.get();
        if (v === null || v === '') continue;
        out[k] = v;
      }
      return out;
    },
    set(k, v) { const c = ctl[k]; if (!c) return; if (kinds[k] === 'check') c.set(v === true); else c.set((kinds[k] === 'num' ? (typeof v === 'number' ? v : null) : String(v ?? '')) as never); },
    show(k, on) { const c = ctl[k]; if (c) setHidden(c.el, !on); },
    options(k, rows) {
      const sel = ctl[k]?.input as HTMLSelectElement | undefined;
      if (!sel) return;
      const sig = rows.map((r) => r.join('\u0001')).join('\u0002');
      if (sel.dataset.sig === sig) return;
      sel.dataset.sig = sig;
      const keep = sel.value;
      sel.replaceChildren(...rows.map(([v, l]) => { const o = document.createElement('option'); o.value = v; o.textContent = l; return o; }));
      if (rows.some((r) => r[0] === keep)) sel.value = keep;
    },
  };
}

export interface RowItem { key: string; badge: string; name: string; sub: string; selected?: boolean; bad?: boolean; thumb?: string }

export function entityList(host: HTMLElement, onPick: (key: string) => void, onDelete?: (key: string) => void): (items: RowItem[]) => void {
  host.addEventListener('click', (e) => {
    const row = (e.target as HTMLElement).closest<HTMLElement>('.p14-row');
    if (!row?.dataset.key) return;
    if ((e.target as HTMLElement).closest('.p14-del')) { onDelete?.(row.dataset.key); return; }
    onPick(row.dataset.key);
  });
  return (items) => patchList(host, items, {
    key: (i) => i.key,
    create: () => el('<div class="u8-row p14-row" role="option"><span class="u8-row-badge"></span><span class="u8-row-name"></span><span class="u8-row-sub"></span><button class="u8-mini p14-del" type="button" title="Delete">x</button></div>'),
    update: (n, i) => {
      setText(q(n, '.u8-row-badge'), i.badge);
      setText(q(n, '.u8-row-name'), i.name);
      setText(q(n, '.u8-row-sub'), i.sub);
      setClass(n, 'is-selected', !!i.selected);
      setClass(n, 'is-bad', !!i.bad);
      setHidden(q(n, '.p14-del'), !onDelete);
    },
  });
}

export interface DataTable { el: HTMLElement; set(head: string[], body: Array<Array<string | number | null>>, bad?: (row: number) => boolean): void }

export function dataTable(rows = 8): DataTable {
  const root = el('<div class="p14-tab" role="table"></div>');
  root.style.setProperty('--p14-rows', String(rows));
  const head = el('<div class="p14-tr is-head" role="row"></div>');
  const bodyHost = el('<div class="p14-tb"></div>');
  root.append(head, bodyHost);
  const heads: HTMLElement[] = [];
  const pool: HTMLElement[][] = [];
  const rowNodes: HTMLElement[] = [];
  let cols = 0;
  const fit = (c: number): void => {
    while (heads.length < c) { const h = el('<span role="columnheader"></span>'); heads.push(h); head.appendChild(h); }
    for (const r of pool) while (r.length < c) { const cell = el('<span role="cell"></span>'); r.push(cell); rowNodes[pool.indexOf(r)].appendChild(cell); }
    if (cols !== c) { cols = c; root.style.setProperty('--p14-cols', String(c)); }
  };
  return {
    el: root,
    set(h, body, bad) {
      fit(Math.max(1, h.length));
      heads.forEach((n, i) => { setText(n, h[i] ?? ''); setHidden(n, i >= h.length); });
      while (pool.length < body.length) { const r = el('<div class="p14-tr" role="row"></div>'); rowNodes.push(r); bodyHost.appendChild(r); pool.push([]); fit(cols); }
      pool.forEach((cells, ri) => {
        const row = rowNodes[ri];
        const data = body[ri];
        setHidden(row, !data);
        setClass(row, 'is-bad', !!data && !!bad?.(ri));
        cells.forEach((cell, ci) => { const v = data?.[ci]; const s = v === null || v === undefined ? '' : String(v); setText(cell, s); setHidden(cell, ci >= h.length); });
      });
    },
  };
}

export const mm = (v: unknown, d = 2): string => (typeof v === 'number' && Number.isFinite(v) ? String(Number(v.toFixed(d))) : '-');
export const sig = (v: unknown, d = 4): string => (typeof v === 'number' && Number.isFinite(v) ? String(Number(v.toPrecision(d))) : '-');
export const asArr = <T = Record<string, unknown>>(v: unknown): T[] => (Array.isArray(v) ? v as T[] : []);
