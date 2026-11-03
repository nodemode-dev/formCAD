import { token } from '../io/api';

export class EngineError extends Error {
  constructor(readonly status: number, message: string, readonly detail: unknown) {
    super(message);
    this.name = 'EngineError';
  }
}

const enc = encodeURIComponent;
export const docUrl = (id: string, tail: string): string => `/api/docs/${enc(id)}/${tail}`;

function headers(json: boolean): Record<string, string> {
  const h: Record<string, string> = {};
  const tok = token();
  if (tok) h['X-FormCAD-Token'] = tok;
  if (json) h['Content-Type'] = 'application/json';
  return h;
}

function messageOf(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object') {
    const m = (detail as { message?: unknown }).message;
    if (typeof m === 'string') return m;
  }
  return fallback;
}

async function fail(res: Response): Promise<never> {
  let detail: unknown = null;
  try { detail = ((await res.json()) as { detail?: unknown }).detail ?? null; } catch { detail = null; }
  throw new EngineError(res.status, messageOf(detail, res.statusText || `Request failed (${res.status})`), detail);
}

export async function req<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { method, headers: headers(body !== undefined), body: body === undefined ? undefined : JSON.stringify(body), signal });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new EngineError(0, 'The engine is not reachable', null);
  }
  if (!res.ok) return fail(res);
  if (res.status === 204) return undefined as T;
  return await res.json() as T;
}

export async function buffer(path: string): Promise<ArrayBuffer | null> {
  let res: Response;
  try {
    res = await fetch(path, { headers: headers(false) });
  } catch {
    throw new EngineError(0, 'The engine is not reachable', null);
  }
  if (res.status === 404) return null;
  if (!res.ok) return fail(res);
  return await res.arrayBuffer();
}

export const text = (e: unknown, fallback = 'The request failed'): string => (e instanceof Error && e.message ? e.message : fallback);
