import { setClass, store, stored } from '../ui/dom';
import { toast } from '../ui/toast';
import { text } from '../u8/net';
import { section as baseSection } from '../u8/ui';

export { reportBox, progressBar, num, fixed } from '../p11/kit';
export { fillSelect, mini } from '../p12/kit';
export type { ReportBox, Bar } from '../p11/kit';

const FOLD_KEY = 'formCAD.p13.folds';
const OPEN_FIRST = new Set(['Studies', 'Selected item', 'Mesh and run', 'Plot', 'Probes']);

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

export const SI = (v: number, unit: string): string => {
  if (!Number.isFinite(v)) return '-';
  const a = Math.abs(v);
  const s = a !== 0 && (a >= 1e5 || a < 1e-3) ? v.toExponential(3) : String(Number(v.toPrecision(5)));
  return unit ? `${s} ${unit}` : s;
};
