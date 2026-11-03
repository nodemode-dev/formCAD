import { el, q, setClass, setText, store, stored } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { text } from '../u8/net';
import { section as baseSection } from '../u8/ui';

export { reportBox, progressBar, fixed } from '../p11/kit';
export type { ReportBox, Bar } from '../p11/kit';
export { button, buttons, checkCtl, numberCtl, selectCtl, readout } from '../u8/ui';
export { fillSelect } from '../p12/kit';

const FOLD_KEY = 'formCAD.p14b.folds';
const OPEN_FIRST = new Set(['Sheets', 'Place', 'Selected part', 'ERC', 'Board', 'Layers and tools', 'Selected item', 'Rules and DRC', 'Autorouter', 'Fabrication files', 'Enclosure link', 'Netlist and BOM']);

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

export function textField(label: string, value = '', onChange?: (v: string) => void): { el: HTMLElement; input: HTMLInputElement; get(): string; set(v: string): void } {
  const root = el('<label class="cv-field"><span></span><input class="cv-input" type="text" spellcheck="false" autocomplete="off"></label>');
  setText(q(root, 'span'), t(label));
  const input = q<HTMLInputElement>(root, 'input');
  input.value = value;
  input.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); input.blur(); } });
  input.addEventListener('change', () => onChange?.(input.value));
  return { el: root, input, get: () => input.value.trim(), set: (v) => { if (input.value !== v && document.activeElement !== input) input.value = v; } };
}

export const num = (v: unknown, d = 0): number => (typeof v === 'number' && Number.isFinite(v) ? v : d);
export const dirOf = (p: string | null | undefined): string => (p ? p.replace(/[\\/][^\\/]*$/, '') : '');
