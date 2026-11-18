export interface Exchange {
  seq: number;
  t: number;
  phase: string;
  method: string;
  path: string;
  query: string;
  body: string | null;
  status: number;
  type: string;
  response: number | null;
  encoding: 'text' | 'base64';
  error?: string;
}

export interface Frame { t: number; phase: string; data: string }

export interface Recording {
  format: 'formcad-replay';
  version: number;
  recorded: string;
  engine: string;
  document: { file: string; id: string; name: string };
  window?: { width: number; height: number };
  steps?: string[];
  exchanges: Exchange[];
  responses: string[];
  frames: Frame[];
}

export interface ReplayRequest { method: string; path: string; query: string; body: string | null }

export interface ReplayOptions {
  message?: string;
  status?: number;
  reads?: RegExp[];
  local?: (req: ReplayRequest) => unknown;
  frames?: 'boot' | 'all' | 'none';
}

export interface ReplayHandle {
  readonly misses: ReplayRequest[];
  restore(): void;
}

export const DESKTOP_ONLY = 'This is a browser demo. The desktop app does this.';

const DEFAULT_READS: RegExp[] = [
  /\/preview$/,
  /\/find$/,
  /\/qselect$/,
  /^\/api\/calc$/,
  /\/dimstyle-preview$/,
  /\/grid$/,
];

const stable = (v: unknown): unknown => {
  if (Array.isArray(v)) return v.map(stable);
  if (v && typeof v === 'object') {
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(v as Record<string, unknown>).sort()) out[k] = stable((v as Record<string, unknown>)[k]);
    return out;
  }
  return v;
};

const normBody = (body: string | null): string => {
  if (body === null || body === '') return '';
  try { return JSON.stringify(stable(JSON.parse(body))); } catch { return body; }
};

const normQuery = (query: string): string => {
  const p = new URLSearchParams(query);
  p.delete('token');
  return [...p.entries()].sort(([a, x], [b, y]) => (a === b ? (x < y ? -1 : x > y ? 1 : 0) : a < b ? -1 : 1)).map(([k, v]) => `${k}=${v}`).join('&');
};

const normPath = (path: string): string => {
  try { return decodeURIComponent(path); } catch { return path; }
};

const keyOf = (r: ReplayRequest): string => `${r.method.toUpperCase()} ${normPath(r.path)}?${normQuery(r.query)}#${normBody(r.body)}`;

const json = (body: unknown, status = 200): Response => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const decode = (b64: string): Uint8Array<ArrayBuffer> => {
  const bin = atob(b64);
  const out = new Uint8Array(new ArrayBuffer(bin.length));
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
};

function selectionState(rec: Recording): (req: ReplayRequest) => unknown {
  const held = new Map<string, Array<string | number>>();
  let rev = 0;
  for (const e of rec.exchanges) if (e.path.endsWith('/selection') && e.response !== null) {
    try { rev = Number((JSON.parse(rec.responses[e.response]) as { rev?: number }).rev) || rev; } catch { rev = rev || 0; }
  }
  return (req) => {
    const m = /^\/api\/docs\/([^/]+)\/selection$/.exec(normPath(req.path));
    if (!m) return undefined;
    const doc = m[1];
    if (req.method === 'GET') return held.has(doc) ? { handles: held.get(doc), pickfirst: true, rev } : undefined;
    if (req.method !== 'PUT') return undefined;
    let ask: { handles?: Array<string | number>; mode?: string } = {};
    try { ask = JSON.parse(req.body ?? '{}') as typeof ask; } catch { ask = {}; }
    const now = new Set(ask.mode === 'set' || !ask.mode ? [] : held.get(doc) ?? []);
    for (const h of ask.handles ?? []) { if (ask.mode === 'remove') now.delete(h); else now.add(h); }
    held.set(doc, [...now]);
    return { handles: [...now], pickfirst: true, rev };
  };
}

export function installReplay(recording: Recording, options: ReplayOptions = {}): ReplayHandle {
  const message = options.message ?? DESKTOP_ONLY;
  const status = options.status ?? 503;
  const reads = [...DEFAULT_READS, ...(options.reads ?? [])];
  const select = selectionState(recording);
  const table = new Map<string, Exchange[]>();
  const cursor = new Map<string, number>();
  for (const e of recording.exchanges) {
    if (e.error && e.response === null) continue;
    const k = keyOf(e);
    const list = table.get(k);
    if (list) list.push(e); else table.set(k, [e]);
  }
  const misses: ReplayRequest[] = [];

  const play = (e: Exchange): Response => {
    if (e.status === 204 || e.response === null) return new Response(null, { status: e.status === 200 ? 204 : e.status });
    const raw = recording.responses[e.response];
    const body = e.encoding === 'base64' ? decode(raw) : raw;
    return new Response(body, { status: e.status, headers: { 'Content-Type': e.type || 'application/json' } });
  };

  const answer = (req: ReplayRequest): Response => {
    const own = options.local?.(req);
    if (own !== undefined) return own instanceof Response ? own : json(own);
    const sel = select(req);
    if (sel !== undefined) return json(sel);
    const readable = req.method === 'GET' || req.method === 'HEAD' || reads.some((r) => r.test(normPath(req.path)));
    if (readable) {
      const k = keyOf(req);
      const list = table.get(k);
      if (list) {
        const at = cursor.get(k) ?? 0;
        cursor.set(k, at + 1);
        return play(list[Math.min(at, list.length - 1)]);
      }
    }
    misses.push(req);
    return json({ detail: message }, status);
  };

  const nativeFetch = window.fetch.bind(window);
  const apiPath = (raw: string): URL | null => {
    let u: URL;
    try { u = new URL(raw, location.href); } catch { return null; }
    return u.pathname === '/api' || u.pathname.startsWith('/api/') ? u : null;
  };

  const replayFetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const u = apiPath(raw);
    if (!u) return nativeFetch(input, init);
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    let body: string | null = null;
    const given = init?.body ?? null;
    if (typeof given === 'string') body = given;
    else if (given instanceof URLSearchParams) body = given.toString();
    else if (given !== null) body = '[binary]';
    else if (input instanceof Request && method !== 'GET' && method !== 'HEAD') body = await input.clone().text();
    if (init?.signal?.aborted) throw new DOMException('The operation was aborted.', 'AbortError');
    await Promise.resolve();
    return answer({ method, path: u.pathname, query: u.search.replace(/^\?/, ''), body });
  };
  window.fetch = replayFetch as typeof window.fetch;

  const pick = options.frames ?? 'boot';
  const frames = pick === 'none' ? [] : recording.frames.filter((f) => pick === 'all' || f.phase === 'boot');

  class ReplaySocket extends EventTarget {
    static readonly CONNECTING = 0;
    static readonly OPEN = 1;
    static readonly CLOSING = 2;
    static readonly CLOSED = 3;
    readonly CONNECTING = 0;
    readonly OPEN = 1;
    readonly CLOSING = 2;
    readonly CLOSED = 3;
    readyState = 0;
    binaryType: BinaryType = 'blob';
    bufferedAmount = 0;
    extensions = '';
    protocol = '';
    onopen: ((e: Event) => void) | null = null;
    onclose: ((e: CloseEvent) => void) | null = null;
    onerror: ((e: Event) => void) | null = null;
    onmessage: ((e: MessageEvent) => void) | null = null;
    constructor(readonly url: string) {
      super();
      window.setTimeout(() => {
        if (this.readyState !== 0) return;
        this.readyState = 1;
        this.fire(new Event('open'));
        let i = 0;
        const next = (): void => {
          if (this.readyState !== 1 || i >= frames.length) return;
          this.fire(new MessageEvent('message', { data: frames[i++].data }));
          window.setTimeout(next, 0);
        };
        window.setTimeout(next, 50);
      }, 0);
    }
    private fire(e: Event): void {
      const own = (this as unknown as Record<string, unknown>)[`on${e.type}`];
      if (typeof own === 'function') (own as (ev: Event) => void).call(this, e);
      this.dispatchEvent(e);
    }
    send(): void { return; }
    close(): void {
      if (this.readyState >= 2) return;
      this.readyState = 3;
      this.fire(new CloseEvent('close', { code: 1000, wasClean: true }));
    }
  }

  const NativeSocket = window.WebSocket;
  window.WebSocket = new Proxy(NativeSocket, {
    construct(target, args: ConstructorParameters<typeof WebSocket>) {
      const url = String(args[0]);
      return url.includes('/api/') || /^wss?:\/\/\/?api\b/.test(url) ? new ReplaySocket(url) as unknown as WebSocket : new target(...args);
    },
  });

  return {
    misses,
    restore(): void {
      window.fetch = nativeFetch;
      window.WebSocket = NativeSocket;
    },
  };
}
