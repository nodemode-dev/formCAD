import { api, ApiError, call, token, type CommandLineState } from './api';

const enc = encodeURIComponent;
const LONG_MS = 400000;

async function slow<T>(path: string, body: unknown): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const tok = token();
  if (tok) headers['X-FormCAD-Token'] = tok;
  const ctl = new AbortController();
  const timer = window.setTimeout(() => ctl.abort(), LONG_MS);
  let res: Response;
  try {
    res = await fetch(path, { method: 'POST', headers, body: JSON.stringify(body), signal: ctl.signal });
  } catch {
    throw new ApiError(0, 'The engine did not answer');
  } finally {
    window.clearTimeout(timer);
  }
  if (!res.ok) {
    let message = res.statusText || `Request failed (${res.status})`;
    try { const d = await res.json() as { detail?: unknown }; if (typeof d.detail === 'string') message = d.detail; } catch { message = res.statusText || message; }
    throw new ApiError(res.status, message);
  }
  return await res.json() as T;
}

export interface LispResult { value: string; lines: string[]; error: string; finished?: boolean }
export interface AppLoadResult { file: string; loaded: boolean; commands: string[]; value: string; lines: string[]; error: string }
export interface ScriptInfo { name: string; line: number; lines: number; state: string; repeat: boolean; iteration: number; note: string }
export interface AliasRow { alias: string; command: string; note: string }
export interface AliasList { file: string; builtin: AliasRow[]; user: AliasRow[]; limit: number; aliasLength: number }
export interface MacroStatus { recording: boolean; name: string; steps: number; lines: string[] }
export interface MacroFile { name: string; size: number; modified: number }
export interface McpClientConfig { addLine: string; mcpJson: string; desktopJson: string }
export interface AutomationStatus {
  mcp: { tools: number; protocols: string[]; httpEndpoint: string; tokenHeader: string; tokenFile: string; headless: McpClientConfig; live: McpClientConfig };
  control: { enabled: boolean; error: string; [key: string]: unknown };
  plugins: number;
  macros: number;
}
export interface PluginRow {
  id: string; name: string; version: string; description: string; tier: string; path?: string; permissions: string[]; problems: string[];
  enabled: boolean; state: 'disabled' | 'enabled' | 'loaded' | 'mismatch' | 'invalid' | 'failed'; error: string; commands: string[]; manifestSha256?: string; files?: unknown;
}
export interface MacroGrants { network: boolean; subprocess: boolean; native: boolean; files: string[] }
export interface PyMacro { path: string; name: string; sha256: string; trusted: boolean; changedSinceTrust: boolean; grants: Partial<MacroGrants> }
export interface PyMacroSource extends PyMacro { source: string }
export interface PyMacroRun { ok: boolean; exit: number; timedOut: boolean; seconds: number; stdout: string; stderr: string }

async function viaCommand<T>(id: string, name: string, args: Record<string, unknown>): Promise<T> {
  const state: CommandLineState & { result?: T } = await api.runCommand(id, name, args);
  if (state.result !== undefined) return state.result;
  if (state.error) throw new Error(state.error);
  return {} as T;
}

export const auto = {
  lisp: (id: string, code: string): Promise<LispResult> => viaCommand<LispResult>(id, 'lisp', { code }),
  appload: (id: string, path: string): Promise<AppLoadResult> => viaCommand<AppLoadResult>(id, 'appload', { path }),
  support: (_id: string): Promise<{ folders: string[] }> => call('GET', '/api/automation/lisp-support'),
  setSupport: (_id: string, folders: string[]): Promise<{ folders: string[] }> => call('PUT', '/api/automation/lisp-support', { folders }),
  loaded: (id: string): Promise<{ loaded: string[] }> => viaCommand(id, 'lisp', { action: 'loaded' }),
  commands: (id: string): Promise<{ commands: string[] }> => viaCommand(id, 'lisp', { action: 'commands' }),

  runScript: (id: string, body: { path?: string; data?: string; repeat?: boolean; times?: number }): Promise<{ result: unknown }> => slow(`/api/docs/${enc(id)}/script`, body),
  scriptInfo: (id: string): Promise<{ script: ScriptInfo | null }> => call('GET', `/api/docs/${enc(id)}/script`),
  resumeScript: (id: string): Promise<unknown> => call('POST', `/api/docs/${enc(id)}/script/resume`, {}),
  stopScript: (id: string): Promise<unknown> => call('POST', `/api/docs/${enc(id)}/script/stop`, {}),

  aliases: (): Promise<AliasList> => call('GET', '/api/aliases'),
  suggest: (text: string): Promise<{ items: string[] }> => call('GET', `/api/aliases/suggest?text=${enc(text)}`),
  replaceAliases: (aliases: Record<string, string>): Promise<unknown> => call('PUT', '/api/aliases', { aliases }),
  loadAliases: (path: string): Promise<{ count: number; file: string; warnings: string[]; message: string }> => call('POST', '/api/aliases/load', { path }),
  saveAliases: (path: string): Promise<{ path: string }> => call('POST', '/api/aliases/save', { path }),
  reinit: (): Promise<unknown> => call('POST', '/api/aliases/reinit', {}),
  clearAliases: (): Promise<unknown> => call('POST', '/api/aliases/clear', {}),

  macroStatus: (id: string): Promise<MacroStatus> => call('GET', `/api/docs/${enc(id)}/macro`),
  macroStart: (id: string, name: string): Promise<unknown> => call('POST', `/api/docs/${enc(id)}/macro/start`, { name }),
  macroStop: (id: string): Promise<{ result: { name: string; steps: number; lines: string[] } }> => call('POST', `/api/docs/${enc(id)}/macro/stop`, {}),
  macroPlay: (id: string, path: string): Promise<unknown> => call('POST', `/api/docs/${enc(id)}/macro/play`, { path }),
  macroSave: (id: string, path: string, format: string): Promise<{ result: { path: string } }> => call('POST', `/api/docs/${enc(id)}/macro/save`, { path, format }),
  macroFiles: (): Promise<{ items: MacroFile[] }> => call('GET', '/api/macros'),

  status: (): Promise<AutomationStatus> => call('GET', '/api/automation/status'),
  plugins: (): Promise<{ folder: string; api: number; plugins: PluginRow[] }> => call('GET', '/api/automation/plugins'),
  enablePlugin: (id: string, enabled: boolean, manifestSha256: string): Promise<PluginRow> => call('POST', `/api/automation/plugins/${enc(id)}/enable`, { enabled, manifestSha256 }),
  pyMacros: (): Promise<{ folder: string; macros: PyMacro[]; limits: Record<string, number> }> => call('GET', '/api/automation/macros'),
  pyMacroSource: (path: string): Promise<PyMacroSource> => call('GET', `/api/automation/macros/source?path=${enc(path)}`),
  trustMacro: (path: string, trusted: boolean, grants: Partial<MacroGrants>, sha256: string): Promise<PyMacro> => call('POST', '/api/automation/macros/trust', { path, trusted, grants, sha256 }),
  runMacro: (path: string, document: string): Promise<PyMacroRun> => slow('/api/automation/macros/run', { path, document }),
};
