import { api, ApiError } from '../../io/api';
import type { CommandLineState } from '../../io/api';
import { docStore } from '../doc-store';
import { toast } from '../toast';

export interface StyleTables {
  textstyles: Array<Record<string, unknown>>;
  dimstyles: Array<{ name: string; vars: Record<string, unknown>; annotative?: boolean; description?: string }>;
  mleaderstyles: Array<Record<string, unknown>>;
  tablestyles: Array<Record<string, unknown>>;
  linetypes: Array<{ name: string }>;
  header: Record<string, unknown>;
  rev: number;
}

export type ExecState = CommandLineState & { result?: Record<string, unknown> };

export const activeDocId = (): string | null => docStore.activeId;

export function failure(e: unknown): string {
  return e instanceof ApiError || e instanceof Error ? e.message : 'The engine did not answer';
}

export const execError = { text: '' };

export async function exec(command: string, args: Record<string, unknown>, quiet = false): Promise<ExecState | null> {
  const id = docStore.activeId;
  execError.text = '';
  if (!id) return null;
  try {
    const state = await api.runCommand(id, command, args) as ExecState;
    document.dispatchEvent(new CustomEvent('formcad:command-state', { detail: { doc: id, state } }));
    if (state.error) {
      execError.text = state.error;
      if (!quiet) toast(state.error, 'error');
      return null;
    }
    return state;
  } catch (e) {
    execError.text = failure(e);
    if (!quiet) toast(execError.text, 'error');
    return null;
  }
}

export async function loadTables(): Promise<StyleTables | null> {
  const id = docStore.activeId;
  if (!id) return null;
  try {
    const snap = await api.snapshot(id, 2147483000) as unknown as { rev: number; tables: Record<string, unknown>; header?: Record<string, unknown> };
    const t = snap.tables;
    return {
      textstyles: (t.textstyles ?? []) as StyleTables['textstyles'],
      dimstyles: (t.dimstyles ?? []) as StyleTables['dimstyles'],
      mleaderstyles: (t.mleaderstyles ?? []) as StyleTables['mleaderstyles'],
      tablestyles: (t.tablestyles ?? []) as StyleTables['tablestyles'],
      linetypes: (t.linetypes ?? []) as StyleTables['linetypes'],
      header: snap.header ?? {},
      rev: snap.rev,
    };
  } catch (e) {
    toast(failure(e), 'error');
    return null;
  }
}

export function sendCommand(name: string): void {
  const id = docStore.activeId;
  if (!id) return;
  void api.sendInput(id, name).then((state) => {
    document.dispatchEvent(new CustomEvent('formcad:command-state', { detail: { doc: id, state } }));
  }).catch((e) => toast(failure(e), 'error'));
}

export function waitCommandEnd(): Promise<void> {
  return new Promise((resolve) => {
    const id = docStore.activeId;
    let started = false;
    const off = (): void => {
      document.removeEventListener('formcad:cmdline-applied', on);
      document.removeEventListener('formcad:command-state', on);
    };
    const on = (e: Event): void => {
      const d = (e as CustomEvent<{ doc: string; state: CommandLineState }>).detail;
      if (!d || d.doc !== id) return;
      if (d.state.active) { started = true; return; }
      if (started) { off(); resolve(); }
    };
    document.addEventListener('formcad:cmdline-applied', on);
    document.addEventListener('formcad:command-state', on);
    window.setTimeout(() => { if (!started) { off(); resolve(); } }, 4000);
  });
}
