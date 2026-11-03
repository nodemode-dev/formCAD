import { docStore } from '../ui/doc-store';
import { el, q, setClass, setText, store, stored } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { req, text, docUrl } from '../u8/net';
import { section as baseSection } from '../u8/ui';

export { req, text, docUrl };

export type Json = Record<string, unknown>;

const FOLD_KEY = 'formCAD.p11.folds';
const OPEN_FIRST = new Set(['Joints', 'New joint', 'Study', 'Timeline', 'Run', 'This document', 'History', 'Conflicts']);

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

export const num = (v: unknown, d = 0): number => (typeof v === 'number' && Number.isFinite(v) ? v : d);

export function fixed(v: number | null | undefined, digits = 3): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '-';
  if (v === 0) return '0';
  return Math.abs(v) >= 1e6 || Math.abs(v) < 1e-3 ? v.toExponential(2) : String(Number(v.toPrecision(digits + 3)));
}

export async function guard<T>(fn: () => Promise<T>): Promise<T | null> {
  try { return await fn(); } catch (e) { toast(text(e), 'error'); return null; }
}

export interface ReportBox { el: HTMLElement; set(lines: string[], bad?: boolean): void }

export function reportBox(rows: number): ReportBox {
  const root = el('<div class="xw-report" role="status" aria-live="polite"></div>');
  const nodes: HTMLElement[] = [];
  for (let i = 0; i < rows; i++) { const n = el('<div class="xw-line"></div>'); root.appendChild(n); nodes.push(n); }
  root.style.setProperty('--xw-rows', String(rows));
  return {
    el: root,
    set(lines, bad = false) {
      setClass(root, 'is-bad', bad);
      nodes.forEach((n, i) => { setText(n, lines[i] ?? ''); if (n.title !== (lines[i] ?? '')) n.title = lines[i] ?? ''; });
    },
  };
}

export interface Bar { el: HTMLElement; set(fraction: number, label: string, on: boolean): void; onCancel(fn: () => void): void }

export function progressBar(): Bar {
  const root = el('<div class="xw-job is-idle"><div class="xw-job-top"><span class="xw-job-phase"></span><button class="u8-btn xw-job-cancel" type="button"></button></div><div class="xw-bar"><span class="xw-fill"></span></div></div>');
  const phase = q(root, '.xw-job-phase');
  const fill = q(root, '.xw-fill');
  const cancel = q<HTMLButtonElement>(root, '.xw-job-cancel');
  setText(cancel, t('Cancel'));
  let handler: () => void = () => undefined;
  cancel.addEventListener('click', () => handler());
  return {
    el: root,
    set(fraction, label, on) {
      setClass(root, 'is-idle', !on);
      setText(phase, label);
      const p = String(Math.round(Math.max(0, Math.min(1, fraction)) * 100));
      if ((fill as HTMLElement).style.getPropertyValue('--xw-p') !== p) (fill as HTMLElement).style.setProperty('--xw-p', p);
    },
    onCancel(fn) { handler = fn; },
  };
}

export const vault = (tail = ''): string => `/api/vault${tail}`;

export const isoTime = (s: number | null | undefined): string => {
  if (!s) return '-';
  const d = new Date(s * 1000);
  const p = (n: number): string => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

export const bytes = (n: number | null | undefined): string => {
  if (n === null || n === undefined) return '-';
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
};
