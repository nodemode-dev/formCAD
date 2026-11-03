import { docStore } from '../ui/doc-store';
import { el, q, setClass, setText, store, stored } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { req, text, docUrl } from '../u8/net';
import { section as baseSection } from '../u8/ui';

export { req, text, docUrl };
export { reportBox, progressBar, num, fixed } from '../p11/kit';
export type { Json, ReportBox, Bar } from '../p11/kit';

const FOLD_KEY = 'formCAD.p12.folds';
const OPEN_FIRST = new Set(['Setups', 'Operations', 'Tool library', 'Simulation', 'Post and export', 'Plates', 'Slicer profile', 'Layer preview', 'Parts and sheets', 'Nest result', 'Slice and export']);

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

export const activeDoc = (): string | null => docStore.activeId;

export async function guard<T>(fn: () => Promise<T>): Promise<T | null> {
  try { return await fn(); } catch (e) { toast(text(e), 'error'); return null; }
}

export const camUrl = (tail = ''): string => `/api/cam${tail}`;
export const docCam = (tail = ''): string => docUrl(docStore.activeId ?? '', `cam${tail}`);
export const docAdd = (tail = ''): string => docUrl(docStore.activeId ?? '', `additive${tail}`);

export function mini(label: string, title: string, on: () => void): HTMLButtonElement {
  const b = el<HTMLButtonElement>('<button class="u8-mini" type="button"></button>');
  b.textContent = label;
  b.title = t(title);
  b.addEventListener('click', (e) => { e.stopPropagation(); on(); });
  return b;
}

export function fillSelect(sel: HTMLSelectElement, rows: ReadonlyArray<readonly [string, string]>): void {
  const sig = rows.map((r) => r.join('\u0001')).join('\u0002');
  if (sel.dataset.sig === sig) return;
  sel.dataset.sig = sig;
  const keep = sel.value;
  const have = new Map(Array.from(sel.options).map((o) => [o.value, o]));
  const want = new Set(rows.map((r) => r[0]));
  for (const [v, o] of have) if (!want.has(v)) o.remove();
  let cursor: Element | null = sel.firstElementChild;
  for (const [v, label] of rows) {
    let o = have.get(v);
    if (!o) { o = document.createElement('option'); o.value = v; }
    if (o.textContent !== label) o.textContent = label;
    if (o !== cursor) sel.insertBefore(o, cursor); else cursor = cursor.nextElementSibling;
  }
  if (want.has(keep)) sel.value = keep;
}

export const dash = '-';

export function secs(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return dash;
  const s = Math.round(v);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h} h ${String(m).padStart(2, '0')} min` : m ? `${m} min ${String(r).padStart(2, '0')} s` : `${r} s`;
}

export function b64f32(s: string): Float32Array {
  if (!s) return new Float32Array(0);
  const bin = atob(s);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return new Float32Array(buf.buffer, 0, Math.floor(buf.length / 4));
}

export function b64u8(s: string): Uint8Array {
  if (!s) return new Uint8Array(0);
  const bin = atob(s);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return buf;
}

export { q, setText };
