import type { DisplayItem, DisplayPayload } from '../canvas/types';

export interface Health { ok: boolean; version: string }

export interface KernelInfo { available: boolean; version: string | null; path: string | null; source: string | null }
export interface Capabilities {
  version: string;
  platform: string;
  dataDir: string;
  dataDirSource: string;
  kernel: KernelInfo;
  desktop: boolean;
}

export interface CommandMeta { name: string; aliases: string[]; group: string; label: string; description: string; menu: string }
export interface SysVar { name: string; value: unknown; type: string; scope: string; readonly: boolean; description: string; default?: unknown; range?: string; profile?: boolean }

export interface DocSummary { id: string; name: string; path: string | null; modified: string; rev: number; kind: string; created?: number | string; dirty: boolean; untitled?: boolean; entities?: number; metric?: boolean; space?: string }
export interface DocCreate { name?: string; template?: string }

export interface PromptOption { key: string; label: string }
export interface CommandLineState {
  active: boolean;
  prompt: string;
  options: PromptOption[];
  defaultValue: string | null;
  history: string[];
  rev: number;
  command?: string;
  kind?: string;
  error?: string;
  historySize?: number;
  transparent?: boolean;
  expect?: 'point' | 'distance' | 'angle' | 'selection' | 'entity' | 'keyword' | 'text' | 'number' | 'none';
  base?: [number, number] | null;
  preview?: boolean;
  accepts?: string[];
  snapOverride?: string | null;
  selection?: Array<string | number>;
  suspended?: string | null;
}

export interface SnapPayload { mode: string; handle: string | number | null; at: [number, number]; aperture?: number }
export type CanvasInput =
  | { point: [number, number]; snap?: SnapPayload }
  | { pick: { point: [number, number]; handle: string | number } }
  | { selection: { handles: Array<string | number>; mode: 'set' | 'add' | 'remove' } };
export interface GripRequest {
  handle: string | number;
  grip: string | number;
  mode: 'stretch' | 'move' | 'rotate' | 'scale' | 'mirror';
  to: [number, number];
  base?: [number, number];
  copy?: boolean;
  preview?: boolean;
  option?: string;
  value?: number;
  more?: Array<[number, number]>;
}

export type EntityRecord = { id: string; type: string; [key: string]: unknown };
export interface Snapshot { rev: number; entities: EntityRecord[]; removed: string[]; tables: Record<string, unknown> }

export interface FileItem { name: string; path: string; size: number; modified: number | string; kind: string }
export interface KernelStatus { available: boolean; version: string | null; installing: boolean; progress: number; message: string }
export interface UndoResult { rev: number; label: string }

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

let cachedToken = '';

export function token(): string {
  if (cachedToken) return cachedToken;
  const meta = document.querySelector<HTMLMetaElement>('meta[name="formcad-token"]');
  cachedToken = meta?.content ?? '';
  return cachedToken;
}

const TIMEOUT_MS = 30000;

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const tok = token();
  if (tok) headers['X-FormCAD-Token'] = tok;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const ctl = new AbortController();
  const timer = window.setTimeout(() => ctl.abort(), TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal: ctl.signal });
  } catch (e) {
    throw new ApiError(0, e instanceof DOMException && e.name === 'AbortError' ? 'The engine did not answer in time' : 'The engine is not reachable');
  } finally {
    window.clearTimeout(timer);
  }
  if (!res.ok) {
    let message = res.statusText || `Request failed (${res.status})`;
    try {
      const data = await res.json() as { detail?: unknown; message?: unknown };
      if (typeof data.detail === 'string') message = data.detail;
      else if (typeof data.message === 'string') message = data.message;
    } catch {
      message = res.statusText || message;
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return await res.json() as T;
}

const enc = encodeURIComponent;
const list = (path: string): Promise<{ items: FileItem[] }> => call('GET', path);

export const api = {
  health: (): Promise<Health> => call('GET', '/api/health'),
  capabilities: (): Promise<Capabilities> => call('GET', '/api/capabilities'),
  commands: (): Promise<{ commands: CommandMeta[] }> => call('GET', '/api/commands'),
  sysvars: (): Promise<{ vars: SysVar[] }> => call('GET', '/api/sysvars'),
  setSysvar: (name: string, value: unknown, doc?: string): Promise<{ name: string; value: unknown }> => call('PUT', `/api/sysvars/${enc(name)}`, doc === undefined ? { value } : { doc, value }),

  docs: (): Promise<{ docs: DocSummary[]; active?: string | null }> => call('GET', '/api/docs'),
  createDoc: (req: DocCreate = {}): Promise<DocSummary> => call('POST', '/api/docs', req),
  openDoc: (path: string): Promise<DocSummary> => call('POST', '/api/docs/open', { path }),
  saveDoc: (id: string, path?: string): Promise<DocSummary> => call('POST', `/api/docs/${enc(id)}/save`, path === undefined ? {} : { path }),
  closeDoc: (id: string, force = false): Promise<{ closed: boolean }> => call('POST', `/api/docs/${enc(id)}/close`, { force }),
  undo: (id: string, steps?: number): Promise<UndoResult> => call('POST', `/api/docs/${enc(id)}/undo`, steps === undefined ? {} : { steps }),
  redo: (id: string, steps?: number): Promise<UndoResult> => call('POST', `/api/docs/${enc(id)}/redo`, steps === undefined ? {} : { steps }),
  snapshot: (id: string, since?: number): Promise<Snapshot> => call('GET', `/api/docs/${enc(id)}/snapshot${since === undefined ? '' : `?since=${since}`}`),

  display: (id: string, since?: number, space?: string): Promise<DisplayPayload> => {
    const q = [since === undefined ? '' : `since=${since}`, space ? `space=${encodeURIComponent(space)}` : ''].filter(Boolean).join('&');
    return call('GET', `/api/docs/${enc(id)}/display${q ? `?${q}` : ''}`);
  },

  sendInput: (id: string, text: string): Promise<CommandLineState> => call('POST', `/api/docs/${enc(id)}/input`, { text }),
  runCommand: (id: string, command: string, args?: Record<string, unknown>): Promise<CommandLineState> => call('POST', `/api/docs/${enc(id)}/command`, args === undefined ? { command } : { command, args }),
  cancelCommand: (id: string): Promise<CommandLineState> => call('POST', `/api/docs/${enc(id)}/cancel`),
  sendCanvasInput: (id: string, body: CanvasInput): Promise<CommandLineState> => call('POST', `/api/docs/${enc(id)}/input`, body),
  preview: (id: string, point: [number, number], snap?: SnapPayload): Promise<{ items: DisplayItem[] }> => call('POST', `/api/docs/${enc(id)}/preview`, snap ? { point, snap } : { point }),
  gripSets: (id: string, handles: Array<string | number>): Promise<{ sets: Array<{ h: string | number; grips: Array<{ id: string | number; p: [number, number]; kind?: string }> }> }> => call('GET', `/api/docs/${enc(id)}/grips?handles=${handles.join(',')}`),
  getSelection: (id: string): Promise<{ handles: Array<string | number>; pickfirst: boolean; rev: number }> => call('GET', `/api/docs/${enc(id)}/selection`),
  putSelection: (id: string, handles: Array<string | number>, mode: 'set' | 'add' | 'remove' = 'set'): Promise<{ handles: Array<string | number>; pickfirst: boolean; rev: number }> => call('PUT', `/api/docs/${enc(id)}/selection`, { handles, mode }),
  grip: (id: string, body: GripRequest): Promise<{ items?: DisplayItem[]; rev?: number; label?: string; handles?: Array<string | number> }> => call('POST', `/api/docs/${enc(id)}/grip`, body),

  recent: (): Promise<{ items: FileItem[] }> => list('/api/recent'),
  library: (): Promise<{ items: FileItem[] }> => list('/api/library'),
  outputs: (): Promise<{ items: FileItem[] }> => list('/api/outputs'),

  kernelStatus: (): Promise<KernelStatus> => call('GET', '/api/kernel/status'),
  kernelInstall: (): Promise<KernelStatus> => call('POST', '/api/kernel/install'),
};
