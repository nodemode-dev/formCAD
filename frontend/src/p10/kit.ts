import { api } from '../io/api';
import { events } from '../io/events';
import { docStore } from '../ui/doc-store';
import { el, q, setClass, setStyleVar, setText, store, stored } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { req, text, docUrl } from '../u8/net';
import { section as baseSection } from '../u8/ui';

export { req, text, docUrl };

export type Json = Record<string, unknown>;

const OPEN_FIRST = new Set(['Form', 'New form','Mesh objects', 'Notes in this part', 'Rule', 'Selection', 'Result', 'New note', 'Checks', 'Last file report']);
const FOLD_KEY = 'formCAD.p10.folds';

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

let lastError = '';
export const lastCmdError = (): string => lastError;

export async function runCmd<T = Json>(command: string, args: Json = {}): Promise<T | null> {
  const id = docStore.activeId;
  lastError = '';
  if (!id) return null;
  try {
    const state = await api.runCommand(id, command, args);
    if (state.error) { lastError = state.error; toast(state.error, 'error'); return null; }
    return ((state as unknown as { result?: T }).result ?? ({} as T));
  } catch (e) {
    lastError = text(e);
    toast(lastError, 'error');
    return null;
  }
}

export const num = (v: unknown, d = 0): number => (typeof v === 'number' && Number.isFinite(v) ? v : d);

export function fixed(v: number | null | undefined, digits = 3): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '-';
  if (v === 0) return '0';
  return Math.abs(v) >= 1e6 || Math.abs(v) < 1e-3 ? v.toExponential(2) : String(Number(v.toPrecision(digits + 3)));
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

export interface JobBar { el: HTMLElement; busy(): boolean }

export function jobBar(commands: string[], cancelUrl: (id: string) => string): JobBar {
  const root = el('<div class="xw-job is-idle"><div class="xw-job-top"><span class="xw-job-phase"></span><button class="u8-btn xw-job-cancel" type="button"></button></div><div class="xw-bar"><span class="xw-fill"></span></div></div>');
  const phase = q(root, '.xw-job-phase');
  const fill = q(root, '.xw-fill');
  const cancel = q<HTMLButtonElement>(root, '.xw-job-cancel');
  setText(cancel, t('Cancel'));
  let on = false;
  cancel.addEventListener('click', () => {
    const id = docStore.activeId;
    if (id) void req('POST', cancelUrl(id), {}).catch(() => undefined);
  });
  events.on('meshjob', (e) => {
    if (e.id !== docStore.activeId || !commands.includes(e.command)) return;
    on = e.state !== 'end';
    setClass(root, 'is-idle', !on);
    setText(phase, `${e.command} · ${e.phase ?? e.message ?? ''}`);
    setStyleVar(fill as HTMLElement, '--xw-p', String(Math.round(Math.max(0, Math.min(1, e.progress ?? 0)) * 100)));
  });
  return { el: root, busy: () => on };
}
