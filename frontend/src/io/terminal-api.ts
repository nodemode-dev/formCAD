import { call, token } from './api';

export type TermKind = 'shell' | 'claude' | 'codex' | 'cursor' | 'antigravity';
export interface TermRecord { id: string; title: string; alive: boolean; kind: TermKind; tip?: string }
export interface ProgramStatus { installed: boolean; version: string | null; install: string; signedIn: boolean | null; title?: string; note?: string }
export interface AgentReport { contract?: string; claude?: ProgramStatus; codex?: ProgramStatus; cursor?: ProgramStatus; antigravity?: ProgramStatus }
export interface TermOpen { cols: number; rows: number; prompt?: string; resume?: string }

const enc = encodeURIComponent;

export function termSocket(id: string): WebSocket {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  const tok = token();
  return new WebSocket(`${scheme}://${location.host}/api/terminal/${enc(id)}/stream${tok ? `?token=${enc(tok)}` : ''}`);
}

export const terminalApi = {
  list: async (): Promise<TermRecord[]> => (await call<{ terminals: TermRecord[] }>('GET', '/api/terminal')).terminals,
  openShell: (cols: number, rows: number): Promise<TermRecord> => call('POST', '/api/terminal', { cols, rows }),
  openAgent: (kind: Exclude<TermKind, 'shell'>, o: TermOpen): Promise<TermRecord> =>
    call('POST', '/api/terminal/agent', { kind, cols: o.cols, rows: o.rows, ...(o.prompt ? { prompt: o.prompt } : {}), ...(o.resume ? { resume: o.resume } : {}) }),
  restart: async (id: string): Promise<void> => { await call('POST', `/api/terminal/${enc(id)}/restart`); },
  close: async (id: string): Promise<void> => { await call('DELETE', `/api/terminal/${enc(id)}`); },
  status: (): Promise<AgentReport> => call('GET', '/api/agents/status'),
};
